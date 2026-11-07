"""Motor independiente de envío. Las barreras de preparación siguen intactas."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit,urldefrag
import json,re
from autojob.storage.database import utc_now
from autojob.forms.preparation import Preparation,inspect
from autojob.forms.runner import fill_field,enrich
from autojob.forms.guard import origin,apply_link,continue_stage
from autojob.browser import BraveSession
from autojob.browser.lock import ProfileLock
from autojob.matching.engine import digest
from autojob.search.jobs import canonical

UNSAFE={'ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA'}

class SubmissionStore:
    def __init__(self,data_path):
        self.data_path=data_path;self.prep=Preparation(data_path);self.db=self.prep.db
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS submission_authorizations(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,revoked INTEGER NOT NULL,mode TEXT NOT NULL,profile_hash TEXT NOT NULL,max_count INTEGER NOT NULL,scope TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS submission_attempts(id TEXT PRIMARY KEY,authorization_id TEXT NOT NULL,job_id TEXT NOT NULL,logical_key TEXT NOT NULL,mode TEXT NOT NULL,state TEXT NOT NULL,started_at TEXT NOT NULL,updated_at TEXT NOT NULL,evidence TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS submission_events(id INTEGER PRIMARY KEY,attempt_id TEXT,job_id TEXT NOT NULL,state TEXT NOT NULL,at TEXT NOT NULL,code TEXT NOT NULL)')
    def rows(self):
        with closing(self.db.connect()) as db:return [dict(r,evidence=json.loads(r['evidence'])) for r in db.execute('SELECT * FROM submission_attempts ORDER BY started_at DESC')]
    def authorize(self,jobs,max_count,upload=False,explicit=False,mode='real',controlled=False,special_consents=None):
        if not explicit or not upload:raise ValueError('Se requieren autorización explícita de envío y permiso independiente de adjuntar CV.')
        if mode not in {'real','local'} or mode=='local' and not controlled:raise ValueError('Modo no autorizado.')
        if type(max_count) is not int or not 1<=max_count<=100:raise ValueError('Objetivo permitido: 1 a 100 por autorización.')
        eligible={r['job']['id']:r for r in self.prep.compatibility.rows() if eligible_row(r)};scope={}
        for id in jobs:
            if id not in eligible:raise ValueError('La vacante requiere elegibilidad, vigencia y CV revisado.')
            r=eligible[id];j=r['job'];url=j.get('application_url') or j['url'];p=urlsplit(url)
            if mode=='real' and (p.scheme!='https' or p.hostname in {'localhost','127.0.0.1'} or p.hostname.endswith('.invalid')):raise ValueError('El envío real requiere un portal HTTPS externo.')
            if mode=='local' and (p.scheme!='http' or p.hostname!='127.0.0.1'):raise ValueError('La prueba solo admite localhost.')
            cv=self.prep.compatibility.library.get(r['evaluation']['resume_selection']['resume_id']);path=self.prep.compatibility.library.original_path(cv['id'],verify=True)
            scope[id]=dict(origin=origin(url),url=url,job_hash=digest(j),cv_id=cv['id'],cv_hash=sha256(path.read_bytes()).hexdigest(),upload=True)
        from autojob.forms.greenhouse import TARGET,PROCESSORS
        for rule in scope.values():
            if rule['url']==TARGET:rule['processor_origins']=PROCESSORS
            from autojob.forms import fiveca
            from autojob.forms.doola import accepts as doola_form
            if doola_form(rule['url']):rule['captcha_provider']='hCaptcha'
            if fiveca.accepts(rule['url']):
                if special_consents!=fiveca.consents():raise ValueError('Revisa y autoriza los dos avisos específicos de 5CA. Las comunicaciones generales se rechazan.')
                rule['specific_consents']=dict(special_consents)
        if not scope:raise ValueError('No hay vacantes elegibles para autorizar.')
        if mode=='real' and not any(r['mode']=='real' and r['state']=='ENVIADA CONFIRMADA' for r in self.rows()) and (max_count!=1 or len(scope)!=1):raise ValueError('La primera validación real requiere una sola vacante expresamente elegida.')
        id=uuid4().hex
        with closing(self.db.connect()) as db,db:db.execute('INSERT INTO submission_authorizations VALUES (?,?,?,0,?,?,?,?)',(id,utc_now(),(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(),mode,self.prep.inputs_hash(),max_count,json.dumps(scope)))
        return id
    def accept_confirmed_answer(self,id,job_id,before_hash):
        # La ventana pide confirmar y autorizar el uso del nuevo dato. No renueva cambios ajenos.
        with closing(self.db.connect()) as db,db:
            r=db.execute('SELECT * FROM submission_authorizations WHERE id=?',(id,)).fetchone()
            if r and not r['revoked'] and r['profile_hash']==before_hash and (job_id in json.loads(r['scope']) or '_batch' in json.loads(r['scope'])):db.execute('UPDATE submission_authorizations SET profile_hash=? WHERE id=?',(self.prep.inputs_hash(),id))
    def revoke(self,id):
        with closing(self.db.connect()) as db,db:db.execute('UPDATE submission_authorizations SET revoked=1 WHERE id=?',(id,))
    def permission(self,id,job):
        from autojob.control import ControlStore
        if ControlStore(self.data_path).is_excluded(job):raise ValueError('Candidatura descartada por el usuario.')
        with closing(self.db.connect()) as db:r=db.execute('SELECT * FROM submission_authorizations WHERE id=?',(id,)).fetchone()
        if not r or r['revoked'] or r['expires_at']<utc_now():raise ValueError('Autorización ausente, revocada o caducada.')
        scope=json.loads(r['scope']);rule=scope.get(job['id']);fingerprint=self.prep.inputs_hash();changed=r['profile_hash']!=fingerprint
        if changed:
            if '_execution' not in scope or any(a['authorization_id']==id and a['job_id']==job['id'] and a['state']=='ENVIANDO' for a in self.rows()):raise ValueError('Los datos cambiaron; revalidar antes de continuar.')
            # INICIAR cubre los datos confirmados que el usuario corrija durante
            # la ejecución. Reevaluar requisitos y CV antes de reutilizarlos.
            self.prep.compatibility.one(job,force=True)
        if '_execution' in scope:
            from autojob.forms.execution import enroll
            rule=enroll(self,id,dict(r),job)
            if changed:
                with closing(self.db.connect()) as db,db:db.execute('UPDATE submission_authorizations SET profile_hash=? WHERE id=? AND revoked=0',(fingerprint,id))
            with closing(self.db.connect()) as db:r=db.execute('SELECT * FROM submission_authorizations WHERE id=?',(id,)).fetchone()
        own_inflight=bool(rule and any(a['authorization_id']==id and a['job_id']==job['id'] and a['state']=='ENVIANDO' for a in self.rows()))
        if '_batch' in scope and not own_inflight:
            if sum(a['authorization_id']==id and a['state'] in UNSAFE for a in self.rows())>=r['max_count']:raise ValueError('Límite de lote alcanzado antes de abrir el formulario.')
        if '_batch' in scope and not own_inflight:
            # El permiso del intento propio ya reclamado conserva su vínculo inmutable.
            # Los demás casos vuelven a comprobar alcance y duplicados; claim sigue transaccional.
            from autojob.forms.batches import enroll
            rule=enroll(self,id,dict(r),job)
        if not rule or rule['job_hash']!=digest(job):raise ValueError('La vacante no coincide con el alcance revisado.')
        cv=self.prep.compatibility.library.original_path(rule['cv_id'],verify=True)
        if sha256(cv.read_bytes()).hexdigest()!=rule['cv_hash']:raise ValueError('El CV autorizado cambió.')
        return dict(r),rule
    def duplicate(self,job):
        key=digest(canonical(job.get('application_url') or job['url']))
        with closing(self.db.connect()) as db:
            old=[r['url'] for r in db.execute("SELECT url FROM applications WHERE status IN ('ENVIADA','NO VERIFICADA','ENVÍO NO VERIFICADO','ENVIANDO')")]
        if any(canonical(u) in {canonical(job['url']),canonical(job.get('application_url') or job['url'])} for u in old):return True
        return any(r['state'] in UNSAFE and (r['job_id']==job['id'] or r['logical_key']==key) for r in self.rows())
    def claim(self,authorization,job):
        auth,_=self.permission(authorization,job);key=digest(canonical(job.get('application_url') or job['url']));id=uuid4().hex
        if json.loads(auth['scope']).get('_prepare_only'):raise ValueError('Esta recuperación solo prepara el formulario. Pulsa INICIAR para autorizar su envío.')
        with closing(self.db.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            from autojob.dispositions import decision
            if decision(db,job):raise ValueError('Candidatura descartada por el usuario antes del envío.')
            if self.duplicate(job):raise ValueError('Postulación anterior confirmada o incierta.')
            if db.execute("SELECT 1 FROM submission_attempts WHERE (job_id=? OR logical_key=?) AND state IN ('ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA')",(job['id'],key)).fetchone():raise ValueError('Ya existe un envío confirmado o incierto; no se repite.')
            count=db.execute("SELECT COUNT(*) FROM submission_attempts WHERE authorization_id=? AND state IN ('ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA')",(authorization,)).fetchone()[0]
            if count>=auth['max_count']:raise ValueError('Objetivo o límite de autorización alcanzado.')
            db.execute('INSERT INTO submission_attempts VALUES (?,?,?,?,?,?,?,?,?)',(id,authorization,job['id'],key,auth['mode'],'ENVIANDO',utc_now(),utc_now(),'{}'))
        self.event(id,job['id'],'ENVIANDO','INTENTO_PERSISTIDO_ANTES_DEL_CLIC');return id
    def event(self,id,job,state,code):
        with closing(self.db.connect()) as db,db:db.execute('INSERT INTO submission_events(attempt_id,job_id,state,at,code) VALUES (?,?,?,?,?)',(id,job,state,utc_now(),code))
    def finish(self,id,state,evidence):
        if state not in {'ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA','NO TRANSMITIDA'}:raise ValueError('Estado posterior al envío inválido.')
        with closing(self.db.connect()) as db,db:db.execute('UPDATE submission_attempts SET state=?,updated_at=?,evidence=? WHERE id=?',(state,utc_now(),json.dumps(evidence),id))
    def recover(self):
        lock=ProfileLock(self.data_path/'submission.lock')
        try:lock.acquire()
        except Exception:return 0
        try:
            from autojob.live import active
            count=0
            for attempt in self.rows():
                if attempt['state']!='ENVIANDO' or active(attempt['job_id']):continue
                own_lock=ProfileLock(self.data_path/'form-sessions'/sha256(str(attempt['job_id']).encode()).hexdigest()/'submission.lock')
                try:own_lock.acquire()
                except Exception:continue
                try:
                    with closing(self.db.connect()) as db,db:count+=db.execute("UPDATE submission_attempts SET state='ENVÍO NO VERIFICADO',updated_at=? WHERE id=? AND state='ENVIANDO'",(utc_now(),attempt['id'])).rowcount
                finally:own_lock.release()
            return count
        finally:
            if lock:lock.release()

def eligible_row(row):
    e=row.get('evaluation') or {};s=e.get('resume_selection') or {}
    return not row.get('stale') and e.get('eligibility')=='COMPATIBLE' and e.get('geography')=='CONFIRMADO' and e.get('availability')=='ABIERTA' and s.get('confirmed') and s.get('resume_id')

GUARD_SCRIPT=r'''(() => {
 window.__autojobDeliveryArmed=false;
 const stop=e=>{e.preventDefault();e.stopImmediatePropagation();};
 document.addEventListener('submit',e=>{if(!window.__autojobDeliveryArmed)stop(e)},true);
 document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target?.tagName!=='TEXTAREA')stop(e)},true);
 document.addEventListener('click',e=>{let b=e.target.closest?.('button,input[type=submit]');if(b&&(b.type==='submit'||/submit|enviar|postular|apply/i.test(b.innerText||b.value||''))&&!window.__autojobDeliveryArmed)stop(e)},true);
})()'''

class DeliveryGuard:
    portal=None
    def __init__(self,browser,site,check,rule=None):
        self.browser=browser;self.context=browser.context;self.site=site;self.check=check;self.endpoint=None;self.final=False;self.used=False;self.responses=[];self.acceptance_signals=[];self.confirmation_url=None;self.blocked=0;self.identity_data_path=None;self.expected=None;self.nav_budget=0;self.expected_fields=None;self.wire_status=None;self.rule=rule or {};self.captcha_provider=self.rule.get('captcha_provider')
        from autojob.forms.greenhouse import CloudbedsProtocol
        self.portal=CloudbedsProtocol(rule,check) if rule and rule.get('processor_origins') else None
        self.context.add_init_script(GUARD_SCRIPT);self.context.route('**/*',self.route);self.context.route_web_socket('**/*',lambda ws:ws.close())
    def route(self,route):
        r=route.request
        try:
            allowed=origin(r.url)==self.site and r.method in {'GET','HEAD','OPTIONS'}
            from urllib.parse import urlsplit
            host=(urlsplit(r.url).hostname or '').lower()
            from autojob.forms.navigation import public_asset
            if public_asset(self.site,r.url,r.method,r.resource_type):allowed=True
            if self.captcha_provider=='hCaptcha' and origin(r.url)==self.site and urlsplit(r.url).path.startswith('/cdn-cgi/challenge-platform/') and r.method=='POST' and r.resource_type in {'xhr','fetch'} and r.headers.get('content-type','').split(';')[0] in {'text/plain','application/json'} and len(r.post_data_buffer or b'')<=100000:self.check();allowed=True
            if self.captcha_provider=='hCaptcha' and (host=='hcaptcha.com' or host.endswith('.hcaptcha.com')) and r.method in {'GET','HEAD','OPTIONS'}:allowed=True
            if self.site=='https://jobs.5ca.com' and r.method in {'GET','HEAD','OPTIONS'} and r.url.split('?')[0] in {'https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.12/js/intlTelInput-jquery.min.js','https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.12/js/utils.js'}:allowed=True
            if self.portal:
                from urllib.parse import urlsplit
                host=urlsplit(r.url).hostname or ''
                if r.method in {'GET','HEAD','OPTIONS'} and (host in {'boards.greenhouse.io','job-boards.cdn.greenhouse.io','www.google.com','www.gstatic.com','www.recaptcha.net'}):allowed=True
                if r.method=='OPTIONS' and self.portal.upload_phase and r.url.rstrip('/')=='https://grnhse-prod-jben-us-east-1.s3.amazonaws.com':allowed=True
                if r.method=='POST':
                    allowed=self.portal.write(r,self.final)
                    if allowed and r.url==self.endpoint:self.used=True
            if not self.portal and self.final and r.method=='POST' and urldefrag(r.url)[0]==self.endpoint and not self.used:
                self.check()
                if self.expected_fields is None:raise ValueError('Falta la validación del cuerpo final.')
                from autojob.forms.wire import verify
                valid,self.wire_status=verify(r,self.expected_fields,self.rule['cv_hash'],self.captcha_provider=='hCaptcha')
                if not valid:raise ValueError('El POST no coincide con la preparación.')
                self.used=True;allowed=True
            if allowed:
                if self.portal and self.portal.replacement_body and self.portal.upload_phase and r.method=='POST' and r.url.rstrip('/')=='https://grnhse-prod-jben-us-east-1.s3.amazonaws.com':route.continue_(post_data=self.portal.replacement_body)
                else:route.continue_()
            else:self.blocked+=1;route.abort()
        except Exception:self.blocked+=1;route.abort()
    def page(self,url):
        from autojob.forms.navigation import category_url,open_page,save
        if category_url(url):raise ValueError('ENLACE INVÁLIDO: categoría sin candidatura identificada.')
        page=self.browser.new_page();cdp=self.context.new_cdp_session(page);cdp.send('Network.enable');cdp.send('Network.setBypassServiceWorker',{'bypass':True})
        if url.startswith('https://apply.workable.com/pavago/j/361F1E680B'):
            self.navigation_result=open_page(self,page,url)
            if self.identity_data_path:save(self.identity_data_path,url,self.navigation_result)
        else:self.navigate(page,url)
        page.on('response',lambda r:self.responses.append((r.url,r.status,r.request.method)));page.on('response',self.observe);page.on('response',lambda r:self.portal.response(r) if self.portal else None)
        return page
    def observe(self,response):
        from autojob.forms.confirmations import observe_response
        signal=observe_response(response,self.endpoint)
        if signal:self.acceptance_signals.append(signal)
    def navigate(self,page,url):
        if origin(url)!=self.site:raise ValueError('El formulario redirige a otro portal; requiere autorización.')
        response=page.goto(url,wait_until='domcontentloaded',timeout=20000)
        if response and response.status>=400:raise ValueError('Portal no disponible.')
    def freeze(self):pass

class SubmissionEngine:
    def __init__(self,settings):
        self.settings=settings;self.store=SubmissionStore(settings.data_path);self.prep=self.store.prep;self.last_operation="INICIO";self.last_guard=None
    def pending(self,job,document,preview,reason,review_optional=(),block_type='DATO OBLIGATORIO PENDIENTE'):
        from autojob.forms.queue import PreparationQueue
        from autojob.control import ControlStore
        q=PreparationQueue(self.settings.data_path);q.add([job['id']]);payload=dict(review_optional=list(review_optional),company=job['company'],title=job['title'],preview=preview,stages=[dict(document=document,preview=preview)],pending=[dict(field=e['label'],required=e.get('required',False)) for e in preview.get('entries',[]) if e.get('status') not in {'CONFIRMADA','DERIVADA','DOCUMENTO LOCAL'}],blocks=[dict(type=block_type,evidence=reason)])
        holding=getattr(self,'retain',False) and self.live_session and not any(r['job_id']==job['id'] for r in self.store.rows())
        q.update(job['id'],'RELLENANDO' if holding else 'PENDIENTE','Envío pendiente: '+reason,payload)
        if holding:
            from autojob.live import wait_prepared
            browser,page,guard=self.live_session
            auth,rule=self.store.permission(self.live_authorization,job)
            ready=None if rule.get('preparation_only') else lambda:SubmissionEngine(self.settings).run(job['id'],self.live_authorization,stop=self.live_stop,session=(browser,page,guard))
            return wait_prepared(self.settings,browser,page,guard,job,self.live_authorization,self.live_stop,on_ready=ready,prepared=getattr(self,'prepared',None))
        ControlStore(self.settings.data_path).sync(q)
        return dict(state='PENDIENTE',reason=reason)
    def run(self,id,authorization,pause=lambda:False,stop=lambda:False,retain=False,session=None,isolated=False,prepared=None):
        self.retain=retain;self.live_session=session;self.live_stop=stop;self.live_authorization=authorization;self.prepared=prepared
        job=next((j for j in self.prep.compatibility.jobs.list() if j['id']==id),None)
        if not job:raise ValueError('Vacante inexistente.')
        if self.store.duplicate(job):return dict(state='BLOQUEADA',reason='Envío anterior confirmado o incierto.')
        auth,rule=self.store.permission(authorization,job)
        if auth['mode']=='real':return dict(state='PENDIENTE',reason='Public edition: review and submit the application manually in Brave.')
        row=next((r for r in self.prep.compatibility.rows() if r['job']['id']==id),{})
        if not eligible_row(row):return dict(state='PENDIENTE',reason='Elegibilidad o vigencia sin confirmar.')
        isolated_lock=self.settings.data_path/'form-sessions'/sha256(str(id).encode()).hexdigest()/'submission.lock'
        lock=ProfileLock(isolated_lock if isolated else self.settings.data_path/'submission.lock') if session is None else None
        if lock:lock.acquire()
        attempt=None
        try:
            cancelled=lambda:pause() or stop()
            def check():
                if cancelled():raise ValueError('Ejecución pausada o detenida.')
                self.store.permission(authorization,job)
            from contextlib import nullcontext
            with ((BraveSession(self.settings,isolated_key=id) if isolated else BraveSession(self.settings)) if session is None else nullcontext(session[0])) as browser:
                self.last_operation='ABRIR PORTAL';guard=session[2] if session else DeliveryGuard(browser,rule['origin'],check,rule);self.last_guard=guard;guard.identity_data_path=self.settings.data_path;page=session[1] if session else guard.page(rule['url']);seen=set();self.live_session=(browser,page,guard)
                if guard.portal:
                    try:page.wait_for_load_state('networkidle',timeout=15000)
                    except Exception:pass
                for stage in range(8):
                    self.last_operation='INSPECCIONAR FORMULARIO';check();doc=inspect(page,max_frames=12);preview=self.prep.prepare(doc,job,cv_approved=bool(rule.get('execution_authorized')))
                    if stage==0 and any(o['type'] in {'SIN FORMULARIO','FORMULARIO NO IDENTIFICADO COMO POSTULACIÓN'} for o in doc['obstacles']):
                        link=apply_link(page)
                        if link and origin(link)==rule['origin']:guard.navigate(page,link);doc=inspect(page,max_frames=12);preview=self.prep.prepare(doc,job,cv_approved=bool(rule.get('execution_authorized')))
                    if guard.portal and any(o['type']=='CAPTCHA' for o in doc['obstacles']):
                        from autojob.auth.verifications import captcha_state
                        state=captcha_state(page)
                        if state['completed'] or not state['interactive']:doc['obstacles']=[o for o in doc['obstacles'] if o['type']!='CAPTCHA']
                    from autojob.forms.doola import accepts as doola_form
                    if doola_form(page.url):doc['obstacles']=[o for o in doc['obstacles'] if o['type']!='CAPTCHA']
                    if doc['obstacles'] and not all(b['type'] in {'CAPTCHA','VIDEO','VOZ'} for b in doc['obstacles']):
                        if any(b['type']=='CAPTCHA' for b in doc['obstacles']):
                            from autojob.auth.verifications import record_obstacle
                            record_obstacle(self.settings.data_path,id,'CAPTCHA PENDIENTE',page.url,job['title'])
                        return self.pending(job,doc,preview,'Obstáculo del portal: '+', '.join(b['type'] for b in doc['obstacles']))
                    # No transmitir datos a un formulario cuyo protocolo final aún no se admite.
                    if not guard.portal:
                        initial_finals=[f for f in doc['fields'] if f.get('action')=='ENVÍO FINAL' and f.get('frame_index',0)==0]
                        if len(initial_finals)==1:
                            method=page.locator(initial_finals[0]['selector']).evaluate('(e)=>(e.form||e.closest("form"))?.method?.toUpperCase()')
                            if method!='POST':return self.pending(job,doc,preview,'El formulario utiliza un protocolo JavaScript o API que requiere un adaptador verificado; no se han introducido datos ni adjuntos.')
                    if any(b['type'] in {'CV PROVISIONAL','CV INCOMPATIBLE','EVALUACIÓN OBSOLETA','VACANTE POR VERIFICAR','DOCUMENTO NO DISPONIBLE'} for b in preview['blocks']):return self.pending(job,doc,preview,'Revisar CV, vacante o evaluación.')
                    if retain:
                        # La misma preparación acotada sirve a INICIAR y RESOLVER AHORA.
                        # Agotar campos seguros y conservar la página antes de notificar.
                        from autojob.live import wait_prepared
                        ready=None if rule.get('preparation_only') else lambda:SubmissionEngine(self.settings).run(id,authorization,pause,stop,session=(browser,page,guard))
                        return wait_prepared(self.settings,browser,page,guard,job,authorization,stop=cancelled,on_ready=ready,prepared=prepared)
                    outcomes=[];cv_loaded=False
                    for entry in sorted(preview['entries'],key=lambda e:e['kind']=='file' and e.get('document')!='cv'):
                        self.last_operation='CAMPO '+(entry.get('public_field_name') or entry.get('kind','desconocido'));check();entry=enrich(self.prep,entry)
                        if entry['kind']=='file':
                            from autojob.forms.answers9b import restricted
                            if restricted(entry['label']):return self.pending(job,doc,preview,'Documento sensible: no se adjunta automáticamente.')
                            if guard.portal and entry.get('document')=='letter' and not entry.get('required'):continue
                            if entry.get('document')!='cv':
                                if entry.get('document')=='letter':
                                    from autojob.forms.submission_letters import SubmissionLetters
                                    letters=SubmissionLetters(self.settings.data_path);artifact=letters.artifact(job,rule['cv_id'])
                                    if artifact:
                                        target=page.frames[entry.get('frame_index',0)].locator(entry['selector'])
                                        if origin(page.frames[entry.get('frame_index',0)].url)!=rule['origin'] or target.count()!=1:raise ValueError('Carta fuera del portal autorizado.')
                                        target.set_input_files(str(artifact))
                                        if not target.evaluate('(e)=>e.files.length===1'):return self.pending(job,doc,preview,'El portal no reconoce la carta.')
                                        continue
                                    from autojob.control import ControlStore
                                    ControlStore(self.settings.data_path).add_intervention(id,job['company'],job['title'],'CARTA DE PRESENTACIÓN','Revisa y autoriza el borrador antes de adjuntarlo.',page.url,profile_hash=self.prep.inputs_hash())
                                    return self.pending(job,doc,preview,'Carta de presentación pendiente de revisión.')
                                if entry.get('required'):return self.pending(job,doc,preview,'Adjunto adicional: revisar el documento.')
                                continue
                            target=page.frames[entry.get('frame_index',0)].locator(entry['selector'])
                            if origin(page.frames[entry.get('frame_index',0)].url)!=rule['origin'] or target.count()!=1:raise ValueError('Adjunto fuera del portal o ambiguo.')
                            cv=self.prep.compatibility.library.original_path(rule['cv_id'],verify=True)
                            if guard.portal:cv_loaded=guard.portal.attach_cv(page,target,cv,check)
                            else:
                                target.set_input_files(str(cv));cv_loaded=target.evaluate('(e)=>e.files.length===1')
                            outcomes.append((entry,dict(status='VERIFICADO' if cv_loaded else 'PENDIENTE')))
                        elif entry.get('semantic')=='phone_5ca':
                            from autojob.forms.fiveca import fill_phone
                            outcomes.append((entry,fill_phone(page,entry)))
                        elif entry.get('requires_specific_consent'):
                            from autojob.forms.fiveca import fill_consent
                            outcomes.append((entry,fill_consent(page,entry,rule)))
                        elif entry.get('public_field_name') in {'question_7859687101[]','question_7859688101[]'}:
                            from autojob.forms.fiveca import fill_multiple
                            outcomes.append((entry,fill_multiple(page,entry)))
                        elif guard.portal and entry['kind']=='combobox':outcomes.append((entry,guard.portal.fill_combobox(page,entry)))
                        else:outcomes.append((entry,fill_field(page,entry,guard)))
                    # Reinspección acotada: una elección puede revelar preguntas obligatorias nuevas.
                    def field_key(e):return (e.get('frame_index',0),e['selector'],e['kind'],e['label'],e.get('required'),tuple((o['label'],o['value']) for o in e.get('options',[])))
                    known={field_key(e) for e,_ in outcomes}
                    for dynamic_round in range(3):
                        fresh_doc=inspect(page,max_frames=12)
                        if doola_form(page.url):fresh_doc['obstacles']=[o for o in fresh_doc['obstacles'] if o['type']!='CAPTCHA']
                        fresh_preview=self.prep.prepare(fresh_doc,job,cv_approved=bool(rule.get('execution_authorized')))
                        if fresh_doc['obstacles'] and not all(b['type'] in {'CAPTCHA','VIDEO','VOZ'} for b in fresh_doc['obstacles']):return self.pending(job,fresh_doc,fresh_preview,'El formulario cambió o presentó un obstáculo antes del envío.')
                        extras=[enrich(self.prep,e) for e in fresh_preview['entries'] if field_key(e) not in known]
                        doc=fresh_doc;preview=fresh_preview
                        if not extras:break
                        for entry in extras:
                            check()
                            if entry['kind']=='file':return self.pending(job,doc,preview,'Apareció un adjunto nuevo: requiere revisión específica.')
                            if entry.get('requires_specific_consent'):
                                from autojob.forms.fiveca import fill_consent
                                outcome=fill_consent(page,entry,rule)
                            elif guard.portal and entry['kind']=='combobox':outcome=guard.portal.fill_combobox(page,entry)
                            else:outcome=fill_field(page,entry,guard)
                            outcomes.append((entry,outcome));known.add(field_key(entry))
                    else:return self.pending(job,doc,preview,'El formulario continúa cambiando; requiere una nueva revisión.')
                    outcomes=list({(e.get('frame_index',0),e['selector']):(e,o) for e,o in outcomes}.values())
                    missing=[e for e,o in outcomes if e.get('required') and o['status'] not in {'VERIFICADO','NO SELECCIONADO'}]
                    for e,o in outcomes:
                        if e.get('required') and e['kind']=='radio':
                            name=e.get('name');radios=[f for f,_ in outcomes if f['kind']=='radio' and f.get('name')==name]
                            if not any(page.frames[f.get('frame_index',0)].locator(f['selector']).evaluate('(e)=>e.checked||e.getAttribute("aria-checked")==="true"') for f in radios):missing.append(e)
                    if missing:return self.pending(job,doc,preview,'Falta información confirmada: '+', '.join(e['label'] for e in missing))
                    if doc['obstacles'] and not guard.captcha_provider:
                        if any(b['type']=='CAPTCHA' for b in doc['obstacles']):
                            from autojob.auth.verifications import record_obstacle
                            record_obstacle(self.settings.data_path,id,'CAPTCHA PENDIENTE',page.url,job['title'])
                        return self.pending(job,doc,preview,'Obstáculos restantes: '+', '.join(b['type'] for b in doc['obstacles']),block_type=doc['obstacles'][0]['type'])
                    optional=[]
                    for e,outcome in outcomes:
                        if e.get('required') or outcome['status'] in {'VERIFICADO','NO SELECCIONADO'}:continue
                        target=page.frames[e.get('frame_index',0)].locator(e['selector'])
                        populated=target.count()!=1 or target.evaluate('(e)=>e.type==="checkbox"||e.type==="radio"?e.checked:e.getAttribute("role")==="checkbox"||e.getAttribute("role")==="radio"?e.getAttribute("aria-checked")==="true":!!String(e.value||e.innerText||" ").trim()')
                        if populated:optional.append(e['label'])
                    if optional:return self.pending(job,doc,preview,'Hay valores opcionales no confirmados o consentimientos sin autorización.',optional)

                    finals=[f for f in doc['fields'] if f.get('action')=='ENVÍO FINAL']
                    if guard.portal:
                        native_button=guard.portal.final_button(page)
                        if native_button is not None:finals=[dict(selector='button[type=submit]',frame_index=0)]
                    if not finals:
                        signature=digest([(f['selector'],f['label']) for f in doc['fields']])
                        if signature in seen:return self.pending(job,doc,preview,'La etapa no cambió; no se repite.')
                        seen.add(signature);advanced,_=continue_stage(page,guard)
                        if advanced:continue
                        return self.pending(job,doc,preview,'No se identifica un paso seguro.')
                    if len(finals)!=1 or not cv_loaded:return self.pending(job,doc,preview,'Se requiere un botón final inequívoco y un CV adjunto verificable en esta etapa.')
                    self.last_operation='REVISIÓN FINAL';f=finals[0]
                    if f.get('frame_index',0)!=0:return self.pending(job,doc,preview,'Envío en iframe: necesita un adaptador revisado.')
                    button=native_button if guard.portal else page.locator(f['selector']);form=button.evaluate('(e)=>{let f=e.form||e.closest("form");return f?{action:e.hasAttribute("formaction")?e.formAction:f.action,method:(e.hasAttribute("formmethod")?e.formMethod:f.method).toUpperCase(),valid:f.checkValidity(),hidden:Array.from(f.querySelectorAll("input[type=hidden]")).map(e=>e.name)}:null}')
                    if guard.portal and guard.portal.native_action(page) and form:
                        from autojob.forms.greenhouse import SUBMIT
                        form.update(action=SUBMIT,method='POST');button=native_button
                    if not form or form['method']!='POST' or not form['valid'] or (origin(form['action'])!=rule['origin'] and not guard.portal):return self.pending(job,doc,preview,'El portal requiere un adaptador de envío específico o tiene campos inválidos.')
                    if any(re.search(r'consent|agree|signature|background|identity|national.?id|government|ssn|cedula|subscribe|newsletter|marketing|create.?account',name,re.I) for name in form['hidden']):return self.pending(job,doc,preview,'Campos ocultos sensibles o consentimientos: necesita un adaptador y revisión específicos.')
                    if re.search(r'payment|contract|offer.accept|background|identity',form['action'],re.I):return self.pending(job,doc,preview,'Acción sensible fuera de la autorización ordinaria.')
                    from autojob.forms.validation import audit
                    verified_entries=[]
                    for entry in preview['entries']:
                        entry=enrich(self.prep,entry)
                        if entry.get('requires_specific_consent'):
                            from autojob.forms.fiveca import key
                            entry=dict(entry,authorized_answer=rule.get('specific_consents',{}).get(key(entry['label'])))
                        verified_entries.append(entry)
                    preflight=audit(page,verified_entries,self.prep.compatibility.library.original_path(rule['cv_id'],verify=True),bool(guard.portal and guard.portal.upload_complete))
                    if not preflight['valid']:
                        preview['blocks']+= [dict(type='VALIDACIÓN ANTES DE ENVÍO',evidence=e.get('field',e['code'])+' · '+e['code']) for e in preflight['errors']]
                        return self.pending(job,doc,preview,'Validación del valor real: '+', '.join(e['code'] for e in preflight['errors']))
                    check();fresh=next((r for r in self.prep.compatibility.rows() if r['job']['id']==id),{})
                    if not eligible_row(fresh):return self.pending(job,doc,preview,'La evaluación cambió antes del envío.')
                    if re.search(r'application (?:has been |was )?(?:received|submitted)|thank you for applying|solicitud recibida',page.locator('body').inner_text(),re.I):return self.pending(job,doc,preview,'El portal ya muestra un posible comprobante; revisa antes de crear un duplicado.')
                    if not guard.portal:
                        from autojob.forms.wire import capture
                        guard.expected_fields=capture(button)
                    self.last_operation='ENVÍO FINAL';attempt=self.store.claim(authorization,job);guard.endpoint=urldefrag(form['action'])[0];guard.final=True;page.evaluate('window.__autojobDeliveryArmed=true')
                    try:
                        from autojob.forms.confirmations import collect
                        from urllib.parse import urljoin
                        try:
                            paths=page.evaluate("() => Object.values(window.__remixContext?.state?.loaderData||{}).filter(v=>v?.confirmationPath).map(v=>v.confirmationPath)")
                            if len(paths)==1:
                                candidate=urljoin(page.url,paths[0])
                                if origin(candidate)==rule['origin']:guard.confirmation_url=candidate
                        except Exception:pass
                        button.click(timeout=10000)
                        if guard.captcha_provider and not guard.used:
                            from autojob.auth.verifications import CaptchaCoordinator,captcha_state
                            try:
                                state=captcha_state(page)
                                if state['detected'] and not state['completed']:
                                    self.last_operation='INTERVENCIÓN HUMANA CAPTCHA'
                                    completed=CaptchaCoordinator(self.settings.data_path).wait(page,guard,id,job['title'],stop,pause,seconds=180)
                                    if completed and not guard.used:
                                        check();again=audit(page,verified_entries,self.prep.compatibility.library.original_path(rule['cv_id'],verify=True))
                                        if again['valid']:guard.expected_fields=capture(button);button.click(timeout=10000)
                            except Exception:pass
                        import time
                        deadline=time.monotonic()+25;observed=None
                        while time.monotonic()<deadline:
                            page.wait_for_timeout(250)
                            try:observed=collect(page,guard,verified_entries)
                            except Exception:continue
                            if observed['state'] in {'ENVIADA CONFIRMADA','RECHAZADA'} or not guard.used and guard.wire_status:break
                        if not observed:raise ValueError('No se pudo observar la recepción.')
                        evidence=dict(observed,preflight=preflight,mode=auth['mode'],cv_id=rule['cv_id'],cv_sha256=rule['cv_hash'],cv_upload_confirmed=bool(guard.portal.upload_complete) if guard.portal else cv_loaded,final_request_released=guard.used)
                        try:
                            folder=self.settings.data_path/'submission-evidence'/attempt;folder.mkdir(parents=True,exist_ok=True);snapshot_path=folder/'despues.png';page.screenshot(path=str(snapshot_path));evidence['screenshot']=str(snapshot_path.relative_to(self.settings.data_path));evidence['screenshot_sha256']=sha256(snapshot_path.read_bytes()).hexdigest()
                        except Exception:evidence['screenshot_unavailable']=True
                        if not guard.used:
                            evidence.update(state='NO TRANSMITIDA',transmission='NO OBSERVADA',code='SOLICITUD_FINAL_NO_LIBERADA',wire_status=guard.wire_status)
                            self.store.finish(attempt,'NO TRANSMITIDA',evidence)
                            self.pending(job,doc,preview,'La solicitud final no salió del navegador. '+(guard.wire_status or 'Intervención o validación del portal pendiente.'),block_type='CAPTCHA PENDIENTE' if guard.captcha_provider else 'VALIDACIÓN ANTES DE ENVÍO')
                            return dict(state='NO TRANSMITIDA',evidence=evidence)
                        evidence['wire_status']=guard.wire_status
                        if observed['state']!='ENVIADA CONFIRMADA':
                            evidence['code']='RECHAZO_EXPLÍCITO_NO_REINTENTAR' if observed['state']=='RECHAZADA' else 'RESULTADO_INCIERTO_NO_REINTENTAR'
                            self.store.finish(attempt,observed['state'],evidence);return dict(state=observed['state'],evidence=evidence)
                        if origin(page.url)!=rule['origin']:raise ValueError('Comprobante fuera del portal autorizado.')
                        evidence.update(evidence_id=digest(dict(attempt=attempt,confirmation=observed)),confirmed_at=utc_now())
                        self.store.finish(attempt,'ENVIADA CONFIRMADA',evidence)
                        from autojob.control import ControlStore
                        controls=ControlStore(self.settings.data_path)
                        for intervention in controls.interventions():
                            if intervention['job_id']==id and intervention['state'] in {'PENDIENTE','POSPUESTA'}:controls.intervention_state(intervention['id'],'RESUELTA')
                        if auth['mode']=='real':
                            with closing(self.store.db.connect()) as db,db:db.execute("INSERT INTO applications(company,title,url,discovered_at,status,applied_at,confirmation) VALUES (?,?,?,?,'ENVIADA',?,?) ON CONFLICT(url) DO UPDATE SET status='ENVIADA',applied_at=excluded.applied_at,confirmation=excluded.confirmation",(job['company'],job['title'],job['url'],job['discovered_at'],utc_now(),json.dumps(evidence)))
                        return dict(state='ENVIADA CONFIRMADA',mode=auth['mode'],evidence=evidence)
                    except Exception:
                        state='ENVÍO NO VERIFICADO' if guard.used else 'NO TRANSMITIDA'
                        evidence=dict(mode=auth['mode'],verified=False,code='RESULTADO_INCIERTO_NO_REINTENTAR' if guard.used else 'SOLICITUD_FINAL_NO_LIBERADA',cv_id=rule['cv_id'],cv_sha256=rule['cv_hash'],cv_upload_confirmed=bool(guard.portal.upload_complete) if guard.portal else cv_loaded,final_request_released=guard.used,wire_status=guard.wire_status,http_response_statuses=[s for u,s,m in guard.responses if u==guard.endpoint and m=='POST'],last_url=page.url.split('?')[0].split('#')[0])
                        self.store.finish(attempt,state,evidence)
                        if not guard.used:self.pending(job,doc,preview,'La solicitud final no salió del navegador; revisar la validación o intervención pendiente.',block_type='CAPTCHA PENDIENTE' if guard.captcha_provider else 'VALIDACIÓN ANTES DE ENVÍO')
                        return dict(state=state,evidence=evidence)
                return self.pending(job,doc,preview,'Límite de ocho etapas alcanzado.')
        finally:
            if lock:lock.release()
