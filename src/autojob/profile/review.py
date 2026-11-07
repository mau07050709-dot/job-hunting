"""Revisión explícita por elemento, sin reescribir CV ni confirmar durante importación."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timezone
import json,re
from autojob.profile.store import ProfileStore,FIELDS,LISTS,BOOLS,empty,validate
from autojob.resumes.service import ResumeLibrary
from autojob.resumes.models import FIELD_LABELS
from autojob.profile.soft_skills import extract_soft_skills
from autojob.matching.engine import digest,normalize

CATEGORIES=['Datos personales','Educación','Experiencia laboral','Habilidades técnicas','Habilidades blandas','Idiomas','Proyectos','Disponibilidad','Preferencias laborales']
def category(field):
 if field in {'skills','programming_languages','technical_skills'}:return 'Habilidades técnicas'
 if field=='soft_skills':return 'Habilidades blandas'
 if field=='languages':return 'Idiomas'
 if field in {'academic_projects'}:return 'Proyectos'
 if field in {'university','degree','academic_status','qualifications','certifications','education_records','education'}:return 'Educación'
 if field in {'experience','experience_records','companies','positions','dates','responsibilities','employment_dates'}:return 'Experiencia laboral'
 if field in {'schedule','start_availability'}:return 'Disponibilidad'
 if field in {'remote','hybrid','onsite','full_time','part_time','accepted_countries','locations','salary_min','salary_max','currency'}:return 'Preferencias laborales'
 return 'Datos personales'
def known(value):return value not in (None,'',[],{})
def fact_text(record):return ' | '.join(str(record.get(k) or '') for k in ('company','position','institution','degree','academic_status','name','description','technologies'))

class ReviewStore:
 def __init__(self,data_path):
  self.profile=ProfileStore(data_path);self.library=ResumeLibrary(data_path);self.db=self.profile.db
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS profile_review_decisions(item_id TEXT PRIMARY KEY,source_hash TEXT NOT NULL,value_json TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS profile_review_history(id INTEGER PRIMARY KEY,item_id TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL)')
 def decisions(self):
  with closing(self.db.connect()) as db:return {r['item_id']:dict(r) for r in db.execute('SELECT * FROM profile_review_decisions')}
 def inventory(self,profile=None,cvs=None):
  p=profile or self.profile.load();cvs=cvs if cvs is not None else [self.library.get(c['id']) for c in self.library.list()];decisions=self.decisions();items=[]
  def add(source,field,value,index=None,group=None,label=None,manual=False):
   identity=f'{source}:{group or "field"}:{field}:{index if index is not None else "scalar"}';d=decisions.get(identity);fingerprint=digest(value)
   state='CONFIRMADO PREVIAMENTE' if manual and known(value) else 'POR REVISAR' if known(value) else 'DESCONOCIDO'
   effective=value
   if d:
    effective=json.loads(d['value_json']);state=d['state'] if d['source_hash']==fingerprint else 'OBSOLETO · fuente modificada'
   label_=label or FIELDS.get(field) or FIELD_LABELS.get(field) or field
   item=dict(id=identity,source=source,field=field,index=index,group=group,category=category(group or field),label=label_,original=value,value=effective,source_hash=fingerprint,state=state,revision=d['revision'] if d else 0,conflict=None)
   if field in {'programming_languages','certifications'} and isinstance(effective,str) and normalize(effective) in {'si','yes','no'}:item['conflict']='Valor inespecífico: indica un lenguaje o certificación concreto, o déjalo desconocido.'
   if source=='profile' and field in p.get('conflicts',{}):item['conflict']='El perfil contiene fuentes contradictorias: '+json.dumps(p['conflicts'][field],ensure_ascii=False)
   items.append(item)
  for field,value in p['values'].items():
   if field in LISTS and value:
    for i,entry in enumerate(value):add('profile',field,entry,i,manual=field in p['manual'])
   else:add('profile',field,value,manual=field in p['manual'])
  for cv in cvs:
   for field,value in dict(cv['fields'],soft_skills=extract_soft_skills(cv.get('source_units',[]))).items():
    if field in {'experience','education','academic_projects'} and field not in cv.get('manual_fields',[]):continue
    if isinstance(value,list) and value:
     for i,entry in enumerate(value):add(cv['id'],field,entry,i,label=cv['title']+' / '+FIELD_LABELS.get(field,field),manual=bool(cv['reviewed'] or field in cv.get('manual_fields',[])))
    else:add(cv['id'],field,value,label=cv['title']+' / '+FIELD_LABELS.get(field,field),manual=bool(cv['reviewed'] or field in cv.get('manual_fields',[])))
   for group,records in cv['structure'].items():
    for i,row in enumerate(records):add(cv['id'],str(row.get('id') or i),row,i,group,label=cv['title']+' / '+str(row.get('position') or row.get('degree') or row.get('name') or group),manual=bool(cv['reviewed'] or row.get('origin')=='manual'))
  # Solo los datos personales comparables se contrastan literalmente. No confundir traducciones con contradicciones.
  for field in ('email','phone','full_name'):
   rows=[r for r in items if r['field']==field and known(r['value'])]
   variants={re.sub(r'[^\w@]','',normalize(str(r['value']))) for r in rows}
   if len(variants)>1:
    for row in rows:row['conflict']='Valores diferentes entre fuentes; revisa y corrige cada fuente o elige el dato del perfil.'
  return items
 def validate_item(self,item,value):
  if item['group']:
   from autojob.resumes.semantics import STRUCTURE_KEYS
   if not isinstance(value,dict):raise ValueError('El registro debe conservar sus campos estructurados.')
   for key in STRUCTURE_KEYS[item['group']]:
    entry=value.get(key)
    if key in {'technologies','responsibilities'}:
     if not isinstance(entry,list) or any(not isinstance(v,str) for v in entry):raise ValueError('Lista de registro inválida.')
    elif entry is not None and not isinstance(entry,str):raise ValueError('Campo de registro inválido.')
   return
  field=item['field']
  if field in {'programming_languages','certifications'} and isinstance(value,str) and normalize(value).strip() in {'si','yes','no'}:raise ValueError('Especifica el dato concreto; «sí/no» no acredita un lenguaje o certificado.')
  if item['source']=='profile':
   p=self.profile.load()['values'];p[field]=([value] if known(value) else []) if field in LISTS and item['index'] is not None else value;validate(p)
  elif field in {'email','phone','full_name','location'}:
   p=empty();target=field if field!='location' else 'city';p[target]=value;validate(p)
 def save(self,ids,confirm=False,values=None,expected=None,resolve_conflicts=False):
  inventory={r['id']:r for r in self.inventory()};values=values or {};changes=[]
  for id in ids:
   if id not in inventory:raise ValueError('El dato ya no existe. Actualiza la revisión.')
   item=inventory[id];value=values.get(id,item['value'])
   if expected and (item['revision'],item['source_hash'])!=expected.get(id):raise ValueError('El dato cambió en otra ventana. Actualiza antes de guardar.')
   self.validate_item(item,value)
   if confirm and not known(value) and not known(item['original']):continue
   if confirm and item['conflict'] and value==item['value'] and not resolve_conflicts:raise ValueError('Resuelve primero la contradicción o confirma explícitamente el valor elegido desde Corregir.')
   changes.append((item,value))
  now=datetime.now(timezone.utc).isoformat()
  with closing(self.db.connect()) as db,db:
   db.execute('BEGIN IMMEDIATE')
   for item,value in changes:
    previous=db.execute('SELECT revision FROM profile_review_decisions WHERE item_id=?',(item['id'],)).fetchone()
    if (previous['revision'] if previous else 0)!=item['revision']:raise ValueError('La revisión cambió en otra ventana.')
    payload=dict(item_id=item['id'],source_hash=item['source_hash'],value_json=json.dumps(value,ensure_ascii=False),state=('CONFIRMADO' if known(value) else 'DESCONOCIDO REVISADO') if confirm else 'BORRADOR',revision=item['revision']+1,updated_at=now)
    db.execute('INSERT OR REPLACE INTO profile_review_decisions VALUES (?,?,?,?,?,?)',tuple(payload.values()));db.execute('INSERT INTO profile_review_history(item_id,payload,updated_at) VALUES (?,?,?)',(item['id'],json.dumps(payload),now))
  return len(changes)
 def effective(self,profile,cvs):
  p=deepcopy(profile);documents=deepcopy(cvs);by_id={c['id']:c for c in documents};confirmed=[]
  for c in documents:c['fields']['soft_skills']=extract_soft_skills(c.get('source_units',[]))
  for item in self.inventory(profile,cvs):
   if item['state'] not in {'CONFIRMADO','BORRADOR','DESCONOCIDO REVISADO'}:continue
   # Los borradores se conservan pero no se usan para afirmar compatibilidad.
   if item['state']=='BORRADOR':
    with closing(self.db.connect()) as db:history=db.execute('SELECT payload FROM profile_review_history WHERE item_id=? ORDER BY id DESC',(item['id'],)).fetchall()
    previous=next((d for r in history if (d:=json.loads(r['payload']))['state'] in {'CONFIRMADO','DESCONOCIDO REVISADO'} and d['source_hash']==item['source_hash']),None)
    if not previous:continue
    item=dict(item,value=json.loads(previous['value_json']),state=previous['state'])
   source=item['source'];key=item['field'];value=item['value'];index=item['index'];group=item['group']
   if item['state']=='DESCONOCIDO REVISADO' and index is not None:value=''
   if source=='profile':
    if index is not None:p['values'][key][index]=value
    else:p['values'][key]=value
    origin='Mi perfil / '+key
    p.get('conflicts',{}).pop(key,None)
    if key not in p.get('manual',[]):p.get('sources',{}).pop(key,None)
    if key not in LISTS:p['manual']=sorted(set(p['manual'])|{key})
   else:
    cv=by_id[source]
    if group:
     cv['structure'][group][index]=value;origin='CV '+source+' / '+group+' / '+str(value.get('id'));value=fact_text(value)
    else:
     if index is not None:cv['fields'][key][index]=value
     else:cv['fields'][key]=value
     origin='CV '+source+' / '+key
   if item['state']!='DESCONOCIDO REVISADO':confirmed.append((origin,digest(str(value))))
  p['_review_confirmed']=confirmed
  return p,documents
 def expected_documents(self):
  docs=self.library.list();missing=[]
  for language,specialty,label in [('es','technical','Técnico en español'),('en','technical','Técnico en inglés'),('en','customer_service','Customer Service en inglés')]:
   if not any(c['language']==language and c['specialty']==specialty for c in docs):missing.append(label)
  return missing
