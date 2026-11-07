from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QSpinBox,QLineEdit,QCheckBox,QPushButton,QLabel,QListWidget,QAbstractItemView,QScrollArea,QWidget
from autojob.ui.background import submit

def parse_origins(text):
    """Validate only explicitly entered HTTPS origins; examples never grant access."""
    import re
    from urllib.parse import urlsplit
    from autojob.forms.guard import origin
    values=[value.strip() for value in text.split(';') if value.strip()]
    if not values:raise ValueError('Campo vacío: escribe al menos un origen HTTPS aquí. Los ejemplos no están autorizados.')
    normalized=[]
    for value in values:
        def invalid(reason):raise ValueError(f'«{value}»: {reason}')
        if re.search(r'\s',value):invalid('contiene espacios o varios orígenes sin separar con punto y coma (;).')
        try:part=urlsplit(value);host=part.hostname;port=part.port
        except ValueError:invalid('URL mal formada o puerto inválido.')
        if part.scheme=='http':invalid('HTTP no está permitido; utiliza HTTPS.')
        if part.scheme!='https' or not host:invalid('URL mal formada; debe comenzar con https:// y tener un dominio.')
        if part.username is not None or part.password is not None:invalid('no se permiten credenciales en la URL.')
        if part.path not in {'','/'} or part.query or part.fragment:invalid('usa el origen sin rutas, consultas ni fragmentos, por ejemplo https://jobs.lever.co.')
        try:ascii_host=host.encode('idna').decode('ascii')
        except UnicodeError:invalid('nombre de dominio mal formado.')
        if not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',label) for label in ascii_host.split('.')) or len(ascii_host)>253:invalid('nombre de dominio mal formado.')
        if host in {'localhost','127.0.0.1'} or host.endswith('.invalid'):invalid('el lote requiere un origen HTTPS público, no un destino local o ficticio.')
        if part.netloc.endswith(':'):invalid('falta el número de puerto después de los dos puntos.')
        if port is not None and port<1:invalid('el puerto debe estar entre 1 y 65535.')
        canonical='https://'+ascii_host.lower()+(f':{port}' if port and port!=443 else '')
        if canonical in normalized:invalid('origen duplicado; déjalo una sola vez.')
        normalized.append(origin(canonical))
    return normalized

class BatchAuthorization(QDialog):
    def __init__(self,shell):
        super().__init__(shell.window);self.shell=shell;self.authorization=None;self.setWindowTitle('Revisar autorización de lote');self.resize(780,750);outer=QVBoxLayout(self);self.scroll=scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll)
        label=QLabel('Autoriza una sesión limitada. Los puestos nuevos solo se incorporan si cumplen TODOS los criterios. Al reiniciar Job Hunting el lote no se activa automáticamente. Contratos, identidad, pagos y declaraciones extraordinarias quedan excluidos.');label.setWordWrap(True);layout.addWidget(label);form=QFormLayout();layout.addLayout(form)
        self.field_errors={}
        def add_field(key,label,widget):
            form.addRow(label,widget);error=QLabel();error.setWordWrap(True);error.setTextFormat(Qt.TextFormat.PlainText);error.setStyleSheet('color:#ff9b9b;font-weight:600');self.field_errors[key]=error;form.addRow('',error)
        self.maximum=QSpinBox();self.maximum.setRange(1,100);self.maximum.setValue(3);add_field('maximum','Máximo de transmisiones finales',self.maximum)
        self.hours=QSpinBox();self.hours.setRange(1,12);self.hours.setValue(2);add_field('hours','Duración (horas)',self.hours)
        self.threshold=QSpinBox();self.threshold.setRange(0,100);self.threshold.setValue(70);add_field('threshold','Umbral profesional',self.threshold)
        self.modalities=QLineEdit('remote');add_field('modalities','Modalidades: remote, onsite, hybrid',self.modalities)
        self.regions=QLineEdit('Costa Rica');add_field('regions','Regiones (separar con ;): Costa Rica; Cartago, Costa Rica',self.regions)
        self.types=QLineEdit('Customer Support; Customer Service; Technical Support');add_field('types','Tipos de puesto (contiene, separar con ;)',self.types)
        self.domains=QLineEdit();self.domains.setObjectName('batch_https_origins');self.domains.setAccessibleName('Orígenes HTTPS exactos autorizados');self.domains.setPlaceholderText('Escribe aquí los orígenes HTTPS (obligatorio)');self.domains.setAccessibleDescription('Campo editable vacío. Separa varios orígenes con punto y coma. Los ejemplos no son permisos.');add_field('domains','&Orígenes HTTPS exactos autorizados',self.domains)
        self.domains.setStyleSheet('QLineEdit{border:2px solid #7ba7d9} QLineEdit:focus{border:2px solid #76ddff}')
        self.domain_help=QLabel('Ejemplos, sin autorización: https://jobs.lever.co; https://job-boards.greenhouse.io\nEscribe solo los orígenes que autorizas, separados por punto y coma (;).');self.domain_help.setWordWrap(True);self.domain_help.setTextFormat(Qt.TextFormat.PlainText);form.addRow('',self.domain_help)
        self.domain_status=QLabel();self.domain_status.setWordWrap(True);self.domain_status.setTextFormat(Qt.TextFormat.PlainText);form.addRow('',self.domain_status);self.domains.textChanged.connect(self.check_domains);self.check_domains()
        self.excluded=QLineEdit();add_field('excluded','Requisitos excluidos (separar con ;)',self.excluded)
        self.salary=QLineEdit();self.salary.setPlaceholderText('Vacío: no aplicar filtro salarial');add_field('salary','Salario mínimo publicado',self.salary)
        self.currency=QLineEdit('USD');add_field('currency','Moneda comparable: USD o CRC',self.currency)
        self.period=QLineEdit('month');add_field('period','Período: month, year, hour',self.period)
        self.cvs=QListWidget();self.cvs.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection);layout.addWidget(QLabel('Selecciona explícitamente los CV autorizados'));layout.addWidget(self.cvs);self.field_errors['cv']=QLabel();self.field_errors['cv'].setWordWrap(True);self.field_errors['cv'].setStyleSheet('color:#ff9b9b;font-weight:600');layout.addWidget(self.field_errors['cv'])
        self.upload=QCheckBox('Autorizo adjuntar los CV seleccionados en los dominios y condiciones indicados');self.send=QCheckBox('He revisado los límites y autorizo enviar formularios ordinarios de este lote')
        layout.addWidget(self.upload);self.field_errors['upload']=QLabel();self.field_errors['upload'].setStyleSheet('color:#ff9b9b;font-weight:600');layout.addWidget(self.field_errors['upload']);layout.addWidget(self.send);self.field_errors['send']=QLabel();self.field_errors['send'].setStyleSheet('color:#ff9b9b;font-weight:600');layout.addWidget(self.field_errors['send']);self.status=QLabel('Cargando CV revisados…');self.status.setWordWrap(True);layout.addWidget(self.status);self.button=QPushButton('AUTORIZAR LOTE');self.button.setEnabled(False);self.button.clicked.connect(self.save);layout.addWidget(self.button);self.rows=[];self.saving=False
        path=shell.settings.data_path
        def load():
            from autojob.forms.submissions import SubmissionStore
            store=SubmissionStore(path);return dict(cvs=[r for r in store.prep.compatibility.library.list() if r['reviewed']],profile=store.prep.data.profile_state()['values'])
        def done(data):
            rows=data['cvs'];self.rows=rows;profile=data['profile']
            if profile.get('salary_min') is not None:self.salary.setText(str(profile['salary_min']));self.currency.setText(profile.get('currency') or 'USD')
            for r in rows:self.cvs.addItem(r['title']+' · '+r['language'])
            self.button.setEnabled(True);self.status.setText('Ningún permiso ni CV está preaceptado. Salario desconocido queda pendiente si defines mínimo; presencial/híbrido solo Cartago, Costa Rica explícito.')
        submit(shell.window,load,done,self.status.setText)
    def check_domains(self):
        try:
            was_invalid=bool(self.field_errors['domains'].text());domains=parse_origins(self.domains.text());self.domain_status.setText(f'{len(domains)} origen(es) introducido(s): '+ '; '.join(domains)+'\nSe autorizarán solo al pulsar AUTORIZAR LOTE.');self.field_errors['domains'].clear()
            if was_invalid and hasattr(self,'status'):self.status.setText('Orígenes válidos. Revisa los demás campos y pulsa AUTORIZAR LOTE.')
        except ValueError as exc:self.domain_status.setText(str(exc))
    def focus_problem(self,key):
        widget={'domains':self.domains,'modalities':self.modalities,'regions':self.regions,'types':self.types,'cv':self.cvs,'upload':self.upload,'send':self.send,'salary':self.salary}.get(key,self.domains)
        widget.setFocus();self.scroll.ensureWidgetVisible(widget,20,90)
    def save(self):
        if self.saving:return
        split=lambda value:[x.strip() for x in value.split(';') if x.strip()]
        for error in self.field_errors.values():error.clear()
        problems={}
        modalities=[x.strip().lower() for x in self.modalities.text().split(',') if x.strip()]
        if not modalities or set(modalities)-{'remote','onsite','hybrid'}:problems['modalities']='Usa uno o más valores: remote, onsite, hybrid (separados por coma).'
        regions=split(self.regions.text())
        if not regions or set(regions)-{'Costa Rica','Cartago, Costa Rica'}:problems['regions']='Usa Costa Rica y/o Cartago, Costa Rica; separa con punto y coma.'
        try:normalized=parse_origins(self.domains.text())
        except ValueError as exc:
            normalized=[];problems['domains']=str(exc)
            if not self.domains.text().strip() and '://' in self.excluded.text():problems['domains']+=' Hay una URL en «Requisitos excluidos»; ese campo no autoriza portales. Revisa y escribe el origen en HTTPS.'
        types=split(self.types.text())
        if not types:problems['types']='Agrega al menos un tipo de puesto.'
        if not self.cvs.selectedItems():problems['cv']='Selecciona al menos un CV revisado para autorizarlo.'
        if not self.upload.isChecked():problems['upload']='Marca esta casilla para permitir adjuntar el CV seleccionado.'
        if not self.send.isChecked():problems['send']='Marca esta casilla para autorizar los envíos ordinarios de este lote.'
        try:salary=float(self.salary.text()) if self.salary.text().strip() else None
        except ValueError:salary=None;problems['salary']='Escribe un importe numérico o deja el campo vacío.'
        if salary is not None and (salary<0 or self.currency.text().strip().upper() not in {'USD','CRC'} or self.period.text().strip().lower() not in {'month','year','hour'}):
            problems['salary']='El salario debe ser positivo y comparable; confirma moneda USD/CRC y período month/year/hour.'
        if problems:
            for key,message in problems.items():self.field_errors[key].setText('⚠ '+message)
            self.status.setText('No se activó el lote. '+next(iter(problems.values())));self.focus_problem(next(iter(problems)));return
        c=dict(modalities=modalities,regions=regions,domains=normalized,cv_ids=[self.rows[self.cvs.row(i)]['id'] for i in self.cvs.selectedItems()],types=types,threshold=self.threshold.value(),excluded=split(self.excluded.text()),salary_min=salary,salary_currency=self.currency.text().strip().upper(),salary_period=self.period.text().strip().lower());args=(c,self.maximum.value(),self.hours.value(),self.upload.isChecked(),self.send.isChecked());path=self.shell.settings.data_path;self.saving=True;self.button.setEnabled(False);self.status.setText('Validando criterios, permisos y CV seleccionados…')
        def save():
            from autojob.forms.submissions import SubmissionStore
            from autojob.forms.batches import create
            return create(SubmissionStore(path),*args)
        def done(id):self.authorization=id;self.accept()
        def failed(message):
            self.saving=False;self.button.setEnabled(True);self.status.setText('No se activó el lote: '+message)
            lower=message.casefold()
            keys=['upload','send'] if 'adjunt' in lower or 'envío ordinario' in lower else ['cv'] if 'cv' in lower or 'currículum' in lower else ['domains'] if 'dominio' in lower or 'https' in lower else ['regions'] if 'geograf' in lower or 'cartago' in lower else ['salary'] if 'salario' in lower else ['maximum','hours'] if 'límite' in lower else ['types','excluded','threshold']
            for key in keys:
                if key in self.field_errors:self.field_errors[key].setText('⚠ '+message)
        submit(self.shell.window,save,done,failed)
