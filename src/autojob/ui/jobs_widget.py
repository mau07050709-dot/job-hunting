import json
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPlainTextEdit,QSpinBox,QComboBox,QPushButton,QTableWidget,QTableWidgetItem,QFileDialog,QCheckBox,QGridLayout,QGroupBox,QScrollArea,QInputDialog
from autojob.search.jobs import JobStore,ENDPOINTS

class SearchWorker(QThread):
 progress=Signal(str);done=Signal(object)
 def __init__(self,store,queries,sources,limit):super().__init__();self.store=store;self.queries=queries;self.sources=sources;self.limit=limit
 def run(self):
  try:self.done.emit(self.store.search(self.queries,self.sources,self.limit,self.isInterruptionRequested,self.progress.emit))
  except Exception as exc:self.done.emit(dict(found=0,duplicates=0,errors=[type(exc).__name__],cancelled=False))

class OfferWorker(QThread):
 status=Signal(str)
 def __init__(self,settings,url):super().__init__();self.settings=settings;self.url=url
 def run(self):
  from autojob.browser import BraveSession
  try:
   with BraveSession(self.settings) as browser:
    page=browser.new_page(self.url);self.status.emit('Oferta abierta: '+page.title())
    while not self.isInterruptionRequested() and not page.is_closed():self.msleep(250)
  except Exception:self.status.emit('No se pudo abrir la oferta; revisa Brave y la disponibilidad del sitio.')

class GeographyWorker(QThread):
 progress=Signal(str);done=Signal(object)
 def __init__(self,store):super().__init__();self.store=store
 def run(self):
  from autojob.search.geography import review_store
  try:self.done.emit(review_store(self.store,self.isInterruptionRequested,self.progress.emit))
  except Exception:self.done.emit({'error':'No se pudo completar la revisión; se conservaron las revisiones ya guardadas.'})

class AvailabilityWorker(QThread):
 progress=Signal(str);done=Signal(object)
 def __init__(self,store,jobs):super().__init__();self.store=store;self.jobs=jobs
 def run(self):
  from autojob.search.availability import Availability
  try:self.done.emit(Availability(self.store).batch(self.jobs,self.isInterruptionRequested,self.progress.emit))
  except Exception:self.done.emit([])

class JobsWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.settings=settings;self.store=JobStore(settings.data_path);self.worker=None;self.offer=None;layout=QVBoxLayout(self)
  layout.addWidget(QLabel('Buscar empleos · APIs públicas y RSS · Enlaces atribuidos a sus fuentes'))
  self.keywords=QPlainTextEdit('Junior Software Developer\nPython Developer\nJunior Programmer\nIT Support\nTechnical Support\nHelp Desk\nService Desk\nQA Tester\nJunior Data Analyst\nElectronics Technician\nEngineering Assistant\nSoftware Engineering Intern\nTechnology Intern\nCustomer Service Representative\nCustomer Support\nCustomer Experience\nChat Support\nEmail Support\nBilingual Customer Service\nTechnical Customer Support\nBack Office\nCall Center\nVirtual Assistant\nAdministrative Assistant');self.keywords.setMaximumHeight(100);layout.addWidget(self.keywords)
  row=QHBoxLayout();self.sources={}
  for name in ENDPOINTS:
   box=QCheckBox(name);box.setChecked(True);self.sources[name]=box;row.addWidget(box)
  self.limit=QSpinBox();self.limit.setRange(1,300);self.limit.setValue(30);row.addWidget(QLabel('Máximo'));row.addWidget(self.limit)
  self.frequency=QSpinBox();self.frequency.setRange(0,168);self.frequency.setSuffix(' h (0 = manual)');row.addWidget(self.frequency);layout.addLayout(row)
  row=QGridLayout()
  for index,(title,fn) in enumerate([('Buscar ahora',self.start),('Detener búsqueda',self.stop),('Actualizar resultados',self.refresh),('Revisar geografía',self.review_geography),('Verificar vigencia',self.verify_availability),('Verificar lote (10)',self.verify_batch),('Historial',self.show_history),('Abrir oferta en Brave',self.open_offer),('Exportar Excel',self.export)]):
   button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button,index//5,index%5)
  layout.addLayout(row);self.filter=QComboBox();self.filter.addItems(['Todas','CONFIRMADO','POSIBLE','DESCONOCIDO','INCOMPATIBLE']);self.filter.currentTextChanged.connect(self.refresh);layout.addWidget(self.filter)
  row=QHBoxLayout();self.source_filter=QComboBox();self.source_filter.addItems(['Todas las fuentes',*ENDPOINTS]);row.addWidget(self.source_filter)
  self.category_filter=QComboBox();self.category_filter.addItems(['Todas las categorías','Tecnología','Customer Service']);row.addWidget(self.category_filter)
  self.mode_filter=QComboBox();self.mode_filter.addItems(['Todas las modalidades','Remoto','Presencial / híbrido en Cartago','Presencial','Híbrido']);row.addWidget(self.mode_filter);layout.addLayout(row)
  for box in (self.source_filter,self.category_filter,self.mode_filter):box.currentTextChanged.connect(self.refresh)
  from autojob.search.filters import Favorites
  self.favorites=Favorites(self.store);self.advanced={}
  panel=QGroupBox('Filtros avanzados · los campos vacíos no restringen');grid=QGridLayout(panel)
  specs=[('country','País',[]),('province','Provincia',[]),('canton','Cantón',[]),('schedule','Jornada',['Full-time','Part-time','Contract']),('seniority','Nivel',[]),('published_days','Publicadas en días',['1','7','30','90']),('availability','Vigencia',['ABIERTA','CERRADA','NO VERIFICADA','ERROR DE VERIFICACIÓN']),('salary','Salario',['Publicado']),('currency','Moneda',['USD','CRC','EUR']),('keywords','Palabras clave',[])]
  for i,(key,label,options) in enumerate(specs):
   control=QComboBox() if options else QLineEdit()
   if options:control.addItems(['',*options]);control.currentTextChanged.connect(self.refresh)
   else:control.setPlaceholderText(label);control.textChanged.connect(self.refresh)
   self.advanced[key]=control;grid.addWidget(QLabel(label),i//4*2,i%4);grid.addWidget(control,i//4*2+1,i%4)
  self.include_unknown=QCheckBox('Incluir campos incompletos (pueden no cumplir los filtros)');self.include_unknown.setChecked(True);self.include_unknown.toggled.connect(self.refresh);grid.addWidget(self.include_unknown,6,0,1,4)
  self.favorite_combo=QComboBox();self.favorite_combo.addItems(list(self.favorites.list()));grid.addWidget(self.favorite_combo,7,0)
  for col,(text,fn) in enumerate([('Guardar favorito',self.save_filters),('Recuperar favorito',self.load_filters),('Limpiar filtros',self.clear_filters)],1):
   button=QPushButton(text);button.clicked.connect(fn);grid.addWidget(button,7,col)
  area=QScrollArea();area.setWidgetResizable(True);area.setWidget(panel);area.setMaximumHeight(210);layout.addWidget(area)
  self.status=QLabel('Listo. Las ofertas remotas sin países explícitos requieren revisión.');self.status.setWordWrap(True);layout.addWidget(self.status)
  self.result_count=QLabel();layout.addWidget(self.result_count)
  self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Fuente','Ubicación','Modalidad','Jornada','Publicación','Geografía']);self.table.itemSelectionChanged.connect(self.details);self.table.setSortingEnabled(True);layout.addWidget(self.table)
  self.description=QPlainTextEdit();self.description.setReadOnly(True);layout.addWidget(self.description)
  self.timer=QTimer(self);self.timer.timeout.connect(self.start);self.frequency.valueChanged.connect(self.schedule)
  self.preferences=settings.data_path/'job-search-settings.json'
  if self.preferences.exists():
   try:
    data=json.loads(self.preferences.read_text(encoding='utf-8'));self.keywords.setPlainText('\n'.join(data['queries']));self.limit.setValue(data['limit']);self.frequency.setValue(data.get('hours',0))
   except (ValueError,KeyError,OSError):pass
  self.refresh()
 def schedule(self,*_):
  self.timer.stop()
  if 0<self.frequency.value()<6:self.frequency.setValue(6);return
  if self.frequency.value():self.timer.start(max(6,self.frequency.value())*3600000)
 def start(self):
  if self.worker and self.worker.isRunning():return
  queries=[q.strip() for q in self.keywords.toPlainText().splitlines() if q.strip()];sources=[name for name,box in self.sources.items() if box.isChecked()]
  if not sources or not queries:self.status.setText('Selecciona fuentes y escribe palabras clave.');return
  self.preferences.write_text(json.dumps(dict(queries=queries,limit=self.limit.value(),hours=self.frequency.value())),encoding='utf-8')
  self.worker=SearchWorker(self.store,queries,sources,self.limit.value());self.worker.progress.connect(self.status.setText);self.worker.done.connect(self.finished);self.worker.start()
 def review_geography(self):
  if self.worker and self.worker.isRunning():return
  self.worker=GeographyWorker(self.store);self.worker.progress.connect(self.status.setText);self.worker.done.connect(self.review_finished);self.worker.start()
 def review_finished(self,result):
  self.status.setText(str(result.get("error") or ("Ofertas revisadas: "+str(result.get("reviewed",0))+" · Confirmadas: "+str(result.get("results",{}).get("CONFIRMADO",0))+" · Posibles: "+str(result.get("results",{}).get("POSIBLE",0))+" · Desconocidas: "+str(result.get("results",{}).get("DESCONOCIDO",0)))));self.refresh()
 def verify_batch(self):
  self.table.clearSelection();self.verify_availability()
 def verify_availability(self):
  if self.worker and self.worker.isRunning():return
  selected=self.selected();jobs=[selected] if selected else self.rows[:10]
  self.worker=AvailabilityWorker(self.store,jobs);self.worker.progress.connect(self.status.setText);self.worker.done.connect(self.availability_finished);self.worker.start()
 def availability_finished(self,results):
  self.status.setText('Vigencia comprobada: '+str(len(results))+' ofertas. Selecciona una fila para consultar evidencia.');self.refresh()
 def stop(self):
  if self.worker:self.worker.requestInterruption();self.status.setText('Deteniendo al terminar la consulta actual...')
 def finished(self,result):self.status.setText(f"{result['found']} nuevas · {result['duplicates']} duplicados · {len(result['errors'])} fuentes no disponibles\n"+'\n'.join(result['errors']));self.refresh()
 def refresh(self,*_):
  if not hasattr(self,"table"):return
  from autojob.search.filters import matches
  def included(row):
   filters=self.filter_values()
   if self.mode_filter.currentIndex()==2 and not (row.get('modality') in {'onsite','hybrid'} and row['geography']=='CONFIRMADO'):return False
   return matches(row,filters,self.include_unknown.isChecked())
  all_rows=self.store.list();self.rows=[row for row in all_rows if included(row)];self.result_count.setText(str(len(self.rows))+' resultados filtrados de '+str(len(all_rows))+' guardados');self.table.setSortingEnabled(False);self.table.setRowCount(len(self.rows))
  for index,row in enumerate(self.rows):
   for column,key in enumerate(['company','title','source','location','modality','schedule','published_at','geography']):
    value=str(row.get(key) or 'Desconocido');item=QTableWidgetItem(value);item.setToolTip(value);item.setData(256,row['id']);self.table.setItem(index,column,item)
  for column,width in enumerate([140,240,90,130,75,80,110,120]):self.table.setColumnWidth(column,width)
  self.table.setWordWrap(False);self.table.setSortingEnabled(True)
  if hasattr(self,'status'):self.table.setToolTip(str(len(self.rows))+' resultados filtrados; los campos desconocidos dependen de la opción Incluir campos incompletos.')
 def selected(self):
  items=self.table.selectedItems()
  return next((row for row in self.rows if items and row['id']==items[0].data(256)),None)
 def details(self):
  row=self.selected()
  if row:self.description.setPlainText(row['title']+'\n'+row['company']+'\nFuente: '+row['source']+'\n'+row['url']+'\nGeografía: '+row['geography']+' — '+row['geography_evidence']+'\nVigencia: '+str(row.get('availability') if row.get('availability') in {'ABIERTA','CERRADA','NO VERIFICADA','ERROR DE VERIFICACIÓN'} else 'NO VERIFICADA')+' · '+str(row.get('availability_checked_at','Sin comprobar'))+'\n'+str(row.get('availability_evidence',''))+'\n\n'+row['description'])
 def open_offer(self):
  row=self.selected()
  if not row:return
  if self.offer and self.offer.isRunning():self.status.setText('Cierra la oferta de Brave anterior para abrir otra.');return
  self.offer=OfferWorker(self.settings,row['url']);self.offer.status.connect(self.status.setText);self.offer.start()
 def export(self):
  filename,_=QFileDialog.getSaveFileName(self,'Exportar vacantes','vacantes.xlsx','Excel (*.xlsx)')
  if not filename:return
  try:
   from autojob.search.filters import export_rows
   export_rows(self.rows,filename)
   self.status.setText('Excel exportado.')
  except Exception:self.status.setText('No se pudo exportar Excel. Comprueba permisos y la dependencia openpyxl.')
 def filter_values(self):
  values={key:(control.currentText() if isinstance(control,QComboBox) else control.text()).strip() for key,control in self.advanced.items()}
  values.update(source=self.source_filter.currentText() if self.source_filter.currentIndex() else '',category=self.category_filter.currentText() if self.category_filter.currentIndex() else '',geography=self.filter.currentText() if self.filter.currentIndex() else '',modality={1:'remote',3:'onsite',4:'hybrid'}.get(self.mode_filter.currentIndex(),''))
  return values
 def clear_filters(self):
  for box in (self.filter,self.source_filter,self.category_filter,self.mode_filter):box.setCurrentIndex(0)
  for control in self.advanced.values():
   if isinstance(control,QComboBox):control.setCurrentIndex(0)
   else:control.clear()
  self.include_unknown.setChecked(True);self.refresh()
 def save_filters(self):
  name,ok=QInputDialog.getText(self,'Guardar filtros','Nombre del favorito:')
  if ok and name.strip():
   self.favorites.save(name,dict(self.filter_values(),_mode=str(self.mode_filter.currentIndex())),self.include_unknown.isChecked());self.favorite_combo.clear();self.favorite_combo.addItems(list(self.favorites.list()));self.favorite_combo.setCurrentText(name.strip());self.status.setText('Filtro guardado en SQLite.')
 def load_filters(self):
  saved=self.favorites.list().get(self.favorite_combo.currentText())
  if not saved:return
  self.clear_filters();values=saved['filters']
  for key,control in self.advanced.items():
   if isinstance(control,QComboBox):control.setCurrentText(values.get(key,''))
   else:control.setText(values.get(key,''))
  for key,control in [('source',self.source_filter),('category',self.category_filter),('geography',self.filter)]:
   if values.get(key):control.setCurrentText(values[key])
  self.mode_filter.setCurrentIndex({'remote':1,'onsite':3,'hybrid':4}.get(values.get('modality'),0));self.mode_filter.setCurrentIndex(int(values.get('_mode',self.mode_filter.currentIndex())));self.include_unknown.setChecked(saved['unknown']);self.refresh()
 def show_history(self):
  row=self.selected()
  if not row:self.status.setText('Selecciona una oferta para consultar su historial.');return
  from autojob.search.availability import Availability
  from datetime import datetime,timezone
  history=Availability(self.store).history(row['id'])
  self.description.setPlainText('Historial de '+row['title']+'\n\n'+'\n\n'.join(datetime.fromtimestamp(item['checked_at'],timezone.utc).isoformat()+' · '+item['state']+'\n'+item['evidence']+'\n'+item['url'] for item in history) if history else 'Esta oferta todavía no tiene verificaciones.')
 def allow_close(self):
  self.stop()
  if self.offer:self.offer.requestInterruption()
  busy=(self.worker and self.worker.isRunning()) or (self.offer and self.offer.isRunning())
  if busy:self.status.setText('Espera a que termine la consulta o se cierre Brave antes de cerrar Job Hunting.')
  return not busy
