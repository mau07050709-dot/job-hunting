from contextlib import closing
from datetime import datetime,timezone
import json,re
from string import Formatter
from uuid import uuid4
from xml.sax.saxutils import escape
from docx import Document
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
from autojob.storage.database import Database
from autojob.resumes.service import ResumeLibrary
from autojob.profile.store import ProfileStore
from autojob.profile.answers import AnswerBank

class Letters:
 def __init__(self,data_path):
  self.db=Database(data_path/'autojob.sqlite3');self.library=ResumeLibrary(data_path);self.profile=ProfileStore(data_path)
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS cover_letters (id TEXT PRIMARY KEY,company TEXT,position TEXT,description TEXT,language TEXT,category TEXT,cv_id TEXT,body TEXT,created_at TEXT)')
   db.execute('CREATE TABLE IF NOT EXISTS cover_letter_templates (language TEXT PRIMARY KEY, body TEXT NOT NULL)')
   for lang,body in [('en','Dear hiring team at {company},\n\nI am interested in the {position} position.\n\n{facts}\n\nI would welcome the opportunity to discuss how my background relates to this role.\n\nSincerely,\n{name}'),('es','Estimado equipo de {company}:\n\nMe interesa el puesto de {position}.\n\n{facts}\n\nAgradezco la oportunidad de conversar sobre mi perfil y el puesto.\n\nAtentamente,\n{name}')]:
    db.execute('INSERT OR IGNORE INTO cover_letter_templates VALUES (?,?)',(lang,body))
 def template(self,language):
  with closing(self.db.connect()) as db:
   row=db.execute('SELECT body FROM cover_letter_templates WHERE language=?',(language,)).fetchone()
   if not row:raise ValueError('Idioma inválido')
   return row[0]
 def save_template(self,language,body):
  if language not in {'es','en'} or not body.strip():raise ValueError('Plantilla o idioma inválidos.')
  for _,key,spec,conversion in Formatter().parse(body):
   if key is not None and (key not in {'company','position','facts','name'} or spec or conversion):raise ValueError('Solo se permiten {company}, {position}, {facts} y {name}.')
  with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO cover_letter_templates VALUES (?,?)',(language,body))
 def generate(self,company,position,description,language,category,cv_id):
  if not company.strip() or not position.strip() or language not in {'en','es'} or category not in {'technical','customer_service'}:raise ValueError('Indica empresa, puesto, idioma y categoría.')
  if not cv_id:raise ValueError('Selecciona un CV.')
  cv=self.library.get(cv_id);self.library.original_path(cv_id)
  if not cv['reviewed']:raise ValueError('Revisa el CV antes de generar la carta.')
  fields=cv['fields'];keywords=set(re.findall(r'\w+',description.casefold()))
  skills=fields.get('technical_skills',[]) if category=='technical' else fields.get('technical_skills',[])+fields.get('languages',[])
  skills=sorted(skills,key=lambda item:len(keywords & set(re.findall(r'\w+',item.casefold()))),reverse=True)[:4]
  jobs=cv['structure'].get('experience',[])
  terms=('customer','cliente','support','servicio') if category=='customer_service' else ('developer','program','technical','tecnic','engineering','ingenier')
  relevant=[r for r in jobs if any(term in (str(r.get('position') or '')+' '+str(r.get('description') or '')).casefold() for term in terms)]
  facts=[]
  if relevant:
   row=relevant[0];role=row.get('position') or '';employer=row.get('company') or ''
   line=(role+(' at ' if language=='en' else ' en ')+employer) if role and employer else role or employer
   if row.get('start_date') and row.get('end_date'):line+=' ('+str(row['start_date'])+'–'+str(row['end_date'])+')'
   if line:facts.append(line)
  if skills:facts.append(', '.join(skills))
  education=cv['structure'].get('education',[])
  if education:
   row=education[0];parts=[]
   for key in ('degree','institution','academic_status'):
    value=str(row.get(key) or '').strip()
    if value and not any(value.casefold() in part.casefold() for part in parts):parts.append(value)
   if parts:facts.append(', '.join(parts))
  if category=='technical' and keywords:
   projects=cv['structure'].get('academic_projects',[])
   for row in projects:
    text=' '.join(str(row.get(key) or '') for key in ('name','description'))
    if len(keywords & set(re.findall(r'\w+',text.casefold())))>=2:
     name=row.get('name') or '';description=row.get('description') or ''
     facts.append((name+': '+description) if name and description else name or description);break
  profile=self.profile.load()
  question='Why do you want to work here?' if language=='en' else '¿Por qué quieres trabajar aquí?'
  approved=AnswerBank(self.library.data_path).match(question,language,profile)
  if approved and company.casefold() in approved['answer'].casefold() and position.casefold() in approved['answer'].casefold():
   facts.append(approved['answer'])
  name=fields.get('full_name') or profile['values'].get('full_name') or ''
  summary=(('My documented background includes: ' if language=='en' else 'Mi trayectoria documentada incluye: ')+'. '.join(facts)+'.') if facts else ''
  return self.template(language).format_map(dict(company=company,position=position,facts=summary,name=name))
 def save(self,company,position,description,language,category,cv_id,body,letter_id=None):
  if not body.strip():raise ValueError('La carta está vacía.')
  if letter_id:
   with closing(self.db.connect()) as db,db:
    if not db.execute('UPDATE cover_letters SET company=?,position=?,description=?,language=?,category=?,cv_id=?,body=? WHERE id=?',(company,position,description,language,category,cv_id,body,letter_id)).rowcount:raise ValueError('La carta ya no existe.')
  else:
   letter_id=str(uuid4())
   with closing(self.db.connect()) as db,db:db.execute('INSERT INTO cover_letters VALUES (?,?,?,?,?,?,?,?,?)',(letter_id,company,position,description,language,category,cv_id,body,datetime.now(timezone.utc).isoformat()))
  return letter_id
 def history(self):
  with closing(self.db.connect()) as db:return [dict(row) for row in db.execute('SELECT * FROM cover_letters ORDER BY created_at DESC')]
 def export(self,body,path):
  if path.suffix.lower()=='.docx':
   doc=Document()
   for line in body.split('\n'):doc.add_paragraph(line)
   doc.save(path)
  elif path.suffix.lower()=='.pdf':
   styles=getSampleStyleSheet();story=[]
   for line in body.split('\n'):
    story.append(Paragraph(escape(line) if line.strip() else '&nbsp;',styles['Normal']));story.append(Spacer(1,5))
   SimpleDocTemplate(str(path)).build(story)
  else:raise ValueError('Selecciona PDF o DOCX.')
