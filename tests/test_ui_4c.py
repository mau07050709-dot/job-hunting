import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from autojob.config import Settings
from autojob.ui.main_window import MainWindow

def test_simulator_ui_and_persistence(tmp_path):
 app=QApplication.instance() or QApplication([]);window=MainWindow(Settings(root=tmp_path));window.show();ui=window.simulator_widget
 ui.scenario.setCurrentText('Obstáculos');ui.position.setText('Developer');ui.run()
 assert 'CAPTCHA' in ui.result.toPlainText() and 'PENDIENTE' in ui.result.toPlainText()
 window.close();app.processEvents();other=MainWindow(Settings(root=tmp_path));assert other.simulator_widget.history.count()==1;other.close()
