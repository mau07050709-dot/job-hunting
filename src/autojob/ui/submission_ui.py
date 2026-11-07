"""Autorización revisable y preguntas pendientes con tipos y alcance explícitos."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPlainTextEdit,QComboBox,QCheckBox,QPushButton,QListWidget,QAbstractItemView,QSpinBox,QTableWidget,QTableWidgetItem,QWidget
from autojob.forms.answers9b import ScopedAnswers,validate_answer,restricted
from autojob.forms.submissions import SubmissionStore,eligible_row

class MissingInformation(QDialog):
    def __init__(self,center,row):
        super().__init__(center.window());self.center=center;self.row=row;self.setWindowTitle('Job Hunting necesita información');self.setModal(False);self.resize(760,580);layout=QVBoxLayout(self)
        self.job={};self.all_entries=[];self.entries=[];self.loading=True;self.saving=False
        label=QLabel(row['company']+' · '+row['title']+'\n'+row['url']);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);layout.addWidget(label);self.question=QComboBox();self.question.addItems([e['label'] for e in self.entries]);layout.addWidget(self.question);self.details=QLabel();self.details.setWordWrap(True);self.details.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.details);self.form=QFormLayout();layout.addLayout(self.form);self.control=None
        self.scope=QComboBox();self.scope.addItem('Solo esta vacante','job');self.scope.addItem('Esta empresa','company');self.scope.addItem('Dato personal reutilizable','personal');self.scope.addItem('Respuesta laboral reutilizable','work');layout.addWidget(self.scope);self.confirm=QCheckBox('Confirmo que esta respuesta es verdadera y autorizo su uso en el alcance seleccionado');layout.addWidget(self.confirm);self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status);buttons=QHBoxLayout()
        for text,fn in [('GUARDAR Y CONTINUAR',self.save),('RESPONDER DESPUÉS',lambda:(center.later(row),self.close())),('OMITIR ESTA POSTULACIÓN',lambda:(center.omit(row),self.close())),('ABRIR EN BRAVE',self.open)]:b=QPushButton(text);b.clicked.connect(fn);buttons.addWidget(b)
        layout.addLayout(buttons);self.question.currentIndexChanged.connect(self.change);self.change()
        from autojob.ui.background import submit
        data_path=center.shell.settings.data_path;job_id=row['job_id']
        def load():
            from autojob.forms.queue import PreparationQueue
            from autojob.forms.runner import enrich
            queue=PreparationQueue(data_path);q=next((r for r in queue.list() if r['job_id']==job_id),{});payload=q.get('payload',{});doc=(payload.get('stages') or [{}])[-1].get('document',{});job=next((j for j in queue.preparation.compatibility.jobs.list() if j['id']==job_id),{});preview=queue.preparation.prepare(doc,job);entries=[];seen=set()
            for e in preview['entries']:
                if (e.get('name') or e['label']) in payload.get('manual_conflicts',[]):e=dict(e,status='DESCONOCIDA',answer=None)
                key=(e['kind'],e.get('group') or e['label'])
                if not e.get('requires_specific_consent') and (e.get('required') or e['label'] in payload.get('review_optional',[])) and enrich(queue.preparation,e).get('status') not in {'CONFIRMADA','DERIVADA','DOCUMENTO LOCAL'} and key not in seen:entries.append(e);seen.add(key)
            from autojob.live import proposed
            for entry in entries:
                value=proposed(job_id,entry)
                if value is not None:entry['answer']=value;entry['reason']='Escrito en la sesión preparada; confirma el dato y su alcance para reutilizarlo.'
            return dict(job=job,all_entries=preview['entries'],entries=entries)
        def loaded(data):
            self.loading=False;self.job=data['job'];self.all_entries=data['all_entries'];self.entries=data['entries'];self.question.addItems([e['label'] for e in self.entries]);self.change()
        def failed(message):self.loading=False;self.status.setText(message)
        self.status.setText('Cargando datos y validaciones…');self.load_task=submit(center.window(),load,loaded,failed)
    def change(self,*args):
        while self.form.count():
            item=self.form.takeAt(0)
            if item.widget():item.widget().deleteLater()
        if not self.entries:self.details.setText('Revisa los datos existentes, documentos o permisos. No hay una pregunta reutilizable pendiente.');self.control=None;return
        e=self.entries[self.question.currentIndex()];kind=e['kind'];self.details.setText('Pregunta original: '+(e.get('group') or e['label'])+'\nTipo: '+kind+(' · Obligatorio' if e.get('required') else ' · Opcional')+'\nInformación relacionada: '+e.get('reason','Sin respuesta confirmada')+'\nFuente: '+e.get('source','Desconocida'))
        options=[o['label'] for o in e.get('options',[])]
        if kind=='radio':options=[o['label'] for o in self.all_entries if o['kind']=='radio' and (o.get('name') or o.get('group'))==(e.get('name') or e.get('group'))]
        translation={'How many years of experience do you have in customer service?':'¿Cuántos años de experiencia tienes en atención al cliente?','Current company':'Empresa actual','Full name':'Nombre completo'}
        original=e.get('group') or e['label']
        if original in translation:self.details.setText(self.details.text()+'\nTraducción: '+translation[original])
        self.confirm.setChecked(False)
        if kind=='multiple':self.control=QListWidget();self.control.addItems(options);self.control.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        elif kind in {'select','radio','combobox','checkbox'}:
            self.control=QComboBox();self.control.addItem('Selecciona...',None)
            for o in (['Yes','No'] if kind=='checkbox' else options):self.control.addItem(o,o)
        elif kind=='textarea':self.control=QPlainTextEdit()
        else:self.control=QLineEdit();self.control.setPlaceholderText('AAAA-MM-DD' if kind=='date' else 'Número sin separadores de miles' if kind=='number' else 'Respuesta confirmada')
        if kind=='number':self.control.setValidator(QDoubleValidator(self.control))
        # Mostrar el dato existente como propuesta, sin confirmarlo ni volver a pedir su escritura.
        proposed=e.get('answer')
        if proposed is not None and e.get('status') not in {'CONFLICTO','BLOQUEADA'} and not e.get('sensitive_identity'):
            if isinstance(self.control,QLineEdit):self.control.setText(str(proposed))
            elif isinstance(self.control,QPlainTextEdit):self.control.setPlainText(str(proposed))
            elif isinstance(self.control,QComboBox):
                from autojob.profile.answers import norm
                expected='Yes' if norm(str(proposed)) in {'si','yes','true'} else 'No' if norm(str(proposed)) in {'no','false'} else str(proposed)
                index=self.control.findData(expected)
                if index>=0:self.control.setCurrentIndex(index)
        self.form.addRow('Respuesta',self.control)
        if restricted(e['label']) or e['kind']=='file':self.control.setEnabled(False);self.status.setText('Usa los datos protegidos, permisos específicos o gestión de documentos. Este diálogo no almacena identificación ni consentimientos.')
        else:self.status.clear()
    def save(self):
        if self.loading or self.saving or not self.control or not self.control.isEnabled():return
        if not self.confirm.isChecked():self.status.setText('Confirma la respuesta y su alcance.');return
        e=dict(self.entries[self.question.currentIndex()]);c=self.control
        value='|'.join(i.text() for i in c.selectedItems()) if isinstance(c,QListWidget) else c.currentData() if isinstance(c,QComboBox) else c.toPlainText() if isinstance(c,QPlainTextEdit) else c.text()
        if value is None:self.status.setText('Selecciona una respuesta.');return
        context=dict(job_id=self.job.get('id'),company=self.job.get('company'),position=self.job.get('title'),modality=self.job.get('modality'));scope=self.scope.currentData();data_path=self.center.shell.settings.data_path;authorization=self.center.shell.delivery_authorization;job=dict(self.job)
        question=e['group'] if e['kind']=='radio' and e.get('group') else ((e.get('group','')+' ') if e.get('group') and e['kind'] in {'checkbox','radio','multiple'} else '')+e['label']
        options=[o['label'] for o in self.all_entries if o['kind']=='radio' and (o.get('name') or o.get('group'))==(e.get('name') or e.get('group'))] if e['kind']=='radio' else [o['label'] for o in e.get('options',[])]
        self.saving=True;self.question.setEnabled(False);self.status.setText('Guardando y revalidando…')
        from autojob.ui.background import submit
        def save():
            from autojob.forms.preparation import Preparation
            prep=Preparation(data_path);before=prep.inputs_hash();ScopedAnswers(data_path).save(question,value,e['kind'],scope,context,True,options)
            current=next((j for j in prep.compatibility.jobs.list() if j['id']==job['id']),job);prep.compatibility.one(current,force=True)
            if authorization:SubmissionStore(data_path).accept_confirmed_answer(authorization,job['id'],before)
            # Revalidar y resolver únicamente el bloqueo cuya evidencia ya es suficiente.
            from autojob.control import Coordinator
            from autojob.interventions import InterventionService
            service=InterventionService(Coordinator(self.center.shell.settings));return service.resume(self.row['id'])
        def done(result):
            from autojob.live import active,command
            if result and result[0] and result[1] and not active(result[1]):self.center.resume_ids.add(result[1])
            command(self.row['job_id'],'CHECK')
            self.saving=False;self.question.setEnabled(True);self.status.setText('Respuesta confirmada guardada. La preparación se revalidará antes de continuar.');self.entries.remove(e);self.question.blockSignals(True);self.question.clear();self.question.addItems([r['label'] for r in self.entries]);self.question.blockSignals(False);self.center.shell.request_refresh()
            if not self.entries:self.close()
            else:self.change()
        def failed(message):self.saving=False;self.question.setEnabled(True);self.status.setText(message)
        self.save_task=submit(self.center.window(),save,done,failed)
    def open(self):
        posts=self.center.shell.posts;posts.refresh()
        for n,r in enumerate(posts.rows):
            if r['job']['id']==self.row['job_id']:posts.table.selectRow(n);posts.open();return

class AuthorizeSubmission(QDialog):
    def __init__(self,shell):
        super().__init__(shell.window);self.shell=shell;self.authorization=None;self.rows=[];self.loading=True;self.review_pending=False;self.review_generation=0;self.saving=False;self.store=None
        self.setWindowTitle('Revisar y autorizar envío automático');self.resize(800,680);layout=QVBoxLayout(self)
        self.review=QPlainTextEdit();self.review.setReadOnly(True);self.review.setMaximumHeight(230);layout.addWidget(self.review)
        layout.addWidget(QLabel('Selecciona UNA candidatura y revisa los datos concretos antes de autorizar.'))
        self.jobs=QListWidget();self.jobs.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection);self.jobs.itemSelectionChanged.connect(self.review_selected);layout.addWidget(self.jobs)
        summary=QLabel('Solo vacantes compatibles, abiertas, con geografía y requisitos verificados y CV revisado.\nEl permiso caduca en 12 horas y vincula puesto, CV y respuestas. No incluye identidad, contratos, pagos, antecedentes ni acuerdos extraordinarios. El primer envío real se limita a una candidatura.');summary.setWordWrap(True);layout.addWidget(summary)
        self.maximum=QSpinBox();self.maximum.setRange(1,100);self.maximum.setValue(1);layout.addWidget(self.maximum)
        self.upload=QCheckBox('Autorizo adjuntar el CV seleccionado (puede transmitirse al seleccionar el archivo)');layout.addWidget(self.upload)
        self.consent=QCheckBox('He revisado los datos, CV, vacantes y alcance; autorizo envíos reales');layout.addWidget(self.consent)
        self.fiveca_assessment=QCheckBox('5CA: autorizo el tratamiento de resultados de las evaluaciones de selección (aviso completo en la revisión)')
        self.fiveca_processing=QCheckBox('5CA: he revisado el aviso de privacidad y autorizo el tratamiento de esta candidatura')
        for box in (self.fiveca_assessment,self.fiveca_processing):layout.addWidget(box);box.hide()
        self.status=QLabel('Cargando candidaturas elegibles…');self.status.setWordWrap(True);layout.addWidget(self.status);row=QHBoxLayout();self.authorize_button=QPushButton('AUTORIZAR MODO AUTOMÁTICO');self.authorize_button.setEnabled(False);self.authorize_button.clicked.connect(self.save);row.addWidget(self.authorize_button);cancel=QPushButton('Cancelar');cancel.clicked.connect(self.reject);row.addWidget(cancel);layout.addLayout(row)
        from autojob.ui.background import submit
        path=shell.settings.data_path
        def load():
            store=SubmissionStore(path);return [r for r in store.prep.compatibility.rows() if eligible_row(r) and not store.duplicate(r['job'])]
        def loaded(rows):
            self.loading=False;self.rows=rows
            for r in rows:self.jobs.addItem(r['job']['company']+' · '+r['job']['title']+' · '+r['job']['url'])
            self.status.setText('Selecciona una candidatura para revisar.' if rows else 'No hay candidaturas nuevas elegibles. Los envíos inciertos o confirmados no se repiten.')
        def failed(message):self.loading=False;self.status.setText(message)
        self.load_task=submit(shell.window,load,loaded,failed)
    def review_selected(self):
        from autojob.forms import fiveca
        from autojob.ui.background import submit
        self.review_generation+=1;generation=self.review_generation;selected=[self.rows[self.jobs.row(i)] for i in self.jobs.selectedItems()]
        for box in (self.upload,self.consent,self.fiveca_assessment,self.fiveca_processing):box.setChecked(False)
        special=any(fiveca.accepts(r['job'].get('application_url') or r['job']['url']) for r in selected)
        for box in (self.fiveca_assessment,self.fiveca_processing):box.setVisible(special)
        self.authorize_button.setEnabled(False)
        if not selected:self.review.clear();self.review_pending=False;return
        self.review_pending=True;self.status.setText('Verificando documentos y respuestas…');path=self.shell.settings.data_path
        def review():
            from autojob.forms.queue import PreparationQueue
            from autojob.forms.runner import enrich
            from hashlib import sha256
            store=SubmissionStore(path);queued={r['job_id']:r for r in PreparationQueue(path).list()};lines=[]
            for r in selected:
                job=r['job'];cv_id=r['evaluation']['resume_selection']['resume_id'];cv=store.prep.compatibility.library.get(cv_id);file=store.prep.compatibility.library.original_path(cv_id,verify=True)
                lines.extend([job['company']+' · '+job['title'],job.get('application_url') or job['url'],'CV: '+cv['title']+' · SHA256: '+sha256(file.read_bytes()).hexdigest()[:16]])
                doc=((queued.get(job['id'],{}).get('payload',{}).get('stages') or [{}])[-1]).get('document')
                if doc:
                    shown=set()
                    for entry in store.prep.prepare(doc,job)['entries']:
                        e=enrich(store.prep,entry);question=e.get('group') if e['kind']=='radio' and e.get('group') else e['label']
                        if e.get('required') and e['kind']!='file' and not e.get('sensitive_identity') and question not in shown:lines.append(question+': '+(str(e['answer']) if e['status'] in {'CONFIRMADA','DERIVADA'} else 'PENDIENTE')+' ['+e.get('source','')+']');shown.add(question)
                else:lines.append('El formulario se revalidará antes de transmitir datos; cualquier respuesta desconocida requiere intervención.')
                from autojob.forms.doola import accepts as doola_form
                if doola_form(job.get('application_url') or job['url']):lines.append('Destino de los datos y CV: jobs.lever.co (Lever, candidatura doola). El portal utiliza controles de seguridad de Cloudflare y hCaptcha, que reciben datos de navegación. Si se solicita un desafío, solo tú lo resolverás en Brave mediante el Centro de intervenciones. No se crearán cuentas ni se aceptarán contratos.')
                from autojob.forms.greenhouse import TARGET,PROCESSORS
                if (job.get('application_url') or job['url'])==TARGET:lines.append('Procesadores autorizados para Cloudbeds: '+', '.join(PROCESSORS))
            if special:lines.extend(['AVISOS ESPECÍFICOS 5CA:',fiveca.ASSESSMENT,fiveca.PROCESSING,'Comunicaciones generales/newsletter: No. No se aportan datos de referencias.','Destino: formulario oficial jobs.5ca.com.'])
            return '\n'.join(lines)
        def done(text):
            if generation!=self.review_generation:return
            self.review_pending=False;self.review.setPlainText(text);self.authorize_button.setEnabled(True);self.status.setText('Revisión disponible. Ningún permiso está preaceptado.')
        def failed(message):
            if generation==self.review_generation:self.review_pending=False;self.status.setText(message)
        self.review_task=submit(self.shell.window,review,done,failed)
    def save(self):
        if self.loading or self.review_pending or self.saving:self.status.setText('Espera a que termine la revisión de esta candidatura.');return
        ids=[self.rows[self.jobs.row(i)]['job']['id'] for i in self.jobs.selectedItems()]
        if not ids:self.status.setText('Selecciona una candidatura elegible.');return
        from autojob.forms import fiveca
        from autojob.ui.background import submit
        args=dict(jobs=ids,max_count=self.maximum.value(),upload=self.upload.isChecked(),explicit=self.consent.isChecked(),special_consents=fiveca.consents() if self.fiveca_assessment.isChecked() and self.fiveca_processing.isChecked() else None);path=self.shell.settings.data_path
        self.saving=True;self.authorize_button.setEnabled(False);self.jobs.setEnabled(False);self.status.setText('Validando y guardando autorización…')
        def done(authorization):self.authorization=authorization;self.saving=False;self.accept()
        def failed(message):self.saving=False;self.jobs.setEnabled(True);self.authorize_button.setEnabled(True);self.status.setText(message)
        self.save_task=submit(self.shell.window,lambda:SubmissionStore(path).authorize(**args),done,failed)


class LetterReview(QDialog):
    def __init__(self,center,row):
        super().__init__(center.window());self.center=center;self.row=row;self.setWindowTitle('Revisar carta de presentación');self.resize(760,650);layout=QVBoxLayout(self)
        from autojob.forms.submission_letters import SubmissionLetters
        self.service=SubmissionLetters(center.shell.settings.data_path);self.job=next(j for j in center.shell.engine.jobs.list() if j['id']==row['job_id']);evaluation=center.shell.engine.compatibility.latest().get(self.job['id']);cv_id=evaluation['resume_selection']['resume_id'];self.letter=self.service.draft(self.job,cv_id)
        label=QLabel(self.job['company']+' · '+self.job['title']+' · Idioma: '+self.letter['language']);label.setWordWrap(True);layout.addWidget(label);self.body=QPlainTextEdit();self.body.setPlainText(self.letter['body']);layout.addWidget(self.body);self.confirm=QCheckBox('Revisé los hechos y autorizo adjuntar esta carta a esta vacante');layout.addWidget(self.confirm);self.status=QLabel();layout.addWidget(self.status);button=QPushButton('GUARDAR Y APROBAR CARTA');button.clicked.connect(self.save);layout.addWidget(button)
    def save(self):
        try:self.service.approve(self.job,self.letter['id'],self.body.toPlainText(),self.confirm.isChecked());self.center.refresh();self.close()
        except ValueError as exc:self.status.setText(str(exc))


class ApprovedAnswersPanel(QWidget):
    def __init__(self,data_path):
        super().__init__();self.store=ScopedAnswers(data_path);layout=QVBoxLayout(self);layout.addWidget(QLabel('Respuestas aprobadas desde intervenciones · Alcance e historial conservados'));self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Pregunta','Alcance','Contexto','Última corrección']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.itemSelectionChanged.connect(self.select);layout.addWidget(self.table);self.value=QPlainTextEdit();layout.addWidget(self.value);self.confirm=QCheckBox('Confirmo esta corrección dentro del mismo alcance');layout.addWidget(self.confirm);button=QPushButton('Guardar corrección');button.clicked.connect(self.save);layout.addWidget(button);self.status=QLabel();layout.addWidget(self.status);self.refresh()
    def refresh(self):
        self.rows=self.store.rows();self.table.setRowCount(len(self.rows))
        for n,r in enumerate(self.rows):
            for col,key in enumerate(['question','scope','scope_key','updated_at']):self.table.setItem(n,col,QTableWidgetItem(r[key]))
        self.table.resizeColumnsToContents()
    def select(self):
        n=self.table.currentRow()
        if 0<=n<len(self.rows):self.value.setPlainText(self.rows[n]['value']);self.confirm.setChecked(False)
    def save(self):
        import json
        n=self.table.currentRow()
        if not 0<=n<len(self.rows):return
        if not self.confirm.isChecked():self.status.setText('Confirma la corrección antes de guardarla.');return
        r=self.rows[n];context=json.loads(r['conditions']);context.update(job_id=r['scope_key'] if r['scope']=='job' else '',company=r['scope_key'] if r['scope']=='company' else '')
        try:self.store.save(r['question'],self.value.toPlainText(),r['kind'],r['scope'],context,True);self.refresh();self.status.setText('Corrección guardada; las preparaciones y autorizaciones anteriores requieren revalidación.')
        except ValueError as exc:self.status.setText(str(exc))
