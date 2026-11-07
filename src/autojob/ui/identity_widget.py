from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QCheckBox,QPushButton,QHBoxLayout,QLabel,QFileDialog,QMessageBox
from autojob.auth.identity import IdentityStore,TYPES,validate

class IdentityWidget(QWidget):
    def __init__(self,settings):
        super().__init__();self.store=IdentityStore(settings.data_path);self.changed=False;layout=QVBoxLayout(self);layout.addWidget(QLabel('Identificación personal · Cifrado DPAPI · Solo uso con autorización específica; excluida de respuestas profesionales'))
        form=QFormLayout();self.kind=QComboBox();self.kind.setEditable(True);self.kind.addItems(TYPES);self.number=QLineEdit();self.number.setEchoMode(QLineEdit.EchoMode.Password);self.number.setPlaceholderText('Escribe un número solo para introducirlo o sustituirlo');self.country=QLineEdit();self.expiry=QLineEdit();self.expiry.setPlaceholderText('AAAA-MM-DD, opcional');self.legal=QLineEdit();self.confirmed=QCheckBox('Dato revisado por mí; no equivale a verificación oficial');self.normalization=QLabel('Sin normalización aplicada');self.accept_normal=QCheckBox('Aplicar la normalización que acabo de revisar');self.accept_normal.setEnabled(False);self.mask=QLabel();self.document=QLabel()
        for label,control in [('Tipo de documento',self.kind),('Número protegido',self.number),('Número guardado',self.mask),('País emisor',self.country),('Vencimiento',self.expiry),('Nombre legal asociado',self.legal),('Estado del dato',self.confirmed),('Vista de normalización',self.normalization),('Decisión de normalizar',self.accept_normal),('Documento digital opcional',self.document)]:form.addRow(label,control)
        layout.addLayout(form);row=QHBoxLayout()
        for label,fn in [('Mostrar normalización',self.preview),('Guardar protegido',self.save),('Confirmar dato',self.confirm),('Visualizar número',self.reveal),('Ocultar',self.hide_number),('Seleccionar documento',self.attach),('Eliminar identificación',self.remove)]:b=QPushButton(label);b.clicked.connect(fn);row.addWidget(b)
        layout.addLayout(row);self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status);layout.addStretch();self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.hide_number);self.number.textEdited.connect(self.edited);self.country.textEdited.connect(self.edited);self.expiry.textEdited.connect(self.edited);self.legal.textEdited.connect(self.edited);self.kind.currentTextChanged.connect(self.edited);self.refresh()
    def edited(self,*args):self.confirmed.setChecked(False);self.accept_normal.setChecked(False);self.accept_normal.setEnabled(False);self.normalization.setText('Sin normalización aplicada')
    def refresh(self):
        row=self.store.summary();self.number.clear();self.number.setEchoMode(QLineEdit.EchoMode.Password);self.accept_normal.setChecked(False)
        if row:
            self.kind.setCurrentText(row['kind']);self.country.setText(row['country']);self.expiry.setText(row['expiry']);self.legal.setText(row['legal_name']);self.confirmed.setChecked(row['confirmed']);self.mask.setText(row['masked']);self.document.setText('Documento cifrado disponible fuera de los respaldos generales' if row['document'] else 'No proporcionado')
        else:self.mask.setText('Sin dato guardado');self.document.setText('No proporcionado');self.confirmed.setChecked(False)
    def preview(self):
        try:
            proposed=validate(self.kind.currentText(),self.number.text());self.normalization.setText(proposed+' · Formato válido; identidad no verificada');self.accept_normal.setEnabled(True);self.timer.start(20000)
        except ValueError as e:self.status.setText(str(e))
    def save(self):
        secret=None
        try:
            number=self.number.text()
            if not number:
                secret=self.store.reveal(True);number=secret.reveal() if secret else ''
            self.store.save(self.kind.currentText(),number,self.country.text(),self.expiry.text(),self.legal.text(),self.confirmed.isChecked(),self.accept_normal.isChecked());self.refresh();self.normalization.setText('Normalización cerrada');self.status.setText('Identificación cifrada para este usuario de Windows. No se ha transmitido.')
        except Exception as e:self.status.setText(str(e) if isinstance(e,ValueError) else 'No se pudo guardar de forma protegida.')
        finally:
            self.number.clear()
            if secret:secret.clear()
    def confirm(self):
        self.confirmed.setChecked(True);self.save()
    def reveal(self):
        secret=self.store.reveal(True)
        if secret:
            try:self.number.setText(secret.reveal());self.number.setEchoMode(QLineEdit.EchoMode.Normal);self.timer.start(20000)
            finally:secret.clear()
    def hide_number(self):self.number.clear();self.number.setEchoMode(QLineEdit.EchoMode.Password);self.normalization.setText('Sin normalización visible');self.accept_normal.setChecked(False)
    def attach(self):
        path,_=QFileDialog.getOpenFileName(self,'Proteger documento local; no adjuntar a portales','','Documento (*.pdf *.png *.jpg *.jpeg)')
        if path:
            try:self.store.attach(path);self.refresh();self.status.setText('Copia cifrada guardada fuera del proyecto. El original no se modifica y no se transmite.')
            except Exception:self.status.setText('No se pudo proteger el documento; revisa formato, tamaño y permisos.')
    def remove(self):
        if QMessageBox.question(self,'Eliminar identidad','¿Eliminar el dato cifrado y la copia protegida opcional?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.store.delete();self.country.clear();self.expiry.clear();self.legal.clear();self.refresh();self.status.setText('Identificación protegida eliminada.')
    def allow_close(self):self.hide_number();return True
