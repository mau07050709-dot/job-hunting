"""Respuestas locales. Los datos no confirmados siempre requieren revisión."""
from contextlib import closing
from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import re
import unicodedata
from uuid import uuid4
from autojob.storage.database import Database

def norm(text):
 return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))

RULES = {
 'full_name':['full name','your name','nombre completo','nombre y apellidos'],
 'email':['email','e-mail','correo electronico','correo de contacto'],
 'phone':['phone','telephone','mobile number','telefono','numero movil','celular'],
 'whatsapp':['whatsapp'], 'country':['country of residence','pais de residencia','where do you live','pais donde reside'],
 'age':['how old are you','what is your age','edad','cuantos anos tienes'],
 'city':['city','ciudad'], 'languages':['languages do you speak','what languages','idiomas habla','idiomas'],
 'skills':['technical skills','habilidades tecnicas','technical abilities'],
 'soft_skills':['soft skills','habilidades blandas','fortalezas profesionales','strengths','fortalezas'],
 'programming_languages':['programming languages','lenguajes de programacion'],
 'education_records':['education','educacion','estudios','academic background'],
 'experience_records':['work experience','professional experience','experiencia laboral','experiencia profesional','customer service experience','customer support experience','experiencia en servicio al cliente','experiencia en atencion al cliente'],
 'schedule':['availability','disponibilidad','working hours','horario'],
 'salary_min':['salary','salarial','salario','sueldo','compensation'],
 'work_authorization':['legally authorized','work authorization','authorized to work','autorizacion laboral','permiso de trabajo'],
 'motivation':['why do you want','why are you interested','por que quieres','por que desea','motivacion'],
}
SENSITIVE=('criminal','conviction','disability','discapacidad','criminal record','antecedentes penales','social security','seguridad social','visa','sponsorship','legal contract','contrato legal','work authorization','authorized to work','autorizacion laboral','permiso de trabajo','legally authorized')

@dataclass
class Resolution:
 question:str
 field:str|None
 answer:str|None
 language:str
 category:str
 source:str
 confidence:str
 approved:bool
 automatic:bool
 review_required:bool
 reason:str

def fingerprint(profile):
 return sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def identify(question,rules=None):
 q=norm(question); matches=[]
 for field,patterns in (rules or RULES).items():
  for pattern in patterns:
   if re.search(r'(?<!\w)'+re.escape(norm(pattern))+r'(?!\w)',q): matches.append((len(pattern),field))
 return max(matches)[1] if matches else None

def _resolve_base(question,context,profile,bank=None,rules=None):
 context=context or {};lang=context.get('language','en' if re.search(r'\b(what|your|do|are|experience|skills|phone|email)\b',norm(question)) else 'es')
 field=identify(question,rules); q=norm(question); sensitive=any(norm(x) in q for x in SENSITIVE)
 def result(answer,category,source,confidence,approved,automatic,reason):
  return Resolution(question,field,answer,lang,category,source,confidence,approved,automatic,not automatic,reason)
 if sensitive: return result(None,'SENSIBLE','Declaración personal','alta',False,False,'Requiere una declaración o autorización específica.')
 if bank:
  matching=bank.match(question,lang,profile)
  if matching: return result(matching['answer'],'CONFIRMADA','Respuesta aprobada','alta',True,True,'Aprobada y vigente para el perfil actual.')
 if field is None:return result(None,'DESCONOCIDA','Sin fuente','baja',False,False,'Pregunta no reconocida; requiere revisión.')
 values=profile.get('values',{});value=values.get(field);manual=field in profile.get('manual',[])
 if field=='age':
  from datetime import date
  from autojob.profile.store import today
  from autojob.profile.calculations import age
  try:
   birth=values.get('birth_date');calculated=age(date.fromisoformat(birth),today()) if birth else None
  except ValueError:calculated=None
  if calculated is None:return result(None,'DESCONOCIDA','Perfil','baja',False,False,'Fecha de nacimiento desconocida o inválida.')
  verified='birth_date' in profile.get('manual',[])
  return result(str(calculated),'DERIVADA' if verified else 'SUGERIDA','Fecha de nacimiento','alta' if verified else 'media',verified,verified,'Edad calculada a la fecha actual en Costa Rica.' if verified else 'Confirma la fecha de nacimiento.')
 if value is None or value=='' or value==[]:return result(None,'DESCONOCIDA','Perfil','baja',False,False,'No hay información confirmada suficiente.')
 if isinstance(value,list):
  if field=='experience_records' and any(x in q for x in ('customer service','customer support','servicio al cliente','atencion al cliente')):
   value=[item for item in value if any(term in norm(item) for term in ('customer','client','cliente','servicio'))]
   if not value:return result(None,'DESCONOCIDA','Experiencia laboral','baja',False,False,'No se encontró experiencia laboral documentada de atención al cliente.')
  value='; '.join(value)
 if isinstance(value,bool):value=('Yes' if value else 'No') if lang=='en' else ('Sí' if value else 'No')
 if field in {'experience_records','education_records','skills','soft_skills','languages','programming_languages','schedule','salary_min','motivation'}:
  return result(str(value),'SUGERIDA','Perfil y CV','media',False,False,'Revisar contexto, vigencia y pertinencia antes de usar.')
 return result(str(value),'CONFIRMADA' if manual else 'SUGERIDA','Perfil confirmado' if manual else 'CV pendiente de revisión','alta' if manual else 'media',manual,manual,'Dato confirmado por el usuario.' if manual else 'El dato importado requiere confirmación.')

class AnswerBank:
 def __init__(self,data_path):
  self.database=Database(data_path/'autojob.sqlite3')
  with closing(self.database.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS answer_bank (id TEXT PRIMARY KEY, category TEXT NOT NULL, language TEXT NOT NULL, questions TEXT NOT NULL, answer TEXT NOT NULL, approved INTEGER NOT NULL, profile_hash TEXT NOT NULL)')
 def all(self):
  with closing(self.database.connect()) as db:return [dict(row) for row in db.execute('SELECT * FROM answer_bank ORDER BY category,language,id')]
 def save(self,category,language,questions,answer,approved,profile,answer_id=None):
  if language not in {'es','en'} or not category.strip() or not answer.strip() or not questions or any(not q.strip() for q in questions):raise ValueError('Completa categoría, idioma, preguntas y respuesta.')
  answer_id=answer_id or str(uuid4())
  with closing(self.database.connect()) as db,db:db.execute('INSERT OR REPLACE INTO answer_bank VALUES (?,?,?,?,?,?,?)',(answer_id,category.strip(),language,json.dumps(questions,ensure_ascii=False),answer.strip(),int(bool(approved)),fingerprint(profile)))
  return answer_id
 def delete(self,answer_id):
  with closing(self.database.connect()) as db,db:db.execute('DELETE FROM answer_bank WHERE id=?',(answer_id,))
 def match(self,question,language,profile):
  field=identify(question); matches=[]
  for item in self.all():
   if not item['approved'] or item['language']!=language or item['profile_hash']!=fingerprint(profile):continue
   questions=json.loads(item['questions'])
   if any(norm(q)==norm(question) or (field in {'full_name','email','phone','whatsapp','country','city'} and identify(q)==field) for q in questions):matches.append(item)
  return matches[0] if len(matches)==1 else None


def resolve_question(question,context,profile,bank=None,rules=None):
 from autojob.profile.advanced import resolve_advanced
 from autojob.profile.templates import TemplateStore,DefaultTemplates
 templates=context.get("template_store") if context and context.get("template_store") else TemplateStore(bank.database.path.parent) if bank else DefaultTemplates()
 return resolve_advanced(question,context,profile,bank,lambda q,c,p,b: _resolve_base(q,c,p,b,rules),templates)
