import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from autojob.config import Settings
from autojob.ui.main_window import MainWindow


def test_window_and_config(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Settings(root=tmp_path))
    window.show()
    app.processEvents()
    assert window.run_button.isEnabled()
    assert window.table.columnCount() == 4
    window.transport.setCurrentText("cdp")
    window.save_settings()
    assert Settings.load(tmp_path).browser_transport == "cdp"
    window.close()
    app.processEvents()
