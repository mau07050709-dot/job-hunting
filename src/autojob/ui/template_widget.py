from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QComboBox,QPlainTextEdit,QPushButton
from autojob.profile.templates import TemplateStore,INTENTS

class TemplateWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.store=TemplateStore(settings.data_path);self.selected=None;layout=QVBoxLayout(self)
  layout.addWidget(QLabel('Plantillas profesionales · Los resultados son borradores sujetos a revisión.'))
  self.items=QComboBox();self.items.currentIndexChanged.connect(self.choose);layout.addWidget(self.items)
  self.intent=QComboBox();self.intent.addItems(list(INTENTS));layout.addWidget(self.intent)
  self.language=QComboBox();self.language.addItems(['es','en']);layout.addWidget(self.language)
  layout.addWidget(QLabel('Variables: {name}, {company}, {position}, {skills}, {experience}, {soft_skills}, {languages}'))
  self.body=QPlainTextEdit();layout.addWidget(self.body)
  self.status=QLabel();layout.addWidget(self.status)
  for title,callback in [('Nueva plantilla',self.new),('Guardar plantilla',self.save)]:
   button=QPushButton(title);button.clicked.connect(callback);layout.addWidget(button)
  self.refresh()
 def refresh(self):
  self.rows=self.store.all();self.items.blockSignals(True);self.items.clear()
  for row in self.rows:self.items.addItem(row['intent']+' · '+row['language']+' · '+row['id'],row['id'])
  self.items.blockSignals(False)
  if self.rows:self.choose(0)
 def choose(self,index):
  if index<0 or index>=len(self.rows):return
  row=self.rows[index];self.selected=row['id'];self.intent.setCurrentText(row['intent']);self.language.setCurrentText(row['language']);self.body.setPlainText(row['body'])
 def new(self):self.selected=None;self.body.clear();self.status.setText('Nueva plantilla: elige tipo e idioma.')
 def save(self):
  try:
   key=self.store.save(self.intent.currentText(),self.language.currentText(),self.body.toPlainText(),self.selected);self.refresh();self.items.setCurrentIndex(self.items.findData(key));self.status.setText('Plantilla guardada.')
  except ValueError as exc:self.status.setText(str(exc))
