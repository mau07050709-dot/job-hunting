import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from autojob.ui.main_window import MainWindow
from autojob.config import Settings

def test_answer_bank_gui(tmp_path):
 app=QApplication.instance() or QApplication([]);window=MainWindow(Settings(root=tmp_path));window.show();widget=window.answers_widget
 widget.language.setCurrentIndex(widget.language.findData('en'));widget.questions.setPlainText('What is your full name?');widget.answer.setPlainText('Test Name');widget.approved.setChecked(True);widget.save()
 widget.question.setText('Full name');widget.preview();assert 'Test Name' in widget.result.toPlainText()
 window.close();app.processEvents();other=MainWindow(Settings(root=tmp_path));assert other.answers_widget.items.count()==1;other.close()
