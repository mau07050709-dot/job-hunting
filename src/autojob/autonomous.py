"""Orquestación secuencial reutilizando búsqueda, compatibilidad, Brave y comprobantes."""
from contextlib import closing
from uuid import uuid4
import json
from autojob.control import Coordinator,now,browser_available
from autojob.forms.submissions import SubmissionStore,SubmissionEngine,eligible_row
from autojob.forms import execution
from autojob.browser.lock import ProfileLock

def verified_jobs(jobs,check,cancel,progress):
    """Tres lecturas públicas como máximo; cancelar no programa más trabajo."""
    from concurrent.futures import ThreadPoolExecutor
    from collections import deque
    pool=ThreadPoolExecutor(max_workers=3);pending=deque();items=iter(jobs)
    def enqueue():
        if cancel():return
        job=next(items,None)
        if job is not None:
            progress('Comprobando enlace: '+job['company']+' · '+job['title'])
            pending.append((job,pool.submit(check,job)))
    try:
        for _ in range(3):enqueue()
        while pending and not cancel():
            job,future=pending.popleft()
            try:future.result()
            except Exception:pass  # El verificador conserva el error; otras fuentes continúan.
            if not cancel():yield job
            enqueue()
    finally:pool.shutdown(wait=True,cancel_futures=True)

class AutomaticCoordinator(Coordinator):
    def __init__(self,settings):
        super().__init__(settings)
        from autojob.form_sessions import FormSessions
        self.sessions=FormSessions(settings)
        self.current_job=None
        self.skipped=set()

    def discard(self,job_id,hide=False):
        job=next((j for j in self.jobs.list() if j['id']==job_id),None)
        if not job:raise ValueError('La vacante seleccionada ya no está disponible en la base local.')
        result=self.store.dispositions.discard(job,hide)
        self.skipped.update(result['related_job_ids'])
        for id in result['related_job_ids']:self.sessions.stop_job(id)
        return result

    def active_job(self):
        id=self.sessions.active_job() or self.current_job
        return id if id not in self.skipped else None

    def run(self,options,pause=lambda:False,stop=lambda:False,progress=lambda s:None,resume_ids=None,services=None):
        services=services or {};token=getattr(self,'delivery_authorization',None)
        if not token:return dict(state='PENDIENTE',reason='Pulsa INICIAR para comenzar una ejecución.')
        sender=SubmissionStore(self.settings.data_path);run=uuid4().hex;cancel=lambda:pause() or stop();checkpoint={'done':[],'errors':[],'deliveries':[]}
        lock=ProfileLock(self.settings.data_path/'control.lock');lock.acquire()
        with closing(self.store.db.connect()) as db,db:db.execute('INSERT INTO control_runs VALUES (?,?,NULL,?,?,?,?,?,?,?)',(run,now(),'EN CURSO','INICIO',None,'Iniciando ejecución solicitada',sender.prep.inputs_hash(),json.dumps({'search':options}),json.dumps(checkpoint)))
        def stage(phase,text,job=None):
            self.current_job=job
            self.store.save_run(run,phase=phase,operation=text,current_job=job,checkpoint=checkpoint);progress(text)
        try:
            execution.state(sender,token,'EN CURSO')
            from autojob.search.availability import Availability
            check=services.get('availability') or Availability(self.jobs).check
            from autojob.search.geography import review_store
            seen=set();accepted={};verified_states={};pending_verification=set();checkpoint.update(existing_reviewed=0,links_valid=0,added=0,verification_pending=0)
            def collect(ids=None,existing=False):
                if cancel():return
                (services.get('geography') or review_store)(self.jobs,cancel,progress)
                jobs=[j for j in self.jobs.list() if (ids is None or j['id'] in ids) and j['id'] not in seen and not sender.duplicate(j) and not self.store.is_excluded(j)]
                seen.update(j['id'] for j in jobs)
                if existing:checkpoint['existing_reviewed']+=len(jobs)
                stage('COMPATIBILIDAD',f'Revisando {len(jobs)} oportunidades guardadas; sin recorte por cantidad…')
                (services.get('evaluate') or self.compatibility.batch)(ids=[j['id'] for j in jobs],cancel=cancel,progress=progress)
                scores=self.compatibility.latest();snapshot=self.compatibility.snapshot()
                jobs.sort(key=lambda j:scores.get(j['id'],{}).get('score',0),reverse=True)
                candidates=[j for j in jobs if j.get('geography')!='INCOMPATIBLE' and not any(x.get('importance')=='OBLIGATORIO' and x.get('state')=='NO CUMPLE' for x in scores.get(j['id'],{}).get('assessments',[]))]
                for index,job in enumerate(verified_jobs(candidates,check,cancel,progress)):
                    if cancel():break
                    e=scores.get(job['id'],{})
                    if job.get('geography')=='INCOMPATIBLE' or any(x.get('importance')=='OBLIGATORIO' and x.get('state')=='NO CUMPLE' for x in e.get('assessments',[])):continue
                    stage('VIGENCIA',f"Verificando {index+1}/{len(jobs)} · {job['company']} · {job['title']}",job['id'])
                    fresh=next(j for j in self.jobs.list() if j['id']==job['id'])
                    if not services.get('evaluate'):
                        result=self.compatibility.one(fresh,snapshot)
                        row=dict(job=fresh,evaluation=result,stale=False)
                    else:
                        services['evaluate'](ids=[fresh['id']],cancel=cancel,progress=progress)
                        row=next(r for r in self.compatibility.rows() if r['job']['id']==fresh['id'])
                    verified_states[job['id']]=fresh.get('availability')
                    checkpoint['links_valid']=sum(v=='ABIERTA' for v in verified_states.values())
                    if eligible_row(row):
                        accepted[job['id']]=row;pending_verification.discard(job['id'])
                        checkpoint['added']+=self.queue.add([job['id']])
                        stage('EN COLA',f"{len(accepted)} candidaturas válidas · {checkpoint['added']} añadidas a POSTULACIONES")
                    else:
                        pending_verification.add(job['id'])
                        if any(q['job_id']==job['id'] and q['state']=='POR PREPARAR' for q in self.queue.list()):self.queue.update(job['id'],'REQUIERE REVISIÓN','La comprobación actual requiere revisar requisitos, acceso o geografía; no ejecutar automáticamente.')
                    checkpoint['verification_pending']=len(pending_verification)
                self.store.save_run(run,checkpoint=checkpoint)
            # Aprovechar primero la base local y guardar candidaturas progresivamente.
            collect(set(resume_ids) if resume_ids else None,existing=True)
            if not resume_ids and not cancel():
                stage('BÚSQUEDA','Consultando fuentes para ampliar la cola…')
                checkpoint['search']=(services.get('search') or self.jobs.search)(options['queries'],options['sources'],options.get('limit'),cancel,progress)
                checkpoint['done'].append('BÚSQUEDA')
                latest=self.compatibility.latest();snap=self.compatibility.snapshot()
                for job in self.jobs.list():
                    if job['id'] in seen and latest.get(job['id'],{}).get('fingerprint')!=self.compatibility.fingerprint(job,snap):
                        seen.discard(job['id']);accepted.pop(job['id'],None)
                collect()
            jobs=self.jobs.list()
            rows=sorted(accepted.values(),key=lambda r:(-r['evaluation'].get('score',0),r['job'].get('discovered_at',''),r['job']['id']))
            checkpoint['eligible']=len(rows);checkpoint['protected_previous']=sum(bool(sender.duplicate(j)) for j in jobs)
            if not rows and not any(r['reviewed'] for r in self.compatibility.library.list()):self.store.add_intervention(None,'Job Hunting','Mis datos','REVISAR CURRÍCULUMS','Faltan datos verificables para evaluar los requisitos. Revisa la extracción o completa tu perfil; no hace falta autorizar cada CV.')
            remaining=rows[:]
            while remaining and not cancel():
                remaining=[r for r in remaining if not self.store.is_excluded(r['job'])]
                if not remaining:break
                existing=next((r for r in remaining if self.sessions.contains(r['job']['id'])),None)
                if existing:remaining.remove(existing);remaining.insert(0,existing)
                if not services.get('send') and not existing and self.sessions.preparing_count()>=self.sessions.limit:
                    parked=self.sessions.park_idle()
                    stage('INTERVENCIÓN','Guardando una preparación sin intervención activa para continuar con la siguiente…' if parked else 'Tres intervenciones humanas activas conservadas. Las demás candidaturas siguen en cola hasta liberar una sesión.')
                    if not parked:
                        checkpoint['browser_deferred']=len(remaining);checkpoint['browser_deferred_ids']=[r['job']['id'] for r in remaining]
                        break
                    import time
                    while self.sessions.preparing_count()>=self.sessions.limit and not cancel():time.sleep(.2)
                    if cancel():break
                row=remaining.pop(0);job=row['job'];id=job['id'];self.queue.add([id])
                if self.store.is_excluded(job):continue
                if self.sessions.contains(id) and not self.sessions.tasks[id].get('preparation_only'):continue
                stage('FORMULARIO','Abriendo '+job['company']+' · '+job['title'],id)
                try:
                    sender.permission(token,job)
                    result=services['send'](id,token,pause,stop,retain=True) if services.get('send') else self.sessions.prepare(id,token,cancel)
                except ValueError as exc:
                    result={'state':'PENDIENTE'}
                    if not self.store.is_excluded(job):self.store.add_intervention(id,job['company'],job['title'],'REVISIÓN NECESARIA',str(exc),job.get('application_url') or job['url'])
                except Exception as exc:
                    result={'state':'PENDIENTE'};checkpoint['errors'].append(type(exc).__name__);self.store.add_intervention(id,job['company'],job['title'],'PORTAL NO DISPONIBLE','No se pudo completar el formulario. La candidatura se conserva.',job.get('application_url') or job['url'])
                checkpoint['deliveries'].append({'job_id':id,**result});self.store.sync(self.queue)
                with closing(sender.db.connect()) as db:
                    used=db.execute("SELECT COUNT(*) FROM submission_attempts WHERE authorization_id=? AND state IN ('ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO')",(token,)).fetchone()[0]
                    maximum=db.execute('SELECT target FROM autonomous_executions WHERE authorization_id=?',(token,)).fetchone()[0]
                if used>=maximum:break
            checkpoint['done']+=['COMPATIBILIDAD','PREPARACIÓN','ENVÍO'];state='DETENIDO' if stop() else 'PAUSADO' if pause() else 'ESPERANDO INTERVENCIÓN' if any(r['state'] in {'PENDIENTE','POSPUESTA'} for r in self.store.interventions()) else 'FINALIZADO'
            execution.state(sender,token,'DETENIDO' if stop() else 'PAUSADO' if pause() else 'EN ESPERA' if state=='ESPERANDO INTERVENCIÓN' else 'FINALIZADO')
            self.store.save_run(run,state=state,phase='FIN',current_job=None,operation='Pausado. Pulsa INICIAR para continuar.' if cancel() else 'Recorrido terminado. Las candidaturas pendientes se conservan.',checkpoint=checkpoint,finished_at=now())
            detail=(f"Revisadas: {checkpoint['existing_reviewed']} guardadas; nuevas: {checkpoint.get('search',{}).get('found',0)}; "
                    f"elegibles: {len(rows)}; enlaces abiertos: {checkpoint['links_valid']}; añadidas: {checkpoint['added']}; "
                    f"formularios intentados: {len(checkpoint['deliveries'])}; por verificar: {checkpoint['verification_pending']}. "
                    + ('Brave reservado: el resto permanece en cola. ' if checkpoint.get('browser_deferred') else 'Ronda agotada; se conserva la cola de verificación. ')
                    + str(checkpoint['protected_previous'])+' resultados anteriores protegidos contra reenvío.')
            return dict(state=state,run_id=run,reason=detail,**checkpoint)
        except Exception as exc:
            execution.state(sender,token,'INTERRUMPIDO');self.store.save_run(run,state='ERROR',operation='La ejecución se interrumpió. Los datos ya guardados se conservan.',checkpoint=checkpoint,finished_at=now());return dict(state='ERROR',reason='No se pudo continuar la ejecución: '+type(exc).__name__)
        finally:
            self.current_job=None
            if cancel():self.sessions.cancel_all()
            lock.release()
