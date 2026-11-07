import json
from datetime import date
from pathlib import Path
from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QCheckBox,QComboBox,QPushButton,QScrollArea,QTabWidget,QTableWidget,QTableWidgetItem,QMessageBox,QFileDialog,QInputDialog,QAbstractItemView
from autojob.profile.application_data import ApplicationData,GROUPS,FIELDS,BOOLS,detect_windows
from autojob.profile.calculations import age
from autojob.profile.store import today
from autojob.forms.preparation import Preparation,inspect_url
from autojob.ui.queue_widget import SafeReviewWorker as OfferWorker

class TaskWorker(QThread):
 done=Signal(object);failed=Signal(str)
 def __init__(self,fn):super().__init__();self.fn=fn
 def run(self):
  try:self.done.emit(self.fn())
  except Exception as exc:self.failed.emit(type(exc).__name__+': '+str(exc)[:240])

class ApplicationDataWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.store=ApplicationData(settings.data_path);self.worker=None;self.controls={};self.checks={};self.loading=False;layout=QVBoxLayout(self)
  label=QLabel('Datos para postulaciones · Todo se guarda localmente. Marca Confirmado solo tras revisar; desconocido puede quedar vacío.');label.setWordWrap(True);layout.addWidget(label);row=QHBoxLayout()
  for title,fn in [('Guardar',self.save),('Actualizar',self.refresh),('Eliminar datos del bloque',self.delete_group),('Detectar equipo Windows',self.detect)]:
   button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button)
  layout.addLayout(row);self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status);self.tabs=QTabWidget();layout.addWidget(self.tabs)
  for group,fields in GROUPS.items():
   scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);scroll.setWidget(body);self.tabs.addTab(scroll,group)
   for key,label in fields.items():
    if key in BOOLS:control=QComboBox();control.addItems(['Desconocido','Sí','No'])
    elif key.endswith('_period'):control=QComboBox();control.addItems(['','month','year','hour'])
    elif key.endswith('_basis'):control=QComboBox();control.addItems(['','gross','net'])
    elif key in {'professional_links','other_work_permits','remote_conditions','onsite_conditions','international_expectations','preferred_schedule'}:control=QPlainTextEdit();control.setMaximumHeight(85)
    else:control=QLineEdit();control.setPlaceholderText('Desconocido / sin proporcionar')
    check=QCheckBox('Confirmado');self.controls[key]=control;self.checks[key]=check;row=QHBoxLayout();row.addWidget(control);row.addWidget(check);form.addRow(label,row)
    signal=control.currentIndexChanged if isinstance(control,QComboBox) else control.textChanged
    signal.connect(lambda *_,key=key:self.edited(key))
  from autojob.ui.identity_widget import IdentityWidget
  self.identity_widget=IdentityWidget(settings);self.tabs.addTab(self.identity_widget,'Identificación personal')
  self.age_label=QLabel();layout.addWidget(self.age_label);self.conversions=QLabel();self.conversions.setWordWrap(True);layout.addWidget(self.conversions)
  faq_widget=QWidget();faq_layout=QVBoxLayout(faq_widget);self.faq_company=QLineEdit();self.faq_company.setPlaceholderText('Empresa / contexto específico (obligatorio para empleo anterior)');faq_layout.addWidget(self.faq_company);self.faq_question=QLineEdit();self.faq_question.setPlaceholderText('Pregunta exacta en español o inglés');faq_layout.addWidget(self.faq_question);self.faq_kind=QComboBox();self.faq_kind.addItems(['DESCONOCIDO','SÍ','NO','Personalizada']);faq_layout.addWidget(self.faq_kind);self.faq_answer=QPlainTextEdit();self.faq_answer.setMaximumHeight(90);faq_layout.addWidget(self.faq_answer);self.faq_confirm=QCheckBox('Respuesta revisada y aprobada para este contexto');faq_layout.addWidget(self.faq_confirm);row=QHBoxLayout()
  for title,fn in [('Guardar respuesta',self.save_faq),('Eliminar respuesta seleccionada',self.delete_faq)]:button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button)
  faq_layout.addLayout(row);self.faq_table=QTableWidget(0,4);self.faq_table.setHorizontalHeaderLabels(['Empresa / contexto','Pregunta','Respuesta','Confirmada']);self.faq_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.faq_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.faq_table.itemSelectionChanged.connect(self.load_faq);faq_layout.addWidget(self.faq_table);self.tabs.addTab(faq_widget,'Preguntas frecuentes')
  self.refresh()
 def edited(self,key):
  if not self.loading:self.checks[key].setChecked(False)
  if key=='birth_date':self.update_age()
 def read(self,key):
  c=self.controls[key]
  if key in BOOLS:return [None,True,False][c.currentIndex()]
  text=c.currentText() if isinstance(c,QComboBox) else c.toPlainText() if isinstance(c,QPlainTextEdit) else c.text()
  return text.strip() or None
 def set_value(self,key,value):
  c=self.controls[key]
  if key in BOOLS:c.setCurrentIndex(0 if value is None else 1 if value else 2)
  elif isinstance(c,QComboBox):c.setCurrentText(value or '')
  elif isinstance(c,QPlainTextEdit):c.setPlainText(value or '')
  else:c.setText(value or '')
 def refresh(self):
  with self.store.read_snapshot():
   self._refresh()
 def _refresh(self):
  self.loading=True;self.saved=self.store.load();self.revisions={k:r['revision'] for k,r in self.saved.items()}
  for key in self.controls:
   r=self.saved.get(key,{});self.set_value(key,r.get('value'));self.checks[key].setChecked(r.get('confirmed',False))
  self.loading=False;self.update_age();conflicts=self.store.conflicts();self.status.setText('Conflictos con Mi perfil: '+', '.join(FIELDS.get(k,k) for k in conflicts) if conflicts else 'Listo. Los datos de Mi perfil se consultan sin sobrescribirlos; no se importan como confirmados automáticamente.');self.refresh_faq();self.update_salary()
 def update_age(self):
  try:value=self.read('birth_date') or self.store.value('birth_date')[0];text=str(age(date.fromisoformat(value),today())) if value else 'Desconocida'
  except ValueError:text='Fecha inválida'
  if hasattr(self,'age_label'):self.age_label.setText('Edad calculada: '+text)
 def update_salary(self):
  lines=[]
  for period,label in [('month','Mensual'),('year','Anual'),('hour','Por hora')]:
   value,state,reason=self.store.salary('main',period,bound='expected');lines.append(label+': '+(value+' '+reason+' ('+state+')' if value is not None else reason))
  self.conversions.setText('Expectativa principal derivada · '+' | '.join(lines))
 def save(self):
  try:
   values={k:self.read(k) for k in self.controls};confirmed={k for k,c in self.checks.items() if c.isChecked()};self.store.save(values,confirmed,self.revisions);self.refresh();self.status.setText('Guardado en SQLite. '+('Revisa conflictos con Mi perfil: '+', '.join(self.store.conflicts()) if self.store.conflicts() else 'Los valores confirmados se mantienen hasta que los edites o elimines explícitamente.'))
  except ValueError as exc:self.status.setText(str(exc))
 def delete_group(self):
  group=self.tabs.tabText(self.tabs.currentIndex())
  if group not in GROUPS:return
  if QMessageBox.question(self,'Eliminar datos adicionales',f'¿Eliminar solo los datos adicionales del bloque {group}? Mi perfil y los CV se conservan.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
  self.store.delete(GROUPS[group]);self.refresh()
 def detect(self):
  if self.worker and self.worker.isRunning():return
  if QMessageBox.question(self,'Lectura local solicitada','¿Leer sistema operativo, RAM y procesador de este equipo? Se propondrán sin confirmar y sin asumir que sea tu equipo de trabajo. No se medirá internet.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
  self.worker=TaskWorker(detect_windows);self.worker.done.connect(self.detected);self.worker.failed.connect(self.status.setText);self.status.setText('Leyendo especificaciones locales...');self.worker.start()
 def detected(self,values):
  for key,value in values.items():
   if not self.read(key):self.set_value(key,str(value));self.checks[key].setChecked(False)
  self.status.setText('Lectura propuesta en campos vacíos; no guardada ni confirmada. Comprueba que corresponda al equipo que usarás para trabajar.')
 def refresh_faq(self):
  self.faq_rows=self.store.faqs();self.faq_table.setRowCount(len(self.faq_rows))
  for i,r in enumerate(self.faq_rows):
   for j,value in enumerate([r['company'],r['question'],r['answer'] if r['answer'] is not None else 'DESCONOCIDO',str(bool(r['confirmed']))]):self.faq_table.setItem(i,j,QTableWidgetItem(value))
  self.faq_table.resizeColumnsToContents()
 def save_faq(self):
  answer=[None,'Sí','No',self.faq_answer.toPlainText().strip() or None][self.faq_kind.currentIndex()]
  try:self.store.faq_save(self.faq_company.text(),self.faq_question.text(),answer,self.faq_confirm.isChecked());self.refresh_faq();self.status.setText('Respuesta guardada localmente para ese contexto.')
  except ValueError as exc:self.status.setText(str(exc))
 def load_faq(self):
  i=self.faq_table.currentRow()
  if 0<=i<len(self.faq_rows):
   r=self.faq_rows[i];self.faq_company.setText(r['company']);self.faq_question.setText(r['question']);self.faq_answer.setPlainText(r['answer'] or '');self.faq_kind.setCurrentIndex(0 if r['answer'] is None else 1 if r['answer']=='Sí' else 2 if r['answer']=='No' else 3);self.faq_confirm.setChecked(bool(r['confirmed']))
 def delete_faq(self):
  i=self.faq_table.currentRow()
  if 0<=i<len(self.faq_rows):self.store.faq_delete(self.faq_rows[i]['id']);self.refresh_faq()
 def allow_close(self):
  self.identity_widget.allow_close();return not (self.worker and self.worker.isRunning())

class PreparationWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.settings=settings;self.service=Preparation(settings.data_path);self.worker=None;self.offer=None;self.document=None;self.preview=None;layout=QVBoxLayout(self);label=QLabel('Preparar postulación · Inspección externa de solo lectura. Respuestas y adjuntos permanecen locales; no hay envío real.');label.setWordWrap(True);layout.addWidget(label)
  self.jobs=QComboBox();layout.addWidget(self.jobs);self.metadata=QLabel();self.metadata.setWordWrap(True);layout.addWidget(self.metadata);self.url=QLineEdit();self.url.setPlaceholderText('URL pública del formulario; puede diferir de la página de la vacante');layout.addWidget(self.url);row=QHBoxLayout();self.cv=QComboBox();row.addWidget(self.cv);self.letter=QComboBox();row.addWidget(self.letter);self.approval=QCheckBox('He revisado el CV seleccionado; aprobación solo para prueba controlada');layout.addLayout(row);layout.addWidget(self.approval);row=QGridLayout()
  for i,(title,fn) in enumerate([('Analizar formulario',self.analyze),('Preparar respuestas',self.prepare),('Revisar datos',self.review_data),('Seleccionar / ver CV',self.view_cv),('Abrir en Brave',self.open_offer),('Guardar como pendiente',self.save),('Exportar resumen',self.export),('Cargar pendiente',self.load_pending),('Prueba local ficticia',self.local_test)]):
   button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button,i//3,i%3)
  layout.addLayout(row);self.status=QLabel('Listo. Los botones de envío detectados se clasifican, nunca se ejecutan.');self.status.setWordWrap(True);layout.addWidget(self.status);self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['Pregunta / campo','Tipo','Obligatorio','Respuesta local','Estado','Selector']);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(self.table,3);self.details=QPlainTextEdit();self.details.setReadOnly(True);layout.addWidget(self.details,2);self.jobs.currentIndexChanged.connect(self.job_changed);self.refresh()
 def refresh(self):
  self.job_rows=self.service.compatibility.rows();self.jobs.blockSignals(True);self.jobs.clear();self.jobs.addItem('Sin vacante asociada',None)
  for row in self.job_rows:self.jobs.addItem(row['job']['company']+' · '+row['job']['title'],row['job']['id'])
  self.jobs.blockSignals(False);self.cv.clear();self.cv.addItem('CV recomendado por evaluación',None)
  for item in self.service.compatibility.library.list():self.cv.addItem(item['title']+' · '+item['language']+' · '+('revisado' if item['reviewed'] else 'provisional'),item['id'])
  self.letter.clear();self.letter.addItem('Sin carta seleccionada',None)
  from contextlib import closing
  with closing(self.service.db.connect()) as db:
   if db.execute("SELECT 1 FROM sqlite_master WHERE name='cover_letters'").fetchone():
    for row in db.execute('SELECT id,company,position FROM cover_letters'):self.letter.addItem(row['company']+' · '+row['position'],row['id'])
  self.job_changed()
 def selected_job(self):return next((r['job'] for r in self.job_rows if r['job']['id']==self.jobs.currentData()),None)
 def job_changed(self,*_):
  job=self.selected_job();row=next((r for r in self.job_rows if job and r['job']['id']==job['id']),None);e=(row or {}).get('evaluation') or {}
  self.metadata.setText(' · '.join([str((job or {}).get('company') or 'Empresa desconocida'),str((job or {}).get('title') or 'Puesto desconocido'),'Compatibilidad: '+str(e.get('score','Sin evaluar')),'Geografía: '+str(e.get('geography','Desconocida')),'Vigencia: '+str(e.get('availability','NO VERIFICADA'))]))
  self.url.setText((job or {}).get('application_url') or (job or {}).get('url') or '');self.document=None;self.preview=None;self.approval.setChecked(False)
 def start_task(self,fn,done,message):
  if self.worker and self.worker.isRunning():self.status.setText('Espera a que termine la operación actual.');return
  self.worker=TaskWorker(fn);self.worker.done.connect(done);self.worker.failed.connect(self.failed);self.status.setText(message);self.worker.start()
 def failed(self,message):
  # No se muestra contenido de respuestas personales en errores de portales.
  self.status.setText('No se pudo completar la operación: '+message.split(':')[0]+'. Se conserva la información anterior.');self.details.setPlainText('Error del portal o de lectura. No se introdujeron datos ni se enviaron solicitudes.')
 def analyze(self):
  url=self.url.text().strip()
  if not url:self.status.setText('Selecciona una vacante o indica la URL pública del formulario.');return
  job=self.selected_job()
  def read():
   document=inspect_url(self.settings,url)
   if document.get('obstacles'):self.service.save(self.service.prepare(document,job))
   return document
  self.start_task(read,self.analyzed,'Inspeccionando campos públicos mediante Brave...')
 def analyzed(self,document):self.document=document;self.preview=None;self.render();self.status.setText(f"{len(document['fields'])} controles detectados · {len(document['obstacles'])} obstáculos. Inspección de solo lectura.")
 def prepare(self):
  if not self.document:self.status.setText('Analiza primero el formulario.');return
  document=self.document;job=self.selected_job();cv_id=self.cv.currentData();letter=self.letter.currentData();approved=self.approval.isChecked();self.start_task(lambda:self.service.prepare(document,job,cv_id,letter,approved),self.prepared,'Preparando respuestas localmente, sin rellenar el sitio...')
 def prepared(self,preview):self.preview=preview;self.render();self.status.setText(preview['state']+' · '+str(len(preview['blocks']))+' bloqueos / revisiones. Nada se ha enviado al portal.')
 def render(self):
  rows=self.preview['entries'] if self.preview else self.document['fields'] if self.document else [];self.table.setRowCount(len(rows))
  for i,row in enumerate(rows):
   for j,value in enumerate([row['label'],row['kind'],str(row['required']),row.get('answer') or '',row.get('status',row.get('action','Detectado')),row['selector']]):self.table.setItem(i,j,QTableWidgetItem(str(value)))
  for i,w in enumerate([350,90,100,320,200,350]):self.table.setColumnWidth(i,w)
  self.details.setPlainText(json.dumps(self.preview or self.document or {},ensure_ascii=False,indent=2))
 def review_data(self):
  window=self.window()
  if hasattr(window,'application_data_widget'):window.tabs.setCurrentWidget(window.application_data_widget)
 def view_cv(self):
  id=self.cv.currentData() or (self.preview or {}).get('cv_id')
  if not id:self.status.setText('Selecciona un CV o prepara la recomendación.');return
  try:
   import os
   os.startfile(self.service.compatibility.library.original_path(id))
  except Exception:self.status.setText('No se pudo abrir el documento local.')
 def open_offer(self):
  if not self.url.text():return
  if self.offer and self.offer.isRunning():self.status.setText('Cierra la oferta de Brave anterior.');return
  self.offer=OfferWorker(self.settings,self.url.text());self.offer.status.connect(self.status.setText);self.offer.start()
 def save(self):
  if not self.preview:self.status.setText('Prepara las respuestas antes de guardar.');return
  self.preview['state']='BLOQUEADA' if self.preview['document'].get('obstacles') else 'PENDIENTE';id=self.service.save(self.preview);self.status.setText('Pendiente guardada localmente: '+id)
 def load_pending(self):
  rows=self.service.history()
  if not rows:self.status.setText('No hay preparaciones guardadas.');return
  choices=[str(i+1)+' · '+str(r.get('company') or '')+' · '+r['url'] for i,r in enumerate(rows)];chosen,ok=QInputDialog.getItem(self,'Preparaciones locales','Selecciona:',choices,0,False)
  if ok:
   self.preview=rows[choices.index(chosen)];self.document=self.preview['document'];self.url.setText(self.preview['url']);self.render();self.status.setText('Preparación obsoleta: prepara de nuevo con los datos actuales.' if self.preview.get('stale') else 'Preparación local recuperada.')
 def export(self):
  if not self.preview and not self.document:self.status.setText('Analiza un formulario primero.');return
  file,_=QFileDialog.getSaveFileName(self,'Exportar vista previa','preparacion.json','JSON (*.json)')
  if file:
   try:Path(file).write_text(json.dumps(self.preview or self.document,ensure_ascii=False,indent=2),encoding='utf-8');self.status.setText('Resumen local exportado. Puede contener datos personales; compártelo solo cuando lo decidas.')
   except OSError:self.status.setText('No se pudo escribir el archivo.')
 def local_test(self):
  from autojob.forms.controlled import run_controlled
  self.start_task(lambda:run_controlled(self.settings),lambda result:(self.details.setPlainText(json.dumps(result,ensure_ascii=False,indent=2)),self.status.setText('Prueba local: dos etapas, respuestas y adjuntos ficticios; sin envío.')),'Probando exclusivamente con datos ficticios en loopback...')
 def allow_close(self):
  if self.worker and self.worker.isRunning():self.status.setText('Espera a que termine la consulta actual antes de cerrar.');return False
  if self.offer and self.offer.isRunning():self.offer.requestInterruption();return False
  return True
