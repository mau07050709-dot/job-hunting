from dataclasses import replace
from datetime import datetime, timezone
import json
import logging

from playwright.sync_api import expect

from autojob.browser import BraveSession
from autojob.config import Settings
from autojob.storage.database import Database
from autojob.testing.server import local_server


def run_smoke(settings: Settings) -> dict:
    database = Database(settings.data_path / "autojob.sqlite3")
    run_id = database.start_run("brave-smoke-" + settings.browser_transport)
    artifacts = settings.data_path / "evidence" / run_id
    artifacts.mkdir(parents=True, exist_ok=True)
    report = {"run_id": run_id, "transport": settings.browser_transport, "headless": settings.headless, "started_at": datetime.now(timezone.utc).isoformat(), "success": False, "scope": "Formulario local; no se contactaron empresas"}
    document = artifacts / "documento-prueba.txt"
    document.write_text("Documento sintético de Job Hunting. No es un CV real.", encoding="utf-8")
    try:
        with local_server() as (url, submissions):
            session = BraveSession(settings)
            with session:
                page = session.new_page(url)
                version_page = session.new_page("brave://version/")
                report["browser_version"] = version_page.locator("body").inner_text()[:6000]
                assert "Brave" in report["browser_version"]
                for unsafe_flag in ("--no-sandbox", "--disable-web-security", "--disable-client-side-phishing-detection", "--disable-ipc-flooding-protection", "--password-store=basic"):
                    assert unsafe_flag not in report["browser_version"], f"Argumento no permitido: {unsafe_flag}"
                session.switch_to(page)
                expect(page).to_have_title("Job Hunting — prueba local")
                report["offer_text_read"] = "Vacante ficticia" in page.locator("body").inner_text()
                page.get_by_label("Nombre completo").fill("Persona de prueba")
                page.get_by_label("Correo electrónico").fill("prueba@example.invalid")
                page.get_by_label("Modalidad").select_option("remote")
                page.get_by_label("Documento de prueba").set_input_files(document)
                page.get_by_label("Confirmo que estos datos son ficticios").check()
                expect(page.get_by_label("Nombre completo")).to_have_value("Persona de prueba")
                expect(page.get_by_label("Correo electrónico")).to_have_value("prueba@example.invalid")
                expect(page.get_by_label("Modalidad")).to_have_value("remote")
                expect(page.get_by_label("Confirmo que estos datos son ficticios")).to_be_checked()
                assert page.get_by_label("Documento de prueba").evaluate("el => el.files[0].name") == document.name
                page.get_by_role("button", name="Enviar prueba local").click()
                expect(page.get_by_role("status")).to_contain_text("RECIBIDA: LOCAL-")
                assert len(submissions) == 1, "El servidor debe recibir una sola prueba"
                received = submissions[0]
                assert received["email"] == "prueba@example.invalid" and received["name"] == "Persona de prueba"
                assert received["modality"] == "remote" and received["file"] == document.name and received["consent"] is True
                expect(page.get_by_role("status")).to_contain_text(received["receipt"])
                report["receipt"] = received["receipt"]
                page.screenshot(path=str(artifacts / "confirmacion.png"), full_page=True)
                report["checks"] = ["Brave real", "navegación HTTP local", "lectura de oferta", "cambio de pestaña", "texto", "selección", "casilla", "archivo", "validación antes de envío", "recepción HTTP y confirmación DOM"]
            assert session.context is None
            report["session_closed"] = True
            # El mismo perfil debe poder abrirse otra vez: verifica cierre y recuperación.
            with BraveSession(replace(settings, timeout_ms=max(settings.timeout_ms, 15000))) as reopened:
                recovered_page = reopened.new_page(url)
                expect(recovered_page.get_by_role("heading")).to_have_text("Job Hunting · laboratorio local")
            report["profile_reopened"] = True
        report["success"] = True
    except Exception as exc:
        report["error"] = str(exc)
        logging.getLogger("autojob").exception("Falló prueba local de Brave")
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["artifacts"] = str(artifacts)
        (artifacts / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        database.finish_run(run_id, report["success"], report)
    return report
