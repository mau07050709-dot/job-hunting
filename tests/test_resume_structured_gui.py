import os
import time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from autojob.config import Settings
from autojob.ui.main_window import MainWindow
from resume_fixtures import write_docx


def wait(app, widget):
    until = time.monotonic() + 20
    while widget.worker.isRunning() and time.monotonic() < until:
        app.processEvents()
        time.sleep(.01)
    assert widget.worker.wait(20000)
    app.processEvents()


def test_structured_editor_and_nondestructive_reprocess(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Settings(root=tmp_path))
    window.show()
    widget = window.resumes_widget
    widget.start_import(write_docx(tmp_path / "cv.docx"))
    wait(app, widget)
    editor = widget.record_editor
    assert editor.table.rowCount() == 1
    assert "Example Labs" in editor.widgets["company"].text()
    assert "FUENTE ORIGINAL" in editor.sources.toPlainText()
    assert "Automático" in editor.table.item(0,2).text()
    editor.widgets["company"].setText("Empresa corregida")
    widget.fields["full_name"].setText("Nombre corregido")
    assert "Manual" in widget.field_labels["full_name"].text()
    assert "#67dfad" in editor.widgets["company"].styleSheet()
    # Reprocesar debe guardar primero las correcciones que se están editando.
    widget.start_reprocess()
    wait(app, widget)
    assert widget.current["fields"]["full_name"] == "Nombre corregido"
    assert widget.current["structure"]["experience"][0]["company"] == "Empresa corregida"
    assert widget.record_editor.widgets["company"].toolTip() == "Corrección manual"
    assert widget.current["provenance"]["email"] == "automatic"
    assert len(widget.library.versions(widget.current["id"])) == 1
    window.close()
    app.processEvents()


def test_structured_add_delete_and_reprocess_keep_manual_category(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Settings(root=tmp_path))
    widget = window.resumes_widget
    widget.start_import(write_docx(tmp_path / "cv.docx"))
    wait(app, widget)
    editor = widget.record_editor
    editor.category.setCurrentIndex(editor.category.findData("academic_projects"))
    editor.add_record()
    editor.widgets["name"].setText("Proyecto escrito por el usuario")
    editor.widgets["description"].setPlainText("Descripción manual verificable")
    widget.save_current()
    assert widget.current["structure"]["academic_projects"][-1]["name"] == "Proyecto escrito por el usuario"
    widget.start_reprocess()
    wait(app, widget)
    editor.category.setCurrentIndex(editor.category.findData("academic_projects"))
    assert len(widget.current["structure"]["academic_projects"]) == 2
    editor.remove_record()
    widget.save_current()
    assert len(widget.current["structure"]["academic_projects"]) == 1
    window.close()
