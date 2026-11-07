"""Opt-in: JOB_HUNTING_TEST_BRAVE=1. Ejecuta Brave real contra páginas locales."""
import json
import os
import subprocess
import time

import pytest
from PySide6.QtWidgets import QApplication

from autojob.browser import BraveSession
from autojob.config import Settings
from autojob.errors import BrowserError
from autojob.testing.server import local_server
from autojob.testing.smoke import run_smoke
from autojob.ui.main_window import MainWindow

pytestmark = pytest.mark.skipif(os.environ.get("JOB_HUNTING_TEST_BRAVE", os.environ.get("AUTOJOB_TEST_BRAVE")) != "1", reason="Activa JOB_HUNTING_TEST_BRAVE=1 para abrir Brave real")


@pytest.mark.parametrize("transport", ["persistent", "cdp"])
def test_brave_real_form(tmp_path, transport):
    report = run_smoke(Settings(root=tmp_path, browser_transport=transport, headless=True))
    assert report["success"] and report["session_closed"] and report["profile_reopened"]
    assert report["offer_text_read"]
    assert report["receipt"].startswith("LOCAL-")


def test_http_error_disconnect_and_recovery(tmp_path):
    session = BraveSession(Settings(root=tmp_path, headless=True))
    with local_server() as (url, _):
        with session:
            with pytest.raises(BrowserError, match="HTTP 404"):
                session.new_page(url + "missing")
            page = session.new_page(url)
            assert "Job Hunting" in page.title()
            session.context.close()  # Simula cierre del navegador por el usuario.
            with pytest.raises(BrowserError, match="No se pudo abrir"):
                session.new_page(url)
        with session:
            assert "Job Hunting" in session.new_page(url).title()


def test_cdp_binds_only_loopback_and_process_exits(tmp_path):
    if os.name != "nt":
        pytest.skip("Verificación de sockets de Windows")
    session = BraveSession(Settings(root=tmp_path, browser_transport="cdp", headless=True))
    with session:
        process = session._process
        output = subprocess.check_output([
            "powershell.exe", "-NoProfile", "-Command",
            f"@(Get-NetTCPConnection -State Listen -OwningProcess {process.pid} -ErrorAction Stop | Select-Object -ExpandProperty LocalAddress) | ConvertTo-Json -Compress"
        ], text=True)
        addresses = json.loads(output)
        if isinstance(addresses, str):
            addresses = [addresses]
        assert addresses and set(addresses) <= {"127.0.0.1", "::1"}
    assert process.poll() is not None


def test_gui_worker_runs_real_brave(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Settings(root=tmp_path, headless=True))
    window.show()
    window.start_smoke()
    deadline = time.monotonic() + 60
    while window.worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if window.worker.isRunning():
        window.worker.wait(30000)
        pytest.fail("El worker de la interfaz excedió el tiempo de prueba")
    app.processEvents()
    assert window.run_button.isEnabled()
    assert "completada" in window.status.text()
    assert json.loads(window.output.toPlainText())["success"]
    assert window.table.rowCount() == 1
    window.close()
