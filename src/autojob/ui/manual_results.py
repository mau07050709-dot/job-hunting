from PySide6.QtWidgets import QCheckBox,QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QPushButton,QHBoxLayout,QApplication
from PySide6.QtCore import Qt
from threading import Event, Thread
from queue import Queue

class ManualBrowser:
    """Entrega enlaces al Brave normal, sin controlar ni poseer su perfil."""
    def __init__(self,settings):
        self.settings=settings;self.events=Queue();self.stop=Event()
    def open(self,url):
        from autojob.manual_search import useful_url
        if not useful_url(url):raise ValueError('El enlace no identifica una oferta pública utilizable.')
        Thread(target=self.launch,args=(url,),daemon=True).start()
    def launch(self,url,announce=True):
        from autojob.browser.discovery import find_brave
        import subprocess
        if self.stop.is_set():return False
        try:
            subprocess.Popen([str(find_brave(self.settings.brave_path)),'--new-tab',url],close_fds=True)
            if announce:self.events.put('Enlace enviado a tu Brave principal. Completa allí la postulación manualmente.')
            return True
        except (OSError,RuntimeError) as exc:
            self.events.put('No se pudo abrir tu Brave principal ('+type(exc).__name__+'). Los enlaces siguen guardados.')
            return False

class LinksDialog(QDialog):
    def __init__(self,shell,result,review_only=False):
        super().__init__(shell.window);self.setWindowTitle('Puestos encontrados — postulación manual');self.resize(1100,650);self.shell=shell;self.verified=result.get('results',[]);self.unverified=result.get('review',[]);self.rows=self.unverified if review_only else self.verified;layout=QVBoxLayout(self)
        if review_only:self.setWindowTitle('Enlaces por verificar — revisión manual')
        info=QLabel(f'{len(self.rows)} enlaces por verificar. No se ha confirmado que estas páginas estén disponibles; revísalas manualmente en Brave.' if review_only else result.get('reason',''));info.setWordWrap(True);layout.addWidget(info)
        note=QLabel('Abre cada enlace y completa tú la postulación en Brave. Geografía posible/desconocida requiere revisión; no significa que Costa Rica esté admitida.');note.setWordWrap(True);layout.addWidget(note)
        toggle=QCheckBox('Mostrar también enlaces por verificar (pueden no estar disponibles)');toggle.toggled.connect(self.toggle);layout.addWidget(toggle)
        if review_only:toggle.hide()
        self.table=QTableWidget(len(self.rows),6);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Ubicación','Geografía','Afinidad orientativa','Enlace']);self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for n,r in enumerate(self.rows):
            for c,v in enumerate([r['job']['company'],r['job']['title'],r['job'].get('location'),r.get('geography'),r.get('score'),r['url']]):self.table.setItem(n,c,QTableWidgetItem(str(v if v is not None else 'Desconocido')))
        self.table.horizontalHeader().setStretchLastSection(True);self.table.setColumnWidth(0,145);self.table.setColumnWidth(1,285);self.table.setColumnWidth(3,115);self.table.setColumnWidth(4,150);layout.addWidget(self.table);buttons=QHBoxLayout()
        for title,fn in [('ABRIR EN BRAVE',self.open),('RELLENAR AUTOMÁTICAMENTE',self.fill),('COPIAR TODOS LOS ENLACES',self.copy),('CERRAR',self.close)]:b=QPushButton(title);b.clicked.connect(fn);buttons.addWidget(b)
        layout.addLayout(buttons);self.table.doubleClicked.connect(self.open)
        if self.rows:self.table.selectRow(0)
    def toggle(self,enabled):
        self.rows=self.verified+self.unverified if enabled else self.verified;self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for c,v in enumerate([r['job']['company'],r['job']['title'],r['job'].get('location'),r.get('geography'),r.get('score'),r['url']]):self.table.setItem(n,c,QTableWidgetItem(str(v if v is not None else 'Desconocido')))
        if self.rows:self.table.selectRow(0)
    def open(self,*a):
        n=self.table.currentRow()
        if 0<=n<len(self.rows):self.shell.manual_browser.open(self.rows[n]['url'])
    def fill(self):
        n=self.table.currentRow()
        if 0<=n<len(self.rows):self.shell.fill_selected(self.rows[n])
    def copy(self):QApplication.clipboard().setText('\n'.join(r['job']['company']+' — '+r['job']['title']+'\n'+r['url'] for r in self.rows))
