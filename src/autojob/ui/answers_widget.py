import json
from dataclasses import asdict
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,QPlainTextEdit,QPushButton,QCheckBox,QListWidget
from autojob.profile.answers import AnswerBank,resolve_question
from autojob.profile.store import ProfileStore

class AnswersWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.store=ProfileStore(settings.data_path);self.bank=AnswerBank(settings.data_path);self.selected=None
  layout=QVBoxLayout(self);title=QLabel('Respuestas frecuentes');title.setStyleSheet('font-size:24px;font-weight:bold');layout.addWidget(title)
  layout.addWidget(QLabel('Las respuestas aprobadas se desactivan si cambia el perfil. Revisa siempre las preguntas sensibles.'))
  self.items=QListWidget();self.items.setMaximumHeight(140);self.items.currentRowChanged.connect(self.choose);layout.addWidget(self.items)
  row=QHBoxLayout();self.category=QComboBox();self.category.addItems(['Información personal','Experiencia laboral','Customer Service','Programación','Educación','Habilidades blandas','Habilidades técnicas','Disponibilidad','Salarios','Trabajo remoto','Motivación','Otras preguntas']);row.addWidget(self.category)
  self.language=QComboBox();self.language.addItem('Español','es');self.language.addItem('English','en');row.addWidget(self.language);self.approved=QCheckBox('Aprobada');row.addWidget(self.approved);layout.addLayout(row)
  self.questions=QPlainTextEdit();self.questions.setMaximumHeight(85);self.questions.setPlaceholderText('Preguntas equivalentes: una por línea');layout.addWidget(self.questions)
  self.answer=QPlainTextEdit();self.answer.setMaximumHeight(85);self.answer.setPlaceholderText('Respuesta editable');layout.addWidget(self.answer)
  buttons=QHBoxLayout()
  for name,method in [('Nueva',self.new),('Guardar',self.save),('Eliminar',self.delete)]:
   button=QPushButton(name);button.clicked.connect(method);buttons.addWidget(button)
  layout.addLayout(buttons);self.status=QLabel('');self.status.setWordWrap(True);layout.addWidget(self.status)
  self.company=QLineEdit();self.company.setPlaceholderText('Empresa de la vacante');layout.addWidget(self.company)
  self.position=QLineEdit();self.position.setPlaceholderText('Puesto de la vacante');layout.addWidget(self.position)
  self.job_category=QComboBox();self.job_category.addItem('Sin filtro',None);self.job_category.addItem('Técnico','technical');self.job_category.addItem('Customer Service','customer_service');layout.addWidget(self.job_category)
  self.template_choice=QComboBox();self.template_choice.addItem('Plantilla predeterminada',None);layout.addWidget(self.template_choice)
  self.question=QLineEdit();self.question.setPlaceholderText('Escribe una pregunta en español o inglés');layout.addWidget(self.question)
  preview=QPushButton('Probar respuesta');preview.clicked.connect(self.preview);layout.addWidget(preview)
  self.result=QPlainTextEdit();self.result.setReadOnly(True);layout.addWidget(self.result);self.refresh()
 def refresh(self):
  self.rows=self.bank.all();self.items.blockSignals(True);self.items.clear()
  for item in self.rows:self.items.addItem(item['category']+' · '+item['language']+(' · Aprobada' if item['approved'] else ' · Sin aprobar'))
  self.items.blockSignals(False)
 def choose(self,index):
  if index<0 or index>=len(self.rows):return
  item=self.rows[index];self.selected=item['id'];self.category.setCurrentText(item['category']);self.language.setCurrentIndex(self.language.findData(item['language']));self.approved.setChecked(bool(item['approved']));self.questions.setPlainText('\n'.join(json.loads(item['questions'])));self.answer.setPlainText(item['answer'])
 def new(self):self.selected=None;self.questions.clear();self.answer.clear();self.approved.setChecked(False);self.items.clearSelection()
 def save(self):
  try:
   self.selected=self.bank.save(self.category.currentText(),self.language.currentData(),[q.strip() for q in self.questions.toPlainText().splitlines() if q.strip()],self.answer.toPlainText(),self.approved.isChecked(),self.store.load(),self.selected);self.refresh();self.status.setText('Respuesta guardada.')
  except ValueError as exc:self.status.setText(str(exc))
 def delete(self):
  if self.selected:self.bank.delete(self.selected);self.new();self.refresh();self.status.setText('Respuesta eliminada.')
 def preview(self):
  from autojob.resumes.service import ResumeLibrary
  from autojob.profile.templates import TemplateStore
  selected_template=self.template_choice.currentData()
  self.template_choice.blockSignals(True);self.template_choice.clear();self.template_choice.addItem('Plantilla predeterminada',None)
  for row in TemplateStore(self.bank.database.path.parent).all():self.template_choice.addItem(row['intent']+' · '+row['language']+' · '+row['id'],row['id'])
  self.template_choice.setCurrentIndex(max(0,self.template_choice.findData(selected_template)));self.template_choice.blockSignals(False)
  library=ResumeLibrary(self.bank.database.path.parent);records=[];verified=True
  for row in library.list():
   item=library.get(row['id']);verified=verified and bool(item['reviewed']);records.extend(item['structure'].get('experience',[]))
  context={'language':self.language.currentData(),'company':self.company.text().strip(),'position':self.position.text().strip(),'job_category':self.job_category.currentData(),'template_id':selected_template,'employment_records':records,'employment_verified':bool(records) and verified}
  result=resolve_question(self.question.text(),context,self.store.load(),self.bank)
  self.result.setPlainText('\n'.join([f'Pregunta: {result.question}',f'Campo: {result.field or "Desconocido"}',f'Categoría: {result.category}',f'Respuesta: {result.answer or "Sin respuesta"}',f'Fuente: {result.source}',f'Confianza: {result.confidence}',f'Utilizable automáticamente: {"Sí" if result.automatic else "No"}',f'Requiere revisión: {"Sí" if result.review_required else "No"}',f'Motivo: {result.reason}']))
