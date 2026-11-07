from PySide6.QtCore import QTimer,Qt,Slot
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QTableWidget,QTableWidgetItem,QPushButton,QLabel,QSystemTrayIcon,QStyle,QApplication
from autojob.auth.verifications import VerificationStore,bus,CaptchaCoordinator
from autojob.ui.accounts_widget import AuthWorker

class NotificationsWidget(QWidget):
    def __init__(self,settings,queue_widget):
        super().__init__();self.settings=settings;self.queue_widget=queue_widget;self.store=VerificationStore(settings.data_path);self.store.recover();self.worker=None;self.pending_resume=set();layout=QVBoxLayout(self);layout.addWidget(QLabel('Gestor de verificaciones CAPTCHA · Centro de notificaciones · Resolución humana, sin servicios de terceros'))
        self.status=QLabel('Un solo perfil de Brave: la reserva manual es temporal. Al omitir o vencer el plazo, la cola conserva el estado y continúa.');self.status.setWordWrap(True);layout.addWidget(self.status);self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['Empresa / vacante','Intervención','Estado','Sesión reservada','Enlace','Actualización']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table)
        row=QHBoxLayout()
        for label,fn in [('Resolver en Brave',self.resolve),('Omitir por ahora',self.skip),('Actualizar',self.refresh)]:b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row);self.tray=QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),self);self.tray.setToolTip('Job Hunting · Verificaciones pendientes');self.tray.show();self.tray.messageClicked.connect(self.focus);bus().notice.connect(self.notice,Qt.ConnectionType.QueuedConnection)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(1500);self.refresh()
    def refresh(self):
        items=self.table.selectedItems();selected=items[0].data(256) if items else None;self.rows=self.store.list();self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for c,value in enumerate([r['title'],r['kind'],r['state'],'Sí' if r['reserved'] else 'No',r['url'],r['updated_at']]):i=QTableWidgetItem(str(value));i.setData(256,r['id']);self.table.setItem(n,c,i)
            if r['id']==selected:self.table.selectRow(n)
        if self.pending_resume and not getattr(self,"coordinated",False) and not (self.queue_widget.worker and self.queue_widget.worker.isRunning()):
            ids=set(self.pending_resume);self.pending_resume.clear();self.queue_widget.queue.requeue(ids);self.queue_widget.start(ids=ids)
        for c,w in enumerate([300,220,210,130,450,210]):self.table.setColumnWidth(c,w)
    def selected(self):
        items=self.table.selectedItems();return next((r for r in self.rows if items and r['id']==items[0].data(256)),None)
    @Slot(str,str,str)
    def notice(self,id,title,body):
        if getattr(self,"silent_mode",False):return
        if not any(r['id']==id for r in self.store.list()):return
        self.last_id=id;self.tray.showMessage(title,body,QSystemTrayIcon.MessageIcon.Warning,10000);self.status.setText(title+' · '+body);self.refresh()
    def focus(self):
        window=self.window();window.showNormal();window.raise_();window.activateWindow()
        if hasattr(window,'tabs'):window.tabs.setCurrentWidget(self)
    def skip(self):
        r=self.selected()
        if r:self.store.update(r['id'],'OMITIDA',command='OMITIR');self.refresh();self.status.setText('Tarea conservada para otra ocasión; se libera la reserva cuando el trabajador recibe la orden.')
    def resolve(self):
        r=self.selected()
        if not r:return
        if getattr(self,'coordinated',False):
            center=self.window().shell.center;row=next((item for item in center.shell.engine.store.interventions() if item.get('verification_id')==r['id']),None)
            if row:center.resolve(row);return
        if r['kind']!='CAPTCHA PENDIENTE':self.status.setText('Esta verificación necesita intervención en la cuenta. No se leen correo ni SMS y no se inventan códigos.');return
        if r['reserved']:self.store.update(r['id'],command='RESOLVER');self.status.setText('Se enfocará la misma sesión reservada. Resuelve manualmente el desafío.');return
        if self.worker and self.worker.isRunning():self.status.setText('Ya hay una sesión de intervención abierta.');return
        from autojob.browser import BraveSession
        from autojob.forms.guard import PreparationGuard
        def run():
            with BraveSession(self.settings) as browser:
                guard=PreparationGuard(browser);page=guard.page(r['url'])
                # La sesión perdida se reconstruye; nunca se supone que el portal conservó respuestas.
                from autojob.auth.verifications import captcha_state
                if not captcha_state(page)['detected']:return dict(completed=False,reason='No se encontró un estado de CAPTCHA verificable; revisa la cuenta.')
                id=self.store.add(r['job_id'],r['kind'],r['url'],r['title'],True);self.store.update(id,command='RESOLVER')
                completed=CaptchaCoordinator(self.settings.data_path).wait(page,guard,r['job_id'],r['title'],seconds=120,manual_start=True)
                return dict(completed=completed,job_id=r['job_id'])
        self.worker=AuthWorker(run);self.worker.done.connect(self.finished);self.worker.start();self.status.setText('Abriendo sesión de intervención manual; se respeta el bloqueo del perfil de Brave.')
    def finished(self,result):
        self.refresh();value=result.get('result') or {}
        if result.get('ok') and value.get('completed'):
            id=value['job_id'];self.pending_resume.add(id);self.status.setText('Verificación completada. Se vuelve a analizar y preparar la vacante, sin enviar solicitudes.')
        else:self.status.setText('Intervención conservada pendiente; no se confirma una verificación sin evidencia del portal.')
    def allow_close(self):
        if self.worker and self.worker.isRunning():self.status.setText('Omite la intervención o espera su plazo antes de cerrar.');return False
        self.tray.hide();return True
