"""Simulación local: no navega ni envía solicitudes."""
from contextlib import closing
from datetime import datetime,timezone
import json
import re
from datetime import date
from decimal import Decimal,InvalidOperation
from uuid import uuid4
from autojob.profile.answers import AnswerBank,resolve_question,fingerprint
from autojob.profile.store import ProfileStore
from autojob.resumes.service import ResumeLibrary
from autojob.resumes.selection import ResumeSelector
from autojob.storage.database import Database

SCENARIOS={
 'Customer Service en inglés': [('Full name','text',True),('Email','email',True),('Phone','phone',True),('Education','text',True),('Customer service experience','textarea',True),('English level','text',True),('Availability','text',False),('Why do you want to work here?','textarea',False),('CV','file',True)],
 'Junior Software Developer': [('Education','text',True),('Programming languages','text',True),('Academic projects','textarea',True),('Professional experience','textarea',True),('Technical skills','textarea',True),('CV','file',True)],
 'Remoto internacional': [('Country of residence','text',True),('Are you legally authorized to work in the United States?','select',True),('What is your time zone?','text',True),('Availability','text',True),('Expected monthly salary','salary',False),('Preferred international contract type','text',True),('CV','file',True)],
 'Obstáculos': [('Unknown mandatory question','text',True),('CAPTCHA','captcha',True),('Personal video','video',True),('Legal contract','legal',True),('CV','file',True)],
}

def valid_for_field(answer,kind,options=None):
 if answer is None or not str(answer).strip():return False
 text=str(answer).strip()
 if kind=='email':return re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',text) is not None
 if kind=='phone':
  import phonenumbers
  try:return phonenumbers.is_valid_number(phonenumbers.parse(text,None))
  except phonenumbers.NumberParseException:return False
 if kind=='date':
  try:date.fromisoformat(text);return True
  except ValueError:return False
 if kind in {'number','salary','experience'}:
  try:
   n=Decimal(text);return n.is_finite() and (kind=='number' or n>=0)
  except InvalidOperation:return False
 if kind in {'select','radio','multiple'}:
  if not options:return False
  allowed={x.casefold().strip() for x in options};values=[v.strip().casefold() for v in text.split('|')] if kind=='multiple' else [text.casefold()]
  return all(value in allowed for value in values)
 if kind=='checkbox':return text.casefold() in {'si','sí','no','yes','true','false'}
 return kind in {'text','textarea'}

class Simulator:
 def __init__(self,data_path):
  self.data_path=data_path;self.database=Database(data_path/'autojob.sqlite3');self.library=ResumeLibrary(data_path);self.profile=ProfileStore(data_path);self.bank=AnswerBank(data_path)
  with closing(self.database.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS local_simulations (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, scenario TEXT NOT NULL, company TEXT NOT NULL, position TEXT NOT NULL, report_json TEXT NOT NULL)')
 def run(self,scenario,company,position,language='en',specialty='auto',custom_fields=None):
  if scenario not in SCENARIOS and not (scenario=='Personalizado' and custom_fields is not None):raise ValueError('Escenario desconocido')
  if custom_fields is not None:
   allowed={'text','email','phone','date','select','radio','multiple','checkbox','textarea','number','salary','experience','file','captcha','video','legal'}
   if not custom_fields or len(custom_fields)>100 or any(not isinstance(row,(list,tuple)) or len(row) not in {3,4} or not str(row[0]).strip() or row[1] not in allowed or type(row[2]) is not bool or (len(row)==4 and (not isinstance(row[3],list) or any(not isinstance(x,str) for x in row[3]))) for row in custom_fields):raise ValueError('Formulario personalizado inválido')
  profile=self.profile.load();selection=ResumeSelector(self.library).select(position,language,specialty)
  selected_cv=self.library.get(selection.resume_id) if selection.resume_id else None
  context={'language':language,'company':company,'position':position,'job_category':specialty,
           'employment_records':selected_cv['structure'].get('experience',[]) if selected_cv else [],
           'employment_verified':bool(selected_cv and selected_cv['reviewed']),
           'academic_projects':selected_cv['structure'].get('academic_projects',[]) if selected_cv else []}
  entries=[]
  for specification in (custom_fields if custom_fields is not None else SCENARIOS[scenario]):
   question,kind,required=specification[:3];options=specification[3] if len(specification)==4 else []
   if kind in {'captcha','video','legal'}:
    entries.append(dict(question=question,kind=kind,required=required,answer=None,status='PENDIENTE',reason='Requiere intervención humana',automatic=False));continue
   if kind=='file':
    entries.append(dict(question=question,kind=kind,required=required,answer=selection.resume_id,status='LISTO' if selection.resume_id else 'PENDIENTE',reason=selection.reason,automatic=bool(selection.resume_id)));continue
   r=resolve_question(question,context,profile,self.bank)
   # Sin opciones explícitas no se puede validar una respuesta de selección.
   automatic=r.automatic and valid_for_field(r.answer,kind,options)
   reason=r.reason if automatic or not r.automatic else 'Debe comprobarse el formato, la unidad o las opciones antes de completar.'
   citations=[]
   if r.field=='academic_projects' and selected_cv:
    for evidence in selected_cv['latest_analysis'].get('evidence',{}).get('academic_projects',[])[:3]:citations.append({'document':selected_cv['title'],'location':evidence['location'],'text':evidence['text']})
   for origin in profile.get('sources',{}).get(r.field or '',[]):
    if origin.get('resume_id'):
     try:
      document=self.library.get(origin['resume_id']);key={'skills':'technical_skills','soft_skills':'technical_skills','dates':'employment_dates','education_records':'education','experience_records':'experience','responsibilities':'experience'}.get(r.field,r.field)
      for evidence in document['latest_analysis'].get('evidence',{}).get(key,[])[:3]:citations.append({'document':origin.get('document','CV'),'location':evidence['location'],'text':evidence['text']})
     except Exception:pass
   entries.append(dict(question=question,kind=kind,required=required,options=options,answer=r.answer,status='LISTO' if automatic else 'REVISAR' if r.answer else 'PENDIENTE',reason=reason,source=r.source,citations=citations,confidence=r.confidence,verified=r.approved,automatic=automatic))
  blockers=[e['question'] for e in entries if e['required'] and e['status']!='LISTO']
  if not selection.resume_id and 'CV' not in blockers:blockers.append('CV')
  report=dict(id=str(uuid4()),scenario=scenario,company=company,position=position,language=language,cv=selection.resume_id,cv_title=selected_cv['title'] if selected_cv else None,cv_version=selected_cv['current_version'] if selected_cv else None,cv_revision=selected_cv['revision'] if selected_cv else None,profile_fingerprint=fingerprint(profile),fields=entries,blockers=blockers,status='PENDIENTE' if blockers else 'PREPARADA')
  with closing(self.database.connect()) as db,db:db.execute('INSERT INTO local_simulations VALUES (?,?,?,?,?,?)',(report['id'],datetime.now(timezone.utc).isoformat(),scenario,company,position,json.dumps(report,ensure_ascii=False)))
  return report
 def history(self):
  with closing(self.database.connect()) as db:reports=[json.loads(row[0]) for row in db.execute('SELECT report_json FROM local_simulations ORDER BY created_at DESC')]
  current=fingerprint(self.profile.load())
  for report in reports:
   stale=report.get('profile_fingerprint')!=current
   if report.get('cv'):
    try:
     cv=self.library.get(report['cv']);self.library.original_path(report['cv'])
     stale=stale or not cv['reviewed'] or cv['current_version']!=report.get('cv_version') or cv['revision']!=report.get('cv_revision')
    except Exception:stale=True
   if stale:
    report['status']='PENDIENTE';report['blockers'].append('Perfil o CV cambió: repetir simulación')
    for field in report['fields']:
     if field.get('automatic'):
      field['status']='REVISAR';field['automatic']=False;field['reason']='El perfil o CV cambió; vuelve a simular.'
  return reports
 def update_answer(self,simulation_id,index,answer,approved=False):
  with closing(self.database.connect()) as db,db:
   db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT report_json FROM local_simulations WHERE id=?',(simulation_id,)).fetchone()
   if not row:raise ValueError('Simulación inexistente')
   report=json.loads(row[0]);field=report['fields'][index]
   if report.get('profile_fingerprint')!=fingerprint(self.profile.load()):raise ValueError('El perfil cambió. Repite la simulación antes de aprobar respuestas.')
   if report.get('cv'):
    try:
     cv=self.library.get(report['cv']);self.library.original_path(report['cv'])
     if not cv['reviewed'] or cv['current_version']!=report.get('cv_version') or cv['revision']!=report.get('cv_revision'):raise ValueError('El CV cambió. Repite la simulación antes de aprobar respuestas.')
    except ValueError:raise
    except Exception:raise ValueError('El CV ya no está disponible. Repite la simulación.') from None
   if field['kind'] in {'captcha','video','legal','file'}:raise ValueError('Este campo requiere intervención fuera de la simulación')
   field['answer']=answer.strip() or None;field['status']='REVISAR' if field['answer'] else 'PENDIENTE';field['automatic']=False
   field['reason']='Editada manualmente; requiere revisión' if field['answer'] else 'Sin respuesta'
   if approved and field['answer']:
    if field.get('source')=='Declaración personal':raise ValueError('Las declaraciones sensibles requieren intervención humana')
    if not valid_for_field(field['answer'],field['kind'],field.get('options')):raise ValueError('La respuesta no coincide con el tipo de campo o sus opciones.')
    db.execute('INSERT INTO answer_bank VALUES (?,?,?,?,?,?,?)',(str(uuid4()),'Otras preguntas',report.get('language','en'),json.dumps([field['question']],ensure_ascii=False),field['answer'],1,fingerprint(self.profile.load())))
    field.update(status='LISTO',automatic=True,verified=True,source='Respuesta aprobada',confidence='alta',reason='Respuesta confirmada y guardada en el banco.')
   report['blockers']=[e['question'] for e in report['fields'] if e['required'] and e['status']!='LISTO']
   if not report['cv'] and 'CV' not in report['blockers']:report['blockers'].append('CV')
   report['status']='PENDIENTE' if report['blockers'] else 'PREPARADA'
   db.execute('UPDATE local_simulations SET report_json=? WHERE id=?',(json.dumps(report,ensure_ascii=False),simulation_id))
  return report
