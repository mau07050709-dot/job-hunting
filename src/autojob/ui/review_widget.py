import json
from copy import deepcopy
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QCheckBox,QPushButton,QTableWidget,QTableWidgetItem,QPlainTextEdit,QAbstractItemView,QDialog,QDialogButtonBox,QFormLayout,QLineEdit,QScrollArea,QMessageBox
from autojob.profile.review import ReviewStore,CATEGORIES,known
from autojob.profile.store import BOOLS,LISTS

class ReviewWidget(QWidget):
 changed=Signal()
 def __init__(self,settings):
  super().__init__();self.store=ReviewStore(settings.data_path);self.items=[];layout=QVBoxLayout(self)
  heading=QLabel('Revisar mi perfil · Confirma únicamente lo que hayas contrastado. Los borradores no cuentan como datos confirmados.');heading.setWordWrap(True);layout.addWidget(heading)
  self.documents=QLabel();self.documents.setWordWrap(True);layout.addWidget(self.documents);row=QHBoxLayout();self.category=QComboBox();self.category.addItems(CATEGORIES);row.addWidget(self.category)
  self.unknown=QCheckBox('Mostrar desconocidos');self.unknown.setChecked(True);row.addWidget(self.unknown)
  for title,fn in [('Actualizar',self.refresh),('Corregir / guardar progreso',self.edit),('Confirmar seleccionados',self.confirm_selected),('Confirmar categoría revisada',self.confirm_category)]:
   button=QPushButton(title);button.clicked.connect(fn);row.addWidget(button)
  layout.addLayout(row);self.status=QLabel('Ningún dato se confirma automáticamente.');self.status.setWordWrap(True);layout.addWidget(self.status)
  self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Dato / documento','Valor','Revisión','Avisos']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.details);layout.addWidget(self.table,3)
  self.source=QPlainTextEdit();self.source.setReadOnly(True);layout.addWidget(self.source,2);self.blockers=QPlainTextEdit();self.blockers.setReadOnly(True);self.blockers.setMaximumHeight(140);layout.addWidget(self.blockers)
  self.category.currentTextChanged.connect(self.refresh);self.unknown.toggled.connect(self.refresh);self.refresh()
 def selected(self):
  ids={item.data(256) for item in self.table.selectedItems()};return [r for r in self.items if r['id'] in ids]
 def refresh(self,*_):
  all_items=self.store.inventory();self.items=[r for r in all_items if r['category']==self.category.currentText() and (self.unknown.isChecked() or known(r['value']))];self.table.setRowCount(len(self.items))
  for i,item in enumerate(self.items):
   values=[('Mi perfil / ' if item['source']=='profile' else '')+item['label'],json.dumps(item['value'],ensure_ascii=False) if isinstance(item['value'],(list,dict,bool)) else str(item['value'] or 'Desconocido'),item['state'],item['conflict'] or '']
   for c,value in enumerate(values):
    cell=QTableWidgetItem(value);cell.setData(256,item['id']);cell.setToolTip(value);self.table.setItem(i,c,cell)
  for c,width in enumerate([340,530,230,430]):self.table.setColumnWidth(c,width)
  missing=self.store.expected_documents();self.documents.setText(f'{len(self.store.library.list())} CV disponibles. '+('Sin clasificación específica para: '+', '.join(missing)+'. Un CV mixto compatible puede recomendarse provisionalmente. Importa o revisa su clasificación desde Mis currículums.' if missing else 'Las tres versiones esperadas están disponibles.'))
  confirmed=sum(r['state'].startswith('CONFIRMADO') for r in all_items);unknown=sum(not known(r['value']) for r in all_items);self.status.setText(f'{confirmed} datos con confirmación registrada · {unknown} desconocidos · {len(self.items)} elementos en este bloque. Selecciona una fila para ver la fuente.')
  self.show_blockers()
 def details(self):
  rows=self.selected()
  if rows:
   r=rows[0];self.source.setPlainText('FUENTE: '+('Mi perfil' if r['source']=='profile' else 'CV '+r['source'])+'\nORIGINAL:\n'+json.dumps(r['original'],ensure_ascii=False,indent=2)+'\n\nVALOR DE REVISIÓN:\n'+json.dumps(r['value'],ensure_ascii=False,indent=2)+'\n\n'+str(r['conflict'] or '')+'\nLas correcciones se guardan como revisión; no se reescribe el documento original.')
 def show_blockers(self):
  from autojob.matching.service import Compatibility
  results=Compatibility(self.store.library.data_path).latest().values();lines=[]
  for e in results:
   pending=[r['name'] for r in e['assessments'] if r['importance']=='OBLIGATORIO' and r['state']=='POR VERIFICAR']
   if pending:lines.append(e['title']+': '+', '.join(dict.fromkeys(pending))+' · CV: '+e['resume_selection'].get('status','Pendiente'))
  self.blockers.setPlainText('DATOS QUE IMPIDEN CONFIRMAR VACANTES (las evaluaciones pueden requerir recalcularse):\n'+'\n'.join(lines))
 def confirm_selected(self):self.confirm(self.selected())
 def confirm_category(self):self.confirm([r for r in self.items if known(r['value']) and not r['conflict']])
 def confirm(self,items):
  if not items:self.status.setText('Selecciona datos conocidos; los conflictos se corrigen individualmente.');return
  if QMessageBox.question(self,'Confirmación explícita',f'¿Has revisado los {len(items)} elementos seleccionados y confirmas su contenido? Los datos desconocidos no se completarán.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
  try:
   n=self.store.save([r['id'] for r in items],confirm=True,expected={r['id']:(r['revision'],r['source_hash']) for r in items});self.refresh();self.status.setText(f'{n} datos confirmados. Las evaluaciones afectadas requieren recalcularse.');self.changed.emit()
  except ValueError as exc:self.status.setText(str(exc))
 def edit(self):
  selected=self.selected()
  if len(selected)!=1:self.status.setText('Selecciona un elemento para corregirlo.');return
  item=selected[0];dialog=QDialog(self);dialog.setWindowTitle('Corregir información / guardar progreso');dialog.resize(780,650);layout=QVBoxLayout(dialog);notice=QLabel(item['label']+'\nGuardar progreso conserva un borrador; Confirmar guarda una decisión explícita.');notice.setWordWrap(True);layout.addWidget(notice);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body);scroll.setWidget(body);layout.addWidget(scroll);controls={};value=item['value']
  from autojob.ui.resume_records import LABELS
  from autojob.resumes.semantics import STRUCTURE_KEYS
  keys=STRUCTURE_KEYS[item['group']] if item['group'] else ['value']
  for key in keys:
   v=value.get(key) if item['group'] else value
   if not item['group'] and item['field'] in BOOLS:
    control=QComboBox();control.addItems(['Desconocido','Sí','No']);control.setCurrentIndex(0 if v is None else 1 if v else 2)
   else:
    control=QPlainTextEdit();control.setMaximumHeight(100);control.setPlainText('\n'.join(v) if isinstance(v,list) else str(v) if v is not None else '')
   controls[key]=control;form.addRow(LABELS.get(key,'Valor'),control)
  confirm=QCheckBox('He revisado este dato y quiero confirmarlo');layout.addWidget(confirm);error=QLabel();error.setWordWrap(True);layout.addWidget(error);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
  def save():
   edited=deepcopy(value) if item['group'] else None
   for key,control in controls.items():
    if isinstance(control,QComboBox):v=[None,True,False][control.currentIndex()]
    else:
     text=control.toPlainText().strip();old=value.get(key) if item['group'] else value
     v=[line.strip() for line in text.splitlines() if line.strip()] if isinstance(old,list) or key in {'technologies','responsibilities'} else text or None
    if item['group']:edited[key]=v
    else:edited=v
   try:
    self.store.save([item['id']],confirm.isChecked(),{item['id']:edited},{item['id']:(item['revision'],item['source_hash'])},resolve_conflicts=confirm.isChecked());dialog.accept();self.refresh();self.changed.emit()
   except ValueError as exc:error.setText(str(exc))
  buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject);dialog.exec()
