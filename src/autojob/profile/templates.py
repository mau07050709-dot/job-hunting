from contextlib import closing
from string import Formatter
from uuid import uuid4
from autojob.storage.database import Database

INTENTS={
 'introduction':['tell me about yourself','tell us about yourself','hablame de ti','cuentanos sobre ti'],
 'candidate':['why should we hire you','good candidate','why should we choose you','por que deberiamos contratarte','buen candidato'],
 'motivation':['why do you want to work','why are you interested','por que quieres trabajar','por que te interesa'],
 'strengths':['what are your strengths','cuales son tus fortalezas'],
 'experience':['describe your professional experience','describe your work experience','describe tu experiencia profesional','describe tu experiencia laboral'],
 'customer_service':['describe your customer service experience','experience with customers','describe tu experiencia en servicio al cliente','experiencia con clientes'],
 'technical':['what technical skills','habilidades tecnicas tienes'],
 'challenge':['challenging situation','difficult situation','situacion dificil','situacion desafiante']}
VARIABLES={'name','company','position','skills','experience','soft_skills','languages'}

class TemplateStore:
 def __init__(self,data_path):
  self.db=Database(data_path/'autojob.sqlite3')
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS professional_templates (id TEXT PRIMARY KEY,intent TEXT NOT NULL,language TEXT NOT NULL,body TEXT NOT NULL)')
   for intent in INTENTS:
    if intent=='challenge':continue
    for language in ('en','es'):
     body=('{name}. Documented experience: {experience}. Skills: {skills}.' if language=='en' else '{name}. Experiencia documentada: {experience}. Habilidades: {skills}.')
     if intent=='motivation':body=('I am interested in the {position} position at {company}. Relevant documented skills: {skills}.' if language=='en' else 'Me interesa el puesto {position} en {company}. Habilidades documentadas relacionadas: {skills}.')
     if intent=='strengths':body=('{soft_skills}.' if language=='en' else '{soft_skills}.')
     if intent=='technical':body='{skills}.'
     if intent in {'experience','customer_service'}:body='{experience}.'
     db.execute('INSERT OR IGNORE INTO professional_templates VALUES (?,?,?,?)',(intent+'-'+language,intent,language,body))
 def all(self):
  with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM professional_templates ORDER BY intent,language,id')]
 def save(self,intent,language,body,template_id=None):
  if intent not in INTENTS or language not in {'en','es'} or not body.strip():raise ValueError('Revisa tipo, idioma y contenido.')
  for literal,key,spec,conversion in Formatter().parse(body):
   if key is not None and (key not in VARIABLES or spec or conversion):raise ValueError('Variable no permitida. Usa: '+', '.join(sorted(VARIABLES)))
  template_id=template_id or str(uuid4())
  with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO professional_templates VALUES (?,?,?,?)',(template_id,intent,language,body))
  return template_id
 def render(self,intent,language,values,template_id=None):
  rows=[r for r in self.all() if r['intent']==intent and r['language']==language and (not template_id or r['id']==template_id)]
  if not template_id:rows=[r for r in rows if r['id']==intent+'-'+language]
  if len(rows)!=1:return None,'Selecciona una plantilla guardada.'
  row=rows[0];needed={key for _,key,_,_ in Formatter().parse(row['body']) if key}
  if any(not values.get(key) for key in needed):return None,'Faltan variables documentadas o contexto de empresa y puesto.'
  return row['body'].format_map(values),row['id']

class DefaultTemplates:
 """Plantillas sin almacenamiento para llamadas puras al motor."""
 render=TemplateStore.render
 def all(self):
  rows=[]
  for intent in INTENTS:
   if intent=='challenge':continue
   for language in ('en','es'):
    body='{experience}.' if intent in {'experience','customer_service'} else '{soft_skills}.' if intent=='strengths' else '{skills}.' if intent=='technical' else ('I am interested in {position} at {company}. Documented skills: {skills}.' if language=='en' else 'Me interesa {position} en {company}. Habilidades documentadas: {skills}.') if intent=='motivation' else ('{name}. Documented experience: {experience}. Skills: {skills}.' if language=='en' else '{name}. Experiencia documentada: {experience}. Habilidades: {skills}.')
    rows.append(dict(id=intent+'-'+language,intent=intent,language=language,body=body))
  return rows
