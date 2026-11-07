from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
import json,math
from autojob.search.jobs import JobStore
from autojob.profile.store import ProfileStore
from autojob.resumes.service import ResumeLibrary
from autojob.resumes.selection import ResumeSelector
from autojob.resumes.analysis import detect_language
from autojob.matching.engine import DEFAULT,VERSION,digest,evaluate,family,concepts

class Compatibility:
 def __init__(self,data_path):
  self.data_path=data_path;self.jobs=JobStore(data_path);self.db=self.jobs.db;self.profile=ProfileStore(data_path);self.library=ResumeLibrary(data_path);self.config_path=data_path/'compatibility-rules.json'
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS compatibility_evaluations(id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,evaluated_at TEXT NOT NULL,fingerprint TEXT NOT NULL,profile_version TEXT NOT NULL,cv_id TEXT,score REAL NOT NULL,confidence REAL NOT NULL,eligibility TEXT NOT NULL,engine_version TEXT NOT NULL,payload TEXT NOT NULL)')
   db.execute('CREATE INDEX IF NOT EXISTS compatibility_job_history ON compatibility_evaluations(job_id,id DESC)')
   db.execute('CREATE TABLE IF NOT EXISTS compatibility_errors(id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,occurred_at TEXT NOT NULL,error_type TEXT NOT NULL)')
 def config(self):
  config=json.loads(self.config_path.read_text(encoding='utf-8-sig')) if self.config_path.exists() else deepcopy(DEFAULT)
  self.validate(config);return config
 @staticmethod
 def validate(config):
  if not isinstance(config,dict) or not {'weights','aliases','certificates','eligible_score'}<=config.keys():raise ValueError('Faltan pesos, equivalencias, certificados o umbral.')
  weights=config['weights']
  if not isinstance(weights,dict) or set(weights)!=set(DEFAULT['weights']) or any(type(v) not in {int,float} or not math.isfinite(v) or v<0 for v in weights.values()) or abs(sum(weights.values())-100)>.001:raise ValueError('Los seis pesos deben ser números positivos o cero y sumar 100.')
  if not isinstance(config['aliases'],dict) or not config['aliases'] or len(config['aliases'])>1000 or any(not isinstance(k,str) or not isinstance(v,list) or not v or any(not isinstance(a,str) or not a.strip() or len(a)>100 for a in v) for k,v in config['aliases'].items()):raise ValueError('Equivalencias inválidas: cada concepto requiere una lista de frases.')
  if not isinstance(config['certificates'],list) or any(not isinstance(v,str) or not v.strip() for v in config['certificates']):raise ValueError('Lista de certificados inválida.')
  if type(config['eligible_score']) not in {int,float} or not 0<=config['eligible_score']<=100:raise ValueError('Umbral inválido.')
 def save_config(self,config):
  self.validate(config);temporary=self.config_path.with_suffix('.tmp');temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(self.config_path)
 def snapshot(self):
  profile=self.profile.load();cvs=[self.library.get(r['id']) for r in self.library.list()];config=self.config();selection_rules=ResumeSelector(self.library).load_rules()
  # Incluye confirmaciones, conflictos, estructura corregida y versión del documento, sin registrar PII en logs.
  version=digest(dict(profile=profile,cvs=[dict({k:cv.get(k) for k in ('id','revision','current_version','reviewed','fields','structure','manual_fields','language','specialty','is_default')},available=self.available(cv['id'])) for cv in cvs],rules=selection_rules))
  from autojob.profile.review import ReviewStore
  review=ReviewStore(self.data_path);version=digest(dict(base=version,review=review.decisions()))
  profile,cvs=review.effective(profile,cvs)
  from autojob.forms.answers9b import ScopedAnswers
  version=digest(dict(base=version,approved_answers=ScopedAnswers(self.data_path).rows()))
  from autojob.profile.semantic import SemanticAnswers
  version=digest(dict(base=version,personal_questions=SemanticAnswers(self.data_path).rows()))
  from autojob.profile.application_data import ApplicationData
  additional=ApplicationData(self.data_path);profile['_application_data']=additional.load()
  answers=ScopedAnswers(self.data_path).rows()
  answers += [dict(r,value=r['answer'],scope='company' if r['company'] else 'personal',scope_key=r['company'],origin='Preguntas personales',confirmed=True) for r in SemanticAnswers(self.data_path).rows() if r['answer']]
  answers += [dict(r,value=r['answer'],scope='company' if r['company'] else 'personal',scope_key=r['company'],origin='Pregunta frecuente') for r in additional.faqs() if r['confirmed'] and r['answer']]
  with closing(self.db.connect()) as db:
   from autojob.profile.answers import fingerprint
   for r in (db.execute('SELECT * FROM answer_bank WHERE approved=1') if db.execute("SELECT 1 FROM sqlite_master WHERE name='answer_bank'").fetchone() else []):
    if r['profile_hash']!=fingerprint(self.profile.load()):continue
    for q in json.loads(r['questions']):answers.append(dict(id=r['id'],question=q,value=r['answer'],scope='personal',scope_key='',confirmed=True,origin='Banco aprobado'))
  profile['_eligibility_answers']=answers
  from autojob.search.onsite import OnsitePreferences
  onsite=OnsitePreferences(self.data_path).load()
  profile['_onsite_localities']=onsite['localities']
  version=digest(dict(base=version,onsite=onsite))
  version=digest(dict(base=version,additional=profile['_application_data'],answers=answers))
  return dict(profile=profile,cvs=cvs,config=config,profile_version=version,review_summary={'confirmed':sum(d['state']=='CONFIRMADO' for d in review.decisions().values()),'drafts':sum(d['state']=='BORRADOR' for d in review.decisions().values())})
 def fingerprint(self,job,snapshot):
  relevant={k:v for k,v in job.items() if k not in {'checked_at','discovered_at'}}
  return digest(dict(job=relevant,profile=snapshot['profile_version'],config=snapshot['config'],engine=VERSION,date=datetime.now(timezone.utc).date().isoformat()))
 def selection(self,job,snapshot):
  category=family(job.get('title',''));specialty='customer_service' if category=='customer_service' else 'technical' if category else 'auto'
  vacancy=(job.get('title') or '')+'\n'+(job.get('description') or '')
  selected=asdict(ResumeSelector(self.library).select(vacancy,specialty=specialty))
  language=selected['language'];relevant=set(concepts(vacancy,snapshot['config']));alternatives=[]
  for cv in snapshot['cvs']:
   overlap=relevant & set(concepts(json.dumps(cv.get('fields',{}),ensure_ascii=False)+' '+json.dumps(cv.get('structure',{}),ensure_ascii=False),snapshot['config']))
   alternatives.append(dict(id=cv['id'],title=cv['title'],reviewed=bool(cv['reviewed']),language=cv['language'],specialty=cv['specialty'],matching_skills=sorted(overlap),compatible_language=cv['language']==language,compatible_specialty=cv['specialty'] in {specialty,'mixed'},available=self.available(cv['id'])))
  alternatives.sort(key=lambda a:(a['reviewed'] and a['available'],a['compatible_language'],a['compatible_specialty'],len(a['matching_skills'])),reverse=True)
  # El selector existente decide primero. Si no hay predeterminado entre varios revisados,
  # un mayor número de competencias documentadas permite desempatar, sin cambiar idioma/familia.
  suitable=[a for a in alternatives if a['reviewed'] and a['available'] and a['compatible_language'] and a['compatible_specialty']]
  if not selected['resume_id'] and suitable:
   best=max(len(a['matching_skills']) for a in suitable);best_items=[a for a in suitable if len(a['matching_skills'])==best]
   if len(best_items)==1:selected.update(resume_id=best_items[0]['id'],reason='CV revisado compatible con mayor cobertura de competencias documentadas.')
  selected['confirmed']=bool(selected['resume_id']);selected['status']='CV confirmado' if selected['resume_id'] else 'CV no disponible'
  if not selected['resume_id']:
   provisional=[a for a in alternatives if a['available'] and a['compatible_language'] and a['compatible_specialty'] and a['matching_skills']]
   if provisional:
    provisional.sort(key=lambda a:(a['specialty']==specialty,len(a['matching_skills'])),reverse=True)
    selected.update(resume_id=provisional[0]['id'],confirmed=True,status='Documento seleccionado automáticamente',reason='Archivo importado disponible, de idioma y especialidad compatibles. La confirmación de sus datos estructurados se evalúa por separado.')
   elif alternatives:selected['status']='CV que requiere revisión'
  selected['alternatives']=alternatives;selected['title']=next((a['title'] for a in alternatives if a['id']==(selected['resume_id'] or selected.get('provisional_resume_id'))),None)
  return selected
 def available(self,resume_id):
  try:self.library.original_path(resume_id);return True
  except ValueError:return False
 def latest(self):
  with closing(self.db.connect()) as db:return {r['job_id']:dict(json.loads(r['payload']),evaluation_id=r['id'],fingerprint=r['fingerprint']) for r in db.execute('SELECT * FROM compatibility_evaluations WHERE id IN (SELECT MAX(id) FROM compatibility_evaluations GROUP BY job_id)')}
 def history(self,job_id):
  with closing(self.db.connect()) as db:return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM compatibility_evaluations WHERE job_id=? ORDER BY id DESC',(job_id,))]
 def one(self,job,snapshot=None,force=False):
  snap=snapshot or self.snapshot();fingerprint=self.fingerprint(job,snap)
  with closing(self.db.connect()) as db:
   previous=db.execute('SELECT payload FROM compatibility_evaluations WHERE job_id=? AND fingerprint=? ORDER BY id DESC LIMIT 1',(job['id'],fingerprint)).fetchone()
  if previous and not force:return dict(json.loads(previous[0]),cached=True)
  from autojob.forms.answers9b import ScopedAnswers,restricted
  from autojob.profile.answers import norm
  answers={}
  from autojob.matching.semantics import applicable_answers
  eligible_answers=applicable_answers(snap['profile'],job)
  for answer in eligible_answers:
   if answer['confirmed'] and norm(answer['value']) in {'yes','si','no'} and not restricted(answer['question']):
    answers[digest(answer['question'])]='No' if norm(answer['value'])=='no' else 'Yes'
  # Vincular las respuestas a la evidencia exacta; nunca sobreescribir requisitos demostrados.
  from autojob.matching.engine import extract
  exact={digest(req['evidence']):answers[digest(norm(req['evidence']))] for req in extract(job,snap['config']) if digest(norm(req['evidence'])) in answers}
  profile=snap['profile'];v=profile['values'];manual=profile.get('manual',[])
  cr=all(k in manual for k in ['country','work_authorization']) and norm(str(v.get('country') or ''))=='costa rica' and v.get('work_authorization') is True and job.get('geography')=='CONFIRMADO' and 'costa rica' in norm(job.get('location') or '')
  answer_facts={digest(req['evidence']):[dict(text=str(a['value']),origin='Respuesta aprobada / '+str(a['id']),confirmed=True) for a in eligible_answers if norm(a['question'])==norm(req['evidence'])] for req in extract(job,snap['config'])}
  assessed_job=dict(job,_requirement_answers=exact,_requirement_answer_facts=answer_facts,_confirmed_cr_authorization=cr)
  result=evaluate(assessed_job,snap['profile'],snap['cvs'],snap['config'],self.selection(job,snap));result.update(profile_version=snap['profile_version'],profile_revision=snap['profile']['revision'],review_summary=snap.get('review_summary',{}),fingerprint=fingerprint)
  previous=self.history(job['id'])
  if previous:
   before=previous[0];result['change_from_previous']=dict(score_before=before['score'],score_after=result['score'],difference=round(result['score']-before['score'],1),eligibility_before=before['eligibility'],eligibility_after=result['eligibility'],engine_before=before['engine_version'])
  result['availability']=job.get('availability') if job.get('availability') in {'ABIERTA','CERRADA','NO VERIFICADA','ERROR DE VERIFICACIÓN'} else 'NO VERIFICADA'
  result['recommendation']=recommendation(result)
  with closing(self.db.connect()) as db,db:db.execute('INSERT INTO compatibility_evaluations(job_id,evaluated_at,fingerprint,profile_version,cv_id,score,confidence,eligibility,engine_version,payload) VALUES (?,?,?,?,?,?,?,?,?,?)',(job['id'],result['evaluated_at'],fingerprint,snap['profile_version'],result['resume_selection'].get('resume_id'),result['score'],result['confidence'],result['eligibility'],VERSION,json.dumps(result,ensure_ascii=False)))
  return result
 def batch(self,ids=None,force=False,cancel=lambda:False,progress=lambda value:None):
  snap=self.snapshot();jobs=[j for j in self.jobs.list() if ids is None or j['id'] in ids];results=[];errors=[]
  for index,job in enumerate(jobs):
   if cancel():break
   progress(f"Evaluando {index+1}/{len(jobs)} · {job.get('title','Sin título')}")
   try:results.append(self.one(job,snap,force))
   except Exception as exc:
    error=type(exc).__name__;errors.append(dict(job_id=job['id'],error=error))
    with closing(self.db.connect()) as db,db:db.execute('INSERT INTO compatibility_errors(job_id,occurred_at,error_type) VALUES (?,?,?)',(job['id'],datetime.now(timezone.utc).isoformat(),error))
  return dict(evaluated=len(results),cached=sum(r.get('cached',False) for r in results),errors=errors,cancelled=cancel())
 def rows(self,job_id=None,snapshot=None):
  snapshot=snapshot or self.snapshot()
  if job_id is None:
   evaluations=self.latest()
  else:
   with closing(self.db.connect()) as db:
    row=db.execute('SELECT * FROM compatibility_evaluations WHERE job_id=? ORDER BY id DESC LIMIT 1',(job_id,)).fetchone()
   evaluations={job_id:dict(json.loads(row['payload']),evaluation_id=row['id'],fingerprint=row['fingerprint'])} if row else {}
  rows=[]
  jobs=self.jobs.list() if job_id is None else self.jobs.list(job_id)
  for job in jobs:
   result=evaluations.get(job['id']);stale=bool(result and result['fingerprint']!=self.fingerprint(job,snapshot))
   rows.append(dict(job=job,evaluation=result,stale=stale))
  return rows

def report(result):
 if not result:return 'Sin evaluación. Selecciona ofertas y pulsa Evaluar.'
 lines=[f"EMPRESA: {result['company']}",f"PUESTO: {result['title']}",f"COMPATIBILIDAD PROFESIONAL: {result['score']} % ({result['band']})",f"RECOMENDACIÓN: {result.get('recommendation','Sin clasificar')}",f"VIGENCIA: {result.get('availability','NO VERIFICADA')}",f"ESTADO DEL CV: {result['resume_selection'].get('status','Pendiente')}",f"CAMBIOS: {result.get('change_from_previous','Primera evaluación')}",f"CONFIANZA: {result['confidence']} %",f"ELEGIBILIDAD: {result['eligibility']}",f"GEOGRAFÍA: {result['geography']}",f"OBLIGATORIOS: {result['mandatory_status']}",f"CV: {result['resume_selection'].get('title') or 'Pendiente'}",result['resume_selection'].get('reason',''),result['heuristic_notice'],f"Perfil revisión {result['profile_revision']} · Motor {result['engine_version']} · {result['evaluated_at']}",'','CRITERIOS: '+json.dumps(result['criteria'],ensure_ascii=False),'','BLOQUEOS Y ADVERTENCIAS:',*result['blocks'],*result['warnings'],'','REQUISITOS Y EVIDENCIAS:']
 for req in result['assessments']:
  lines.extend([f"{req['importance']} · {req['kind']}: {req['name']} — {req['state']}",req['reason'],'Oferta: '+req['evidence'],'Fuente: '+str(req['source'])])
  lines.extend('Perfil: '+fact['text']+' · '+fact['origin']+(' [confirmado]' if fact['confirmed'] else ' [sin revisar]') for fact in req['profile_evidence'])
 lines.extend(['','COINCIDENCIAS DOCUMENTADAS (pueden ser provisionales):'])
 lines.extend(r['kind']+' / '+r['name']+' · '+r['state']+' · '+r['reason'] for r in result['assessments'] if r.get('support',0)>0)
 lines.extend(['Revisiones explícitas del usuario: '+json.dumps(result.get('review_summary',{}),ensure_ascii=False),'','DATOS PUBLICADOS (null = desconocido):',json.dumps(result.get('published_facts',{}),ensure_ascii=False,indent=2),'','RESPONSABILIDADES PUBLICADAS:'])
 lines.extend(r['evidence'] for r in result.get('requirements',[]) if r['kind']=='responsibility')
 lines.extend(['','COMPARACIÓN DE CV:',json.dumps(result['resume_selection'].get('alternatives',[]),ensure_ascii=False,indent=2)])
 return '\n'.join(str(line) for line in lines)

def export(rows,filename):
 from openpyxl import Workbook
 book=Workbook();sheet=book.active;sheet.append(['Empresa','Puesto','Compatibilidad profesional','Confianza','Elegibilidad','Geografía','CV','Obsoleta','Fuente','Análisis','Recomendación','Vigencia','Estado CV','Puntuación anterior'])
 for row in rows:
  job=row['job'];e=row.get('evaluation') or {};values=[job.get('company'),job.get('title'),e.get('score'),e.get('confidence'),'OBSOLETA: REVISAR' if row['stale'] else e.get('eligibility','SIN EVALUAR'),e.get('geography',job.get('geography')),(e.get('resume_selection') or {}).get('title'),str(row['stale']),job.get('url'),report(e) if e else 'Sin evaluar',e.get('recommendation'),e.get('availability'),(e.get('resume_selection') or {}).get('status'),(e.get('change_from_previous') or {}).get('score_before')]
  sheet.append([str(v)[:32767] if v is not None else '' for v in values])
  for cell in sheet[sheet.max_row]:cell.data_type='s'
 book.save(filename)


def recommendation(result):
 if result.get('eligibility')=='INCOMPATIBLE':return 'D. Incompatibles'
 mandatory=[r for r in result.get('assessments',[]) if r['importance']=='OBLIGATORIO']
 missing=[r for r in mandatory if r['state']=='POR VERIFICAR' and not r.get('support')]
 # A/B expresan adecuación profesional, no geografía, vigencia ni autorización.
 if mandatory and not missing and result['score']>=80:return 'A. Alta compatibilidad'
 if mandatory and not missing and result['score']>=60:return 'B. Compatibilidad moderada'
 return 'C. Requieren verificación'
