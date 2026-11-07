import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from autojob.config import Settings
from autojob.resumes.service import ResumeLibrary
from autojob.ui.main_window import MainWindow
from resume_fixtures import EN_SERVICE, write_docx, write_pdf


def wait_worker(app, widget):
    deadline = time.monotonic() + 20
    while widget.worker and widget.worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    if widget.worker:
        assert widget.worker.wait(20000)
    app.processEvents()
    assert widget.import_button.isEnabled()


def test_gui_import_review_select_replace_delete_and_restart(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings = Settings(root=tmp_path)
    window = MainWindow(settings)
    window.show()
    cv = window.resumes_widget
    window.tabs.setCurrentWidget(cv)
    assert window.tabs.tabText(1) == "Mis currículums"
    source = write_docx(tmp_path / "tech-en.docx")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(source), ""))
    QTest.mouseClick(cv.import_button, Qt.MouseButton.LeftButton)
    wait_worker(app, cv)
    assert cv.table.rowCount() == 1
    assert cv.fields["email"].text() == "alex@example.invalid"
    cv.title.setText("Técnico en inglés")
    cv.fields["phone"].setText("+506 8888-0000")
    cv.reviewed.setChecked(True)
    QTest.mouseClick(cv.save_button, Qt.MouseButton.LeftButton)
    assert cv.current["reviewed"]
    assert cv.current["fields"]["phone"] == "+506 8888-0000"
    QTest.mouseClick(cv.default_button, Qt.MouseButton.LeftButton)
    assert cv.library.get(cv.current["id"])["is_default"]
    cv.detail_tabs.setCurrentIndex(3)
    cv.vacancy.setPlainText("Junior Python Developer")
    QTest.mouseClick(cv.select_button, Qt.MouseButton.LeftButton)
    assert "Técnico en inglés" in cv.selection_result.toPlainText()
    assert "compatible" in cv.selection_result.toPlainText()
    assert "Documento" in cv.source.toPlainText()
    assert "Fuentes:" in cv.audit.toPlainText()
    # Mismo contenido mediante diálogo: no agrega una segunda fila.
    cv.start_import(source)
    wait_worker(app, cv)
    assert cv.table.rowCount() == 1 and "duplicado" in cv.message.text()
    # Sustitución desde el control público de la interfaz.
    replacement = write_pdf(tmp_path / "tech-es.pdf")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(replacement), ""))
    QTest.mouseClick(cv.replace_button, Qt.MouseButton.LeftButton)
    wait_worker(app, cv)
    assert cv.current["language"] == "es" and not cv.current["reviewed"]
    assert len(cv.library.versions(cv.current["id"])) == 2
    identity = cv.current["id"]
    window.close()
    app.processEvents()
    reopened = MainWindow(settings)
    reopened.show()
    app.processEvents()
    cv = reopened.resumes_widget
    assert cv.current["id"] == identity
    assert cv.current["language"] == "es"
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    QTest.mouseClick(cv.delete_button, Qt.MouseButton.LeftButton)
    assert cv.table.rowCount() == 0 and source.exists() and replacement.exists()
    reopened.close()
    app.processEvents()


def test_gui_corrupt_file_and_unknown_values(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Settings(root=tmp_path))
    window.show()
    cv = window.resumes_widget
    damaged = tmp_path / "damaged.docx"
    damaged.write_bytes(b"bad")
    cv.start_import(damaged)
    wait_worker(app, cv)
    assert cv.table.rowCount() == 0 and "dañado" in cv.message.text()
    source = write_docx(tmp_path / "service.docx", EN_SERVICE)
    cv.start_import(source)
    wait_worker(app, cv)
    assert cv.fields["phone"].text() == ""
    assert cv.fields["phone"].placeholderText() == "Desconocido"
    window.close()
    app.processEvents()


def test_gui_rules_dialog_saves(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Settings(root=tmp_path))
    cv = window.resumes_widget
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit

    def edit_open_dialog():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QDialog)
        editors = dialog.findChildren(QPlainTextEdit)
        editors[1].appendPlainText("MoonDesk assistant")
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.StandardButton.Save).click()

    QTimer.singleShot(100, edit_open_dialog)
    cv.edit_rules()
    assert "MoonDesk assistant" in cv.selector.load_rules()["customer_service"]
    window.close()
