from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from zoneinfo import ZoneInfo
import phonenumbers
from autojob.storage.database import Database
from autojob.profile.calculations import age

GROUPS = {
 'Información personal': {'full_name':'Nombre completo','birth_date':'Fecha de nacimiento (AAAA-MM-DD)','email':'Correo','phone':'Teléfono','whatsapp':'WhatsApp','country':'País','province':'Provincia','city':'Ciudad','nationality':'Nacionalidad','work_authorization':'Autorización laboral','linkedin':'LinkedIn'},
 'Educación': {'university':'Universidad','degree':'Carrera','academic_status':'Estado académico','qualifications':'Titulaciones obtenidas','certifications':'Certificaciones','education_records':'Estudios documentados'},
 'Experiencia': {'companies':'Empresas','positions':'Puestos','dates':'Fechas documentadas','responsibilities':'Responsabilidades','skills':'Habilidades técnicas','programming_languages':'Lenguajes de programación','soft_skills':'Habilidades blandas / Soft Skills','languages':'Idiomas','experience_records':'Experiencia documentada'},
 'Preferencias laborales': {'remote':'Remoto','hybrid':'Híbrido','onsite':'Presencial','accepted_countries':'Países aceptados','locations':'Ubicaciones aceptadas','full_time':'Tiempo completo','part_time':'Medio tiempo','schedule':'Horarios (America/Costa_Rica)','salary_min':'Salario mínimo mensual','salary_max':'Salario máximo mensual','currency':'Moneda (código ISO)','start_availability':'Disponibilidad de incorporación'}
}
FIELDS = {key:label for group in GROUPS.values() for key,label in group.items()}
BOOLS = {'remote','hybrid','onsite','full_time','part_time','work_authorization'}
LISTS = {'qualifications','certifications','companies','positions','dates','responsibilities','skills','programming_languages','soft_skills','languages','accepted_countries','locations','education_records','experience_records'}

def today(): return datetime.now(ZoneInfo('America/Costa_Rica')).date()
def empty(): return {key: [] if key in LISTS else None for key in FIELDS}
def validate(values):
 if set(values) != set(FIELDS): raise ValueError('Campos de perfil inválidos')
 for key,value in values.items():
  if key in BOOLS:
   if value is not None and type(value) is not bool: raise ValueError('Selección inválida')
  elif key in LISTS:
   if not isinstance(value,list) or any(not isinstance(v,str) or len(v)>50000 for v in value): raise ValueError('Lista inválida')
  elif value is not None and (not isinstance(value,str) or len(value)>10000): raise ValueError('Texto inválido')
 if values['birth_date']:
  try: age(date.fromisoformat(values['birth_date']),today())
  except ValueError: raise ValueError('Revisa la fecha de nacimiento: AAAA-MM-DD, sin fechas futuras') from None
 if values['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']): raise ValueError('Correo inválido')
 for key in ('phone','whatsapp'):
  if values[key]:
   try:
    number=phonenumbers.parse(values[key], 'CR' if values['country'] and values['country'].casefold()=='costa rica' else None)
    if not phonenumbers.is_valid_number(number): raise ValueError()
   except Exception: raise ValueError('Teléfono o WhatsApp inválido; incluye prefijo internacional') from None
 if values['linkedin'] and not re.fullmatch(r'https://(?:www\.)?linkedin\.com/[^\s]+',values['linkedin']): raise ValueError('LinkedIn debe ser una URL https://linkedin.com/...')
 amounts=[]
 for key in ('salary_min','salary_max'):
  if values[key]:
   try:
    amount=Decimal(values[key])
    if not amount.is_finite() or amount<0: raise ValueError()
    amounts.append(amount)
   except (InvalidOperation,ValueError): raise ValueError('Salario inválido: utiliza una cantidad positiva sin separadores de miles') from None
 if len(amounts)==2 and amounts[0]>amounts[1]: raise ValueError('El salario mínimo supera al máximo')
 if values['currency'] and not re.fullmatch('[A-Z]{3}',values['currency']): raise ValueError('Moneda: utiliza tres letras mayúsculas, por ejemplo CRC o USD')

class ProfileStore:
 def __init__(self,data_path):
  self.db=Database(data_path/'autojob.sqlite3')
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS personal_profile (id INTEGER PRIMARY KEY CHECK(id=1), values_json TEXT NOT NULL, manual_json TEXT NOT NULL, sources_json TEXT NOT NULL, conflicts_json TEXT NOT NULL, revision INTEGER NOT NULL)')
   db.execute('INSERT OR IGNORE INTO personal_profile VALUES (1,?,?,?,?,0)',(json.dumps(empty()),'[]','{}','{}'))
 def load(self):
  with closing(self.db.connect()) as db: row=db.execute('SELECT * FROM personal_profile WHERE id=1').fetchone()
  return dict(values={**empty(),**json.loads(row['values_json'])}, manual=json.loads(row['manual_json']),sources=json.loads(row['sources_json']),conflicts=json.loads(row['conflicts_json']),revision=row['revision'])
 def _save(self,state):
  with closing(self.db.connect()) as db,db:
   cursor=db.execute('UPDATE personal_profile SET values_json=?,manual_json=?,sources_json=?,conflicts_json=?,revision=revision+1 WHERE id=1 AND revision=?',(json.dumps(state['values'],ensure_ascii=False),json.dumps(state['manual']),json.dumps(state['sources'],ensure_ascii=False),json.dumps(state['conflicts'],ensure_ascii=False),state['revision']))
   if cursor.rowcount!=1: raise ValueError('El perfil cambió en otra ventana. Actualiza antes de guardar.')
  return self.load()
 def save(self,values,revision,confirmed=()):
  validate(values)
  state=self.load()
  if state['revision']!=revision: raise ValueError('El perfil cambió en otra ventana. Actualiza antes de guardar.')
  changed={key for key in FIELDS if values[key]!=state['values'][key]} | set(confirmed)
  if not changed<=set(FIELDS): raise ValueError('Confirmación inválida')
  state['manual']=sorted(set(state['manual'])|changed)
  for key in changed:
   state['sources'][key]=[{'origin':'manual','status':'Confirmado manualmente'}]
   state['conflicts'].pop(key,None)
  state['values']=values
  return self._save(state)
 def import_resumes(self,library):
  state=self.load(); candidates={}
  def offer(key,value,cv,rank):
   if value in (None,'',[]): return
   candidates.setdefault(key,[]).append((rank,value,{'resume_id':cv['id'],'document':cv['title'],'origin':'cv','status':'CV revisado' if cv['reviewed'] else 'Extraído sin revisar','rank':rank}))
  for entry in library.list():
   cv=library.get(entry['id']); f=cv['fields']; base=2 if cv['reviewed'] else 1
   mapping={'full_name':'full_name','email':'email','phone':'phone','certifications':'certifications','companies':'companies','positions':'positions','employment_dates':'dates','technical_skills':'skills','programming_languages':'programming_languages','languages':'languages'}
   for source,target in mapping.items(): offer(target,f.get(source),cv,3 if source in cv.get('manual_fields',[]) else base)
   from autojob.profile.soft_skills import extract_soft_skills
   offer('soft_skills',extract_soft_skills(cv.get('source_units',[])),cv,base)
   location=f.get('location') or ''
   parts=[part.strip() for part in location.split(',')]
   if parts and parts[-1].casefold()=='costa rica':
    offer('country','Costa Rica',cv,base)
    if len(parts)==3:
     offer('city',parts[0],cv,base);offer('province',parts[1],cv,base)
   for link in f.get('professional_links',[]):
    if 'linkedin.com/' in link: offer('linkedin',link if link.startswith('https://') else 'https://'+link.removeprefix('www.'),cv,base)
   edu=cv['structure'].get('education',[])
   for row in edu:
    rank=3 if row.get('origin')=='manual' else base
    offer('education_records',[' | '.join(str(row.get(key)) for key in ('institution','degree','academic_status','start_date','end_date') if row.get(key))],cv,rank)
   if edu:
    row=edu[0]; rank=3 if row.get('origin')=='manual' else base
    for source,target in [('institution','university'),('degree','degree'),('academic_status','academic_status')]: offer(target,row.get(source),cv,rank)
   for row in cv['structure'].get('experience',[]):
    rank=3 if row.get('origin')=='manual' else base
    offer('experience_records',[' | '.join(str(row.get(key)) for key in ('company','position','start_date','end_date','description') if row.get(key))],cv,rank)
    offer('responsibilities',row.get('responsibilities'),cv,rank)
  def canonical(value): return ' '.join(value.casefold().split())
  for key,items in candidates.items():
   if key in state['manual']: continue
   items.sort(key=lambda item:item[0],reverse=True)
   if key in LISTS:
    values=[]; seen=set()
    for _,entries,_ in items:
     for value in entries:
      marker=canonical(value)
      if marker not in seen: seen.add(marker);values.append(value)
    state['values'][key]=values
   else:
    distinct={canonical(str(value)) for _,value,_ in items}
    if len(distinct)>1:
     state['conflicts'][key]=[{'value':v,'source':s} for _,v,s in items]
     state['values'][key]=None
    else: state['values'][key]=items[0][1];state['conflicts'].pop(key,None)
   state['sources'][key]=[source for _,_,source in items]
  return self._save(state)
