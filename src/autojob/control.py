"""Estado persistente y coordinación sobre los servicios existentes, sin envíos."""
from contextlib import closing
from datetime import datetime,timezone
from uuid import uuid4
from urllib.parse import urlsplit
import json,hashlib
from autojob.storage.database import Database
from autojob.forms.queue import PreparationQueue
from autojob.browser.lock import ProfileLock
from autojob.matching.service import Compatibility

def now():return datetime.now(timezone.utc).isoformat()
DEFAULT=dict(target=30,max_verify=3,max_evaluate=50,max_prepare=3,popups=True,notifications=True,search=None,excluded_companies=[])

def completion_text(state,pending,eligible,queued,browser_free=True,scheduled=False):
    if state=='PAUSADO':return 'Pausado por el usuario. Puedes reanudar desde el punto seguro guardado.'
    if state=='DETENIDO':return 'Detenido por el usuario. Los resultados y las tareas pendientes se conservaron.'
    if queued:
        text=('Brave está reservado; hay '+str(queued)+' operaciones de navegador pospuestas.' if not browser_free else 'Se alcanzó el límite de preparación de esta ejecución; quedan '+str(queued)+' candidaturas en cola.')
    elif not eligible:text='No quedan vacantes elegibles en esta ejecución. Hay '+str(pending)+' intervenciones pendientes.'
    else:text='Sin candidaturas procesables actualmente. Hay '+str(pending)+' intervenciones pendientes.'
    if not browser_free and not queued:text+=' Brave está reservado; se posponen solo sus operaciones.'
    if scheduled:text+=' Hay una búsqueda programada pendiente.'
    return text

class ControlStore:
    def __init__(self,data_path):
        self.data_path=data_path;self.db=Database(data_path/'autojob.sqlite3')
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS control_settings(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS control_runs(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,state TEXT NOT NULL,phase TEXT NOT NULL,current_job TEXT,operation TEXT NOT NULL,profile_hash TEXT NOT NULL,config TEXT NOT NULL,checkpoint TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS control_events(id INTEGER PRIMARY KEY,run_id TEXT,at TEXT NOT NULL,phase TEXT NOT NULL,code TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS control_interventions(id TEXT PRIMARY KEY,fingerprint TEXT UNIQUE NOT NULL,job_id TEXT,company TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL,url TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,alerted INTEGER NOT NULL DEFAULT 0,resumed INTEGER NOT NULL DEFAULT 0,verification_id TEXT,profile_hash TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS control_exclusions(job_id TEXT PRIMARY KEY,excluded_at TEXT NOT NULL)')
        from autojob.dispositions import Dispositions
        self.dispositions=Dispositions(data_path)
    def config(self):
        with closing(self.db.connect()) as db:r=db.execute('SELECT payload FROM control_settings WHERE id=1').fetchone()
        return DEFAULT| (json.loads(r[0]) if r else {})
    def configure(self,**values):
        if not set(values)<=set(DEFAULT):raise ValueError('Opción desconocida.')
        merged=self.config()|values
        for key,maximum in [('target',10000),('max_verify',10),('max_evaluate',300),('max_prepare',20)]:
            if type(merged[key]) is not int or not (1 if key=='target' else 0)<=merged[key]<=maximum:raise ValueError('Límite inválido.')
        for key in ['popups','notifications']:
            if type(merged[key]) is not bool:raise ValueError('Selección inválida.')
        if not isinstance(merged['excluded_companies'],list) or any(not isinstance(c,str) or not c.strip() for c in merged['excluded_companies']):raise ValueError('Empresas excluidas inválidas.')
        with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO control_settings VALUES (1,?)',(json.dumps(merged),))
    def latest(self):
        with closing(self.db.connect()) as db:r=db.execute('SELECT * FROM control_runs ORDER BY started_at DESC LIMIT 1').fetchone()
        return dict(r,config=json.loads(r['config']),checkpoint=json.loads(r['checkpoint'])) if r else None
    def save_run(self,id,**values):
        allowed={'state','phase','current_job','operation','profile_hash','checkpoint','finished_at'}
        if not set(values)<=allowed:raise ValueError('Estado inválido.')
        with closing(self.db.connect()) as db,db:
            for key,value in values.items():db.execute('UPDATE control_runs SET '+key+'=? WHERE id=?',(json.dumps(value) if key=='checkpoint' else value,id))
    def event(self,id,phase,code):
        with closing(self.db.connect()) as db,db:db.execute('INSERT INTO control_events(run_id,at,phase,code) VALUES (?,?,?,?)',(id,now(),phase,code[:200]))
    def recover(self):
        lock=ProfileLock(self.data_path/'control.lock')
        try:lock.acquire()
        except Exception:return 0
        try:
            with closing(self.db.connect()) as db,db:return db.execute("UPDATE control_runs SET state='INTERRUMPIDO',operation='Reanudar desde un punto seguro; revisar sesión externa.' WHERE state='EN CURSO'").rowcount
        finally:lock.release()
    def excluded(self):
        with closing(self.db.connect()) as db:return {r[0] for r in db.execute('SELECT job_id FROM control_exclusions')}
    def is_excluded(self,job):
        return bool(self.dispositions.get(job)) or job['id'] in self.excluded() or job.get('company','').strip().casefold() in {c.strip().casefold() for c in self.config()['excluded_companies']}
    def excluded_ids(self,jobs):
        from autojob.dispositions import decision
        with closing(self.db.connect()) as db:
            ids={r[0] for r in db.execute('SELECT job_id FROM control_exclusions')}
            row=db.execute('SELECT payload FROM control_settings WHERE id=1').fetchone()
            companies={c.strip().casefold() for c in (json.loads(row[0]).get('excluded_companies',DEFAULT['excluded_companies']) if row else DEFAULT['excluded_companies'])}
            return {job['id'] for job in jobs if job['id'] in ids or job.get('company','').strip().casefold() in companies or decision(db,job)}
    def exclude_company(self,company):
        names=self.config()['excluded_companies'];name=company.strip()
        if not name:raise ValueError('Indica la empresa.')
        self.configure(excluded_companies=list(dict.fromkeys(names+[name.casefold()])))
        with closing(self.db.connect()) as db,db:
            rows=[(r['id'],json.loads(r['payload'])) for r in db.execute('SELECT id,payload FROM discovered_jobs')] if db.execute("SELECT 1 FROM sqlite_master WHERE name='discovered_jobs'").fetchone() else []
            for id,job in rows:
                if job.get('company','').strip().casefold()!=name.casefold():continue
                db.execute('INSERT OR REPLACE INTO control_exclusions VALUES (?,?)',(id,now()))
                db.execute("UPDATE control_interventions SET state='OMITIDA',updated_at=? WHERE job_id=? AND state IN ('PENDIENTE','POSPUESTA')",(now(),id))
    def omit(self,id):
        row=next((r for r in self.interventions() if r['id']==id),None)
        if not row:return
        with closing(self.db.connect()) as db,db:
            db.execute("UPDATE control_interventions SET state='OMITIDA',updated_at=? WHERE id=?",(now(),id))
            if row['job_id']:db.execute('INSERT OR REPLACE INTO control_exclusions VALUES (?,?)',(row['job_id'],now()))
    def add_intervention(self,job_id,company,title,kind,message,url='',verification_id=None,profile_hash=''):
        # No contiene respuestas ni valores personales, solo referencias y categorías.
        fingerprint=hashlib.sha256(json.dumps([job_id,kind,message],ensure_ascii=False).encode()).hexdigest();id=uuid4().hex
        from autojob.auth.detection import safe_url
        safe=safe_url(url) if url else ''
        with closing(self.db.connect()) as db,db:
            db.execute("INSERT OR IGNORE INTO control_interventions VALUES (?,?,?,?,?,?,?,?, 'PENDIENTE',?,?,0,0,?,?)",(id,fingerprint,job_id,company,title,kind,message,safe,now(),now(),verification_id,profile_hash))
            row=db.execute('SELECT id FROM control_interventions WHERE fingerprint=?',(fingerprint,)).fetchone()
        id=row[0]
        from autojob.intervention_context import capture
        current=next(r for r in self.interventions() if r['id']==id)
        capture(self,current,PreparationQueue(self.data_path))
        return id
    def interventions(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute("SELECT * FROM control_interventions ORDER BY CASE state WHEN 'PENDIENTE' THEN 0 WHEN 'POSPUESTA' THEN 1 ELSE 2 END,created_at")]
    def intervention_state(self,id,state):
        if state not in {'PENDIENTE','POSPUESTA','RESUELTA','OMITIDA'}:raise ValueError('Estado inválido.')
        with closing(self.db.connect()) as db,db:db.execute('UPDATE control_interventions SET state=?,updated_at=? WHERE id=?',(state,now(),id))
    def sync(self,queue):
        from autojob.auth.verifications import VerificationStore
        jobs={j['id']:j for j in queue.preparation.compatibility.jobs.list()};fingerprint=queue.preparation.inputs_hash()
        for r in queue.list():
            if r['state'] not in {'PENDIENTE','BLOQUEADA','ERROR','REQUIERE REVISIÓN'} or r['job_id'] in jobs and self.is_excluded(jobs[r['job_id']]):continue
            p=r['payload'];blocks=p.get('blocks',[])
            for b in blocks:
                kind=b.get('type','REVISIÓN');kind='INFORMACIÓN FALTANTE' if re_match_missing(kind) else 'CAPTCHA PENDIENTE' if kind=='CAPTCHA' else kind
                self.add_intervention(r['job_id'],p.get('company',''),p.get('title','Vacante'),kind,('Revisar campos requeridos: '+', '.join(str(f.get('field') or f.get('label') or '') for f in p.get('pending',[]) if f.get('required'))) if kind=='INFORMACIÓN FALTANTE' else kind,r['url'],profile_hash=fingerprint)
            if not blocks and r['state']=='ERROR':self.add_intervention(r['job_id'],p.get('company',''),p.get('title','Vacante'),'ERROR DE PREPARACIÓN','Revisar el enlace y la disponibilidad del portal.',r['url'],profile_hash=fingerprint)
        for v in VerificationStore(self.data_path).list():
            if v['job_id'] in jobs and self.is_excluded(jobs[v['job_id']]):continue
            if v['kind']=='FORMULARIO PREPARADO':
                with closing(self.db.connect()) as db,db:db.execute("UPDATE control_interventions SET state='SUPERADA',resumed=1 WHERE job_id=? AND kind='FORMULARIO PREPARADO' AND state IN ('PENDIENTE','POSPUESTA')",(v['job_id'],))
                continue
            j=jobs.get(v['job_id'],{});id=self.add_intervention(v['job_id'],j.get('company',''),j.get('title') or v['title'],v['kind'],v['kind'],v['url'],v['id'],fingerprint)
            with closing(self.db.connect()) as db,db:db.execute('UPDATE control_interventions SET verification_id=? WHERE id=?',(v['id'],id))
        from autojob.live import reconcile
        reconcile(self,queue)
    def confirmed_urls(self):
        # Un estado ENVIADA sin comprobante externo verificable no cuenta.
        with closing(self.db.connect()) as db:rows=db.execute("SELECT url,confirmation,applied_at FROM applications WHERE status='ENVIADA'").fetchall()
        with closing(self.db.connect()) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='submission_attempts'").fetchone():
                for attempt in db.execute("SELECT a.evidence,j.payload,a.updated_at FROM submission_attempts a JOIN discovered_jobs j ON j.id=a.job_id WHERE a.mode='real' AND a.state='ENVIADA CONFIRMADA'"):
                    rows.append(dict(url=json.loads(attempt['payload'])['url'],confirmation=attempt['evidence'],applied_at=attempt['updated_at']))
        confirmed=set()
        for r in rows:
            try:
                evidence=json.loads(r['confirmation'] or '{}');p=urlsplit(r['url'])
                if evidence.get('mode')=='real' and evidence.get('verified') is True and (evidence.get('receipt_id') or evidence.get('evidence_id') and (evidence.get('source')=='MANUAL_USUARIO' and evidence.get('manual_checked') and evidence.get('receipt_file_sha256') or evidence.get('confirmation_kind') and evidence.get('final_request_released') and any(200<=code<400 for code in evidence.get('http_response_statuses',[])))) and r['applied_at'] and p.scheme=='https' and p.hostname not in {'localhost','127.0.0.1','example.invalid'} and not p.hostname.endswith('.invalid'):confirmed.add(r['url'])
            except (ValueError,AttributeError):pass
        return confirmed
    def confirmed(self):return len(self.confirmed_urls())
    def counts(self,queue):
        with closing(self.db.connect()) as db:
            deliveries=[dict(r) for r in db.execute("SELECT job_id,state FROM submission_attempts WHERE mode='real' AND state IN ('ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA')")] if db.execute("SELECT 1 FROM sqlite_master WHERE name='submission_attempts'").fetchone() else []
        no_longer_prepared={r['job_id'] for r in deliveries}|{j['id'] for j in queue.preparation.compatibility.jobs.list() if self.is_excluded(j)}
        rows=[r for r in queue.list() if r['job_id'] not in no_longer_prepared];latest=self.latest();evaluation_rows=queue.preparation.compatibility.rows();evaluations={r['job']['id']:r['evaluation'] for r in evaluation_rows if r['evaluation'] and not r['stale']};jobs=queue.preparation.compatibility.jobs.list();current_hash=queue.preparation.inputs_hash()
        return dict(found=len(jobs),compatible=sum(e.get('eligibility')=='COMPATIBLE' for e in evaluations.values()),prepared=sum(r['state']=='PREPARADA' and (r['payload'].get('preview') or {}).get('inputs_hash')==current_hash for r in rows),sent=self.confirmed(),pending=sum(r['state'] in {'POR PREPARAR','PENDIENTE','REQUIERE REVISIÓN','BLOQUEADA'} or r['state']=='PREPARADA' and (r['payload'].get('preview') or {}).get('inputs_hash')!=current_hash for r in rows),errors=sum(r['state']=='ERROR' for r in rows)+len((latest or {}).get('checkpoint',{}).get('errors',[])),interventions=sum(r['state'] in {'PENDIENTE','POSPUESTA'} for r in self.interventions()),target=self.config()['target'])

def re_match_missing(kind):return any(word in kind for word in ('DATO','DOCUMENTO OBLIGATORIO','SOLICITUD OBLIGATORIA'))

def browser_available(data_path):
    lock=ProfileLock(data_path/'browser.lock')
    try:lock.acquire();return True
    except Exception:return False
    finally:lock.release()

class Coordinator:
    def __init__(self,settings):
        self.settings=settings;self.store=ControlStore(settings.data_path);self.queue=PreparationQueue(settings.data_path);self.compatibility=self.queue.preparation.compatibility;self.jobs=self.compatibility.jobs;self.queue.defer_interventions=True
    def run(self,search_options,pause=lambda:False,stop=lambda:False,progress=lambda text:None,resume_ids=None,services=None):
        from autojob.search.availability import Availability
        from autojob.search.geography import review_store
        services=services or {};lock=ProfileLock(self.settings.data_path/'control.lock');lock.acquire();latest=self.store.latest();config=self.store.config();run_id=uuid4().hex;checkpoint=dict(done=[],errors=[],prepared_ids=[])
        if resume_ids is None and latest and latest['state'] in {'PAUSADO','INTERRUMPIDO'} and latest['config']['search']==search_options:
            run_id=latest['id'];checkpoint=latest['checkpoint'];search_options=latest['config']['search']
        else:
            with closing(self.store.db.connect()) as db,db:db.execute('INSERT INTO control_runs VALUES (?,?,NULL,?,?,?,?,?,?,?)',(run_id,now(),'EN CURSO','INICIO',None,'Iniciando modo preparación',self.queue.preparation.inputs_hash(),json.dumps(dict(search=search_options,limits=config)),json.dumps(checkpoint)))
        cancelled=lambda:pause() or stop()
        def stage(name,text):
            self.store.save_run(run_id,state='EN CURSO',phase=name,current_job=None,operation=text);self.store.event(run_id,name,'ETAPA_INICIADA');progress(text)
        def complete(name):
            if name not in checkpoint['done']:checkpoint['done'].append(name)
            self.store.save_run(run_id,checkpoint=checkpoint)
        try:
            self.store.save_run(run_id,state='EN CURSO')
            current_hash=self.queue.preparation.inputs_hash()
            if latest and latest['profile_hash']!=current_hash:self.store.event(run_id,'DATOS','PREPARACIONES_REQUIEREN_REVALIDACIÓN')
            self.store.save_run(run_id,profile_hash=current_hash)
            if resume_ids is None and 'BÚSQUEDA' not in checkpoint['done'] and not cancelled():
                stage('BÚSQUEDA','Buscando vacantes en las fuentes habilitadas…')
                result=(services.get('search') or self.jobs.search)(search_options['queries'],search_options['sources'],search_options.get('limit',30),cancelled,progress)
                checkpoint['search']=result;checkpoint['errors']+=['FUENTE_NO_DISPONIBLE']*len(result.get('errors',[]))
                if not cancelled():complete('BÚSQUEDA')
            if resume_ids is None and 'GEOGRAFÍA' not in checkpoint['done'] and not cancelled():
                stage('GEOGRAFÍA','Revisando las restricciones geográficas…');(services.get('geography') or review_store)(self.jobs,cancelled,progress)
                if not cancelled():complete('GEOGRAFÍA')
            all_jobs=self.jobs.list();ids=resume_ids if resume_ids else [j['id'] for j in all_jobs[:config['max_evaluate']]]
            if 'VIGENCIA' not in checkpoint['done'] and not cancelled():
                stage('VIGENCIA','Comprobando vigencia cuando el portal lo permite…')
                checker=services.get('availability') or Availability(self.jobs).check
                for job in [j for j in all_jobs if j['id'] in ids and j.get('geography')!='INCOMPATIBLE'][:config['max_verify']]:
                    if cancelled():break
                    self.store.save_run(run_id,current_job=job['id']);checker(job)
                if not cancelled():complete('VIGENCIA')
            if not cancelled():
                stage('COMPATIBILIDAD','Evaluando compatibilidad y seleccionando currículums…');checkpoint['evaluation']=(services.get('evaluate') or self.compatibility.batch)(ids=ids,cancel=cancelled,progress=progress)
                if not cancelled():complete('COMPATIBILIDAD')
            if not cancelled():
                stage('COLA','Organizando vacantes elegibles…');eligible=[]
                for r in self.compatibility.rows():
                    j=r['job'];e=r['evaluation'] or {};selection=e.get('resume_selection') or {}
                    if j['id'] in self.store.excluded() or j['url'] in self.store.confirmed_urls():continue
                    if j['id'] in ids and not r['stale'] and e.get('eligibility')=='COMPATIBLE' and e.get('geography')=='CONFIRMADO' and e.get('availability')=='ABIERTA' and selection.get('confirmed') and selection.get('resume_id'):eligible.append(j['id'])
                self.queue.add(eligible)
                current_hash=self.queue.preparation.inputs_hash()
                for old in self.queue.list():
                    if old['job_id'] in eligible and old['state']=='PREPARADA' and (old['payload'].get('preview') or {}).get('inputs_hash')!=current_hash:self.queue.requeue([old['job_id']])
                if not any(c.get('reviewed') for c in self.compatibility.library.list()):self.store.add_intervention(None,'Job Hunting','Tus currículums','REVISAR CURRÍCULUMS','Revisa y confirma los datos de al menos un CV; no se confirma información automáticamente.',profile_hash=current_hash)
                active=[r['job_id'] for r in self.queue.list() if r['state']=='POR PREPARAR' and r['job_id'] in eligible][:config['max_prepare']]
                # Las continuaciones explícitas pueden inspeccionarse sin autorizar relleno: el motor existente vuelve a validar sus permisos.
                if resume_ids:active=[r['job_id'] for r in self.queue.list() if r['job_id'] in resume_ids and r['state']=='POR PREPARAR' and r['job_id'] not in self.store.excluded()][:config['max_prepare']]
                checkpoint['eligible']=len(eligible);checkpoint['eligible_ids']=list(eligible);checkpoint['active_ids']=active;self.store.save_run(run_id,checkpoint=checkpoint)
                stage('PREPARACIÓN','Preparando formularios; envíos reales desactivados…')
                for id in active:
                    if cancelled():break
                    if not browser_available(self.settings.data_path):
                        self.store.event(run_id,'PREPARACIÓN','BRAVE_RESERVADO_TAREA_CONSERVADA');progress('Brave reservado: vacante conservada; búsqueda y evaluación local continúan.');continue
                    if getattr(self,'delivery_authorization',None) and not services.get('prepare'):continue
                    self.store.save_run(run_id,current_job=id);result=(services.get('prepare') or self.queue.run)(self.settings,ids={id},pause=pause,stop=stop,progress=progress)
                    checkpoint['prepared_ids'].append(id);self.store.sync(self.queue);self.store.save_run(run_id,checkpoint=checkpoint)
                if not cancelled():complete('PREPARACIÓN')
            authorization=getattr(self,'delivery_authorization',None)
            if authorization and not cancelled():
                from autojob.forms.submissions import SubmissionEngine
                sender=SubmissionEngine(self.settings);sender.store.recover();stage('ENVÍO','Procesando envíos dentro de la autorización revisada…');checkpoint['deliveries']=[]
                for id in eligible[:config['max_prepare']]:
                    if cancelled() or self.store.confirmed()>=config['target']:break
                    if not browser_available(self.settings.data_path):
                        self.store.event(run_id,'ENVÍO','BRAVE_RESERVADO_ENVÍO_POSPUESTO');continue
                    self.store.save_run(run_id,current_job=id)
                    try:
                        job=next(j for j in all_jobs if j['id']==id);sender.store.permission(authorization,job)
                        outcome=sender.run(id,authorization,pause,stop,retain=True)
                    except ValueError as exc:
                        self.store.add_intervention(id,job['company'],job['title'],'ALCANCE O PERMISO','La candidatura no cumple los límites o permisos vigentes del lote; revisa su alcance sin transmitir datos.',job.get('application_url') or job['url'])
                        outcome=dict(state='PENDIENTE',code='ALCANCE_O_PERMISO_NO_VALIDO')
                    except Exception as exc:outcome=dict(state='BLOQUEADA',code=type(exc).__name__)
                    checkpoint['deliveries'].append(dict(job_id=id,**outcome));self.store.save_run(run_id,checkpoint=checkpoint)
                if not cancelled():complete('ENVÍO')
            self.store.sync(self.queue);state='DETENIDO' if stop() else 'PAUSADO' if pause() else 'ESPERANDO INTERVENCIÓN' if any(r['state'] in {'PENDIENTE','POSPUESTA'} for r in self.store.interventions()) else 'FINALIZADO';self.store.save_run(run_id,state=state,phase='FIN',current_job=None,operation=completion_text(state,sum(r['state'] in {'PENDIENTE','POSPUESTA'} for r in self.store.interventions()),checkpoint.get('eligible',0),sum(r['state']=='POR PREPARAR' and r['job_id'] in checkpoint.get('eligible_ids',[]) for r in self.queue.list()),browser_available(self.settings.data_path),bool(search_options.get('hours'))),checkpoint=checkpoint,finished_at=now() if state!='PAUSADO' else None)
            return dict(run_id=run_id,state=state,**checkpoint)
        except Exception as exc:
            checkpoint['errors'].append(type(exc).__name__);self.store.save_run(run_id,state='ERROR',operation='Operación interrumpida; resultados ya guardados conservados.',checkpoint=checkpoint,finished_at=now());return dict(state='ERROR',error=type(exc).__name__)
        finally:lock.release()
