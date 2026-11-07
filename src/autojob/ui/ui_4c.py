import json
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QPlainTextEdit,QPushButton,QFileDialog,QListWidget,QTableWidget,QTableWidgetItem,QCheckBox,QSpinBox,QDialog,QDialogButtonBox
from autojob.profile.letters import Letters
from autojob.testing.simulation_4c import Simulator,SCENARIOS

class LettersWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.service=Letters(settings.data_path);self.selected=None;layout=QVBoxLayout(self)
  layout.addWidget(QLabel('Cartas de presentación · revisa el borrador antes de utilizarlo'))
  row=QHBoxLayout();self.company=QLineEdit();self.company.setPlaceholderText('Empresa');row.addWidget(self.company);self.position=QLineEdit();self.position.setPlaceholderText('Puesto');row.addWidget(self.position);layout.addLayout(row)
  row=QHBoxLayout();self.language=QComboBox();self.language.addItem('Español','es');self.language.addItem('English','en');row.addWidget(self.language);self.category=QComboBox();self.category.addItem('Técnico','technical');self.category.addItem('Customer Service','customer_service');row.addWidget(self.category);self.cv=QComboBox();row.addWidget(self.cv);layout.addLayout(row)
  self.description=QPlainTextEdit();self.description.setMaximumHeight(100);self.description.setPlaceholderText('Descripción de la vacante');layout.addWidget(self.description)
  self.body=QPlainTextEdit();self.body.setPlaceholderText('Carta editable');layout.addWidget(self.body)
  buttons=QHBoxLayout()
  for label,fn in [('Actualizar CV',self.refresh_cvs),('Editar plantilla',self.edit_template),('Generar / regenerar',self.generate),('Nueva',self.new),('Copiar',self.copy),('Guardar',self.save),('Exportar PDF/DOCX',self.export)]:
   b=QPushButton(label);b.clicked.connect(fn);buttons.addWidget(b)
  layout.addLayout(buttons);self.status=QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status)
  layout.addWidget(QLabel('Cartas anteriores'));self.history=QListWidget();self.history.setMaximumHeight(100);self.history.currentRowChanged.connect(self.choose);layout.addWidget(self.history)
  self.refresh_cvs();self.refresh()
 def refresh_cvs(self):
  current=self.cv.currentData();self.cv.clear();self.cv.addItem('Seleccionar CV',None)
  for row in self.service.library.list():self.cv.addItem(row['title']+(' · revisado' if row['reviewed'] else ' · por revisar'),row['id'])
  self.cv.setCurrentIndex(max(0,self.cv.findData(current)))
 def generate(self):
  try:self.body.setPlainText(self.service.generate(self.company.text(),self.position.text(),self.description.toPlainText(),self.language.currentData(),self.category.currentData(),self.cv.currentData()));self.status.setText('Borrador generado. Revisa y edita su contenido.')
  except ValueError as exc:self.status.setText(str(exc))
 def new(self):self.selected=None;self.body.clear();self.company.clear();self.position.clear();self.description.clear();self.history.clearSelection()
 def copy(self):QApplication.clipboard().setText(self.body.toPlainText());self.status.setText('Texto copiado.')
 def save(self):
  try:self.selected=self.service.save(self.company.text(),self.position.text(),self.description.toPlainText(),self.language.currentData(),self.category.currentData(),self.cv.currentData(),self.body.toPlainText(),self.selected);self.refresh();self.status.setText('Carta guardada.')
  except ValueError as exc:self.status.setText(str(exc))
 def refresh(self):
  self.rows=self.service.history();self.history.blockSignals(True);self.history.clear()
  for row in self.rows:self.history.addItem(row['company']+' · '+row['position']+' · '+row['created_at'])
  self.history.blockSignals(False)
 def choose(self,index):
  if index<0 or index>=len(self.rows):return
  item=self.rows[index];self.selected=item['id'];self.company.setText(item['company']);self.position.setText(item['position']);self.description.setPlainText(item['description']);self.language.setCurrentIndex(self.language.findData(item['language']));self.category.setCurrentIndex(self.category.findData(item['category']));self.refresh_cvs();self.cv.setCurrentIndex(max(0,self.cv.findData(item['cv_id'])));self.body.setPlainText(item['body'])
 def export(self):
  import re
  suffix=re.sub(r'[^\w-]+','-',self.company.text()+'-'+self.position.text()).strip('-')[:80] or 'borrador'
  filename,selected=QFileDialog.getSaveFileName(self,'Exportar carta','carta-'+suffix,'PDF (*.pdf);;Word (*.docx)')
  if filename:
   if not Path(filename).suffix:filename+=('.docx' if 'Word' in selected else '.pdf')
   try:self.service.export(self.body.toPlainText(),Path(filename));self.status.setText('Carta exportada.')
   except Exception:self.status.setText('No se pudo exportar: comprueba la extensión y los permisos.')
 def edit_template(self):
  dialog=QDialog(self);dialog.setWindowTitle('Editar plantilla de carta');dialog.resize(650,500);layout=QVBoxLayout(dialog)
  layout.addWidget(QLabel('Variables: {company}, {position}, {facts}, {name}. Los cambios se aplican al idioma seleccionado.'))
  editor=QPlainTextEdit(self.service.template(self.language.currentData()));layout.addWidget(editor);message=QLabel();layout.addWidget(message)
  buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons);buttons.rejected.connect(dialog.reject)
  def save():
   try:self.service.save_template(self.language.currentData(),editor.toPlainText());dialog.accept();self.status.setText('Plantilla guardada.')
   except ValueError as exc:message.setText(str(exc))
  buttons.accepted.connect(save);dialog.exec()

class SimulatorWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.service=Simulator(settings.data_path);layout=QVBoxLayout(self)
  layout.addWidget(QLabel('Simulador de postulaciones · no envía solicitudes'))
  self.current=None;self.scenario=QComboBox();self.scenario.addItems(SCENARIOS);self.scenario.addItem('Personalizado');layout.addWidget(self.scenario)
  self.company=QLineEdit();self.company.setPlaceholderText('Empresa simulada');layout.addWidget(self.company)
  self.position=QLineEdit();self.position.setPlaceholderText('Puesto simulado');layout.addWidget(self.position)
  self.language=QComboBox();self.language.addItem('English','en');self.language.addItem('Español','es');layout.addWidget(self.language)
  self.category=QComboBox();self.category.addItem('Detectar','auto');self.category.addItem('Técnico','technical');self.category.addItem('Customer Service','customer_service');layout.addWidget(self.category)
  self.custom=QTableWidget(0,4);self.custom.setHorizontalHeaderLabels(['Pregunta personalizada','Tipo','Obligatorio','Opciones separadas por |']);self.custom.horizontalHeader().setStretchLastSection(True);self.custom.setMaximumHeight(120);layout.addWidget(self.custom)
  self.custom.hide();self.scenario.currentTextChanged.connect(lambda value:self.custom.setVisible(value=='Personalizado'))
  self.add_field=QPushButton('Agregar campo personalizado');self.add_field.clicked.connect(self.add_custom);self.add_field.hide();layout.addWidget(self.add_field)
  self.scenario.currentTextChanged.connect(lambda value:self.add_field.setVisible(value=='Personalizado'))
  self.remove_field=QPushButton('Quitar campo seleccionado');self.remove_field.clicked.connect(self.remove_custom);self.remove_field.hide();layout.addWidget(self.remove_field)
  self.scenario.currentTextChanged.connect(lambda value:self.remove_field.setVisible(value=='Personalizado'))
  run=QPushButton('Simular postulación');run.clicked.connect(self.run);layout.addWidget(run)
  self.result=QPlainTextEdit();self.result.setReadOnly(True);layout.addWidget(self.result)
  edit=QHBoxLayout();self.field_index=QSpinBox();self.field_index.setMinimum(1);self.field_index.setPrefix('Campo #');edit.addWidget(self.field_index)
  self.manual=QLineEdit();self.manual.setPlaceholderText('Corrección de respuesta');edit.addWidget(self.manual)
  self.approve=QCheckBox('Guardar aprobada en banco');edit.addWidget(self.approve)
  save=QPushButton('Guardar respuesta revisada');save.clicked.connect(self.update_answer);edit.addWidget(save);layout.addLayout(edit)
  layout.addWidget(QLabel('Historial de simulaciones'));self.history=QListWidget();self.history.setMaximumHeight(120);self.history.currentRowChanged.connect(self.choose);layout.addWidget(self.history);self.refresh()
 def run(self):
  try:
   fields=None
   if self.scenario.currentText()=='Personalizado':
    fields=[]
    for row in range(self.custom.rowCount()):
     item=self.custom.item(row,0);choices=self.custom.item(row,3);fields.append((item.text() if item else '',self.custom.cellWidget(row,1).currentText(),self.custom.cellWidget(row,2).isChecked(),[x.strip() for x in choices.text().split('|') if x.strip()] if choices else []))
   result=self.service.run(self.scenario.currentText(),self.company.text(),self.position.text(),self.language.currentData(),self.category.currentData(),fields);self.show_result(result);self.refresh()
  except Exception as exc:self.result.setPlainText('No se pudo completar la simulación. Comprueba el formulario y la configuración.')
 def add_custom(self):
  row=self.custom.rowCount();self.custom.insertRow(row);self.custom.setItem(row,0,QTableWidgetItem(''))
  kinds=QComboBox();kinds.addItems(['text','email','phone','date','select','radio','multiple','checkbox','textarea','number','salary','experience','file','captcha','video','legal']);self.custom.setCellWidget(row,1,kinds)
  required=QCheckBox();required.setChecked(True);self.custom.setCellWidget(row,2,required);self.custom.setItem(row,3,QTableWidgetItem(''))
 def remove_custom(self):
  if self.custom.currentRow()>=0:self.custom.removeRow(self.custom.currentRow())
 def update_answer(self):
  if not self.current:return
  try:self.show_result(self.service.update_answer(self.current['id'],self.field_index.value()-1,self.manual.text(),self.approve.isChecked()));self.refresh()
  except (ValueError,IndexError) as exc:self.result.setPlainText(str(exc))
 def show_result(self,result):
  self.current=result;self.field_index.setMaximum(max(1,len(result['fields'])))
  counts={status:sum(field['status']==status for field in result['fields']) for status in ('LISTO','REVISAR','PENDIENTE')}
  lines=[f"Estado: {result['status']}",f"CV: {result.get('cv_title') or result['cv'] or 'Pendiente'}",f"Listos: {counts['LISTO']} · Requieren revisión: {counts['REVISAR']} · Pendientes: {counts['PENDIENTE']}",f"Bloqueos: {', '.join(result['blockers']) or 'Ninguno'}",'']
  for index,item in enumerate(result['fields'],1):
   lines.extend([f"{index}. {item['question']} · {item['kind']} · {item['status']} · {'Obligatorio' if item['required'] else 'Opcional'}",f"Respuesta: {item.get('answer') or 'Desconocida'}",f"Fuente: {item.get('source','—')} · Confianza: {item.get('confidence','—')} · Verificada: {'Sí' if item.get('verified') else 'No'} · Automática: {'Sí' if item['automatic'] else 'No'} · Intervención: {'No' if item['automatic'] else 'Sí'}",f"Motivo: {item['reason']}",''])
   for citation in item.get('citations',[]):lines.append(f"  {citation['document']} · {citation['location']}: {citation['text']}")
  self.result.setPlainText('\n'.join(lines))
 def refresh(self):
  self.rows=self.service.history();self.history.blockSignals(True);self.history.clear()
  for row in self.rows:self.history.addItem(row['scenario']+' · '+row['company']+' · '+row['status'])
  self.history.blockSignals(False)
 def choose(self,index):
  if 0<=index<len(self.rows):self.show_result(self.rows[index])
