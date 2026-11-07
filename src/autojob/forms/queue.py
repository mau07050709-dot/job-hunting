from contextlib import closing
from datetime import datetime,timezone
from uuid import uuid4
import json
from autojob.forms.preparation import Preparation
from autojob.browser.lock import ProfileLock

STATES={'POR PREPARAR','ANALIZANDO','RELLENANDO','PREPARADA','PENDIENTE','BLOQUEADA','ERROR','REQUIERE REVISIÓN'}
ACTIVE={'ANALIZANDO','RELLENANDO'}
def now():return datetime.now(timezone.utc).isoformat()

class PreparationQueue:
 def __init__(self,data_path):
  self.data_path=data_path;self.preparation=Preparation(data_path);self.db=self.preparation.db
  with closing(self.db.connect()) as db,db:
   db.execute("CREATE TABLE IF NOT EXISTS preparation_queue(job_id TEXT PRIMARY KEY,priority INTEGER NOT NULL,url TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('POR PREPARAR','ANALIZANDO','RELLENANDO','PREPARADA','PENDIENTE','BLOQUEADA','ERROR','REQUIERE REVISIÓN')),stage INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,last_action TEXT NOT NULL,updated_at TEXT NOT NULL,payload TEXT NOT NULL)")
   db.execute('CREATE TABLE IF NOT EXISTS preparation_queue_events(id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,run_id TEXT,at TEXT NOT NULL,state TEXT NOT NULL,details TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS preparation_queue_runs(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,result TEXT)')
   db.execute('CREATE TABLE IF NOT EXISTS preparation_site_permissions(origin TEXT PRIMARY KEY,profile_hash TEXT NOT NULL,confirmed_text INTEGER NOT NULL,updated_at TEXT NOT NULL)')
 def add(self,ids,url=None):
  rows={r['job']['id']:r for r in self.preparation.compatibility.rows()};added=0
  with closing(self.db.connect()) as db,db:
   for id in dict.fromkeys(ids):
    if id not in rows:continue
    from autojob.dispositions import decision
    if decision(db,rows[id]['job']):continue
    r=rows[id];j=r['job'];e=r['evaluation'] or {};priority=int(e.get('score',0)*10)+(3000 if e.get('geography')=='CONFIRMADO' else 0)+(1000 if j.get('modality')=='remote' else 0)+(10000 if e.get('eligibility')=='COMPATIBLE' and not r['stale'] else 0)
    payload=dict(company=j['company'],title=j['title'],score=e.get('score'),cv=e.get('resume_selection') or {},filled=[],pending=[],blocks=[],stages=[],interrupted=False)
    added+=db.execute('INSERT OR IGNORE INTO preparation_queue(job_id,priority,url,state,last_action,updated_at,payload) VALUES (?,?,?,?,?,?,?)',(id,priority,url or j.get('application_url') or j['url'],'POR PREPARAR','Añadida localmente',now(),json.dumps(payload,ensure_ascii=False))).rowcount
  return added
 def list(self):
  with closing(self.db.connect()) as db:return [dict(r,payload=json.loads(r['payload'])) for r in db.execute('SELECT * FROM preparation_queue ORDER BY priority DESC,updated_at,job_id')]
 def update(self,id,state,details,payload=None,stage=None,run_id=None):
  if state not in STATES:raise ValueError('No hay estados de envío en la cola de preparación.')
  with closing(self.db.connect()) as db,db:
   row=db.execute('SELECT * FROM preparation_queue WHERE job_id=?',(id,)).fetchone()
   if not row:return
   from autojob.dispositions import decision
   job=db.execute('SELECT payload FROM discovered_jobs WHERE id=?',(id,)).fetchone()
   if job and decision(db,dict(json.loads(job['payload']),id=id)):
    state='BLOQUEADA';details='DESCARTADA POR EL USUARIO; evidencia histórica conservada.'
   db.execute('UPDATE preparation_queue SET state=?,stage=?,last_action=?,updated_at=?,payload=? WHERE job_id=?',(state,row['stage'] if stage is None else stage,details,now(),row['payload'] if payload is None else json.dumps(payload,ensure_ascii=False),id))
   db.execute('INSERT INTO preparation_queue_events(job_id,run_id,at,state,details) VALUES (?,?,?,?,?)',(id,run_id,now(),state,details))
 def history(self,id):
  with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM preparation_queue_events WHERE job_id=? ORDER BY id DESC',(id,))]
 def recover(self):
  lock=ProfileLock(self.data_path/'preparation-queue.lock')
  try:lock.acquire()
  except Exception:return 0
  try:
   rows=[r for r in self.list() if r['state'] in ACTIVE]
   for row in rows:
    p=row['payload'];p['interrupted']=True;self.update(row['job_id'],'REQUIERE REVISIÓN','Ejecución interrumpida: reanalizar y reconstruir; no se supone estado externo guardado.',p)
   return len(rows)
  finally:lock.release()
 def requeue(self,ids,interrupted_only=False):
  for row in self.list():
   if row['job_id'] in ids and row['state'] not in ACTIVE and (not interrupted_only or row['payload'].get('interrupted')):self.update(row['job_id'],'POR PREPARAR','Reintento explícito; se volverá a analizar el formulario.')
 def priority(self,id,value):
  with closing(self.db.connect()) as db,db:db.execute('UPDATE preparation_queue SET priority=? WHERE job_id=?',(int(value),id))
 def remove(self,ids):
  with closing(self.db.connect()) as db,db:
   for id in ids:db.execute("DELETE FROM preparation_queue WHERE job_id=? AND state NOT IN ('ANALIZANDO','RELLENANDO')",(id,))
 def allow_site(self,url,confirmed):
  from autojob.forms.guard import origin
  site=origin(url);fingerprint=self.preparation.inputs_hash()
  with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO preparation_site_permissions VALUES (?,?,?,?)',(site,fingerprint,int(confirmed),now()))
 def site_allowed(self,url):
  from autojob.forms.guard import origin
  with closing(self.db.connect()) as db:r=db.execute('SELECT * FROM preparation_site_permissions WHERE origin=?',(origin(url),)).fetchone()
  return bool(r and r['confirmed_text'] and r['profile_hash']==self.preparation.inputs_hash())
 def run(self,settings,ids=None,pause=lambda:False,stop=lambda:False,progress=lambda message:None,processor=None):
  from autojob.forms.runner import process
  lock=ProfileLock(self.data_path/'preparation-queue.lock');lock.acquire();run_id=str(uuid4());results=[]
  try:
   with closing(self.db.connect()) as db,db:db.execute('INSERT INTO preparation_queue_runs(id,started_at) VALUES (?,?)',(run_id,now()))
   rows=[r for r in self.list() if r['state']=='POR PREPARAR' and (ids is None or r['job_id'] in ids)]
   from autojob.control import ControlStore
   omitted=ControlStore(self.data_path).excluded();rows=[r for r in rows if r['job_id'] not in omitted]
   for index,row in enumerate(rows):
    if pause() or stop():break
    id=row['job_id'];progress(f"Preparando {index+1}/{len(rows)} · {row['payload'].get('title','')}")
    self.update(id,'ANALIZANDO','Abriendo y analizando; envío final deshabilitado.',run_id=run_id)
    with closing(self.db.connect()) as db,db:db.execute('UPDATE preparation_queue SET attempts=attempts+1 WHERE job_id=?',(id,))
    try:
     result=(processor or process)(self,row,settings,pause,stop,run_id)
     if processor is None and result.get('authentication'):
      self.update(id,'ANALIZANDO','Preparación guardada antes de comprobar autenticación.',result,result.get('stage',0),run_id)
      from autojob.auth.external import ExternalAuth
      from autojob.auth.permissions import scope
      engine=ExternalAuth(self.data_path);engine.defer_interventions=getattr(self,'defer_interventions',False);origin=result['authentication']['origin'];accounts=[a for a in engine.accounts.list() if a['origin']==origin]
      if len(accounts)==1:
       account=accounts[0];action='LOGIN' if account['exists_remotely'] else 'REGISTRO'
       if engine.permissions.allowed(origin,action,scope(engine.accounts,account,action)):
        outcome=engine.run(settings,account['id'],action,result.get('last_url') or row['url'],id,row['payload'].get('title','Vacante'),pause,stop)
        result['authentication_result']=outcome;result['verification_status']=outcome['state']
        if outcome['state']=='ACTIVA' and not pause() and not stop():result=process(self,row,settings,pause,stop,run_id)
     if processor is None and result.get('auto_resume') and not pause() and not stop():result=process(self,row,settings,pause,stop,run_id)
     if result.get('interrupted'):

      state='POR PREPARAR' if pause() else 'PENDIENTE';self.update(id,state,'PAUSA: progreso local conservado.' if pause() else 'DETENIDA: progreso local conservado.',result,run_id=run_id);results.append(state);break
     self.update(id,result.get('state','PENDIENTE'),result.get('last_action','Preparación local conservada; sin envío.'),result,result.get('stage',0),run_id);results.append(result.get('state','PENDIENTE'))
    except Exception as exc:
     latest=next((r for r in self.list() if r['job_id']==id),row);payload=dict(latest['payload']);payload['blocks']=payload.get('blocks',[])+[dict(type=type(exc).__name__,evidence='Error de consulta o navegación; no se registran valores personales en logs.')];self.update(id,'ERROR',type(exc).__name__+'; se continúa con la siguiente vacante.',payload,run_id=run_id);results.append('ERROR')
   result=dict(processed=len(results),states=results,paused=pause(),stopped=stop())
   return result
  finally:
   with closing(self.db.connect()) as db,db:db.execute('UPDATE preparation_queue_runs SET finished_at=?,result=? WHERE id=?',(now(),json.dumps(locals().get('result',{'interrupted':True})),run_id))
   lock.release()
