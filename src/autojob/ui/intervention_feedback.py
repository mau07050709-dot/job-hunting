"""Respuesta visible de intervención y diagnóstico sin valores personales."""
from threading import Event
from pathlib import Path
import logging,re,traceback
from PySide6.QtCore import QThread,Signal,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton
log=logging.getLogger(__name__)

def diagnostic(exc,code='I9I_INTERVENTION'):
    kind=type(exc).__name__;http=re.search(r'HTTP\s+(\d{3})',str(exc));suffix=' HTTP '+http[1] if http else ''
    frames=[Path(f.filename).name+':'+str(f.lineno) for f in traceback.extract_tb(exc.__traceback__)]
    log.warning('%s exception=%s%s frames=%s',code,kind,suffix,','.join(frames))
    return code+'_'+kind+suffix

class InterventionWorker(QThread):
    done=Signal(object);progress=Signal(str)
    def __init__(self,operation):super().__init__();self.operation=operation;self.cancelled=Event()
    def run(self):
        try:self.done.emit(dict(ok=True,result=self.operation(self.progress.emit,self.cancelled.is_set)))
        except Exception as exc:
            code=diagnostic(exc,'I9I_NAVIGATION')
            self.done.emit(dict(ok=False,code=code,error='No se pudo abrir o recuperar la etapa de Brave. '+code+'. La candidatura sigue pendiente; no se repetirá un envío incierto.'))

class ActionRequired(QDialog):
    def __init__(self,center,row,message,cv_title=None):
        super().__init__(center.window());self.setWindowTitle('Job Hunting · Autorización necesaria');self.setModal(False);self.resize(700,330);self.center=center;self.row=row
        box=QVBoxLayout(self);label=QLabel(row.get('company','')+' · '+row.get('title','')+'\n\n'+message+('\nCV seleccionado: '+cv_title if cv_title else '')+'\n\nModo preparación: las autorizaciones guardadas no se activan al reiniciar. Puedes revisar un permiso nuevo o abrir la página sin rellenar ni adjuntar documentos.');label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);box.addWidget(label);buttons=QHBoxLayout()
        review=QPushButton('REVISAR AUTORIZACIÓN');review.setObjectName('review_intervention_permission');review.clicked.connect(self.review);buttons.addWidget(review)
        readonly=QPushButton('ABRIR SOLO LECTURA');readonly.setObjectName('readonly_intervention');readonly.setShortcut('Alt+L');readonly.clicked.connect(self.readonly);buttons.addWidget(readonly)
        close=QPushButton('CERRAR');close.clicked.connect(self.close);buttons.addWidget(close);box.addLayout(buttons);self.status=QLabel();self.status.setWordWrap(True);box.addWidget(self.status)
    def review(self):
        if self.center.shell.occupied():self.status.setText('Brave o una operación siguen ocupados. Termina o usa RESOLVER DESPUÉS antes de revisar una autorización nueva; esta ventana y la candidatura se conservan.');return
        self.close();self.center.shell.authorize()
        if self.center.shell.delivery_authorization:self.center.resolve(self.row)
    def readonly(self):self.close();self.center.open_direct(self.row,readonly=True)

class OperationFeedback(QDialog):
    def __init__(self,center,row,worker):
        super().__init__(center.window());self.setWindowTitle('Job Hunting · Resolviendo intervención');self.setModal(False);self.resize(700,270);self.worker=worker;box=QVBoxLayout(self)
        heading=QLabel(row.get('company','')+' · '+row.get('title',''));heading.setTextFormat(Qt.TextFormat.PlainText);box.addWidget(heading);self.message=QLabel('Recuperando el contexto de la candidatura…');self.message.setTextFormat(Qt.TextFormat.PlainText);self.message.setWordWrap(True);box.addWidget(self.message)
        self.cancel=QPushButton('CANCELAR OPERACIÓN');self.cancel.clicked.connect(self.stop);box.addWidget(self.cancel)
    def stop(self):self.worker.cancelled.set();self.message.setText('Cancelación solicitada; se conservará la candidatura.');self.cancel.setEnabled(False)
    def closeEvent(self,event):
        if self.worker.isRunning():self.worker.cancelled.set()
        event.accept()

def plan(settings,row,authorization):
    from autojob.forms.submissions import SubmissionStore
    from autojob.forms.queue import PreparationQueue
    from autojob.live import historical
    store=SubmissionStore(settings.data_path);job=next((j for j in store.prep.compatibility.jobs.list() if j['id']==row.get('job_id')),None)
    if not job:return dict(error='La intervención no contiene una referencia válida a una vacante. No se abrirá una página genérica.')
    if historical(store,job['id']):return dict(historical=True,job=job)
    url=job.get('application_url') or job['url'];row.update(url=url,company=job['company'],title=job['title'])
    if job.get('availability')=='CERRADA':return dict(error='La vacante figura como cerrada. No se reconstruirá una postulación; puedes revisar el enlace en los detalles.')
    rule=None;reason=''
    if authorization:
        try:_,rule=store.permission(authorization,job)
        except ValueError as exc:reason='El permiso no cubre esta candidatura: '+str(exc)
    q=next((q for q in PreparationQueue(settings.data_path).list() if q['job_id']==job['id']),{});preview=q.get('payload',{}).get('preview') or {};evaluation=store.prep.compatibility.latest().get(job['id']) or {};cv_id=(evaluation.get('resume_selection') or {}).get('resume_id') or preview.get('cv_id')
    title=None
    if cv_id:
        try:title=store.prep.compatibility.library.get(cv_id)['title'];store.prep.compatibility.library.original_path(cv_id,verify=True)
        except ValueError:return dict(error='El CV seleccionado no está disponible o cambió su archivo. Revisa Mis datos → Currículums antes de autorizarlo.')
    if rule:return dict(job=job,url=url,rule=rule,cv_id=cv_id,cv_title=title)
    text_allowed=PreparationQueue(settings.data_path).site_allowed(url)
    cv_pending=('Resume/CV' in row.get('message','') or row['kind']=='AUTORIZACIÓN CV') or any(f.get('kind')=='file' and f.get('document')=='cv' and f.get('required') for f in preview.get('entries',[]))
    if cv_pending or not text_allowed or reason:
        return dict(job=job,url=url,cv_id=cv_id,cv_title=title,authorization_required=True,message=('Se necesita autorización para adjuntar el CV seleccionado' if cv_pending else 'Se necesita autorización para transmitir los datos personales confirmados a este formulario')+('. '+reason if reason else '. No existe un permiso activo en esta sesión.'))
    return dict(job=job,url=url,cv_id=cv_id,cv_title=title)

def open_prepared(settings,row,authorization,progress,cancelled):
    """Reopen only pre-submission work, validating its current scope before Brave."""
    from autojob.forms.submissions import SubmissionStore,SubmissionEngine,DeliveryGuard
    from autojob.forms.guard import PreparationGuard
    from autojob.forms.queue import PreparationQueue
    from autojob.browser import BraveSession
    from autojob.intervention_context import capture
    from autojob.live import wait_prepared
    from autojob.control import ControlStore
    store=SubmissionStore(settings.data_path);decision=plan(settings,row,authorization)
    if decision.get('historical'):return dict(state='BLOQUEADA',reason='Resultado final existente: solo revisar comprobante.')
    if decision.get('error') or decision.get('authorization_required'):return dict(state='BLOQUEADA',reason=decision.get('error') or decision['message'],authorization_required=bool(decision.get('authorization_required')))
    if cancelled():return dict(state='PENDIENTE',reason='Operación cancelada antes de abrir Brave.')
    queue=PreparationQueue(settings.data_path);capture(ControlStore(settings.data_path),row,queue)
    job=decision['job'];rule=decision.get('rule');progress('Reconstruyendo el formulario actual; se repondrán solo datos y adjuntos autorizados. El portal puede haber perdido la etapa anterior.')
    with BraveSession(settings) as browser:
        guard=DeliveryGuard(browser,rule['origin'],lambda:store.permission(authorization,job),rule) if rule else PreparationGuard(browser)
        if rule:guard.check()
        page=guard.page(decision['url']);page.bring_to_front()
        progress('Completando y verificando campos conocidos antes de enfocar el impedimento pendiente…')
        return wait_prepared(settings,browser,page,guard,job,authorization,stop=cancelled,human_active=True,on_ready=(lambda:SubmissionEngine(settings).run(job['id'],authorization,stop=cancelled,session=(browser,page,guard))) if authorization else None)

def open_readonly(settings,row,progress,cancelled):
    from autojob.browser import BraveSession
    from autojob.forms.guard import PreparationGuard
    from autojob.forms.preparation import inspect
    progress('Abriendo Brave en SOLO LECTURA: sin rellenar campos, adjuntar CV ni pulsar SUBMIT.')
    with BraveSession(settings) as browser:
        if cancelled():return dict(cancelled=True)
        responses=[]
        browser.context.on('response',lambda r:responses.append(r.status) if r.request.is_navigation_request() and r.request.method=='GET' else None)
        guard=PreparationGuard(browser);url=row['url'];page=guard.page(url[:-6] if url.endswith('/apply') else url);job_body=page.locator('body').inner_text()
        if url.endswith('/apply'):guard.navigate(page,url)
        page.bring_to_front();document=inspect(page,max_frames=12);body=page.locator('body').inner_text()
        observation=dict(automatic_fill_enabled=False,cv_upload_enabled=False,cv_selected_files=page.locator('input[type=file]').evaluate_all('(es)=>es.reduce((n,e)=>n+(e.files?.length||0),0)'),contact_fields_populated=page.locator('input[name=name],input[name=email],input[name=phone]').evaluate_all('(es)=>es.filter(e=>!!e.value).length'),url=row['url'],title=document['title'],captcha=any(x['type']=='CAPTCHA' for x in document['obstacles']),latin_america_explicit='Latin America' in job_body,http_status=responses[-1] if responses else None,closed=bool(re.search(r'no longer accepting|no longer available|job not found',body,re.I)),readonly=True)
        progress('La vacante ya no acepta candidaturas; solo revisión, sin transmitir datos.' if observation['closed'] else 'Brave abierto en SOLO LECTURA. Para rellenar datos y adjuntar el CV, revisa la autorización en Job Hunting. Puedes cerrar esta pestaña o cancelar esta ventana.')
        while not cancelled() and not page.is_closed():page.wait_for_timeout(200)
        return observation


def display(row):
    if row['kind']=='INFORMACIÓN FALTANTE' and row.get('message','').strip()=='Revisar campos requeridos: Resume/CV':return 'AUTORIZACIÓN CV','Se necesita autorización para adjuntar el CV seleccionado'
    return row['kind'],row['message']
