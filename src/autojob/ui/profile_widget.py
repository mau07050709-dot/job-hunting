from datetime import date
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QScrollArea,QTabWidget,QLabel,QLineEdit,QPlainTextEdit,QComboBox,QPushButton,QMessageBox
from autojob.profile.store import ProfileStore,GROUPS,FIELDS,BOOLS,LISTS,today
from autojob.profile.calculations import age,salary,convert_time
from autojob.resumes.service import ResumeLibrary

class ProfileWidget(QWidget):
 def __init__(self,settings):
  super().__init__();self.settings=settings;self.store=ProfileStore(settings.data_path);self.dirty=False;self.loading=False;self.widgets={};self.labels={};self.confirmers={}
  layout=QVBoxLayout(self);title=QLabel('Mi perfil');title.setStyleSheet('font-size:25px;font-weight:700');layout.addWidget(title)
  self.message=QLabel('Vacío significa desconocido. Confirma solo datos que hayas comprobado.');self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.message)
  self.save_status=QLabel('Sin cambios pendientes');self.save_status.setStyleSheet('color:#a8d5ff;font-weight:bold');layout.addWidget(self.save_status)
  row=QHBoxLayout();self.import_button=QPushButton('Importar datos de mis currículums');self.import_button.clicked.connect(self.import_cvs);row.addWidget(self.import_button)
  self.save_button=QPushButton('Guardar perfil');self.save_button.clicked.connect(self.save);row.addWidget(self.save_button);layout.addLayout(row)
  tabs=QTabWidget();layout.addWidget(tabs)
  for category,fields in GROUPS.items():
   scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body)
   for key,label in fields.items():
    if key in BOOLS:
     widget=QComboBox();widget.addItem('Desconocido',None);widget.addItem('Sí',True);widget.addItem('No',False);widget.currentIndexChanged.connect(self.mark_dirty)
    elif key in LISTS or key in {'schedule','start_availability'}:
     widget=QPlainTextEdit();widget.setMaximumHeight(90);widget.setPlaceholderText('Desconocido · una entrada completa por línea');widget.textChanged.connect(self.mark_dirty)
    else:
     widget=QLineEdit();widget.setPlaceholderText('Desconocido');widget.textChanged.connect(self.mark_dirty)
    self.widgets[key]=widget;self.labels[key]=QLabel(label);form.addRow(self.labels[key],widget)
    confirm=QPushButton('Confirmar este dato');confirm.clicked.connect(lambda *_,k=key:self.confirm(k));self.confirmers[key]=confirm;form.addRow('',confirm)
    if key=='birth_date':
     self.age_label=QLabel('Edad: desconocida');form.addRow(self.age_label);widget.textChanged.connect(self.update_age)
   scroll.setWidget(body);tabs.addTab(scroll,category)
  self.review=QPlainTextEdit();self.review.setReadOnly(True);tabs.addTab(self.review,'Fuentes y conflictos');self.reload()
 def mark_dirty(self,*_):
  if not self.loading:self.dirty=True;self.save_status.setText('Cambios sin guardar')
 def update_age(self,*_):
  try:self.age_label.setText('Edad: '+str(age(date.fromisoformat(self.widgets['birth_date'].text()),today())))
  except ValueError:self.age_label.setText('Edad: desconocida o fecha inválida')
 def values(self):
  result={}
  for key,w in self.widgets.items():
   if key in BOOLS:result[key]=w.currentData()
   elif key in LISTS:result[key]=[line.strip() for line in w.toPlainText().splitlines() if line.strip()]
   else:result[key]=(w.toPlainText() if isinstance(w,QPlainTextEdit) else w.text()).strip() or None
  return result
 def reload(self):
  self.loading=True;self.state=self.store.load()
  lines=[]
  for key,w in self.widgets.items():
   value=self.state['values'][key]
   if key in BOOLS:w.setCurrentIndex(w.findData(value))
   elif isinstance(w,QPlainTextEdit):w.setPlainText('\n'.join(value) if isinstance(value,list) else value or '')
   else:w.setText(value or '')
   manual=key in self.state['manual'];self.labels[key].setText(FIELDS[key]+(' · Confirmado manualmente' if manual else ' · Por revisar' if value else ' · Desconocido'))
   w.setStyleSheet('border-left:3px solid '+('#67dfad' if manual else '#80aaff')+';padding:4px')
   for source in self.state['sources'].get(key,[]):lines.append(FIELDS[key]+': '+source.get('document','Usuario')+' · '+source['status'])
  for key,conflicts in self.state['conflicts'].items():
   lines.append('\nCONFLICTO · '+FIELDS[key])
   for item in conflicts:lines.append(str(item['value'])+' — '+item['source']['document'])
  self.review.setPlainText('\n'.join(lines) or 'Todavía no hay información importada.');self.loading=False;self.dirty=False;self.save_status.setText('Sin cambios pendientes');self.update_age()
 def save(self,*_,confirmed=()):
  try:self.store.save(self.values(),self.state['revision'],confirmed);self.reload();self.message.setText('Perfil guardado correctamente.');self.save_status.setText('Perfil guardado correctamente');return True
  except ValueError as exc:self.message.setText('No se guardó el perfil: '+str(exc));self.save_status.setText('Hay cambios sin guardar');return False
  except Exception:self.message.setText('No se pudo guardar el perfil. Comprueba que Job Hunting tenga acceso a la base de datos.');self.save_status.setText('Hay cambios sin guardar');return False
 def confirm(self,key):self.save(confirmed=[key])
 def import_cvs(self):
  if self.dirty and not self.save():return
  try:
   self.store.import_resumes(ResumeLibrary(self.settings.data_path));self.reload();self.message.setText('Datos importados. Revisa Fuentes y conflictos. Los campos confirmados se conservaron.')
  except Exception:self.message.setText('No se pudo importar. Los datos guardados se conservan; comprueba la biblioteca.')
 def allow_close(self):
  if not self.dirty:return True
  choice=QMessageBox.question(self,'Perfil sin guardar','¿Guardar los cambios de Mi perfil antes de cerrar?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
  if choice==QMessageBox.StandardButton.Save:return self.save()
  return choice==QMessageBox.StandardButton.Discard
