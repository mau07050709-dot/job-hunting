import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from autojob.browser.discovery import find_brave
from autojob.config import Settings
from autojob.logging_setup import configure_logging
from autojob.storage.database import Database


def main(argv=None):
    parser = argparse.ArgumentParser(prog="job-hunting", description="Job Hunting 0.2 — Brave y currículums; sin postulaciones reales")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="Carpeta del proyecto; por defecto, directorio actual")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Crear configuración y base de datos")
    sub.add_parser("doctor", help="Comprobar Python, Brave y rutas")
    smoke = sub.add_parser("smoke", help="Prueba real de Brave con formulario HTTP local")
    smoke.add_argument("--headless", action="store_true")
    smoke.add_argument("--transport", choices=["persistent", "cdp"])
    sub.add_parser("gui", help="Panel gráfico inicial")
    sub.add_parser("history", help="Historial de pruebas locales")
    sub.add_parser("recover", help="Marcar pruebas interrumpidas; ejecutar con el worker detenido")
    args = parser.parse_args(argv)
    try:
        settings = Settings.load(args.project)
        logger = configure_logging(settings.data_path)
        if args.command == "gui":
            from autojob.ui.main_window import launch
            return launch(settings)
        database = Database(settings.data_path / "autojob.sqlite3")
        if args.command == "init":
            if not (settings.root / "config.json").exists():
                settings.save()
            print("Proyecto inicializado en", settings.root)
        elif args.command == "doctor":
            from importlib.metadata import version
            print(json.dumps({"python": sys.version, "executable": sys.executable, "brave": str(find_brave(settings.brave_path)), "playwright": version("playwright"), "PySide6": version("PySide6"), "profile": str(settings.profile_path), "transport": settings.browser_transport, "mode": settings.mode}, ensure_ascii=False, indent=2))
        elif args.command == "smoke":
            from autojob.testing.smoke import run_smoke
            settings = replace(settings, headless=args.headless or settings.headless, browser_transport=args.transport or settings.browser_transport)
            print(json.dumps(run_smoke(settings), ensure_ascii=False, indent=2))
        elif args.command == "history":
            print(json.dumps(database.recent_runs(), ensure_ascii=False, indent=2))
        elif args.command == "recover":
            from autojob.browser.lock import ProfileLock
            lock = ProfileLock(settings.data_path / "browser.lock")
            lock.acquire()
            try:
                print("Pruebas marcadas como interrumpidas:", database.recover_runs())
            finally:
                lock.release()
        return 0
    except KeyboardInterrupt:
        print("Operación interrumpida.", file=sys.stderr)
        return 130
    except Exception as exc:
        import logging
        logging.getLogger("autojob").exception("Error de ejecución")
        print(f"Job Hunting: {exc}", file=sys.stderr)
        return 1
