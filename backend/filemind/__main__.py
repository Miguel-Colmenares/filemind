"""Línea de comandos de FileMind.

    python -m filemind serve [--host 127.0.0.1 --port 8000]
    python -m filemind escritorio        (ventana nativa con API y puente de WhatsApp)
    python -m filemind grupos "Obra Vía Puerto Gaitán" "Compras Vichada"
    python -m filemind analizar archivo.pdf --grupo "Compras Vichada"
    python -m filemind vigilar carpeta/ --grupo "Compras Vichada"
    python -m filemind entrenar
    python -m filemind usuario admin "Nombre Apellido" --rol admin   (crea o restablece la contraseña)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .config import ROOT, load_settings


def _autostart_gateway(data_dir) -> None:
    """Enciende el puente de WhatsApp junto con FileMind (si no hay uno ya encendido)."""
    import threading
    from .infrastructure import gateway

    def run():
        try:
            if gateway.available() is None and not gateway.running(data_dir):
                print(f"Encendiendo el puente de WhatsApp (proceso {gateway.start(data_dir)}); "
                      f"su registro queda en {data_dir}/whatsapp-gateway.log")
        except Exception as e:  # el puente es opcional: FileMind sigue sin él
            print("No se pudo encender el puente de WhatsApp:", e)
    threading.Thread(target=run, daemon=True).start()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="filemind")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--sin-whatsapp", action="store_true", help="No encender el puente de WhatsApp")
    g = sub.add_parser("grupos")
    g.add_argument("nombres", nargs="*")
    a = sub.add_parser("analizar")
    a.add_argument("archivos", nargs="+")
    a.add_argument("--grupo", required=True)
    a.add_argument("--remitente")
    a.add_argument("--json", action="store_true")
    v = sub.add_parser("vigilar")
    v.add_argument("carpeta")
    v.add_argument("--grupo", required=True)
    sub.add_parser("entrenar")
    sub.add_parser("escritorio")
    us = sub.add_parser("usuario", help="Crea un usuario o restablece su contraseña")
    us.add_argument("usuario")
    us.add_argument("nombre", nargs="?", default=None)
    us.add_argument("--rol", choices=["admin", "miembro"], default="miembro")
    args = ap.parse_args(argv)

    if args.cmd == "escritorio":
        from .desktop import main as desktop
        desktop()
        return

    if args.cmd == "serve":
        import uvicorn
        from .api.app import create_app
        settings = load_settings()
        if settings.whatsapp_autostart and not args.sin_whatsapp:
            _autostart_gateway(settings.data_dir)
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return
    if args.cmd == "entrenar":
        subprocess.run([sys.executable, str(ROOT / "scripts" / "entrenar.py")], check=True)
        return

    from .services.analysis_service import FileMind
    fm = FileMind(load_settings())
    if args.cmd == "usuario":
        import getpass
        from .infrastructure.accounts import Accounts
        acc = Accounts(fm.audit)
        pwd = getpass.getpass("Contraseña (mínimo 8, letras y números): ")
        existing = next((u for u in acc.list_users() if u["username"] == args.usuario.lower()), None)
        try:
            if existing:
                acc.update_user(existing["id"], password=pwd, active=True, role=args.rol if args.nombre else None)
                fm.audit.log("usuario_modificado", usuario=existing["username"], cambios=["contrasena_restablecida"],
                             por="consola")
                print(f"Contraseña de «{existing['username']}» restablecida.")
            else:
                u = acc.create_user(args.usuario, args.nombre or args.usuario, pwd, args.rol)
                fm.audit.log("usuario_creado", usuario=u["username"], rol=u["role"], por="consola")
                print(f"Usuario «{u['username']}» creado con rol {u['role']}.")
        except ValueError as e:
            print(f"Error: {e}")
        fm.shutdown()
        return
    if args.cmd == "grupos":
        if args.nombres:
            fm.audit.set_groups(args.nombres)
            fm.audit.log("grupos_configurados", groups=fm.groups)
        print("\n".join(fm.groups) or "(ningún grupo configurado)")
    elif args.cmd == "analizar":
        for p in args.archivos:
            rec = fm.process(Path(p).read_bytes(), Path(p).name, args.grupo, args.remitente)
            if rec is None:
                print(f"{p}: ignorado (el grupo '{args.grupo}' no está monitoreado)")
            elif args.json:
                print(json.dumps({k: v for k, v in rec.items() if k != "report"}, ensure_ascii=False, default=str))
            else:
                print(f"\n=== {p}\n{rec['notification']}\n(estado={rec['status']}, "
                      f"categoría={rec.get('category')}, {rec.get('protocol_seconds')} s)")
    elif args.cmd == "vigilar":
        from .infrastructure.folder_connector import watch_folder
        watch_folder(fm, Path(args.carpeta), args.grupo)
    fm.shutdown()


if __name__ == "__main__":
    main()
