"""Pruebas de verificación de los requisitos funcionales y no funcionales.

Cada prueba cita el requisito de filemind_seguridad.pdf que verifica.
"""
import hashlib
import os
import random
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from filemind.ai.dataset import generate_text, render, to_docx, to_pdf
from filemind.infrastructure.repository import AuditStore
from filemind.security import samples
from filemind.security.signatures import EICAR_SHA256
from filemind.security.static import detect_type, run_static
from filemind.security.signatures import SignatureRepository

from conftest import GROUP

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
JARGON = ["sha", "hash", "vba", "sandbox", " ole", "dde", "base64", "powershell", "magic", "rdap",
          "javascript", "heur", "/openaction", "punycode"]


def legit_pdf(seed=1):
    return to_pdf(generate_text("Facturas", random.Random(seed)))


# ------------------------------------------------------------------- RF1
def test_rf1_solo_grupos_configurados(fm):
    assert fm.process(legit_pdf(), "a.pdf", "Grupo Familiar") is None
    assert fm.process(legit_pdf(), "a.pdf", None) is None
    assert fm.audit.list_files() == []
    ev = [e["event"] for e in fm.audit.events()]
    assert ev.count("ignorado_grupo_no_monitoreado") == 2
    assert fm.process(legit_pdf(), "a.pdf", GROUP)["status"] == "clasificado"


# ------------------------------------------------------------------- RF2
def test_rf2_latencia_registrada(fm):
    ts = time.time() - 2
    rec = fm.process(legit_pdf(2), "b.pdf", GROUP, message_ts=ts)
    det = [e for e in fm.audit.events(rec["sha256"]) if e["event"] == "archivo_detectado"][0]
    assert det["detail"]["latency_s"] <= 10 and det["detail"]["rf2_ok"]


# ------------------------------------------------------------------- RF3
def _sha256_externo(p):
    """Huella calculada por la herramienta del sistema operativo, no por Python."""
    import shutil
    if shutil.which("sha256sum"):
        out = subprocess.run(["sha256sum", str(p)], capture_output=True, text=True).stdout
        return out.split()[0].lstrip(chr(92))   # sha256sum antepone una barra si la ruta tiene barras invertidas
    if shutil.which("shasum"):   # macOS
        out = subprocess.run(["shasum", "-a", "256", str(p)], capture_output=True, text=True).stdout
        return out.split()[0]
    out = subprocess.run(["certutil", "-hashfile", str(p), "SHA256"], capture_output=True, text=True).stdout
    return out.splitlines()[1].replace(" ", "").lower()   # Windows


def test_rf3_sha256_antes_de_procesar(fm, tmp_path):
    data = legit_pdf(3)
    rec = fm.process(data, "c.pdf", GROUP)
    p = tmp_path / "c.pdf"
    p.write_bytes(data)
    externo = _sha256_externo(p)
    assert rec["sha256"] == externo == hashlib.sha256(data).hexdigest()
    orden = [e["event"] for e in reversed(fm.audit.events(rec["sha256"]))]
    assert orden.index("hash_calculado") < orden.index("fase1_estatico")


# ------------------------------------------------------------------- RF4
def test_rf4_extensiones_falsificadas(tmp_path):
    sigs = SignatureRepository(tmp_path / "f.txt")
    casos = samples.spoofed_extension_set()
    assert len(casos) >= 10
    for name, data, real in casos:
        st = run_static(data, name, sigs)
        assert st["real_type"] == real, name
        assert st["extension_mismatch"], name


def test_rf4_extension_correcta_no_alerta(tmp_path):
    sigs = SignatureRepository(tmp_path / "f.txt")
    for fmt in ("pdf", "docx", "xlsx", "pptx"):
        st = run_static(render("Acta de reunión No. 5", fmt), f"doc.{fmt}", sigs)
        assert not st["extension_mismatch"], fmt


def test_rf4_doble_extension_y_rtlo(tmp_path):
    sigs = SignatureRepository(tmp_path / "f.txt")
    assert run_static(samples.EXE_STUB, "factura_pendiente.pdf.exe", sigs)["double_extension"]
    assert run_static(samples.EXE_STUB, "factura‮fdp.exe", sigs)["bidi_override"]


# ------------------------------------------------------------------- RF5
def test_rf5_firma_conocida(fm):
    rec = fm.process(EICAR, "comprobante.pdf", GROUP)
    assert hashlib.sha256(EICAR).hexdigest() == EICAR_SHA256
    assert rec["status"] == "cuarentena" and rec["risk_score"] == 100
    q = [e for e in fm.audit.events(rec["sha256"]) if e["event"] == "fase1_estatico"][0]
    assert q["detail"]["signature_query"]["malicious"] and q["detail"]["signature_query"]["queried"]


# ------------------------------------------------------------------- RF6
@pytest.mark.parametrize("gen,kind", [
    (samples.phishing_sample, "completo"),
    (samples.ransomware_sample, "docm_autoopen"),
    (samples.ransomware_sample, "pdf_js"),
])
def test_rf6_patrones(fm, gen, kind):
    rng = random.Random(0)
    for _ in range(300):
        name, data, k = gen(rng)
        if k == kind:
            break
    rec = fm.process(data, name, GROUP)
    ids = {f["id"] for f in rec["report"]["heuristic"]["findings"]}
    esperado = {"completo": {"phishing_url", "phishing_text"}, "docm_autoopen": {"macro_autoexec"},
                "pdf_js": {"pdf_js"}}[kind]
    assert esperado & ids, ids


def test_rf6_legitimo_sin_hallazgos(fm):
    rec = fm.process(to_docx("Acta de reunión\nAsistentes: Ing. Laura\nCompromisos"), "acta.docx", GROUP)
    assert rec["report"]["heuristic"]["findings"] == []
    assert rec["risk_level"] == "bajo"


# ------------------------------------------------------------------- RF7
def test_rf7_puntaje_0_100_reproducible(fm, settings):
    rng = random.Random(5)
    for gen in (samples.legit_sample, samples.phishing_sample, samples.ransomware_sample):
        name, data, _ = gen(rng)
        a = fm.process(data, name, GROUP)
        assert 0 <= a["risk_score"] <= 100
        from filemind.security.risk import score
        again = score(a["report"]["features"], fm.risk_model)
        assert again["score"] == a["risk_score"]


# ------------------------------------------------------------------- RF8
def test_rf8_cuarentena_cifrada_y_acceso_restringido(fm, settings):
    data = samples.EXE_STUB + b"\x00" * 4000
    rec = fm.process(data, "factura_pendiente.pdf.exe", GROUP)
    assert rec["status"] == "cuarentena" and rec["risk_score"] > 70
    stored = settings.quarantine_dir / f"{rec['sha256']}.fmq"
    assert stored.exists() and data not in stored.read_bytes()
    if os.name == "nt":  # Windows solo distingue "solo lectura", no permisos por usuario
        assert not os.access(stored, os.W_OK)
    else:
        assert oct(stored.stat().st_mode)[-3:] == "400"
    assert not any(settings.library_dir.rglob("factura_pendiente*"))
    assert "no lo abras" in rec["notification"].lower()


def test_rf8_api_bloquea_descarga_y_exige_confirmacion(settings):
    from fastapi.testclient import TestClient
    from filemind.api.app import create_app
    with TestClient(create_app(settings)) as c:
        c.headers['X-FileMind-Token'] = c.app.state.service_token  # el puente se autentica con su token
        r = c.post("/api/ingest", data={"grupo": GROUP}, files={"file": ("factura.pdf.exe", samples.EXE_STUB)})
        sha = r.json()["sha256"]
        assert r.json()["status"] == "cuarentena"
        assert c.get(f"/api/archivos/{sha}/descargar").status_code == 403
        assert c.post(f"/api/cuarentena/{sha}/liberar", json={"categoria": "Otros", "motivo": "x"}).status_code in (400, 422)
        ok = c.post(f"/api/cuarentena/{sha}/liberar",
                    json={"categoria": "Otros", "motivo": "Verificado por llamada con el proveedor", "confirmar": True})
        assert ok.status_code == 200
        assert c.get(f"/api/archivos/{sha}/descargar").status_code == 200


# ------------------------------------------------------------------ RNF1
def test_rnf1_tiempo_por_archivo_20mb(fm):
    big = render("Informe de avance\n" + "Actividades ejecutadas. " * 50, "txt") + os.urandom(20 * 1024 * 1024 - 2000)
    t = time.perf_counter()
    rec = fm.process(big, "grande.bin", GROUP)
    assert time.perf_counter() - t < 15 and rec["protocol_seconds"] < 15


# ------------------------------------------------------------------ RNF5
def test_rnf5_sandbox_aislado_y_efimero():
    from filemind.security.sandbox import pick_backend, run_sandbox
    if pick_backend("auto") == "subprocess":
        pytest.skip("Sin Docker ni unshare no hay aislamiento de red: instala Docker Desktop para cumplir RNF5")
    r = run_sandbox(legit_pdf(9), "x.pdf")
    iso = r["isolation"]
    assert r["status"] == "ok"
    assert iso["network_blocked"] and iso["fs_write_blocked"] and iso["ephemeral"]
    assert iso["files_written_in_workdir"] == [] and iso["rnf5_ok"]


# ------------------------------------------------------------------ RNF7
def test_rnf7_notificacion_sin_jerga(fm):
    rng = random.Random(3)
    for _ in range(12):
        name, data, _ = samples.ransomware_sample(rng)
        rec = fm.process(data, name, GROUP)
        msg = rec["notification"].lower()
        assert not [j for j in JARGON if j in msg], msg


# ------------------------------------------------------------------ RNF8
def test_rnf8_trazabilidad_y_retencion(tmp_path):
    a = AuditStore(tmp_path / "x.db", retention_days=30)   # se fuerza el mínimo de 183
    assert a.retention_days >= 183
    a.log("evento", "abc")
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=170)).isoformat()
    a._conn.execute("INSERT INTO events(ts,event) VALUES (?,?)", (old, "viejo"))
    a._conn.execute("INSERT INTO events(ts,event) VALUES (?,?)", (recent, "reciente"))
    a._conn.commit()
    assert a.purge_expired() == 1
    names = [e["event"] for e in a.events()]
    assert "reciente" in names and "viejo" not in names
    assert all(e["ts"] for e in a.events())
    assert (tmp_path / "audit.jsonl").read_text().count("\n") >= 1


# --------------------------------------------------------- IA / problema original
def test_clasificacion_y_duplicados(fm, settings):
    data = to_docx("CONTRATO DE OBRA No. 12-2026\nCLÁUSULA PRIMERA - OBJETO\nCLÁUSULA SEGUNDA - VALOR\nPólizas de cumplimiento")
    rec = fm.process(data, "contrato.docx", GROUP)
    assert rec["status"] == "clasificado" and rec["category"] == "Contratos"
    assert (settings.library_dir / "Contratos" / "contrato.docx").exists()
    dup = fm.process(data, "contrato (1).docx", "Compras Vichada")
    assert dup["duplicate"]


def test_retroalimentacion_mueve_y_registra(fm, settings):
    rec = fm.process(to_pdf("Lista de mercado\narroz, aceite"), "lista.pdf", GROUP)
    out = fm.correct_category(rec["sha256"], "Financiero")
    assert (settings.library_dir / "Financiero" / "lista.pdf").exists()
    assert fm.audit.feedback_rows()[0]["corrected"] == "Financiero"
    assert out["category"] == "Financiero"


# ------------------------------------------------------------- RF9 a RF11
def test_rf9_rf10_rf11_exportar_chat_en_cola_y_guardar_por_categoria(settings, tmp_path):
    """Exportar un chat NO monitoreado: la cola procesa en orden, los seguros se guardan
    en la carpeta escogida con una subcarpeta por categoría y el riesgoso queda en cuarentena."""
    import io
    import zipfile
    from fastapi.testclient import TestClient
    from filemind.api.app import create_app
    contrato = to_docx("CONTRATO DE OBRA No. 12-2026\nCLÁUSULA PRIMERA - OBJETO\nCLÁUSULA SEGUNDA - VALOR\nPólizas de cumplimiento")
    archivos = [("contrato.docx", contrato), ("factura.pdf", legit_pdf(3)), ("factura.pdf.exe", samples.EXE_STUB)]
    with TestClient(create_app(settings)) as c:
        c.headers['X-FileMind-Token'] = c.app.state.service_token  # el puente se autentica con su token
        job = c.post("/api/exportaciones", json={"chat_id": "57300@c.us", "chat_nombre": "Cliente Pérez"}).json()
        assert job["estado"] == "esperando_puente"
        pend = c.get("/api/exportaciones/pendiente").json()["trabajo"]
        assert pend["id"] == job["id"] and c.get("/api/exportaciones/pendiente").json()["trabajo"] is None
        r = c.post(f"/api/exportaciones/{job['id']}/items", json={"items": [{"nombre": n} for n, _ in archivos]})
        assert r.json()["total"] == 3 and r.json()["conteo"]["en_cola"] == 3
        estados = []
        for i, (name, data) in enumerate(archivos):
            c.post(f"/api/exportaciones/{job['id']}/items/{i}/estado", json={"estado": "descargando"})
            it = c.post(f"/api/exportaciones/{job['id']}/items/{i}/archivo", files={"file": (name, data)}).json()["item"]
            estados.append(it["estado"])
            pendientes = c.get(f"/api/exportaciones/{job['id']}").json()["conteo"]["en_cola"]
            assert pendientes == len(archivos) - i - 1  # uno tras otro
        assert estados == ["seguro", "seguro", "cuarentena"]
        final = c.get(f"/api/exportaciones/{job['id']}").json()
        assert final["estado"] == "terminado"

        destino = tmp_path / "Mis expedientes"
        out = c.post(f"/api/exportaciones/{job['id']}/guardar", json={"destino": str(destino)}).json()
        assert out["archivos"] == 2
        assert (destino / "Contratos" / "contrato.docx").exists()
        assert not any(destino.rglob("factura.pdf.exe*"))  # lo riesgoso nunca sale de la cuarentena
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/exportaciones/{job['id']}/zip").content))
        assert "Contratos/contrato.docx" in z.namelist() and len(z.namelist()) == 2
        eventos = [e["event"] for e in c.get("/api/eventos?limite=500").json()]
        assert {"exportacion_solicitada", "exportacion_terminado", "exportacion_guardada"} <= set(eventos)


# ------------------------------------------- controles de ciberseguridad (RF4, RF5, RF6)
# Técnica -> control que debe alertar (muestras inertes de security.samples)
CONTROL_ESPERADO = {
    "zip_exe": "comprimidos", "zip_anidado": "comprimidos", "zip_contrasena": "comprimidos",
    "zip_macro": "yara", "zip_ruta": "comprimidos", "zip_eicar": "hashes",
    "poliglota_jpg_zip": "tipo_real", "pdf_adjunto_exe": "pdf_activo", "pdf_js_nombres": "pdf_activo",
    "rtf_equation": "macros_ole", "rtf_paquete": "macros_ole", "html_contrabando": "yara",
    "html_enlace_enganoso": "html", "excel4_xlm": "macros_ole", "lnk_disfrazado": "tipo_real",
}


def test_controles_en_reporte_y_auditoria(fm):
    rec = fm.process(to_docx("Acta de reunión\nAsistentes: Ing. Laura\nCompromisos"), "acta.docx", GROUP)
    ctl = rec["report"]["controls"]
    assert [c["id"] for c in ctl] == ["tipo_real", "hashes", "macros_ole", "pdf_activo", "comprimidos", "yara",
                                      "entropia", "urls", "html", "ingenieria_social"]
    assert all(c["estado"] in ("ok", "no_aplica") for c in ctl), ctl
    assert next(c for c in ctl if c["id"] == "yara")["detalles"]   # las reglas se aplicaron
    eventos = [e["event"] for e in reversed(fm.audit.events(rec["sha256"]))]
    assert eventos.index("fase2_heuristico") < eventos.index("controles_seguridad") < eventos.index("fase4_puntaje")
    assert rec["risk_level"] == "bajo"


@pytest.mark.parametrize("kind", sorted(CONTROL_ESPERADO))
def test_controles_detectan_tecnicas_nuevas(fm, kind):
    name, data = samples.control_attack_sample(kind, random.Random(5))
    rec = fm.process(data, name, GROUP)
    estados = {c["id"]: c["estado"] for c in rec["report"]["controls"]}
    assert estados[CONTROL_ESPERADO[kind]] == "alerta", estados
    assert rec["status"] == "cuarentena" and rec["risk_score"] > 70


@pytest.mark.parametrize("kind", samples.CONTROL_LEGIT)
def test_controles_sin_falsos_positivos(fm, kind):
    name, data = samples.control_legit_sample(kind, random.Random(5))
    rec = fm.process(data, name, GROUP)
    assert rec["status"] == "clasificado" and rec["risk_level"] == "bajo", rec["report"]["risk"]["rule_contributions"]


def test_controles_firmas_md5_y_listas(fm, settings):
    data = b"muestra inerte registrada en una lista local por su MD5"
    lista = settings.data_dir / "firmas"
    lista.mkdir(exist_ok=True)
    (lista / "lista_equipo.txt").write_text(f"{hashlib.md5(data).hexdigest()};Prueba-MD5\n", encoding="utf-8")
    fm.signatures.reload()
    rec = fm.process(data, "nota.txt", GROUP)
    assert rec["status"] == "cuarentena" and rec["risk_score"] == 100
    hashes = next(c for c in rec["report"]["controls"] if c["id"] == "hashes")
    assert hashes["estado"] == "alerta" and "Prueba-MD5" in hashes["resumen"]


def test_controles_lenguaje_claro():
    """RNF7: las explicaciones para el usuario de reglas y controles no usan jerga técnica."""
    import yara
    from filemind.security.controls import RULES_DIR
    rules = yara.compile(filepaths={p.stem: str(p) for p in RULES_DIR.glob("*.yar")})
    textos = [r.meta["claro"] for r in rules]
    rng = random.Random(8)
    fm_text = []
    for kind in samples.CONTROL_ATTACKS:
        if kind == "zip_bomba":
            continue
        name, data = samples.control_attack_sample(kind, rng)
        from filemind.infrastructure.extract import extract
        from filemind.security.controls import run_controls
        st = run_static(data, name, SignatureRepository(Path(os.environ.get("TMP", ".")) / "fm_firmas_test.txt"))
        fm_text += [f["claro"] for f in run_controls(data, name, st, extract(data, st["real_type"]))["findings"]]
    for t in textos + fm_text:
        assert not [j for j in JARGON if j in t.lower()], t
