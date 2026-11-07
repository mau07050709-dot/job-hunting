"""Laboratorio manual repetible desde la interfaz, con datos temporales ficticios."""
from tempfile import TemporaryDirectory
from pathlib import Path
from dataclasses import replace
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QTabWidget
from autojob.ui.accounts_widget import AccountsWidget,AuthWorker
from autojob.ui.identity_widget import IdentityWidget
from autojob.ui.queue_widget import QueueWidget
from autojob.ui.notifications_widget import NotificationsWidget
from autojob.auth.lab8b import run_lab

class ManualDemo(QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True);self.cleaned=False;self.setWindowTitle('Job Hunting · Laboratorio ficticio 8B');self.resize(1250,900);self.temp=TemporaryDirectory(prefix='autojob8b-manual-');self.root=Path(self.temp.name);self.settings=replace(settings,root=self.root,data_dir='data');self.worker=None
        layout=QVBoxLayout(self);self.label=QLabel('Solo datos ficticios. Los datos del laboratorio se eliminan al cerrar. En Brave, pulsa «He revisado el desafío ficticio» cuando aparezca; no es un CAPTCHA real.');self.label.setWordWrap(True);layout.addWidget(self.label);self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.accounts_widget=AccountsWidget(self.settings);self.identity_widget=IdentityWidget(self.settings);self.queue_widget=QueueWidget(self.settings);self.notifications_widget=NotificationsWidget(self.settings,self.queue_widget)
        for widget,title in [(self.accounts_widget,'Cuenta ficticia'),(self.notifications_widget,'Gestor de CAPTCHA'),(self.identity_widget,'Identificación ficticia')]:self.tabs.addTab(widget,title)
        QTimer.singleShot(300,self.start)
    def start(self):
        self.worker=AuthWorker(lambda:run_lab(self.settings,False,self.root));self.accounts_widget.worker=self.worker;self.worker.done.connect(self.accounts_widget.finished);self.worker.done.connect(lambda result:self.label.setText('Resultado de la prueba local disponible en Cuenta ficticia. No se enviaron postulaciones ni se transmitió identificación.'));self.worker.start()
    def closeEvent(self,event):
        if self.cleaned:event.accept();return
        if self.worker and self.worker.isRunning():
            for row in self.notifications_widget.store.list():
                if row['reserved']:self.notifications_widget.store.update(row['id'],command='OMITIR')
            self.label.setText('Se solicitó omitir y liberar la sesión. Espera un momento y vuelve a cerrar.');event.ignore();return
        if not self.notifications_widget.allow_close():event.ignore();return
        self.identity_widget.store.delete()
        for row in self.accounts_widget.store.list():self.accounts_widget.store.remove(row['id'])
        self.identity_widget.allow_close();self.notifications_widget.timer.stop();self.queue_widget.timer.stop();self.temp.cleanup();self.cleaned=True;event.accept()
