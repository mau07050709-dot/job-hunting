import json
from threading import Event
from PySide6.QtCore import QThread,Signal,QTimer,Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QPushButton,QLabel,QComboBox,QTableWidget,QTableWidgetItem,QPlainTextEdit,QAbstractItemView,QInputDialog,QMessageBox,QFileDialog
from autojob.forms.queue import PreparationQueue

class QueueWorker(QThread):
 progress=Signal(str);done=Signal(object)
 def __init__(self,queue,settings,ids=None):super().__init__();self.queue=queue;self.settings=settings;self.ids=ids;self.paused=Event();self.stopped=Event()
 def run(self):
  try:self.done.emit(self.queue.run(self.settings,self.ids,self.paused.is_set,self.stopped.is_set,self.progress.emit))
  except Exception as exc:self.done.emit(dict(error=type(exc).__name__))

class SafeReviewWorker(QThread):
 status=Signal(str)
 def __init__(self,settings,url):super().__init__();self.settings=settings;self.url=url
 def run(self):
  from autojob.browser import BraveSession
  from autojob.forms.guard import PreparationGuard
  try:
   with BraveSession(self.settings) as browser:
    guard=PreparationGuard(browser);page=guard.page(self.url);guard.freeze();self.status.emit('Brave en modo preparación: envío y adjuntos externos bloqueados.')
    while not self.isInterruptionRequested() and not page.is_closed():self.msleep(200)
  except Exception as exc:self.status.emit('No se pudo abrir el modo de preparación: '+type(exc).__name__)

class QueueWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.settings=settings;self.queue=PreparationQueue(settings.data_path);self.worker=None;self.offer=None;recovered=self.queue.recover();layout=QVBoxLayout(self);title=QLabel('Cola de postulaciones · Preparación sin envío · Adjuntos externos deshabilitados');title.setWordWrap(True);layout.addWidget(title)
  row=QHBoxLayout();self.jobs=QComboBox();self.job_rows=self.queue.preparation.compatibility.jobs.list()
  for job in self.job_rows:self.jobs.addItem(job['company']+' · '+job['title'],job['id'])
  row.addWidget(self.jobs);button=QPushButton('Añadir a cola');button.clicked.connect(lambda:self.add_ids([self.jobs.currentData()]));row.addWidget(button);layout.addLayout(row)
  grid=QGridLayout()
  actions=[('Preparar seleccionadas',self.selected_start),('Iniciar cola',self.start),('Pausar',self.pause),('Reanudar',self.resume),('Detener',self.stop),('Abrir formulario en Brave',self.open_form),('Revisar respuestas',self.details),('Ver obstáculos',self.blocks),('Reintentar',self.retry),('Eliminar de cola',self.remove),('Prioridad',self.priority),('Actualizar',self.refresh),('Editar enlace público',self.edit_url),('Autorizar texto para este origen',self.authorize),('Revocar autorización',self.revoke)]
  for i,(text,fn) in enumerate(actions):button=QPushButton(text);button.clicked.connect(fn);grid.addWidget(button,i//5,i%5)
  layout.addLayout(grid);self.status=QLabel('Recuperadas '+str(recovered)+' entradas interrumpidas. Sin permisos nuevos: inspección externa de solo lectura.');self.status.setWordWrap(True);layout.addWidget(self.status);self.counter=QLabel();layout.addWidget(self.counter)
  self.table=QTableWidget(0,11);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Compatibilidad','CV seleccionado','Estado','Completados','Pendientes','Obstáculos','Última acción','Preparación / última actualización','Acceso / verificación']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.details);layout.addWidget(self.table,3);self.output=QPlainTextEdit();self.output.setReadOnly(True);layout.addWidget(self.output,2)
  self.timer=QTimer(self);self.timer.timeout.connect(lambda:self.refresh() if self.isVisible() or self.worker and self.worker.isRunning() else None);self.timer.start(1500);self.refresh()
 def ids(self):return {i.data(256) for i in self.table.selectedItems()}
 def add_ids(self,ids,url=None):
  ids=[id for id in ids if id]
  if not ids:self.status.setText('Selecciona una o varias vacantes.');return
  n=self.queue.add(ids,url);self.refresh();self.status.setText(str(n)+' añadidas · '+str(len(ids)-n)+' duplicadas o ya presentes.')
 def refresh(self,*_):
  selected=self.ids();self.rows=self.queue.list();self.table.blockSignals(True);self.table.setRowCount(len(self.rows))
  counts={}
  for i,row in enumerate(self.rows):
   p=row['payload'];counts[row['state']]=counts.get(row['state'],0)+1;cv=p.get('cv') or {};values=[p.get('company'),p.get('title'),p.get('score'),cv.get('cv_title') or cv.get('title') or 'Pendiente',row['state'],len(p.get('filled',[])),len(p.get('pending',[])),', '.join(b.get('type','') for b in p.get('blocks',[])),row['last_action'],p.get('prepared_at') or row['updated_at'],p.get('verification_status') or (p.get('authentication') or {}).get('task') or 'Sin bloqueo de acceso conocido']
   for c,value in enumerate(values):item=QTableWidgetItem(str(value if value is not None else 'Desconocido'));item.setData(256,row['job_id']);item.setToolTip(item.text());self.table.setItem(i,c,item)
   if row['job_id'] in selected:
    for c in range(11):self.table.item(i,c).setSelected(True)
  self.table.blockSignals(False)
  for i,w in enumerate([140,270,110,200,180,100,100,230,330,220]):self.table.setColumnWidth(i,w)
  self.counter.setText(f"Preparadas: {counts.get('PREPARADA',0)} · Pendientes / revisión: {counts.get('PENDIENTE',0)+counts.get('REQUIERE REVISIÓN',0)} · Bloqueadas: {counts.get('BLOQUEADA',0)} · Errores: {counts.get('ERROR',0)} · Por preparar: {counts.get('POR PREPARAR',0)}")
 def start(self,*_,ids=None):
  if self.worker and self.worker.isRunning():self.status.setText('Espera a que termine la pausa u operación actual.');return
  self.worker=QueueWorker(self.queue,self.settings,ids);self.worker.progress.connect(self.status.setText);self.worker.done.connect(self.finished);self.worker.start()
 def selected_start(self):
  ids=self.ids()
  if not ids:self.status.setText('Selecciona entradas de la cola.');return
  self.queue.requeue(ids);self.start(ids=ids)
 def pause(self):
  if self.worker:self.worker.paused.set();self.status.setText('Pausa solicitada; se conserva el último campo verificado antes de liberar Brave.')
 def stop(self):
  if self.worker:self.worker.stopped.set();self.status.setText('Detención solicitada; no se perderán los resultados guardados.')
 def resume(self):
  self.queue.requeue([r['job_id'] for r in self.queue.list()],interrupted_only=True);self.start()
 def finished(self,result):self.status.setText('Resultado local: '+json.dumps(result,ensure_ascii=False)+' · Nunca se realizaron envíos.');self.refresh()
 def chosen(self):return next((r for r in self.rows if r['job_id'] in self.ids()),None)
 def details(self):
  row=self.chosen()
  if row:self.output.setPlainText(json.dumps(dict(row,history=self.queue.history(row['job_id'])),ensure_ascii=False,indent=2))
 def blocks(self):
  row=self.chosen()
  if row:self.output.setPlainText(json.dumps(row['payload'].get('blocks',[]),ensure_ascii=False,indent=2))
 def retry(self):self.selected_start()
 def remove(self):self.queue.remove(self.ids());self.refresh()
 def priority(self):
  row=self.chosen()
  if row:
   value,ok=QInputDialog.getInt(self,'Prioridad','Mayor número = primero',row['priority'],-1000000,1000000)
   if ok:self.queue.priority(row['job_id'],value);self.refresh()
 def edit_url(self):
  row=self.chosen()
  if row and row['state'] not in {'ANALIZANDO','RELLENANDO'}:
   value,ok=QInputDialog.getText(self,'Enlace público','Formulario o ficha oficial:',text=row['url'])
   if ok:
    from autojob.forms.guard import origin
    try:origin(value)
    except ValueError:self.status.setText('URL no válida.');return
    from contextlib import closing
    with closing(self.queue.db.connect()) as db,db:db.execute('UPDATE preparation_queue SET url=? WHERE job_id=?',(value,row['job_id']))
    self.queue.update(row['job_id'],'POR PREPARAR','URL editada explícitamente; reanalizar.');self.refresh()
 def authorize(self):
  row=self.chosen()
  if not row:return
  from autojob.forms.guard import origin
  url=row['payload'].get('last_url') or row['url'];site=origin(url)
  if QMessageBox.question(self,'Autorización específica de texto',f'¿Autorizas introducir datos confirmados en el DOM de {site}? Solo se habilita con elegibilidad, geografía y vigencia confirmadas. Los scripts del sitio pueden leer los campos; nuevas transmisiones, adjuntos y envío final seguirán bloqueados. Los permisos caducan si cambian tus datos.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:self.queue.allow_site(url,True);self.status.setText('Autorización de texto guardada para '+site+'; los CV externos siguen bloqueados.')
 def revoke(self):
  row=self.chosen()
  if row:self.queue.allow_site(row['payload'].get('last_url') or row['url'],False);self.status.setText('Permiso de texto revocado.')
 def open_form(self):
  row=self.chosen()
  if not row:return
  from autojob.live import historical,command
  from autojob.forms.submissions import SubmissionStore
  if historical(SubmissionStore(self.settings.data_path),row['job_id']):self.status.setText('Resultado final existente: revisar o incorporar comprobante, sin reabrir el formulario.');return
  if command(row['job_id'],'FOCUS'):self.status.setText('Se enfoca la sesión preparada original.');return
  if self.offer and self.offer.isRunning():self.status.setText('Cierra la ventana anterior de preparación.');return
  self.offer=SafeReviewWorker(self.settings,row['payload'].get('last_url') or row['url']);self.offer.status.connect(self.status.setText);self.offer.start()
 def allow_close(self):
  if self.worker and self.worker.isRunning():self.stop();return False
  if self.offer and self.offer.isRunning():self.offer.requestInterruption();return False
  return True

def connect_source(window, widget, preparation=False):
 if preparation:
  button=QPushButton('Añadir vacante actual a cola')
  def add():
   queue=window.queue_widget
   job=widget.selected_job()
   queue.add_ids([job['id']] if job else [],widget.url.text().strip() or None)
   window.tabs.setCurrentWidget(queue)
 else:
  widget.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
  widget.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
  button=QPushButton('Añadir seleccionadas a cola de postulaciones')
  def add():
   queue=window.queue_widget
   queue.add_ids({item.data(256) for item in widget.table.selectedItems()})
   window.tabs.setCurrentWidget(queue)
 widget.layout().insertWidget(1,button)
 button.clicked.connect(add)
