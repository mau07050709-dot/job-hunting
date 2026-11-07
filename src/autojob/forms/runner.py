"""Navegación y relleno verificado sin envío; las pruebas usan capacidades locales."""
from pathlib import Path
from hashlib import sha256
from urllib.parse import urlsplit
import re,json
from autojob.forms.preparation import inspect
from autojob.forms.guard import PreparationGuard,origin,apply_link,continue_stage
from autojob.browser import BraveSession

READY={'CONFIRMADA','DERIVADA'}
def enrich(prep,entry):
 entry=dict(entry)
 if entry.get('kind') in {'radio','combobox','checkbox'} and entry.get('status')=='REVISAR FORMATO' and entry.get('prepared_status') in READY:entry['status']=entry['prepared_status']
 if entry.get('semantic')=='phone_country_code':
  profile=prep.profile_snapshot()['profile'];phone=profile['values'].get('phone')
  if phone and 'phone' in profile.get('manual',[]):
   import phonenumbers
   try:
    parsed=phonenumbers.parse(phone,None)
    if phonenumbers.is_valid_number(parsed):entry.update(answer='+'+str(parsed.country_code),status='DERIVADA',source='Prefijo del teléfono confirmado',reason='No se confunde con el país de residencia.')
   except phonenumbers.NumberParseException:pass
 if entry.get('semantic')=='experience' and entry.get('kind')=='number':
  from autojob.matching.engine import candidate
  from autojob.profile.experience import calculate_experience
  snap=prep.profile_snapshot();facts=candidate(snap['profile'],snap['cvs'])['buckets']['experience'];records=[f['record'] for f in facts if f.get('record')]
  category='programming' if re.search(r'program|software',entry['label'],re.I) else 'customer_service' if re.search(r'customer|cliente',entry['label'],re.I) else None
  calc=calculate_experience(records,category)
  if facts and all(f['confirmed'] for f in facts) and calc['status']=='exact':entry.update(answer=str(calc['minimum']['calendar_years']),status='DERIVADA',source='Períodos profesionales confirmados',reason='Años completos calculados; sin añadir proyectos académicos.')
 return entry
def truth(value):
 value=str(value).strip().casefold()
 if value in {'yes','sí','si','true'}:return True
 if value in {'no','false'}:return False
 return None

def fill_field(page,entry,guard,fixture=None,files=None):
 if entry.get('sensitive_identity'):
  import os
  if os.environ.get('PWDEBUG') not in {None,'','0'} or 'pw:' in os.environ.get('DEBUG',''):return dict(status='PENDIENTE',reason='No se introduce identidad con trazas de navegador habilitadas.')
  from autojob.auth.identity import IdentityStore
  from autojob.auth.permissions import Permissions
  data_path=getattr(guard,'identity_data_path',None)
  if data_path is None:return dict(status='PENDIENTE',reason='Identificación reservada; falta autorización del dato concreto.')
  identity=IdentityStore(data_path);summary=identity.summary();field=entry['identity_field']
  if not summary or not summary['confirmed'] or summary['revision']!=entry.get('identity_revision') or entry.get('status')=='DESCONOCIDA' or not Permissions(data_path).allowed(page.url,'IDENTIDAD',summary['revision']+':'+field,bool(fixture)):return dict(status='PENDIENTE',reason='Tipo, confirmación o permiso de identidad sin verificar.')
  try:secret=identity.reveal(True,summary['revision']) if field=='number' else None
  except ValueError:return dict(status='PENDIENTE',reason='La identificación cambió durante la preparación; revisa sus permisos.')
  try:
   value=secret.reveal() if secret else summary.get(field)
   safe=dict(entry,sensitive_identity=False,answer=value,status='CONFIRMADA')
   outcome=fill_field(page,safe,guard,fixture,files);outcome['reason']='Campo de identidad tratado con permiso específico; valor omitido del historial.';return outcome
  finally:
   if secret:secret.clear()
 if entry['kind']=='button':return dict(status='OMITIDO',reason='No se rellenan botones.')
 if entry['kind']=='file':
  if not fixture:return dict(status='PENDIENTE',reason='Los CV reales permanecen locales; adjuntos externos deshabilitados.')
  artifact=(files or {}).get(entry.get('document'))
  if not artifact:return dict(status='PENDIENTE',reason='Documento ficticio no disponible.')
  path=Path(artifact['path']).resolve();root=Path(fixture['artifact_root']).resolve()
  if not path.is_relative_to(root) or sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:return dict(status='BLOQUEADO',reason='Documento fuera de prueba o con hash inesperado.')
 elif entry.get('status') not in READY or entry.get('answer') is None:return dict(status='PENDIENTE',reason='Solo se utilizan respuestas confirmadas o derivadas inequívocas.')
 if entry.get('disabled'):return dict(status='PENDIENTE',reason='Control deshabilitado por el portal o la política de preparación.')
 if re.search(r'\b(?:i accept|i agree|i certify|i attest|acepto|aceptar|certifico|declaro|signature|firma|terms|terminos|privacy|privacidad)\b',entry.get('label','')+' '+entry.get('group',''),re.I):return dict(status='PENDIENTE',reason='Declaración o consentimiento requiere revisión humana.')
 frame=next((f for i,f in enumerate(page.frames) if i==entry.get('frame_index',0)),None)
 if frame is None:return dict(status='PENDIENTE',reason='El frame ya no existe; reanalizar.')
 try:
  if not fixture and origin(frame.url)!=origin(page.url):return dict(status='PENDIENTE',reason='Frame de otro origen no autorizado.')
 except ValueError:return dict(status='PENDIENTE',reason='Frame no verificable.')
 target=frame.locator(entry['selector'])
 if target.count()!=1:return dict(status='PENDIENTE',reason='Selector ausente o ambiguo; no se utilizan coordenadas.')
 kind=entry['kind'];answer=entry.get('answer');guard.freeze()
 try:
  if kind=='file':
   target.set_input_files(str(path));actual=target.evaluate('(e)=>e.files[0]?.name');ok=actual==path.name
  elif entry.get('checkbox_group'):
   answers={a.strip() for a in str(answer).split('|')};options=entry.get('options',[])
   if not answers or not answers<={o['label'] for o in options}:return dict(status='PENDIENTE',reason='Selección de casillas sin una respuesta confirmada válida.')
   actual=set()
   for option in options:
    box=frame.locator(option['selector'])
    if box.count()!=1:return dict(status='PENDIENTE',reason='Casilla ausente o ambigua.')
    box.set_checked(option['label'] in answers)
    if box.is_checked():actual.add(option['label'])
   ok=actual==answers
  elif kind in {'select','multiple'}:
   answers=[a.strip() for a in str(answer).split('|')] if kind=='multiple' else [str(answer)]
   options=target.locator('option').evaluate_all('(es)=>es.map(e=>({label:e.label,value:e.value,disabled:e.disabled}))')
   matched=[]
   for item in answers:
    matches=[o for o in options if not o['disabled'] and (item.casefold() in {o['label'].strip().casefold(),o['value'].casefold()} or entry.get('semantic')=='phone_country_code' and re.search(r'(?<!\d)\+?'+re.escape(item.lstrip('+'))+r'(?!\d)',o['label']))]
    if len(matches)!=1:return dict(status='PENDIENTE',reason='La respuesta no coincide con una opción única.')
    matched.append(matches[0]['value'])
   target.select_option(matched);actual=target.evaluate('(e)=>Array.from(e.selectedOptions).map(o=>o.value)');ok=set(actual)==set(matched)
  elif kind=='radio':
   value=(entry.get('label') or '').strip().casefold();expected=str(answer).strip().casefold();yes_no=truth(answer)
   selected=(truth(value)==yes_no) if yes_no is not None and truth(value) is not None else value==expected
   if not selected:return dict(status='NO SELECCIONADO',reason='Opción distinta de la respuesta confirmada.')
   if target.get_attribute('role')=='radio':
    if target.get_attribute('aria-checked')!='true':target.click()
    ok=target.get_attribute('aria-checked')=='true'
   else:target.check();ok=target.is_checked()
  elif kind=='checkbox':
   value=truth(answer)
   if value is None:return dict(status='PENDIENTE',reason='Se requiere un Sí/No confirmado; no se interpreta texto libre.')
   if target.get_attribute('role')=='checkbox':
    if (target.get_attribute('aria-checked')=='true')!=value:target.click()
    ok=(target.get_attribute('aria-checked')=='true')==value
   else:target.set_checked(value);ok=target.is_checked()==value
  elif kind=='combobox':
   # Solo opciones accesibles explícitas; nunca se escoge una coincidencia parcial.
   target.click();options=frame.get_by_role('option',name=str(answer),exact=True)
   if options.count()!=1:return dict(status='PENDIENTE',reason='Lista dinámica sin opción exacta única.')
   options.click();actual=target.input_value() if target.evaluate('(e)=>e.tagName==="INPUT"') else target.inner_text();ok=str(answer).strip().casefold()==actual.strip().casefold()
  else:
   existing=target.input_value() if target.evaluate('(e)=>"value" in e') else target.inner_text()
   if existing and existing.strip()!=str(answer).strip():return dict(status='PENDIENTE',reason='El portal ya tiene otro valor; no se sobrescribe silenciosamente.')
   target.fill(str(answer));actual=target.input_value() if target.evaluate('(e)=>"value" in e') else target.inner_text();ok=actual.strip()==str(answer).strip()
  if ok and kind!='file':ok=target.evaluate('(e)=>!e.willValidate||e.validity.valid')
  return dict(status='VERIFICADO' if ok else 'PENDIENTE',reason='Valor introducido y contrastado con el DOM y su validez.' if ok else 'El portal no conserva o no valida el valor esperado.')
 except Exception as exc:return dict(status='PENDIENTE',reason=type(exc).__name__+': no se pudo completar y verificar el control.')

def process(queue,row,settings,pause,stop,run_id,fixture=None,files=None):
 from autojob.live import historical
 from autojob.forms.submissions import SubmissionStore
 if historical(SubmissionStore(queue.data_path),row['job_id']):return dict(state='BLOQUEADA',blocks=[dict(type='COMPROBANTE NO VERIFICADO',evidence='Resultado final existente: no reabrir ni adjuntar CV.')],pending=[],last_action='Solo revisar comprobante.')
 prep=queue.preparation;id=row['job_id'];job=next((j for j in prep.compatibility.jobs.list() if j['id']==id),None)
 if not job:raise ValueError('La vacante ya no existe.')
 current=next((r for r in prep.compatibility.rows() if r['job']['id']==id),None);e=(current or {}).get('evaluation') or {};payload=dict(row['payload'],filled=[],pending=[],blocks=[],stages=[],interrupted=False,submission_enabled=False,attachments_external_enabled=False,stage=0)
 selected=(e.get('resume_selection') or {}).get('resume_id') or (e.get('resume_selection') or {}).get('provisional_resume_id')
 if selected and not fixture:
  try:prep.compatibility.library.original_path(selected,verify=True)
  except ValueError:return dict(payload,state='BLOQUEADA',blocks=[dict(type='INTEGRIDAD DEL CV',evidence='Archivo ausente o hash diferente; no se transmite.')],last_action='Documento requiere revisión.')
 if not fixture and (e.get('eligibility')=='INCOMPATIBLE' or job.get('geography')=='INCOMPATIBLE' or e.get('availability')=='CERRADA' or job.get('availability')=='CERRADA'):
  return dict(payload,state='BLOQUEADA',blocks=[dict(type='ELEGIBILIDAD O VIGENCIA',evidence='Vacante incompatible o cerrada; no se abre para rellenar.')],last_action='Excluida antes de acciones externas.')
 allowed=False
 with BraveSession(settings) as browser:
  guard=PreparationGuard(browser,fixture['origin'] if fixture else None);guard.identity_data_path=queue.data_path;guard.defer_interventions=getattr(queue,'defer_interventions',False);page=guard.page(row['url']);visited={page.url}
  for _ in range(3):
   try:page.wait_for_function("document.querySelector('input[type=file],input[type=email]') || Array.from(document.querySelectorAll('a[href]')).some(a=>/apply|postular/i.test(a.innerText))",timeout=6000)
   except Exception:pass
   document=inspect(page,max_frames=12)
   if not any(o['type'] in {'SIN FORMULARIO','FORMULARIO NO IDENTIFICADO COMO POSTULACIÓN'} for o in document['obstacles']):break
   link=apply_link(page)
   if not link or link in visited:break
   visited.add(link);guard.navigate(page,link)
  if fixture:
   if origin(page.url)!=fixture['origin'] or page.locator('meta[name="autojob-fixture"]').get_attribute('content')!=fixture['token']:raise ValueError('No es un entorno controlado autorizado.')
   allowed=True
  else:allowed=bool(current and not current['stale'] and e.get('eligibility')=='COMPATIBLE' and e.get('geography')=='CONFIRMADO' and e.get('availability')=='ABIERTA' and queue.site_allowed(page.url))
  for stage in range(1,9):
   if pause() or stop():return dict(payload,interrupted=True,last_action='Interrumpida de forma segura.')
   document=inspect(page,max_frames=12)
   if not fixture and any(o['type']=='CAPTCHA' for o in document['obstacles']):
    from autojob.auth.verifications import captcha_state
    try:completed=captcha_state(page)['completed']
    except Exception:completed=False
    if completed:document['obstacles']=[o for o in document['obstacles'] if o['type']!='CAPTCHA']
   preview=prep.prepare(document,job);preview['execution_mode']='CONTROLLED LAB' if fixture else 'AUTHORIZED DOM' if allowed else 'READ ONLY';preview['external_fill_enabled']=bool(allowed and not fixture);payload.update(mode=preview['execution_mode'],stage=stage,last_url=page.url,cv=preview and dict(e.get('resume_selection') or {},cv_id=preview.get('cv_id'),cv_title=preview.get('cv_title')),preview=preview)
   # Se comprueba integridad incluso si no habrá adjuntos externos.
   if preview.get('cv_id'):prep.compatibility.library.original_path(preview['cv_id'],verify=True)
   payload['stages'].append(dict(stage=stage,document=document,preview=preview,outcomes=[]))
   if not fixture:
    from autojob.auth.detection import inspect_auth
    from autojob.auth.service import Accounts
    try:auth=inspect_auth(page)
    except Exception:auth=dict(kind='DESCONOCIDO')
    if auth['kind'] in {'REGISTRO','LOGIN','RECUPERACIÓN','VERIFICACIÓN'} or any(b in {'CUENTA BLOQUEADA','CREDENCIALES INCORRECTAS','SESIÓN EXPIRADA'} for b in auth.get('blocks',[])):
     requirement=Accounts(queue.data_path).require_auth(id,auth);payload['authentication']=requirement
     from autojob.auth.verifications import record_obstacle
     kind='CAPTCHA PENDIENTE' if 'CAPTCHA' in auth.get('blocks',[]) else 'VERIFICACIÓN DE CORREO PENDIENTE' if 'CORREO' in auth.get('blocks',[]) else 'CUENTA BLOQUEADA' if 'CUENTA BLOQUEADA' in auth.get('blocks',[]) else 'REQUIERE REGISTRO' if requirement['task']=='PREPARAR REGISTRO' else 'REQUIERE LOGIN'
     payload['verification_status']=kind;record_obstacle(queue.data_path,id,kind,page.url,job['company']+' · '+job['title'])
     return dict(payload,state='PENDIENTE',pending=[dict(field=f['label'],reason='Autenticación pendiente.') for f in preview['entries']],blocks=[dict(type='AUTENTICACIÓN',evidence=requirement['task'])]+document['obstacles'],last_action='Tarea de autenticación guardada; se comprueba el permiso específico antes de autenticar. Se continúa con otra vacante.')
   if not fixture and allowed and document['obstacles'] and all(o['type'] in {'CAPTCHA','VIDEO','VOZ'} for o in document['obstacles']):
    from autojob.live import wait_prepared
    result=wait_prepared(settings,browser,page,guard,job,stop=stop)
    fresh=next((r for r in queue.list() if r['job_id']==id),{}).get('payload',payload)
    return dict(fresh,state='PENDIENTE',last_action=result.get('reason','Preparación conservada; revisar la continuación.'))
   if not fixture and any(o['type']=='CAPTCHA' for o in document['obstacles']):
    from autojob.auth.verifications import CaptchaCoordinator
    queue.update(id,'ANALIZANDO','Respuestas preparadas guardadas antes de la intervención CAPTCHA.',payload,stage,run_id)
    if hasattr(guard,'context') and CaptchaCoordinator(queue.data_path).wait(page,guard,id,job['company']+' · '+job['title'],stop,pause):
     document=inspect(page,max_frames=12);document['obstacles']=[o for o in document['obstacles'] if o['type']!='CAPTCHA'];preview=prep.prepare(document,job)
     payload.update(verification_status='LISTA PARA CONTINUAR',preview=preview);payload['stages'][-1].update(document=document,preview=preview)
     queue.update(id,'ANALIZANDO','Verificación completada; continuar en la misma pestaña sin perder el token del portal.',payload,stage,run_id)
    else:
     return dict(payload,state='BLOQUEADA',verification_status='CAPTCHA PENDIENTE',pending=[dict(field=f['label'],reason='CAPTCHA pendiente.') for f in preview['entries']],blocks=document['obstacles'],last_action='Intervención pendiente; la reserva se libera y la cola continúa.')
   if document['obstacles']:
    return dict(payload,state='BLOQUEADA',pending=[dict(field=f['label'],reason='Campo sin completar por obstáculo del portal.',required=f.get('required',False)) for f in preview['entries']],blocks=document['obstacles'],last_action='Obstáculo detectado; navegador liberado sin evadirlo.')
   if not allowed:
    payload['pending']=[dict(label=f['label'],reason='Inspección externa: faltan elegibilidad, vigencia o autorización del origen.') for f in preview['entries']]
    return dict(payload,state='REQUIERE REVISIÓN',blocks=preview['blocks']+[dict(type='SOLO LECTURA',evidence='No hay autorización vigente y elegibilidad confirmada para rellenar este origen.')],last_action='Formulario localizado y respuestas preparadas localmente; ningún campo externo modificado.')
   critical=[b for b in preview['blocks'] if b['type'] in {'VACANTE POR VERIFICAR','CV PROVISIONAL','CV INCOMPATIBLE','DOCUMENTO NO DISPONIBLE','VACANTE INCOMPATIBLE','EVALUACIÓN OBSOLETA'}]
   if critical and not fixture:return dict(payload,state='REQUIERE REVISIÓN',blocks=critical,last_action='Verificar identidad de vacante, documentos y evaluación antes de introducir texto.')
   queue.update(id,'RELLENANDO','Etapa '+str(stage)+'; envío bloqueado técnicamente.',payload,stage,run_id)
   for entry in preview['entries']:
    if pause() or stop():return dict(payload,interrupted=True,last_action='Interrumpida entre campos; se conservan los verificados.')
    if not fixture and not queue.site_allowed(page.url):return dict(payload,state='PENDIENTE',blocks=[dict(type='AUTORIZACIÓN CAMBIADA',evidence='Permiso revocado o datos modificados; detener y revisar.')],last_action='Se detuvo el relleno antes del siguiente campo.')
    entry=enrich(prep,entry)
    outcome=fill_field(page,entry,guard,fixture,files)
    result=dict(stage=stage,field=entry['label'],selector=entry['selector'],source=entry.get('source'),answer=entry.get('answer'),**outcome)
    payload['stages'][-1]['outcomes'].append(result)
    if outcome['status']=='VERIFICADO':payload['filled'].append(result)
    elif outcome['status']!='NO SELECCIONADO':payload['pending'].append(dict(result,required=entry.get('required',False)))
    queue.update(id,'RELLENANDO','Comprobando campo de etapa '+str(stage),payload,stage,run_id)
   required=[r for r in payload['pending'] if r.get('stage')==stage and r.get('required')]
   radio_groups={f.get('name') or f.get('group') for f in preview['entries'] if f['kind']=='radio' and f.get('required')}
   for group in radio_groups:
    options=[f for f in preview['entries'] if f['kind']=='radio' and (f.get('name') or f.get('group'))==group]
    if not any(page.frames[f.get('frame_index',0)].locator(f['selector']).evaluate('(e)=>e.checked===true||e.getAttribute("aria-checked")==="true"') for f in options):required.append(dict(field=group or 'Selección única obligatoria'))
   if required:return dict(payload,state='PENDIENTE',blocks=[dict(type='DATO O DOCUMENTO OBLIGATORIO',evidence=r['field']) for r in required],last_action='Etapa conservada; faltan campos obligatorios o documentos.')
   before=page.url+'|'+json.dumps([(f['selector'],f['label']) for f in document['fields']])
   if fixture and page.url in fixture.get('next_urls',{}):guard.expected=fixture['next_urls'][page.url];guard.nav_budget=1
   advanced,reason=continue_stage(page,guard)
   if not advanced:
    ambiguous=any(f.get('action')=='CONTINUACIÓN' for f in document['fields'])
    return dict(payload,state='PREPARADA' if not ambiguous and any(f.get('action')=='ENVÍO FINAL' for f in document['fields']) else 'REQUIERE REVISIÓN',last_action='Detenida antes del envío final. '+reason,blocked_requests=guard.blocked,prepared_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
   after_doc=inspect(page,max_frames=12);after=page.url+'|'+json.dumps([(f['selector'],f['label']) for f in after_doc['fields']])
   if after==before:return dict(payload,state='REQUIERE REVISIÓN',blocks=[dict(type='ETAPA SIN CAMBIO',evidence='La continuación no produjo una etapa nueva; no se repite indefinidamente.')],last_action='Revisar botón o portal; transmisiones bloqueadas.')
  return dict(payload,state='PENDIENTE',blocks=[dict(type='LÍMITE DE ETAPAS',evidence='Máximo ocho etapas por intento.')],last_action='Límite de navegación alcanzado sin envío.')
