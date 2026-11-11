"""Versión web: inicio de sesión, roles, espacios de trabajo, búsqueda por contenido,
reporte PDF y serie de tiempo."""
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import GROUP
from filemind.api.app import create_app
from filemind.infrastructure.accounts import hash_password, verify_password

OTRO = "Compras Vichada"
TEXTO = ("Acta de reunión de obra. Se revisó el avance de la pavimentación y el cronograma del puente "
         "sobre el río Guatiquía. Compromisos: enviar presupuesto actualizado.")


def _ingest(c, name, text, grupo):
    r = c.post("/api/ingest", data={"grupo": grupo}, files={"file": (name, text.encode("utf-8"))},
               headers={"X-FileMind-Token": c.app.state.service_token})
    assert r.status_code == 200 and r.json()["procesado"], r.text
    return r.json()["sha256"]


def test_contrasenas_con_sal_y_sin_texto_plano():
    h1, h2 = hash_password("clave-segura-1"), hash_password("clave-segura-1")
    assert h1 != h2 and "clave-segura-1" not in h1          # sal distinta en cada hash
    assert verify_password("clave-segura-1", h1) and not verify_password("otra-clave-2", h1)


def test_sin_sesion_no_hay_datos(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").status_code == 200           # la salud sigue pública (RNF2)
        for ruta in ("/api/archivos", "/api/estadisticas", "/api/modelos", "/api/eventos", "/api/usuarios"):
            assert c.get(ruta).status_code == 401, ruta
        assert c.get("/api/auth/estado").json()["configurado"] is False


def test_primer_administrador_inicio_y_bloqueo(settings):
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "corta"})
        assert r.status_code == 400                           # política de contraseñas
        r = c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Filemind2026"})
        assert r.status_code == 200 and r.json()["usuario"]["role"] == "admin"
        cookie = r.cookies.get("fm_session")
        assert cookie and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
        assert c.post("/api/auth/configurar", json={"usuario": "otro", "nombre": "X",
                                                     "contrasena": "Filemind2026"}).status_code == 409
        assert c.get("/api/auth/yo").json()["usuario"]["username"] == "admin"
        c.post("/api/auth/salir")
        assert c.get("/api/auth/yo").status_code == 401        # la sesión se borró en el servidor
        for _ in range(5):
            assert c.post("/api/auth/entrar", json={"usuario": "admin", "contrasena": "mala-clave1"}).status_code == 401
        r = c.post("/api/auth/entrar", json={"usuario": "admin", "contrasena": "Filemind2026"})
        assert r.status_code == 401 and "bloqueada" in r.json()["detail"]
        eventos = [e["event"] for e in c.app.state.fm.audit.events(limit=50)]
        assert "inicio_sesion_fallido" in eventos and "inicio_sesion" not in eventos[:5]


def test_espacios_de_trabajo_limitan_lo_que_ve_cada_miembro(settings):
    with TestClient(create_app(settings)) as c:
        c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Filemind2026"})
        sha_obra = _ingest(c, "acta_obra.txt", TEXTO, GROUP)
        sha_compras = _ingest(c, "cotizacion.txt", "Cotización de cemento gris y arena de río.", OTRO)
        ana = c.post("/api/usuarios", json={"usuario": "ana", "nombre": "Ana", "contrasena": "Miembro2026",
                                            "rol": "miembro"}).json()
        luis = c.post("/api/usuarios", json={"usuario": "luis", "nombre": "Luis", "contrasena": "Miembro2026"}).json()
        ws = c.post("/api/espacios", json={"nombre": "Obra", "miembros": [ana["id"], luis["id"]],
                                           "chats": [GROUP]}).json()
        assert ws["chats"] == [GROUP] and len(ws["miembros"]) == 2

        with TestClient(c.app) as ana_c:
            assert ana_c.post("/api/auth/entrar", json={"usuario": "ana", "contrasena": "Miembro2026"}).status_code == 200
            vistos = {f["sha256"] for f in ana_c.get("/api/archivos").json()}
            assert sha_obra in vistos and sha_compras not in vistos
            assert ana_c.get(f"/api/archivos/{sha_compras}").status_code == 404
            assert ana_c.get(f"/api/archivos/{sha_compras}/descargar").status_code == 404
            assert ana_c.get("/api/usuarios").status_code == 403          # no es administradora
            assert ana_c.get("/api/eventos").status_code == 403
            assert [w["nombre"] for w in ana_c.get("/api/espacios").json()] == ["Obra"]
            assert sum(ana_c.get("/api/estadisticas").json()["por_estado"].values()) == 1
            # corrige una categoría: la ve todo el espacio
            cat = c.get("/api/categorias").json()[0]["nombre"]
            assert ana_c.post(f"/api/archivos/{sha_obra}/categoria", json={"categoria": cat}).status_code == 200
        with TestClient(c.app) as luis_c:
            luis_c.post("/api/auth/entrar", json={"usuario": "luis", "contrasena": "Miembro2026"})
            assert luis_c.get(f"/api/archivos/{sha_obra}").json()["category"] == cat
        # el administrador ve todo
        assert {sha_obra, sha_compras} <= {f["sha256"] for f in c.get("/api/archivos").json()}


def test_busqueda_dentro_del_contenido_reporte_pdf_y_serie(settings):
    with TestClient(create_app(settings)) as c:
        c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Filemind2026"})
        sha = _ingest(c, "documento.txt", TEXTO, GROUP)
        _ingest(c, "otro.txt", "Factura de venta número 15 por suministro de concreto.", GROUP)
        res = c.get("/api/archivos", params={"q": "guatiquia"}).json()   # sin tilde y en minúscula
        assert [r["sha256"] for r in res] == [sha] and "guatiquia" in res[0]["coincidencia"]
        assert c.get("/api/archivos", params={"q": "guatiquia", "contenido": False}).json() == []
        pdf = c.get(f"/api/archivos/{sha}/reporte.pdf")
        assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and len(pdf.content) > 3000
        serie = c.get("/api/estadisticas/serie", params={"dias": 7}).json()["dias"]
        assert len(serie) == 7 and serie[-1]["total"] == 2


def test_desvincular_whatsapp(settings):
    """El administrador pide desvincular el número; el puente recibe la orden en su próximo latido."""
    with TestClient(create_app(settings)) as c:
        token = c.app.state.service_token
        svc = {"X-FileMind-Token": token}
        assert c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Clave2026"}).status_code == 200
        assert c.post("/api/whatsapp/desvincular").status_code == 409  # sin puente
        r = c.post("/api/whatsapp/estado", json={"estado": "conectado", "cuenta": "Bufete"}, headers=svc)
        assert r.json()["accion"] is None
        assert c.post("/api/whatsapp/desvincular").status_code == 200
        assert c.get("/api/whatsapp").json()["estado"] == "iniciando"
        r = c.post("/api/whatsapp/estado", json={"estado": "conectado"}, headers=svc)
        assert r.json()["accion"] == "desvincular"
        r = c.post("/api/whatsapp/estado", json={"estado": "esperando_qr", "qr": "data:x"}, headers=svc)
        assert r.json()["accion"] is None


def test_carpeta_del_bufete_guarda_por_etiqueta(settings, tmp_path):
    """Carpeta del bufete: subcarpetas por etiqueta, guardado automático, pendientes y cambio de etiqueta."""
    destino = tmp_path / "Bufete"
    with TestClient(create_app(settings)) as c:
        c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Filemind2026"})
        sha_antes = _ingest(c, "acta_obra.txt", TEXTO, GROUP)              # llega antes de tener carpeta
        r = c.get("/api/bufete/resumen").json()
        assert not r["configurada"] and r["faltan"] == 1
        assert c.get("/api/archivos").json()[0]["carpeta"]["estado"] == "sin_carpeta"
        # la carpeta no existe: se pide confirmación y luego se crea con sus subcarpetas
        assert c.put("/api/bufete", json={"ruta": str(destino)}).status_code == 409
        v = c.put("/api/bufete", json={"ruta": str(destino), "crear": True, "preparar": True}).json()
        assert v["auto"] and all(k["existe"] for k in v["categorias"])
        assert {"Otros", "Contratos"} <= {k["nombre"] for k in v["categorias"]}
        # «Guardar los que faltan»
        g = c.post("/api/bufete/guardar-pendientes").json()
        assert g["guardados"] == 1 and g["restantes"] == 0
        rec = c.get(f"/api/archivos/{sha_antes}").json()
        ruta = Path(rec["carpeta"]["ruta"])
        assert rec["carpeta"]["estado"] == "guardado" and ruta.is_file()
        assert ruta.parent.parent == destino
        assert c.get("/api/archivos?carpeta=guardado").json()[0]["sha256"] == sha_antes
        assert c.get("/api/archivos?carpeta=falta").json() == []
        # guardado automático de un archivo nuevo
        sha_nuevo = _ingest(c, "cotizacion.txt", "Cotización de cemento gris y arena de río.", OTRO)
        assert c.get(f"/api/archivos/{sha_nuevo}").json()["carpeta"]["estado"] == "guardado"
        # corregir la etiqueta mueve la copia (no la duplica) y respeta el nombre de subcarpeta escogido
        c.put("/api/bufete", json={"subcarpetas": {"Contratos": "Contratos firmados"}})
        assert c.post(f"/api/archivos/{sha_antes}/categoria", json={"categoria": "Contratos"}).status_code == 200
        nueva = Path(c.get(f"/api/archivos/{sha_antes}").json()["carpeta"]["ruta"])
        assert nueva.parent == destino / "Contratos firmados" and nueva.is_file() and not ruta.exists()
        # si alguien borra la copia del PC vuelve a figurar como pendiente
        nueva.unlink()
        assert c.get("/api/bufete/resumen").json()["faltan"] == 1
        # con el guardado automático apagado no se copia lo nuevo
        c.put("/api/bufete", json={"auto": False})
        sha_3 = _ingest(c, "otro.txt", "Factura de venta número 123 por servicios de consultoría.", GROUP)
        assert c.get(f"/api/archivos/{sha_3}").json()["carpeta"]["estado"] == "falta"
        assert c.post(f"/api/archivos/{sha_3}/guardar-en-carpeta").json()["estado"] == "guardado"
        # al cambiar de carpeta, lo copiado en la anterior vuelve a figurar como pendiente
        otra = tmp_path / "Otra"
        c.put("/api/bufete", json={"ruta": str(otra), "crear": True})
        assert c.get("/api/bufete/resumen").json()["guardados"] == 0
        assert c.post("/api/bufete/guardar-pendientes").json()["guardados"] == 3
        assert all(Path(f["carpeta"]["ruta"]).is_relative_to(otra) for f in c.get("/api/archivos").json())


def test_espacio_filtra_por_etiquetas(settings):
    """Un miembro solo ve los archivos de los chats de su espacio con las etiquetas elegidas."""
    with TestClient(create_app(settings)) as c:
        c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Filemind2026"})
        sha_a = _ingest(c, "acta.txt", TEXTO, GROUP)
        sha_b = _ingest(c, "otro.txt", "Factura de venta número 123 por servicios de consultoría.", GROUP)
        cat_a = c.get(f"/api/archivos/{sha_a}").json()["category"]
        cat_b = "Contratos" if cat_a != "Contratos" else "Facturas"
        c.post(f"/api/archivos/{sha_b}/categoria", json={"categoria": cat_b})
        ana = c.post("/api/usuarios", json={"usuario": "ana", "nombre": "Ana", "contrasena": "Miembro2026"}).json()
        ws = c.post("/api/espacios", json={"nombre": "Solo una etiqueta", "miembros": [ana["id"]], "chats": [GROUP],
                                           "categorias": [cat_a]}).json()
        assert ws["categorias"] == [cat_a] and ws["archivos"] == 1
        with TestClient(c.app) as ana_c:
            ana_c.post("/api/auth/entrar", json={"usuario": "ana", "contrasena": "Miembro2026"})
            vistos = {f["sha256"] for f in ana_c.get("/api/archivos").json()}
            assert vistos == {sha_a}
            assert ana_c.get(f"/api/archivos/{sha_b}").status_code == 404
            assert sum(ana_c.get("/api/estadisticas").json()["por_estado"].values()) == 1
            assert ana_c.get("/api/bufete/resumen").json()["total"] == 1
        # el administrador que escoge ese espacio también ve solo esa etiqueta
        assert {f["sha256"] for f in c.get(f"/api/archivos?espacio={ws['id']}").json()} == {sha_a}
        # sin etiquetas marcadas = todas
        c.put(f"/api/espacios/{ws['id']}", json={"nombre": "Solo una etiqueta", "miembros": [ana["id"]],
                                                 "chats": [GROUP], "categorias": []})
        assert {f["sha256"] for f in c.get(f"/api/archivos?espacio={ws['id']}").json()} == {sha_a, sha_b}


def test_conteo_por_chat_y_encender_puente(settings):
    """La página de chats muestra cuántos archivos van por chat; el puente solo se enciende desde el mismo PC."""
    with TestClient(create_app(settings)) as c:
        c.post("/api/auth/configurar", json={"usuario": "admin", "nombre": "Admin", "contrasena": "Filemind2026"})
        _ingest(c, "acta.txt", TEXTO, GROUP)
        assert c.get("/api/grupos/conteo").json() == {GROUP: 1}
        r = c.post("/api/whatsapp/encender")              # TestClient no es 127.0.0.1
        assert r.status_code == 409 and "mismo PC" in r.json()["detail"] or "PC" in r.json()["detail"]
        ana = c.post("/api/usuarios", json={"usuario": "ana", "nombre": "Ana", "contrasena": "Miembro2026"}).json()
        assert ana["username"] == "ana"
        with TestClient(c.app) as ana_c:
            ana_c.post("/api/auth/entrar", json={"usuario": "ana", "contrasena": "Miembro2026"})
            assert ana_c.post("/api/whatsapp/encender").status_code == 403
            assert ana_c.get("/api/grupos/conteo").status_code == 403
