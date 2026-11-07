import json
from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QPlainTextEdit,QComboBox,QSpinBox,QFileDialog,QDialog,QDialogButtonBox,QAbstractItemView
from autojob.matching.service import Compatibility,report,export
from autojob.ui.jobs_widget import OfferWorker

class EvaluationWorker(QThread):
 progress=Signal(str);done=Signal(object)
 def __init__(self,service,ids,force):super().__init__();self.service=service;self.ids=ids;self.force=force
 def run(self):
  try:self.done.emit(self.service.batch(self.ids,self.force,self.isInterruptionRequested,self.progress.emit))
  except Exception as exc:self.done.emit(dict(evaluated=0,cached=0,errors=[dict(error=type(exc).__name__)],cancelled=False))

class CompatibilityWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.settings=settings;self.service=Compatibility(settings.data_path);self.worker=None;self.offer=None;self.rows=[]
  layout=QVBoxLayout(self);layout.addWidget(QLabel('Compatibilidad laboral · Evaluación local explicable · Puntuación heurística, no probabilidad de contratación'))
  layout.addWidget(QLabel('Selecciona una o varias filas (Ctrl/Mayús). Sin selección se evalúan todas. Reanudar conserva resultados vigentes; Reevaluar crea historial.'))
  buttons=QHBoxLayout()
  for text,fn in [('Evaluar / reanudar',self.start),('Reevaluar',lambda:self.start(True)),('Detener',self.stop),('Seleccionar todas',lambda:self.table.selectAll()),('Actualizar',self.refresh),('Configurar motor',self.configure)]:
   button=QPushButton(text);button.clicked.connect(fn);buttons.addWidget(button)
  layout.addLayout(buttons);row=QHBoxLayout();self.minimum=QSpinBox();self.minimum.setRange(0,100);self.minimum.setSuffix(' % mínimo');row.addWidget(self.minimum)
  self.filter=QComboBox();self.filter.addItems(['Todas','COMPATIBLE','REQUIERE REVISIÓN','INCOMPATIBLE','SIN EVALUAR','OBSOLETA','A. Alta compatibilidad','B. Compatibilidad moderada','C. Requieren verificación','D. Incompatibles']);row.addWidget(self.filter)
  for text,fn in [('Ver análisis completo',self.details),('Historial',self.history),('Ordenar por compatibilidad',lambda:self.table.sortItems(2,Qt.SortOrder.DescendingOrder)),('Abrir en Brave',self.open_offer),('Exportar Excel',self.export)]:
   button=QPushButton(text);button.clicked.connect(fn);row.addWidget(button)
  layout.addLayout(row);self.status=QLabel('Listo. No se enviarán solicitudes.');self.status.setWordWrap(True);layout.addWidget(self.status);self.count=QLabel();layout.addWidget(self.count)
  self.table=QTableWidget(0,14);self.table.setHorizontalHeaderLabels(['Empresa','Puesto','Compatibilidad profesional','Elegibilidad','Modalidad','País / ubicación','Geografía','CV recomendado','Requisitos faltantes','Confianza','Recomendación','Vigencia','Estado del CV','Cambio de puntuación'])
  self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.details);layout.addWidget(self.table,3)
  self.analysis=QPlainTextEdit();self.analysis.setReadOnly(True);layout.addWidget(self.analysis,2)
  self.minimum.valueChanged.connect(self.refresh);self.filter.currentTextChanged.connect(self.refresh);self.refresh()
 def selected_rows(self):
  ids={item.data(256) for item in self.table.selectedItems()}
  return [r for r in self.rows if r['job']['id'] in ids]
 def start(self,force=False):
  if self.worker and self.worker.isRunning():return
  ids={r['job']['id'] for r in self.selected_rows()} or None
  self.worker=EvaluationWorker(self.service,ids,bool(force));self.worker.progress.connect(self.status.setText);self.worker.done.connect(self.finished);self.worker.start()
 def stop(self):
  if self.worker:self.worker.requestInterruption();self.status.setText('Cancelación solicitada; se conservará cada evaluación ya guardada.')
 def finished(self,result):
  self.status.setText(f"{result['evaluated']} procesadas · {result['cached']} reutilizadas vigentes · {len(result['errors'])} errores · "+('Cancelada; puedes reanudar.' if result['cancelled'] else 'Finalizada.'))
  self.refresh()
 def refresh(self,*_):
  selected={r['job']['id'] for r in self.selected_rows()};all_rows=self.service.rows();self.rows=[]
  for row in all_rows:
   e=row['evaluation'];state='OBSOLETA' if row['stale'] else e['eligibility'] if e else 'SIN EVALUAR'
   if self.filter.currentText()!='Todas' and state!=self.filter.currentText() and (row.get('stale') or not e or e.get('recommendation')!=self.filter.currentText()):continue
   if (e or {}).get('score',0)<self.minimum.value():continue
   self.rows.append(row)
  self.table.setSortingEnabled(False);self.table.setRowCount(len(self.rows))
  for index,row in enumerate(self.rows):
   j=row['job'];e=row['evaluation'] or {};selection=e.get('resume_selection') or {};state='OBSOLETA: REVISAR' if row['stale'] else e.get('eligibility','SIN EVALUAR')
   missing=[r['name']+' ('+r['state']+')' for r in e.get('assessments',[]) if r['importance']=='OBLIGATORIO' and r['state']!='CUMPLE']
   values=[j.get('company'),j.get('title'),e.get('score'),state,j.get('modality'),j.get('country') or j.get('location'),e.get('geography',j.get('geography')),selection.get('title') or 'Pendiente',', '.join(missing) or ('Sin obligatorios detectados' if e.get('mandatory_status')=='POR VERIFICAR' else ''),e.get('confidence'),e.get('recommendation','Sin clasificar'),e.get('availability','NO VERIFICADA'),selection.get('status','Pendiente'),(e.get('change_from_previous') or {}).get('difference')]
   for column,value in enumerate(values):
    item=QTableWidgetItem();item.setData(Qt.ItemDataRole.DisplayRole,value if value is not None else 'Desconocido');item.setData(256,j['id']);item.setToolTip(str(value));self.table.setItem(index,column,item)
   if j['id'] in selected:self.table.selectRow(index)
  self.table.setSortingEnabled(True)
  for col,width in enumerate([150,270,150,200,90,170,125,160,230,100,200,150,230,150]):self.table.setColumnWidth(col,width)
  self.count.setText(f'{len(self.rows)} visibles / {len(all_rows)} vacantes · Las evaluaciones obsoletas requieren recalcularse.')
 def details(self):
  selected=self.selected_rows()
  if selected:
   row=selected[0];self.analysis.setPlainText(('EVALUACIÓN OBSOLETA: cambió el perfil, CV, configuración, fecha o vacante. Reevalúa antes de usar.\n\n' if row['stale'] else '')+report(row['evaluation']))
 def history(self):
  selected=self.selected_rows()
  if not selected:return
  records=self.service.history(selected[0]['job']['id']);self.analysis.setPlainText('\n\n' .join(report(r) for r in records) if records else 'Sin historial.')
 def open_offer(self):
  rows=self.selected_rows()
  if not rows:return
  if self.offer and self.offer.isRunning():self.status.setText('Cierra la oferta anterior de Brave.');return
  self.offer=OfferWorker(self.settings,rows[0]['job']['url']);self.offer.status.connect(self.status.setText);self.offer.start()
 def export(self):
  file,_=QFileDialog.getSaveFileName(self,'Exportar compatibilidad','compatibilidad.xlsx','Excel (*.xlsx)')
  if not file:return
  try:export(self.rows,file);self.status.setText('Exportación de resultados filtrados completada.')
  except Exception:self.status.setText('No se pudo guardar el Excel. Revisa la ruta y si el archivo está abierto.')
 def configure(self):
  dialog=QDialog(self);dialog.setWindowTitle('Pesos y equivalencias configurables');dialog.resize(800,650);layout=QVBoxLayout(dialog);layout.addWidget(QLabel('Edita JSON. Los seis pesos deben sumar 100. Guardar invalida las evaluaciones anteriores.'))
  editor=QPlainTextEdit(json.dumps(self.service.config(),ensure_ascii=False,indent=2));layout.addWidget(editor);error=QLabel();error.setWordWrap(True);layout.addWidget(error);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
  def save():
   try:self.service.save_config(json.loads(editor.toPlainText()));dialog.accept();self.refresh()
   except (ValueError,OSError) as exc:error.setText(str(exc))
  buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject);dialog.exec()
 def allow_close(self):
  if self.worker and self.worker.isRunning():self.stop();return False
  if self.offer and self.offer.isRunning():self.offer.requestInterruption();return False
  return True
