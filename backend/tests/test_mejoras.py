"""Pruebas de la importación incremental, la salud del puente y las métricas del modelo.

- Importación incremental: al volver a exportar un chat solo se descargan los archivos nuevos.
- Estado de salud del puente de WhatsApp en la API.
- Métricas detalladas, explicación de cada clasificación y salud del modelo.
"""
import hashlib
import random

import numpy as np
import pytest
from fastapi.testclient import TestClient

from filemind.ai.dataset import generate_text, to_docx, to_pdf
from filemind.api.app import create_app

CHAT = "573001112233-1600000000@g.us"


def _doc(seed):
    return to_pdf(generate_text("Facturas", random.Random(seed)))


def _items(files):
    return [{"msg_id": mid, "nombre": name, "huella": hashlib.sha256(data).hexdigest()} for mid, name, data in files]


def _run(c, job, files):
    """Hace lo que el puente: sube solo lo que FileMind dejó en cola."""
    view = c.post(f"/api/exportaciones/{job['id']}/items", json={"items": _items(files)}).json()
    subidos = []
    for it in view["items"]:
        if it["estado"] != "en_cola":
            continue
        _, name, data = files[it["idx"]]
        c.post(f"/api/exportaciones/{job['id']}/items/{it['idx']}/archivo", files={"file": (name, data)})
        subidos.append(name)
    return c.get(f"/api/exportaciones/{job['id']}").json(), subidos


def test_importacion_incremental_solo_trae_lo_nuevo(settings):
    a, b, nuevo = _doc(1), _doc(2), _doc(3)
    primera = [("m1", "a.pdf", a), ("m2", "b.pdf", b), ("m3", "a_reenviado.pdf", a)]
    with TestClient(create_app(settings)) as c:
        c.headers['X-FileMind-Token'] = c.app.state.service_token  # el puente se autentica con su token
        job = c.post("/api/exportaciones", json={"chat_id": CHAT, "chat_nombre": "Clientes"}).json()
        c.get("/api/exportaciones/pendiente")
        fin, subidos = _run(c, job, primera)
        # el mismo archivo reenviado dentro del chat se descarga una sola vez
        assert subidos == ["a.pdf", "b.pdf"]
        assert fin["incremental"] == {"ya_importado": 0, "misma_huella": 1, "nuevos": 2}
        assert fin["estado"] == "terminado"
        assert c.get("/api/exportaciones/historial", params={"chat_id": CHAT}).json()["importados"] == 2

        # segunda exportación del mismo chat: solo viaja el archivo nuevo
        segunda = primera + [("m4", "nuevo.pdf", nuevo)]
        job2 = c.post("/api/exportaciones", json={"chat_id": CHAT, "chat_nombre": "Clientes"}).json()
        c.get("/api/exportaciones/pendiente")
        fin2, subidos2 = _run(c, job2, segunda)
        assert subidos2 == ["nuevo.pdf"]
        assert fin2["incremental"] == {"ya_importado": 2, "misma_huella": 1, "nuevos": 1}
        assert fin2["conteo"]["seguro"] == 1 and fin2["conteo"]["omitido"] == 3
        # el ZIP de la segunda exportación trae solo lo nuevo
        import io, zipfile
        z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/exportaciones/{job2['id']}/zip").content))
        assert [n.split("/")[-1] for n in z.namelist()] == ["nuevo.pdf"]

        # otro chat que comparte un archivo ya analizado: se omite por huella sin descargarlo
        job3 = c.post("/api/exportaciones", json={"chat_id": "otro@g.us", "chat_nombre": "Otro"}).json()
        c.get("/api/exportaciones/pendiente")
        fin3, subidos3 = _run(c, job3, [("x1", "b_copia.pdf", b)])
        assert subidos3 == [] and fin3["incremental"]["misma_huella"] == 1 and fin3["estado"] == "terminado"

        # exportación completa a pedido: ignora el registro (sigue sin duplicar el análisis por SHA-256)
        job4 = c.post("/api/exportaciones", json={"chat_id": CHAT, "chat_nombre": "Clientes", "completo": True}).json()
        c.get("/api/exportaciones/pendiente")
        fin4, subidos4 = _run(c, job4, segunda)
        assert len(subidos4) == 4 and fin4["incremental"]["nuevos"] == 4
        eventos = [e for e in c.get("/api/eventos?limite=500").json() if e["event"] == "exportacion_iniciada"]
        assert eventos[0]["detail"]["nuevos"] == 4


def test_huella_invalida_no_omite(settings):
    with TestClient(create_app(settings)) as c:
        c.headers['X-FileMind-Token'] = c.app.state.service_token  # el puente se autentica con su token
        job = c.post("/api/exportaciones", json={"chat_id": CHAT, "chat_nombre": "Clientes"}).json()
        c.get("/api/exportaciones/pendiente")
        v = c.post(f"/api/exportaciones/{job['id']}/items",
                   json={"items": [{"msg_id": "z1", "nombre": "a.pdf", "huella": "no-es-hash"}]}).json()
        assert v["items"][0]["estado"] == "en_cola" and v["items"][0]["huella"] is None


def test_estado_del_puente_con_salud(settings):
    with TestClient(create_app(settings)) as c:
        c.headers['X-FileMind-Token'] = c.app.state.service_token  # el puente se autentica con su token
        salud = {"reconexiones": 3, "fallas_seguidas": 0, "ultimo_error": "detached Frame", "cola_pendiente": 2}
        c.post("/api/whatsapp/estado", json={"estado": "reconectando", "reintento_en_s": 10, "salud": salud})
        st = c.get("/api/whatsapp").json()
        assert st["estado"] == "reconectando" and st["reintento_en_s"] == 10
        assert st["salud"]["reconexiones"] == 3 and st["salud"]["cola_pendiente"] == 2
        c.post("/api/whatsapp/estado", json={"estado": "conectado", "cuenta": "Bufete"})
        assert c.get("/api/whatsapp").json()["salud"]["reconexiones"] == 3  # se conserva el último reporte


# --------------------------------------------------------------- métricas y explicación
def test_metricas_detalladas_por_modelo():
    """Revisa el reporte del último entrenamiento (el que muestra la pantalla de Modelos)."""
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "reportes" / "tema_metricas.json"
    meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "modelos" not in meta or "parametros" not in next(iter(meta["modelos"].values())):
        pytest.skip("reporte generado con una versión anterior; corra scripts/entrenar.py")
    for name, m in meta["modelos"].items():
        assert m["parametros"]["clasificador"], name
        assert {"media", "p50", "p95"} <= set(m["latencia_ms"])
        assert m["latencia_ms"]["p95"] >= m["latencia_ms"]["p50"] > 0
        for cat, v in m["por_clase_prueba"].items():
            assert {"precision", "recall", "f1", "soporte"} <= set(v)
        assert m["tamano_kb"] > 0
    assert "curva_aprendizaje" in meta and "calibracion" in meta


def test_explicacion_de_la_clasificacion(fm):
    data = to_docx("CONTRATO DE OBRA No. 12-2026\nCLÁUSULA PRIMERA - OBJETO\nCLÁUSULA SEGUNDA - VALOR\n"
                   "Pólizas de cumplimiento, contratista y contratante")
    rec = fm.process(data, "contrato.docx", "Obra Vía Puerto Gaitán")
    topic = rec["report"]["topic"]
    assert topic["explicacion"], "debe decir qué palabras pesaron"
    palabras = [e["termino"] for e in topic["explicacion"]]
    assert any("contrat" in p or "clausula" in p for p in palabras)
    assert all(e["peso"] > 0 for e in topic["explicacion"])


def test_salud_del_modelo(fm, settings):
    from filemind.ai.health import model_health
    vacio = model_health([], fm.topic.meta)
    assert vacio["estado"] == "sin_datos"
    for i in range(12):
        fm.process(_doc(100 + i), f"f{i}.pdf", "Obra Vía Puerto Gaitán")
    rows = fm.audit.list_files(status="clasificado")
    h = model_health(rows, fm.topic.meta)
    assert h["archivos"] == 12 and 0 <= h["confianza_media"] <= 1
    assert h["estado"] in ("estable", "vigilar", "reentrenar")
    # simulación de deriva: confianzas bajas -> recomienda reentrenar
    bajos = [{"category_confidence": 0.2, "category": "Otros"} for _ in range(30)]
    assert model_health(bajos, fm.topic.meta)["estado"] == "reentrenar"
    with TestClient(create_app(settings)) as c:
        c.headers['X-FileMind-Token'] = c.app.state.service_token  # el puente se autentica con su token
        assert "salud" in c.get("/api/modelos").json()


def test_benchmark_baselines_funcionan():
    from filemind.ai.baselines import KeywordRules, ZeroShotTfidf
    docs = ["accion de tutela derecho fundamental a la salud", "demanda de inconstitucionalidad contra la ley exequible",
            "ley aprobatoria del tratado internacional convenio", "decreto legislativo estado de emergencia economica",
            "objeciones gubernamentales al proyecto de ley"]
    cats = ["Tutela", "Inconstitucionalidad", "Tratados", "DecretosLegislativos", "Objeciones"]
    rules = KeywordRules(perfil="constitucional").fit(docs, cats)
    assert list(rules.predict(docs)) == cats
    zs = ZeroShotTfidf(perfil="constitucional").fit(docs, cats)
    pred = zs.predict(docs)
    assert len(pred) == 5 and set(pred) <= set(cats)
    assert np.isclose(zs.predict_proba(docs).sum(1), 1).all()
