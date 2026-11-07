"""Inspección pública de solo lectura. Sin operaciones de relleno externas ni envío."""
from contextlib import closing, contextmanager
from threading import local
from dataclasses import asdict
from datetime import datetime,timezone,date
from urllib.parse import urlsplit
from uuid import uuid4
import json,re
from autojob.profile.application_data import ApplicationData,BRIDGE
from autojob.profile.answers import resolve_question,AnswerBank,norm
from autojob.profile.calculations import age
from autojob.profile.store import today
from autojob.matching.service import Compatibility

SCAN_JS=r'''() => {
 const visible=e=>e.getClientRects().length>0 && getComputedStyle(e).visibility!=='hidden';
 const selector=e=>{if(e.id&&document.querySelectorAll('#'+CSS.escape(e.id)).length===1)return '#'+CSS.escape(e.id);let p=[];while(e&&e.nodeType===1&&e.tagName!=='HTML'){let s=e.tagName.toLowerCase();let same=Array.from(e.parentElement?.children||[]).filter(x=>x.tagName===e.tagName);if(same.length>1)s+=':nth-of-type('+(same.indexOf(e)+1)+')';p.unshift(s);e=e.parentElement;}return p.join(' > ');};
 const label=e=>{let labels=e.labels?Array.from(e.labels).map(l=>l.innerText).join(' '):'';let aria=(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ');return (aria||e.getAttribute('aria-label')||labels||e.getAttribute('placeholder')||e.getAttribute('name')||e.id||'Sin etiqueta').trim();};
 let controls=Array.from(document.querySelectorAll('input,select,textarea,button,[role="combobox"],[role="checkbox"],[role="radio"],[contenteditable="true"]')).filter(e=>(visible(e)||e.type==='file')&&!['hidden','password'].includes(e.type));
 return {title:document.title,fields:controls.slice(0,200).map((e,i)=>({id:String(i),selector:selector(e),label:label(e),tag:e.tagName.toLowerCase(),kind:e.tagName==='SELECT'?(e.multiple?'multiple':'select'):e.tagName==='TEXTAREA'?'textarea':e.getAttribute('role')||e.type||'text',required:e.required||e.getAttribute('aria-required')==='true',disabled:e.disabled||e.getAttribute('aria-disabled')==='true',options:e.tagName==='SELECT'?Array.from(e.options).map(o=>({label:o.text,value:o.value})):[],group:e.closest('fieldset')?.querySelector('legend')?.textContent||'',name:e.name||'',aria_label:e.getAttribute('aria-label')||'',aria_labelledby_text:(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' '),data_ui:e.getAttribute('data-ui')||'',accept:e.accept||'',autocomplete:e.autocomplete||'',button_text:['BUTTON'].includes(e.tagName)||['submit','button'].includes(e.type)?(e.innerText||e.value||''):''})),text:document.body?.innerText?.slice(0,150000)||'',frames:Array.from(document.querySelectorAll('iframe')).map(e=>({title:e.title,src:e.src})).concat(Array.from(document.querySelectorAll('script[src*="captcha"],[data-sitekey]')).map(e=>({title:'CAPTCHA marker',src:e.src||''}))),password:!!document.querySelector('input[type=password]')};
}'''

def obstacles(text,frames=(),password=False):
 q=norm(text+' '+json.dumps(list(frames)))
 patterns={'CAPTCHA':r'captcha|verify you are human|verifica que eres humano','VIDEO':r'video (?:interview|recording|personal)|record (?:a |your )?video|grabar (?:un )?video|video personal','VOZ':r'voice recording|audio recording|grabacion de voz|record your voice','IDENTIDAD':r'identity verification|upload.{0,30}(?:passport|national id)|verificacion de identidad','FIRMA LEGAL':r'electronic signature|legal signature|firma (?:legal|electronica)|accept.{0,25}(?:terms|agreement)|acept[oa].{0,25}(?:terminos|contrato)','ERROR DEL PORTAL':r'access denied|temporarily unavailable|acceso denegado|service unavailable'}
 result=[dict(type=k,evidence=m.group(0)) for k,p in patterns.items() if (m:=re.search(p,q))]
 if password:result.append(dict(type='AUTENTICACIÓN',evidence='El formulario requiere contraseña; no se crean cuentas.'))
 return result

def inspect(page,max_frames=None):
 document=dict(url=page.url,title='',fields=[],obstacles=[],stages=[],inspected_at=datetime.now(timezone.utc).isoformat())
 for frame_index,frame in enumerate(page.frames):
  if max_frames is not None and frame_index>=max_frames:
   document['obstacles'].append(dict(type='LÍMITE DE FRAMES',evidence='Demasiados documentos embebidos; inspección acotada para revisión.'));break
  if max_frames is not None and frame_index and frame.url in {'about:blank',''}:continue
  if re.search(r'recaptcha|hcaptcha|captcha',frame.url,re.I):continue
  try:data=frame.evaluate(SCAN_JS)
  except Exception:document['obstacles'].append(dict(type='FRAME NO DISPONIBLE',evidence='No se pudo leer un documento embebido.'));continue
  if frame_index==0:document['title']=data['title']
  document['obstacles'].extend(obstacles(data['text'],data['frames'],data['password']))
  for field in data['fields']:
   field.update(id=str(frame_index)+':'+field['id'],frame_index=frame_index,frame_url=frame.url)
   q=norm(field['label']+' '+field['group']+' '+field['name']+' '+field['selector'])
   if re.search(r'country|pais',norm(field['label'])) and re.search(r'phone|telefono',norm(field['group'])):field['semantic']='phone_country_code'
   if field['kind'] in {'submit','button','reset'} or field['tag']=='button' and field['kind'] not in {'checkbox','radio','combobox'}:
    text=norm(field['button_text'] or field['label']);field['action']='ENVÍO FINAL' if re.search(r'submit|send application|apply now|enviar|postular|candidatura',text) else 'CONTINUACIÓN' if re.search(r'next|continue|siguiente|continuar',text) else 'GUARDADO' if re.search(r'save|guardar',text) else 'OTRA ACCIÓN';field['kind']='button';document['stages'].append(dict(label=field['button_text'],action=field['action']))
   elif field['kind']=='file':
    from autojob.forms.documents import document_kind
    field['document']=document_kind(field)
   elif re.search(r'salary|salario|salarial|sueldo',q):field['semantic']='salary'
   elif re.search(r'years.{0,20}experience|anos.{0,20}experiencia',q):field['semantic']='experience'
   document['fields'].append(field)
 from autojob.forms.greenhouse import enrich_page
 document=enrich_page(document)
 from autojob.forms.fiveca import enrich_page as enrich_fiveca
 document=enrich_fiveca(document)
 from autojob.forms.doola import enrich_page as enrich_doola
 document=enrich_doola(document,page)
 if not document['fields']:document['obstacles'].append(dict(type='SIN FORMULARIO',evidence='No se detectaron controles públicos visibles; puede requerir navegación manual o autenticación.'))
 elif not any(f.get('document')=='cv' for f in document['fields']) and not (any(re.search(r'full name|first name|nombre',norm(f['label'])) for f in document['fields']) and any(re.search(r'email|correo',norm(f['label'])) for f in document['fields'])):document['obstacles'].append(dict(type='FORMULARIO NO IDENTIFICADO COMO POSTULACIÓN',evidence='Hay controles, pero pueden corresponder a búsqueda o a otra función del portal.'))
 return document

QUESTION_KEYS={
 'first_name':['first name','given name','nombre de pila','nombres'], 'last_name':['last name','surname','apellidos'],
 'birth_date':['date of birth','birth date','fecha de nacimiento'],'nationality':['nationality','nacionalidad'],'country':['country of residence','pais de residencia'],'province':['province','provincia'],'canton':['canton'],'address':['street address','home address','direccion'],'postal_code':['postal code','zip code','codigo postal'],'whatsapp':['whatsapp'],'linkedin':['linkedin'],'professional_links':['portfolio','professional links','portafolio'],
 'own_computer':['own computer','computadora propia','equipo propio'],'computer_type':['desktop or laptop','tipo de computadora'],'operating_system':['operating system','sistema operativo'],'ram_gb':['ram','memoria ram'],'processor':['processor','procesador'],'webcam':['webcam','camara web'],'microphone':['microphone','microfono'],'headset':['headset','audifonos'],'stable_internet':['stable internet','internet estable'],'download_mbps':['download speed','velocidad de descarga'],'upload_mbps':['upload speed','velocidad de subida'],'connection_type':['connection type','tipo de conexion'],'private_workspace':['private workspace','espacio privado'],'backup_power':['backup power','respaldo electrico'],'alternative_connection':['alternative connection','conexion alternativa'],'other_work_permits':['other work permits','otros permisos laborales'],
 'start_date':['start date','when can you start','fecha de incorporacion','cuando puedes comenzar'],'immediate_start':['immediately available','disponibilidad inmediata'],'weekly_hours':['weekly hours','hours per week','horas semanales'],'weekends':['weekends','fines de semana'],'nights':['night shift','horario nocturno'],'preferred_schedule':['preferred schedule','horario preferido'],'accepted_shifts':['accepted shifts','turnos aceptados'],'timezone':['time zone','timezone','zona horaria'],'accepted_contracts':['contractor','contract type','tipo de contrato'],'full_time':['full time','tiempo completo'],'part_time':['part time','medio tiempo']}

class Preparation:
 def __init__(self,data_path):
  self._reads=local()
  self.data=ApplicationData(data_path);self.compatibility=Compatibility(data_path);self.bank=AnswerBank(data_path);self.db=self.data.db
  with closing(self.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS form_preparations(id TEXT PRIMARY KEY,job_id TEXT,url TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL)')
 def resolve(self,question,context=None):
  from autojob.forms.answers9b import ScopedAnswers,restricted
  existing=self._resolve_existing(question,context)
  from autojob.profile.answers import identify
  profile=self.data.profile_state();key=identify(question)
  exact={'university':'university','universidad':'university','degree':'degree','carrera':'degree','academic status':'academic_status','estado academico':'academic_status','certifications':'certifications','certificaciones':'certifications','qualifications':'qualifications','titulaciones':'qualifications','previous companies':'companies','empresas anteriores':'companies','positions held':'positions','puestos desempenados':'positions','responsibilities':'responsibilities','responsabilidades':'responsibilities','work dates':'dates','fechas laborales':'dates','availability to start':'start_availability'}
  key=exact.get(norm(question),key)
  if key in profile.get('manual',[]) and key in {'education_records','experience_records','skills','soft_skills','languages','programming_languages','schedule','university','degree','academic_status','certifications','qualifications','companies','positions','responsibilities','dates','start_availability'} and existing.get('status') in {'SUGERIDA','DESCONOCIDA'}:
   value=profile['values'].get(key)
   if value not in (None,'',[]):
    if existing.get('answer') is not None:value=existing['answer']
    existing=dict(answer='; '.join(value) if isinstance(value,list) else str(value),status='CONFIRMADA',source='Mis datos · Perfil confirmado',reason='Dato declarado y confirmado; se conserva el texto original.',automatic=False)

  if restricted(question) or existing.get('status') in {'CONFLICTO','BLOQUEADA','SENSIBLE'}:return existing
  bank=ScopedAnswers(self.data.data_path);saved=bank.resolve(question,context or {})
  if saved is None:
   from autojob.profile.semantic import SemanticAnswers
   saved=SemanticAnswers(self.data.data_path).resolve(question,context or {})
  if saved is None and question==question.strip():saved=bank.resolve(' '+question,context or {})
  if saved and existing.get('status') in {'CONFIRMADA','DERIVADA'}:
   from autojob.profile.contact import whatsapp_intent,same_phone
   same_contact=whatsapp_intent(question)=='number' and same_phone(saved['answer'],existing['answer'])
   if not same_contact and norm(str(saved['answer']))!=norm(str(existing['answer'])):return dict(answer=None,status='CONFLICTO',source='Mis datos / Respuestas aprobadas',reason='Resuelve la contradicción entre respuestas confirmadas.',automatic=False)
   return existing
  return saved or existing
 def _resolve_existing(self,question,context=None):
  from autojob.auth.identity import question_kind,IdentityStore
  if question_kind(question):return IdentityStore(self.data.data_path).resolve(question)
  context=context or {};q=norm(question);language=context.get('language') or ('en' if re.search(r'\b(?:your|what|do|are|you|date|name)\b',q) else 'es')
  def out(answer=None,state='DESCONOCIDA',source='Sin dato confirmado',reason='Requiere revisión.'):return dict(answer=answer,status=state,source=source,reason=reason,automatic=False)
  from autojob.profile.contact import whatsapp_intent,canonical_phone
  wa=whatsapp_intent(question)
  if wa:
   if wa in {'consent','preference','unknown'}:return out(reason='Pregunta de consentimiento, preferencia o uso: no se deduce de disponer de un número de WhatsApp.')
   if 'whatsapp' in self.data.conflicts():return out(state='CONFLICTO',source='WhatsApp / fuentes existentes',reason='Los números de WhatsApp son distintos: confirma cuál corresponde.')
   value,status=self.data.value('whatsapp')
   number=canonical_phone(value)
   if status!='CONFIRMADA' or not number:return out(reason='Falta un número de WhatsApp confirmado; no se utiliza el teléfono como sustituto.')
   return out(number if wa=='number' else 'Yes','CONFIRMADA' if wa=='number' else 'DERIVADA','Mi perfil / WhatsApp confirmado','Número internacional confirmado; no constituye consentimiento de contacto.')
  if re.search(r'^(?:are|do|can|have|how).{0,100}(?:phone call|calls|calling)',q):return out(reason='Pregunta sobre capacidad de atender llamadas; no solicita el número telefónico.')
  # Las declaraciones legales siempre requieren revisión específica; los datos pueden mostrarse sin aceptar acuerdos.
  if re.search(r'signature|firma|accept.{0,20}(?:terms|agreement)|acept.{0,20}(?:terminos|contrato)|criminal|disability',q):return out(state='BLOQUEADA',reason='Declaración legal o sensible: intervención humana.')
  if re.search(r'work authorization|authorized to work|permiso de trabajo|autorizacion laboral',q):
   if 'costa rica' not in q:return out(reason='Se necesita autorización confirmada para el país específico; no se extrapola Costa Rica.')
   value,status=self.data.value('work_authorization_cr');return out(('Yes' if value else 'No') if value is not None else None,status,'Datos para postulaciones','Declaración específica para Costa Rica; no se acepta ningún acuerdo.')
  if re.search(r'worked.{0,20}(?:company|before)|previously employed|trabajado.{0,25}empresa|anteriormente',q) and not context.get('company'):return out(reason='Falta identificar la empresa.')
  faqs=[f for f in self.data.faqs() if norm(f['question'])==q and f['company'] in {'',context.get('company','').strip().casefold()}]
  company_specific=any(x in q for x in ('worked','anteriormente','esta empresa','this company','herramienta','tool'))
  if company_specific:faqs=[f for f in faqs if f['company'] and f['company']==context.get('company','').strip().casefold()]
  if len(faqs)==1 and faqs[0]['confirmed']:
   answer=faqs[0]['answer']
   if norm(answer or '') in {'si','yes','no'}:answer=('Yes' if norm(answer) in {'si','yes'} else 'No') if language=='en' else ('Sí' if norm(answer) in {'si','yes'} else 'No')
   return out(answer,'CONFIRMADA','Respuesta específica aprobada','Confirmada para este contexto.')
  if re.search(r'\bworked\b|previously employed|\btrabajado\b|anteriormente',q):return out(reason='No existe una respuesta confirmada específica para esta empresa.')
  if re.search(r'salary|salario|salarial|sueldo',q):
   periods=[p for p,pat in [('month',r'month|mensual'),('year',r'annual|anual|year'),('hour',r'hour|hora')] if re.search(pat,q)]
   if len(periods)!=1:return out(reason='Falta un período salarial inequívoco.')
   currencies=re.findall(r'\b(?:USD|CRC|EUR|GBP|CAD)\b',question.upper())
   if len(set(currencies))>1:return out(reason='La moneda es ambigua.')
   prefix='contractor' if 'contractor' in q else 'part' if re.search(r'part.time|medio tiempo',q) else 'full' if re.search(r'full.time|tiempo completo',q) else 'main'
   amount,status,reason=self.data.salary(prefix,periods[0],currencies[0] if currencies else None,bound='expected')
   if amount is None:
    minimum,s1,r1=self.data.salary(prefix,periods[0],currencies[0] if currencies else None,bound='min');maximum,s2,r2=self.data.salary(prefix,periods[0],currencies[0] if currencies else None,bound='max')
    if minimum and maximum and r1==r2:amount,status,reason=minimum+'–'+maximum,'DERIVADA','Rango confirmado: '+r1+'; un campo numérico requiere elegir una expectativa exacta.'
   if re.search(r'net|neto|gross|bruto',q):
    basis,bstate=self.data.value(prefix+'_basis');expected='net' if re.search(r'net|neto',q) else 'gross'
    if bstate!='CONFIRMADA' or basis not in ({'net','neto'} if expected=='net' else {'gross','bruto'}):return out(reason='No está confirmado el salario bruto/neto solicitado.')
   return out(amount,status,'Rango salarial confirmado / conversión local',reason)
  if re.search(r'\bage\b|\bedad\b',q):
   birth,status=self.data.value('birth_date')
   return out(str(age(date.fromisoformat(birth),today())),'DERIVADA','Fecha confirmada','Edad a la fecha actual.') if birth and status=='CONFIRMADA' else out(reason='Falta fecha de nacimiento confirmada.')
  if re.search(r'availability|disponibilidad|weekends|fines de semana|weekly hours|hours per week|horas semanales|night|nocturn|full.time|part.time|turnos|preferred schedule|when can you start',q):
   keys=['remote_conditions'] if context.get('modality')=='remote' else ['onsite_conditions'] if context.get('modality') in {'onsite','hybrid'} else ['remote_conditions','onsite_conditions']
   notes=[self.data.value(key)[0] for key in keys if self.data.value(key)[0]]
   if notes:return out(state='REQUIERE REVISIÓN',source='Condiciones por modalidad',reason='Contrasta la disponibilidad general con estas condiciones específicas: '+' | '.join(notes))
  matches=[(len(term),key) for key,terms in QUESTION_KEYS.items() for term in terms if re.search(r'(?<!\w)'+re.escape(norm(term))+r'(?!\w)',q)]
  if matches:
   if len({key for _,key in matches})>1:return out(reason='Pregunta compuesta: revisa todas las condiciones, no se responde usando solo una de ellas.')
   key=max(matches)[1]
   if key=='own_computer' and re.search(r'video|audio|camera|microphone|webcam|processor|ram|windows',q):
    if re.search(r'processor|ram|windows|memory|cpu',q):return out(reason='Se requieren características específicas confirmadas, no solo disponer de computadora.')
    required=['own_computer']+(['webcam'] if re.search(r'video|camera|webcam',q) else [])+(['microphone'] if re.search(r'audio|microphone',q) else [])
    facts=[self.data.value(k) for k in required]
    if all(status=='CONFIRMADA' and isinstance(value,bool) for value,status in facts):return out('Yes' if all(value for value,status in facts) else 'No','DERIVADA','Equipo confirmado en Mis datos','Se contrastan todas las capacidades solicitadas; no se inventan especificaciones.')
    return out(reason='Falta confirmar alguna capacidad específica del equipo.')
   if key in self.data.conflicts():return out(state='CONFLICTO',source='Mi perfil / Datos para postulaciones',reason='Resuelve la diferencia antes de usar esta respuesta.')
   value,status=self.data.value(key)
   profile=self.data.profile_state();linked=BRIDGE.get(key)
   if status=='SUGERIDA' and linked in profile.get('manual',[]) and str(value)==str(profile['values'].get(linked)):status='CONFIRMADA'
   if key in {'first_name','last_name'} and status=='SUGERIDA' and 'full_name' in profile.get('manual',[]):
    first=self.data.value('first_name')[0];last=self.data.value('last_name')[0]
    full=norm(profile['values'].get('full_name') or '')
    if first and last and norm(str(first)+' '+str(last))==full:status='DERIVADA'
    elif first and last and full.endswith(' '+norm(str(last))):
     # Prioridad al nombre corregido en el perfil. Solo dividir usando apellidos ya presentes y coincidentes.
     given=full[:-len(norm(str(last)))].strip()
     if given and norm(str(first)).startswith(given+' '):
      value=(str(profile['values']['full_name'])[:len(given)] if key=='first_name' else str(profile['values']['full_name'])[-len(norm(str(last))):]);status='DERIVADA'


   if value is None:return out()
   answer=('Yes' if value else 'No') if isinstance(value,bool) and language=='en' else ('Sí' if value else 'No') if isinstance(value,bool) else str(value)
   return out(answer,status,'Datos para postulaciones / Mi perfil','Dato confirmado.' if status=='CONFIRMADA' else 'Dato derivado de información confirmada y componentes existentes coincidentes.' if status=='DERIVADA' else 'Confirma antes de utilizarlo.')
  snap=self.profile_snapshot();profile=snap['profile'];cv=next((c for c in snap['cvs'] if c['id']==context.get('cv_id')),None)
  ctx=dict(context,language=language,employment_records=(cv or {}).get('structure',{}).get('experience',[]),employment_verified=bool(cv and cv['reviewed']),academic_projects=(cv or {}).get('structure',{}).get('academic_projects',[]))
  class ExistingBank:
   database=self.bank.database
   def match(inner,question,language,state):return self.bank.match(question,language,{k:v for k,v in state.items() if not k.startswith('_')})
  resolution=resolve_question(question,ctx,profile,ExistingBank());return dict(answer=resolution.answer,status=resolution.category,source=resolution.source,reason=resolution.reason,automatic=False)
 @contextmanager
 def read_snapshot(self):
  if getattr(self._reads,'profile',None) is not None:
   yield
   return
  self._reads.profile=self.compatibility.snapshot()
  try:
   with self.data.read_snapshot():yield
  finally:self._reads.profile=None
 def profile_snapshot(self):
  return getattr(self._reads,'profile',None) or self.compatibility.snapshot()
 def prepare(self,document,job=None,cv_id=None,letter_id=None,cv_approved=False):
  with self.read_snapshot():
   return self._prepare(document,job,cv_id,letter_id,cv_approved)
 def _prepare(self,document,job,cv_id,letter_id,cv_approved):
  job=job or {};current=next(iter(self.compatibility.rows(job['id'],self.profile_snapshot())),None) if job.get('id') else None;e=(current or {}).get('evaluation') or {};selection=e.get('resume_selection') or {};cv_id=cv_id or selection.get('resume_id') or selection.get('provisional_resume_id');cv=None;blocks=list(document.get('obstacles',[]));entries=[]
  if not current:blocks.append(dict(type='VACANTE SIN EVALUACIÓN',evidence='La inspección no acredita la identidad ni la elegibilidad de una vacante.'))
  if e.get('eligibility')=='INCOMPATIBLE':blocks.append(dict(type='VACANTE INCOMPATIBLE',evidence='La evaluación identifica requisitos o geografía incompatibles.'))
  if e.get('geography') in {'POSIBLE','DESCONOCIDO'}:blocks.append(dict(type='GEOGRAFÍA POR VERIFICAR',evidence='La preparación no confirma que puedas trabajar desde Costa Rica.'))
  if e.get('availability')!='ABIERTA':blocks.append(dict(type='VIGENCIA POR VERIFICAR',evidence='No se ha confirmado una oferta abierta.'))
  if current and current['stale']:blocks.append(dict(type='EVALUACIÓN OBSOLETA',evidence='Reevalúa la compatibilidad.'))
  if job and document.get('title') and not any(norm(value) in norm(document['title']) for value in (job.get('company',''),job.get('title','')) if value):blocks.append(dict(type='VACANTE POR VERIFICAR',evidence='El título de la página no identifica inequívocamente la empresa o puesto seleccionados.'))
  if cv_id:
   try:cv=self.compatibility.library.get(cv_id);self.compatibility.library.original_path(cv_id)
   except ValueError:blocks.append(dict(type='DOCUMENTO NO DISPONIBLE',evidence='No se encontró el CV seleccionado.'))
  if cv and not cv['reviewed'] and not cv_approved:blocks.append(dict(type='CV PROVISIONAL',evidence='Revisa el documento antes de aprobar su uso en un entorno de prueba controlado.'))
  if cv and (selection.get('language') not in {None,'unknown',cv['language']} or selection.get('specialty') not in {None,'auto','unknown',cv['specialty']} and cv['specialty']!='mixed'):blocks.append(dict(type='CV INCOMPATIBLE',evidence='Idioma o categoría no coinciden con la evaluación.'))
  letter=None
  if letter_id:
   with closing(self.db.connect()) as db:
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='cover_letters'").fetchone():letter=db.execute('SELECT body FROM cover_letters WHERE id=?',(letter_id,)).fetchone()
   if not letter:blocks.append(dict(type='DOCUMENTO NO DISPONIBLE',evidence='La carta seleccionada no está disponible.'));letter_id=None
  context=dict(job_id=job.get('id'),company=job.get('company',''),position=job.get('title',''),cv_id=cv_id,job_category=cv['specialty'] if cv else None,modality=job.get('modality'))
  radio_resolutions={}
  for field in document.get('fields',[]):
   if field['kind']=='button':continue
   radio_key=(field.get('name'),field.get('group'),field.get('semantic')) if field['kind']=='radio' and field.get('name') and (field.get('group') or str(field.get('semantic','')).startswith('doola_')) and field.get('semantic')!='demographic_decline' else None
   if radio_key is not None and radio_key in radio_resolutions:resolved=dict(radio_resolutions[radio_key])
   elif field['kind']=='file':
    document_kind=field.get('document','unknown')
    if document_kind=='unknown':
     from autojob.forms.documents import document_kind as classify_document
     document_kind=classify_document(field)
    answer=cv_id if document_kind=='cv' and cv else letter_id if document_kind=='letter' else None
    resolved=dict(answer=answer,status='DOCUMENTO LOCAL' if answer else 'DESCONOCIDA',source='Gestor de CV / Cartas',reason='Solo vista previa: no se adjunta a sitios externos.',automatic=False)
   elif field.get('semantic')=='demographic_decline':resolved=dict(answer=field.get('decline_option'),status='DERIVADA',source='Opción de privacidad publicada por Greenhouse',reason='Se utiliza exclusivamente la opción explícita de no responder; no se infieren datos protegidos.',automatic=False)
   elif field.get('semantic')=='hospitality_experience':
    proven=any(a['kind']=='experience' and a.get('sector')=='front_of_house_hospitality' and a['state']=='CUMPLE' for a in e.get('assessments',[]))
    resolved=dict(answer='Yes' if proven else None,status='DERIVADA' if proven else 'DESCONOCIDA',source='Experiencia documentada y revisada',reason='Se verifica experiencia de atención en alojamiento, sin contar solo alimentos o bebidas.',automatic=False)
   elif str(field.get('semantic','')).startswith('doola_'):
    from autojob.forms.doola import resolve as resolve_doola
    resolved=resolve_doola(self,field,context)
   elif field.get('semantic')=='residence_country':resolved=self.resolve('Country of residence',context)
   elif field.get('semantic')=='residence_city_5ca':resolved=self.resolve('City of residence',context)
   elif field.get('semantic') in {'shifts_5ca','days_5ca'}:resolved=self.resolve(field['label'],context)
   elif field.get('semantic')=='english_level_5ca':
    from autojob.matching.engine import level,LANGUAGES,contains
    profile=self.data.profile_state();langs=profile['values'].get('languages') or []
    sufficient='languages' in profile.get('manual',[]) and any(any(contains(value,alias) for alias in LANGUAGES['English']) and (level(value) or 0)>=5 for value in langs)
    resolved=dict(answer='Advanced (C1/C2)' if sufficient else None,status='DERIVADA' if sufficient else 'DESCONOCIDA',source='Nivel de inglés confirmado',reason='La opción publicada agrupa C1 y C2; el nivel declarado sigue siendo C1.',automatic=False)
   elif field.get('requires_specific_consent'):resolved=dict(answer=None,status='REQUIERE AUTORIZACIÓN',source='Aviso específico de 5CA',reason='Requiere revisión expresa para esta vacante; no se acepta desde el banco de respuestas.',automatic=False)

   elif field.get('semantic')=='fluency_en_es':
    from autojob.matching.engine import level,LANGUAGES,contains
    profile=self.data.profile_state();langs=profile['values'].get('languages') or []
    sufficient='languages' in profile.get('manual',[]) and all(any(any(contains(value,alias) for alias in LANGUAGES[language]) and (level(value) or 0)>=5 for value in langs) for language in ['English','Spanish'])
    resolved=dict(answer='Yes' if sufficient else None,status='DERIVADA' if sufficient else 'DESCONOCIDA',source='Idiomas confirmados en Mi perfil',reason='Se contrastan ambos idiomas; no se modifica el nivel ni se inventa un certificado.',automatic=False)
   elif field.get('semantic')=='authorization_cr':
    profile=self.data.profile_state();v=profile['values'];manual=profile.get('manual',[])
    known=all(k in manual for k in ['country','work_authorization']) and norm(str(v.get('country') or ''))=='costa rica' and 'costa rica' in norm(job.get('location') or '') and job.get('geography')=='CONFIRMADO'
    resolved=dict(answer=('Yes' if v['work_authorization'] else 'No') if known else None,status='DERIVADA' if known else 'DESCONOCIDA',source='Mi perfil confirmado / país de la vacante',reason='Autorización vinculada exclusivamente a Costa Rica, sin extrapolar otros países.',automatic=False)
   elif field.get('semantic')=='phone_country_code' or re.search(r'country|pais',norm(field['label'])) and re.search(r'phone|telefono',norm(field.get('group',''))):resolved=dict(answer=None,status='DESCONOCIDA',source='Código telefónico',reason='Este campo solicita un código o país telefónico; no el número completo ni necesariamente el país de residencia.',automatic=False)
   elif field['label']=='Sin etiqueta':resolved=dict(answer=None,status='DESCONOCIDA',source='Campo sin etiqueta fiable',reason='Se necesita identificar la pregunta antes de proponer una respuesta.',automatic=False)
   elif field['kind']=='textarea' and re.search(r'cover letter|carta de presentacion',norm(field['label'])) and letter:resolved=dict(answer=letter['body'],status='SUGERIDA',source='Carta guardada',reason='Borrador local; revisa su correspondencia con la empresa y el puesto.',automatic=False)
   else:resolved=self.resolve(field['group'] if field['kind']=='radio' and field.get('group') else ((field.get('group','')+' ') if field.get('group') and field['kind'] in {'checkbox','radio','multiple'} else '')+field['label'],context)
   # Compatibilidad con respuestas anteriores guardadas con pregunta y etiqueta de opción.
   if field['kind']=='radio' and field.get('group') and resolved.get('status')=='DESCONOCIDA' and not str(field.get('semantic','')).startswith('doola_'):
    previous=self.resolve(field['group']+' '+field['label'],context)
    if previous.get('status') in {'CONFIRMADA','DERIVADA'}:resolved=previous
   if radio_key is not None:radio_resolutions[radio_key]=dict(resolved)
   from autojob.forms.answers9b import ScopedAnswers,restricted
   question=field.get('group') if field['kind']=='radio' and field.get('group') else field['label']
   approved=ScopedAnswers(self.data.data_path).resolve(question,context) if not restricted(question) and not field.get('sensitive_identity') and not field.get('requires_specific_consent') else None
   if approved and resolved.get('status') not in {'CONFLICTO','BLOQUEADA','SENSIBLE'}:resolved=approved
   entry=dict(field,prepared_status=resolved['status'],**resolved)
   if resolved['answer'] is not None and resolved['status'] in {'CONFIRMADA','DERIVADA'}:
    from autojob.testing.simulation_4c import valid_for_field
    kind={'tel':'phone','url':'text','search':'text'}.get(field['kind'],field['kind'])
    options=[o['label'] for o in field.get('options',[])]
    if field['kind']=='checkbox':kind='checkbox'
    if field['kind']=='radio':
     options=[f['label'] for f in document.get('fields',[]) if f['kind']=='radio' and (f.get('name') or f.get('group'))==(field.get('name') or field.get('group'))]
     from autojob.forms.runner import truth
     if options and all(truth(o) is not None for o in options) and truth(resolved['answer']) is not None:kind='checkbox'
    if not valid_for_field(resolved['answer'],kind,options):entry.update(status='REVISAR FORMATO',reason='La respuesta existe, pero el tipo, las unidades u opciones del campo requieren revisión.')
   if field['required'] and (entry['answer'] is None or entry['status'] not in {'CONFIRMADA','DERIVADA','DOCUMENTO LOCAL'}):blocks.append(dict(type='PERMISO ESPECÍFICO PENDIENTE' if field.get('requires_specific_consent') else 'DATO OBLIGATORIO PENDIENTE',evidence=field['label']))
   if re.search(r'captcha|signature|firma|record.{0,10}voice|video.{0,15}(?:interview|recording)|(?:record|upload|grabar).{0,20}video',norm(field['label'])):blocks.append(dict(type='REQUISITO ESPECIAL',evidence=field['label']));entry.update(answer=None,status='BLOQUEADA')
   entries.append(entry)
  from autojob.matching.engine import digest
  return dict(job_id=job.get('id'),job_data_hash=digest(job),company=job.get('company'),position=job.get('title'),url=document['url'],compatibility=e.get('score'),geography=e.get('geography',job.get('geography')),availability=e.get('availability',job.get('availability')),cv_id=cv_id,cv_title=(cv or {}).get('title'),cv_confirmed=bool(cv and cv['reviewed']),cv_approved_for_controlled_test=bool(cv_approved),letter_id=letter_id,inputs_hash=self.inputs_hash(),document=document,entries=entries,blocks=blocks,state='BLOQUEADA' if document.get('obstacles') else 'PENDIENTE' if blocks else 'PREPARADA',external_fill_enabled=False,submission_enabled=False,prepared_at=datetime.now(timezone.utc).isoformat())
 def inputs_hash(self):
  from autojob.matching.engine import digest
  from autojob.forms.answers9b import ScopedAnswers
  return digest(dict(approved=ScopedAnswers(self.data.data_path).rows(),engine='PAVAGO-FIELDS.1',date=today().isoformat(),profile=self.profile_snapshot()['profile_version'],additional=self.data.load(),faq=self.data.faqs()))
 def save(self,preview):
  if preview.get('state') not in {'PENDIENTE','BLOQUEADA','PREPARADA'}:raise ValueError('Estado no permitido en fase 7A.')
  id=str(uuid4());preview={k:v for k,v in preview.items() if k not in {'id','stale'}}
  with closing(self.db.connect()) as db,db:db.execute('INSERT INTO form_preparations VALUES (?,?,?,?,?,?)',(id,preview.get('job_id'),preview['url'],datetime.now(timezone.utc).isoformat(),preview['state'],json.dumps(preview,ensure_ascii=False)))
  return id
 def history(self):
  with closing(self.db.connect()) as db:rows=[dict(id=r['id'],**json.loads(r['payload'])) for r in db.execute('SELECT * FROM form_preparations ORDER BY created_at DESC')]
  fingerprint=self.inputs_hash();jobs={j['id']:j for j in self.compatibility.jobs.list()}
  from autojob.matching.engine import digest
  for row in rows:row['stale']=row.get('inputs_hash')!=fingerprint or bool(row.get('job_id') and row.get('job_data_hash')!=digest(jobs.get(row['job_id'],{})))
  return rows

def inspect_url(settings,url):
 if urlsplit(url).scheme not in {'http','https'}:raise ValueError('Solo se admiten páginas HTTP/HTTPS públicas.')
 from autojob.browser import BraveSession
 try:
  with BraveSession(settings) as browser:
   browser.context.route('**/*',lambda route:route.continue_() if route.request.method in {'GET','HEAD','OPTIONS'} else route.abort())
   page=browser.new_page(url)
   try:page.wait_for_function("document.querySelector('input[type=file],input[type=email]') || /no longer available|job not found|vacante cerrada/i.test(document.body?.innerText||'')",timeout=6000)
   except Exception:pass
   result=inspect(page);result['original_url']=url;return result
 except Exception as exc:return dict(url=url,title=None,fields=[],stages=[],inspected_at=datetime.now(timezone.utc).isoformat(),obstacles=[dict(type='ERROR DEL PORTAL',evidence=type(exc).__name__)])
