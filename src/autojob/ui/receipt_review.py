from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QLineEdit,QComboBox,QCheckBox,QFileDialog
from autojob.forms.submissions import SubmissionStore
from autojob.forms.manual_receipts import incorporate

class ReceiptReview(QDialog):
    def __init__(self,shell,job_id):
        super().__init__(shell.window);self.shell=shell;self.store=SubmissionStore(shell.settings.data_path);self.path=None;self.attempt=next((r for r in self.store.rows() if r['job_id']==job_id and r['state']=='ENVÍO NO VERIFICADO'),None);self.setWindowTitle('Incorporar comprobante legítimo');self.resize(700,480);box=QVBoxLayout(self)
        job=next(j for j in self.store.prep.compatibility.jobs.list() if j['id']==job_id);label=QLabel(job['company']+' · '+job['title']+'\n'+job['url']+'\nNo se consulta tu correo ni se repite el envío. Aporta un archivo de confirmación que ya hayas revisado.');label.setWordWrap(True);box.addWidget(label)
        self.file=QLabel('Ningún archivo seleccionado');box.addWidget(self.file);choose=QPushButton('Seleccionar comprobante');choose.clicked.connect(self.choose);box.addWidget(choose);self.channel=QComboBox();self.channel.addItems(['Correo','Portal']);box.addWidget(self.channel);self.date=QLineEdit();self.date.setPlaceholderText('Fecha recibida: AAAA-MM-DDTHH:MM:SS-06:00');box.addWidget(self.date);self.reference=QLineEdit();self.reference.setPlaceholderText('Identificador real del portal, si existe (opcional)');box.addWidget(self.reference);self.confirm=QCheckBox('Revisé el archivo: es una recepción legítima de esta empresa, este puesto y este intento');box.addWidget(self.confirm);self.status=QLabel();self.status.setWordWrap(True);box.addWidget(self.status);save=QPushButton('GUARDAR COMPROBANTE Y CONCILIAR');save.clicked.connect(self.save);box.addWidget(save)
    def choose(self):
        name,_=QFileDialog.getOpenFileName(self,'Seleccionar comprobante aportado','','Comprobantes (*.eml *.txt *.pdf *.png *.jpg *.jpeg)')
        if name:self.path=name;self.file.setText(name)
    def save(self):
        try:
            if not self.attempt or not self.path:raise ValueError('Selecciona el intento incierto y su comprobante.')
            incorporate(self.store,self.attempt['id'],self.path,self.date.text().strip(),self.channel.currentText(),self.reference.text().strip(),self.confirm.isChecked());self.shell.refresh();self.accept()
        except (ValueError,UnicodeError) as exc:self.status.setText(str(exc))
