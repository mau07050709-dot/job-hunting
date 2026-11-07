"""Sesiones humanas: Playwright permanece exclusivamente en su hilo propietario."""
from threading import Event,RLock
from contextlib import closing
import json,time
from autojob.forms.preparation import inspect
from autojob.forms.runner import enrich,fill_field
from autojob.forms.answers9b import restricted

_lock=RLock();_sessions={}
clock=time.monotonic

def command(job,action):
    with _lock:
        item=_sessions.get(job)
        if not item:return False
        if action=='PARK':
            if item.get('active') or item.get('sending'):return False
            item['end'].set();return True
        if action in {'LATER','CANCEL'}:item['end'].set()
        elif action=='FOCUS':item['focus'].set();item['active']=True
        elif action=='CHECK':item['check'].set()
        return True

def active(job=None):
    with _lock:return job in _sessions if job else bool(_sessions)

def status(job):
    with _lock:
        item=_sessions.get(job)
        return item.get('message') if item else None

def cancel_all():
    with _lock:
        for item in _sessions.values():item['end'].set()

def proposed(job,field):
    with _lock:return (_sessions.get(job) or {}).get('proposed',{}).get(field.get('name') or field['label'])

def historical(store,job):
    from autojob.forms.submissions import UNSAFE
    from autojob.matching.engine import digest
    from autojob.search.jobs import canonical
    with closing(store.db.connect()) as db:record=db.execute('SELECT payload FROM discovered_jobs WHERE id=?',(job,)).fetchone()
    data=dict(json.loads(record[0]),id=job) if record else {};url=data.get('application_url') or data.get('url');key=digest(canonical(url)) if url else None
    rows=[r for r in store.rows() if r['job_id']==job or key and r['logical_key']==key]
    if not rows and data and store.duplicate(data):return 'UNCERTAIN'
    if any(r['state']=='ENVIADA CONFIRMADA' for r in rows):return 'CONFIRMED'
    if any(r['state'] in {'ENVÍO NO VERIFICADO','RECHAZADA'} for r in rows):return 'UNCERTAIN'
    if any(r['state']=='ENVIANDO' for r in rows):return 'INFLIGHT'
    return None

def reconcile(store,queue):
    """Archivar bloqueos previos; jamás cambiar evidencia o estado del intento."""
    from autojob.forms.submissions import SubmissionStore
    sender=SubmissionStore(store.data_path);jobs={r['job_id']:historical(sender,r['job_id']) for r in sender.rows()};changed=0
    for job,state in jobs.items():
        if not state or state=='INFLIGHT':continue
        rows=[r for r in store.interventions() if r['job_id']==job and r['state'] in {'PENDIENTE','POSPUESTA'}];kept=False
        for row in rows:
            receipt='COMPROBANTE' in row['kind'] and state=='UNCERTAIN'
            if receipt and not kept:kept=True;continue
            with closing(store.db.connect()) as db,db:changed+=db.execute("UPDATE control_interventions SET state='SUPERADA',resumed=1 WHERE id=?",(row['id'],)).rowcount
        q=next((q for q in queue.list() if q['job_id']==job),None)
        if q and q['state'] in {'POR PREPARAR','ANALIZANDO','RELLENANDO'}:queue.update(job,'BLOQUEADA','Resultado final existente: solo revisar comprobante; no reabrir ni adjuntar CV.')
    # En preparación, una instantánea agregada nueva sustituye avisos de datos más antiguos.
    for q in queue.list():
        if jobs.get(q['job_id']):continue
        infos=[r for r in store.interventions() if r['job_id']==q['job_id'] and r['kind']=='INFORMACIÓN FALTANTE' and r['state'] in {'PENDIENTE','POSPUESTA'} and r.get('message','').strip()!='Revisar campos requeridos: Resume/CV']
        for old in sorted(infos,key=lambda r:r['created_at'],reverse=True)[1:]:
            with closing(store.db.connect()) as db,db:changed+=db.execute("UPDATE control_interventions SET state='SUPERADA',resumed=1 WHERE id=?",(old['id'],)).rowcount
    return changed

def prepare(page,guard,prep,job,rule=None,allow_text=True):
    """Punto fijo acotado; conservar valores existentes y agotar solo acciones autorizadas."""
    from autojob.forms.validation import audit
    from autojob.forms.queue import PreparationQueue
    from autojob.forms.submissions import SubmissionStore
    store=SubmissionStore(prep.data.data_path)
    if historical(store,job['id']):raise ValueError('Resultado final existente: solo comprobante.')
    allowed=allow_text and (bool(rule) or PreparationQueue(prep.data.data_path).site_allowed(page.url))
    if rule:
        from autojob.forms.guard import origin
        allowed=allowed and origin(page.url)==rule['origin']
    from autojob.forms.answers9b import ScopedAnswers
    approved_store=ScopedAnswers(prep.data.data_path);approved_rows=approved_store.rows();approved_store.rows=lambda:approved_rows;resolved={}
    outcomes={};entries=[];doc=None;pending=[]
    for round in range(4):
        doc=inspect(page,max_frames=12);preview=prep.prepare(doc,job,cv_approved=bool(rule and rule.get('execution_authorized')));entries=[enrich(prep,e) for e in preview['entries']];changes=0;pending=[]
        critical={'CV PROVISIONAL','CV INCOMPATIBLE','EVALUACIÓN OBSOLETA','VACANTE POR VERIFICAR','DOCUMENTO NO DISPONIBLE','VACANTE INCOMPATIBLE'}
        if any(b['type'] in critical for b in preview['blocks']) or any(b['type'] in {'AUTENTICACIÓN','ERROR DEL PORTAL'} for b in doc['obstacles']):allowed=False
        for entry in entries:
            from autojob.forms.answers9b import ScopedAnswers
            question=entry.get('group') if entry['kind']=='radio' and entry.get('group') else entry['label']
            if question not in resolved:resolved[question]=approved_store.resolve(question,dict(job_id=job['id'],company=job['company'],position=job['title'],modality=job.get('modality')))
            approved=resolved[question]
            if approved and entry.get('status') not in {'CONFLICTO','BLOQUEADA','SENSIBLE'} and not restricted(question):entry.update(approved)
            key=entry.get('name') or entry['label'];target=page.frames[entry.get('frame_index',0)].locator(entry['selector'])
            if target.count()!=1:continue
            if entry.get('sensitive_identity') or entry.get('requires_specific_consent') or restricted(entry.get('group') or entry['label']):
                if entry.get('required'):pending.append(entry)
                continue
            if entry['kind']=='file':
                if entry.get('document')!='cv' or not rule or not rule.get('upload'):
                    if entry.get('required') and not target.evaluate('(e)=>!!e.files?.length'):pending.append(entry)
                    continue
                path=prep.compatibility.library.original_path(rule['cv_id'],verify=True)
                files=target.evaluate('(e)=>Array.from(e.files||[]).map(f=>({name:f.name,size:f.size}))')
                if not files and allowed:
                    if hasattr(guard,'check'):guard.check()
                    if getattr(guard,'portal',None):guard.portal.attach_cv(page,target,path,guard.check)
                    else:target.set_input_files(str(path))
                    changes+=1
                    actual=target.evaluate('(e)=>Array.from(e.files||[]).map(f=>({name:f.name,size:f.size}))')
                    verified=bool(getattr(getattr(guard,'portal',None),'upload_complete',False)) or len(actual)==1 and actual[0]['name']==path.name and actual[0]['size']==path.stat().st_size
                    if not verified:pending.append(entry)
                elif not files and entry.get('required'):pending.append(entry)
                elif files and (len(files)!=1 or files[0]['name']!=path.name or files[0]['size']!=path.stat().st_size):pending.append(entry)
                continue
            if not allowed and entry.get('answer') is not None and entry['status'] in {'CONFIRMADA','DERIVADA'}:
                existing=target.evaluate('(e)=>({value:e.value||"",valid:!e.willValidate||e.validity.valid})')
                if existing['valid'] and str(existing['value']).strip()==str(entry['answer']).strip():continue
            if entry.get('answer') is None or entry['status'] not in {'CONFIRMADA','DERIVADA'} or not allowed:
                if entry.get('required'):pending.append(entry)
                continue
            # Una corrección humana válida en la página no se sustituye por el perfil.
            current=target.evaluate('(e)=>({value:e.value||"",valid:!e.willValidate||e.validity.valid,checked:e.checked})')
            if entry['kind']=='radio' and entry.get('name'):
                group=[e for e in entries if e['kind']=='radio' and e.get('name')==entry['name']]
                selected=[e['label'] for e in group if page.frames[e.get('frame_index',0)].locator(e['selector']).is_checked()]
                if selected and str(entry['answer']) not in selected:
                    pending.append(dict(entry,status='DESCONOCIDA',answer=None));continue
            if entry['kind'] in {'select','multiple'} and not entry.get('checkbox_group'):
                selected=target.locator('option:checked').all_text_contents()
                actual=target.input_value() if entry['kind']=='select' else ''
                if actual and current['valid'] and str(entry['answer']) not in [x.strip() for x in selected]:
                    pending.append(dict(entry,status='DESCONOCIDA',answer=None));continue
            if entry['kind'] not in {'radio','checkbox','multiple','combobox','select'} and current['value'] and current['valid']:
                if str(current['value']).strip()!=str(entry['answer']).strip():
                    pending.append(dict(entry,status='DESCONOCIDA',answer=None));continue
                outcomes[key]='VERIFICADO';continue
            if entry.get('semantic')=='phone_5ca':
                from autojob.forms.fiveca import fill_phone
                result=fill_phone(page,entry)
            elif getattr(guard,'portal',None) and entry['kind']=='combobox':result=guard.portal.fill_combobox(page,entry)
            else:
                if hasattr(guard,'check'):guard.check()
                result=fill_field(page,entry,guard)
            if outcomes.get(key)!=result['status']:changes+=1
            outcomes[key]=result['status']
            if result['status'] not in {'VERIFICADO','NO SELECCIONADO'} and entry.get('required'):pending.append(entry)
        if not changes:break
    else:pending.append(dict(label='El formulario sigue cambiando',name='',kind='dynamic',required=True))
    if any(e['kind']=='file' and e.get('document')=='cv' for e in entries) and not (rule and rule.get('upload')):
        preview['blocks'].append(dict(type='AUTORIZACIÓN CV',evidence='No hay permiso vigente para adjuntar el CV. INICIAR aplica los permisos de la ejecución; no se solicita buscar otro documento.'))
    state=dict(document=doc,preview=preview,pending=pending,rounds=round+1,allowed=allowed,outcomes=outcomes)
    return state

def wait_prepared(settings,browser,page,guard,job,authorization=None,stop=lambda:False,on_ready=None,fixture=None,human_active=False,prepared=None):
    from autojob.forms.submissions import SubmissionStore
    from autojob.forms.queue import PreparationQueue
    from autojob.control import ControlStore
    from autojob.auth.verifications import captcha_state,VerificationStore,notify
    from autojob.intervention_context import focus
    store=SubmissionStore(settings.data_path);prep=store.prep;queue=PreparationQueue(settings.data_path);controls=ControlStore(settings.data_path);jid=job['id']
    if historical(store,jid):return dict(state='BLOQUEADA',reason='Solo revisar comprobante.')
    item=dict(end=Event(),focus=Event(),check=Event(),active=human_active,proposed={})
    if human_active:item['focus'].set()
    with _lock:
        if jid in _sessions:raise ValueError('Esta candidatura ya tiene una sesión reservada.')
        _sessions[jid]=item
    rule=None;last_hash=None;state=None;last_scan=0;notified=False;advances=set();ready_signature=None;manual_baselines={}
    verification=VerificationStore(settings.data_path);vid=verification.add(jid,'FORMULARIO PREPARADO',page.url,job['title'],True)
    try:
        while not item['end'].is_set() and not stop() and not page.is_closed():
            if historical(store,jid):return dict(state='BLOQUEADA',reason='Resultado final existente; no repetir.')
            now=clock();explicit_check=item['check'].is_set()
            if now-last_scan>=1 or item['check'].is_set():
                # Una respuesta escrita por la persona en esta sesión solo se
                # reutiliza para esta vacante. No confundir valores iniciales
                # del portal con respuestas humanas ni aprender datos sensibles.
                if state and item['active'] and authorization:
                    from autojob.forms.answers9b import ScopedAnswers,validate_answer
                    bank=ScopedAnswers(settings.data_path);before_hash=prep.inputs_hash();learned=False
                    context=dict(job_id=jid,company=job['company'],position=job['title'],modality=job.get('modality'))
                    for field in state['pending']:
                        key=(field.get('frame_index',0),field.get('selector'));question=field.get('group') or field.get('label','')
                        if key not in manual_baselines or field.get('status') in {'CONFLICTO','BLOQUEADA','SENSIBLE'} or field.get('answer') is not None or field.get('kind') not in {'text','textarea','email','tel','number','date','select'} or restricted(question):continue
                        target=page.frames[key[0]].locator(key[1])
                        if target.count()!=1:continue
                        if not target.evaluate('(e)=>!!e.ownerDocument.defaultView.__jobMaxxingManualInputs?.has(e)'):continue
                        value=target.input_value()
                        if not value.strip() or value==manual_baselines[key] or not target.evaluate('(e)=>!e.willValidate||e.validity.valid'):continue
                        if field['kind']=='select':value=target.locator('option:checked').inner_text().strip()
                        existing=bank.resolve(question,context)
                        if existing and existing.get('answer')==value:continue
                        try:validate_answer(value,field['kind'],[o['label'] for o in field.get('options',[])])
                        except ValueError:continue
                        bank.save(question,value,field['kind'],'job',context,True,options=[o['label'] for o in field.get('options',[])]);learned=True
                    if learned:prep.compatibility.one(job,force=True);store.accept_confirmed_answer(authorization,jid,before_hash)
                permission_error=False
                if authorization:
                    try:_,rule=store.permission(authorization,job)
                    except ValueError:rule=None;permission_error=True
                current_hash=prep.inputs_hash();state=prepare(page,guard,prep,job,rule,allow_text=not permission_error);last_hash=current_hash;last_scan=now;item['check'].clear()
                for field in state['pending']:
                    key=(field.get('frame_index',0),field.get('selector'))
                    if key[1] and key not in manual_baselines and field.get('kind') in {'text','textarea','email','tel','number','date','select'} and not restricted(field.get('group') or field['label']):
                        target=page.frames[key[0]].locator(key[1])
                        if target.count()==1:
                            manual_baselines[key]=target.input_value()
                            target.evaluate('''e=>{const w=e.ownerDocument.defaultView;if(!w.__jobMaxxingManualInputs){w.__jobMaxxingManualInputs=new WeakSet();for(const name of ['input','change'])e.ownerDocument.addEventListener(name,event=>{if(event.isTrusted)w.__jobMaxxingManualInputs.add(event.target);},true);}}''')
                cap=captcha_state(page,fixture);blocks=[b for b in state['document']['obstacles'] if b['type']!='CAPTCHA' or not cap['completed']]
                if permission_error:blocks.append(dict(type='AUTORIZACIÓN PENDIENTE',evidence='Permiso caducado, revocado o datos modificados; sesión conservada sin enviar.'))
                # Continuaciones ordinarias inequívocas, nunca el botón final.
                if not state['pending'] and not blocks and state['allowed']:
                    from autojob.forms.guard import continue_stage
                    signature=(page.url,tuple((f.get('selector'),f.get('label')) for f in state['document']['fields']))
                    if not any(f.get('action')=='ENVÍO FINAL' for f in state['document']['fields']) and signature not in advances and len(advances)<8:
                        advances.add(signature)
                        advanced,_=continue_stage(page,guard)
                        if advanced:last_scan=0;continue
                # Guardar manifiesto, no valores de formulario ni tokens.
                entries=state['preview']['entries'];pending=state['pending'];safe=dict(session_state='INTERVENCIÓN HUMANA ACTIVA' if item['active'] else 'FORMULARIO PREPARADO',field_states=[dict(name=e.get('name'),kind=e['kind'],known=e['status'] in {'CONFIRMADA','DERIVADA','DOCUMENTO LOCAL'}) for e in entries],cv_attached=any(e['kind']=='file' and page.frames[e.get('frame_index',0)].locator(e['selector']).evaluate('(e)=>!!e.files?.length') for e in entries),url=job.get('application_url') or job['url'])
                queue.add([jid]);payload=dict(company=job['company'],title=job['title'],preview=state['preview'],stages=[dict(document=state['document'],preview=state['preview'])],pending=[dict(field=e.get('group') or e['label'],required=True) for e in pending],blocks=blocks+([dict(type='DATO OBLIGATORIO PENDIENTE',evidence='; '.join(e.get('group') or e['label'] for e in pending))] if pending else []),live_snapshot=safe)
                payload['manual_conflicts']=[e.get('name') or e['label'] for e in pending if e.get('answer') is None and any((p.get('name') or p['label'])==(e.get('name') or e['label']) and p['status'] in {'CONFIRMADA','DERIVADA'} for p in entries)]
                from copy import deepcopy
                from autojob.auth.detection import safe_url
                stored=deepcopy(payload)
                for section in [stored['preview'],stored['stages'][0]['document'],stored['stages'][0]['preview']]:
                    if section.get('url'):section['url']=safe_url(section['url'])
                    for field in section.get('fields',section.get('entries',[])):
                        if field.get('frame_url'):field['frame_url']=safe_url(field['frame_url'])
                queue.update(jid,'PENDIENTE','Formulario preparado conservado en la sesión propietaria.',stored);controls.sync(queue)
                attached=safe['cv_attached'] or bool(getattr(getattr(guard,'portal',None),'upload_complete',False))
                from autojob.application_status import prepared_message
                with _lock:
                    item['message']=prepared_message(dict(state,document=dict(state['document'],obstacles=blocks)),attached,sum(value=='VERIFICADO' for value in state.get('outcomes',{}).values()),bool(rule and rule.get('preparation_only')))
                if rule and attached and not any(e.get('kind')=='file' and e.get('document')=='cv' for e in pending):
                    for old in controls.interventions():
                        if old['job_id']==jid and old['state'] in {'PENDIENTE','POSPUESTA'} and old.get('message','').strip()=='Revisar campos requeridos: Resume/CV':controls.intervention_state(old['id'],'RESUELTA')
                with _lock:
                    for e in pending:
                        if e.get('selector') and e['kind'] not in {'file','radio','checkbox'} and not restricted(e.get('group') or e['label']):
                            target=page.frames[e.get('frame_index',0)].locator(e['selector'])
                            if target.count()==1:item['proposed'][e.get('name') or e['label']]=target.input_value()
                if (pending or blocks) and not notified:notify(vid,'Job Hunting · formulario preparado',job['company']+' · '+job['title']);notified=True
                if fixture and fixture.get('on_prepared'):fixture['on_prepared'](page,state,item)
                if prepared and (pending or blocks):prepared.set()
                if not pending and not blocks and state['allowed']:
                    verification.update(vid,'LISTA PARA CONTINUAR',reserved=False)
                    stored['live_snapshot'].update(portal_verified=True,inputs_hash=current_hash)
                    queue.update(jid,'PENDIENTE','Bloqueo resuelto y comprobado en la sesión actual; revalidar antes de enviar.',stored)
                    signature=(page.url,current_hash,tuple((f.get('selector'),f.get('kind'),f.get('label')) for f in state['document']['fields']))
                    if on_ready and signature!=ready_signature:
                        with _lock:
                            if item['end'].is_set():break
                            item['sending']=True
                        try:ready_signature=signature;result=on_ready()
                        finally:
                            with _lock:item['sending']=False
                        if result.get('state') in {'ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA','BLOQUEADA'}:return result
                        # Una etapa nueva puede revalidarse sin volver a INICIAR.
                        # La firma impide reintentar un bloqueo idéntico; historical impide otro POST.
                        controls.add_intervention(jid,job['company'],job['title'],'REVISIÓN DE CONTINUACIÓN',result.get('reason','Revisar la etapa actual sin repetir el envío final.'),page.url)
                        continue
                    if not authorization or explicit_check:return dict(state='PREPARADA',same_session=True)
            # Preparar primero, incluso si FOCUS llegó mientras se abría la página.
            # Playwright y la espera humana permanecen en este hilo propietario.
            if state and item['focus'].is_set():
                page.bring_to_front();item['focus'].clear();verification.update(vid,'EN INTERVENCIÓN');focus(page,dict(fields=state['pending']))
                from autojob.auth.verifications import CaptchaCoordinator
                cap=captcha_state(page,fixture)
                if cap.get('interactive') and not cap['completed']:
                    CaptchaCoordinator(settings.data_path).wait(page,guard,jid,job['title'],stop=lambda:item['end'].is_set() or stop(),manual_start=True,fixture=fixture)
                last_scan=0
            page.wait_for_timeout(200)
        return dict(state='PENDIENTE',reason='Intervención pospuesta, cancelada o pestaña cerrada; preparación conservada.')
    finally:
        verification.update(vid,reserved=False)
        with _lock:_sessions.pop(jid,None)
