"""Permiso interno de una ejecución iniciada por la persona; sin lotes ni diálogos."""
from contextlib import closing
from uuid import uuid4
from hashlib import sha256
from urllib.parse import urlsplit
import ipaddress,json
from autojob.storage.database import utc_now

def ensure(store):
    with closing(store.db.connect()) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS autonomous_executions(id TEXT PRIMARY KEY,authorization_id TEXT NOT NULL,state TEXT NOT NULL,target INTEGER NOT NULL,started_at TEXT NOT NULL,updated_at TEXT NOT NULL)')

def begin(store,target,mode='real',controlled=False):
    if type(target) is not int or not 1<=target<=10000:raise ValueError('Objetivo inválido.')
    if mode not in {'real','local'} or mode=='local' and not controlled:raise ValueError('Ejecución local no controlada.')
    ensure(store);id=uuid4().hex;token=uuid4().hex;stamp=utc_now();fingerprint=store.prep.inputs_hash()
    with closing(store.db.connect()) as db,db:
        db.execute('INSERT INTO autonomous_executions VALUES (?,?,?,?,?,?)',(id,token,'EN CURSO',target,stamp,stamp))
        db.execute('INSERT INTO submission_authorizations VALUES (?,?,?,0,?,?,?,?)',(token,stamp,'9999-12-31T23:59:59+00:00',mode,fingerprint,target,json.dumps({'_execution':{'id':id}})))
    return token

def preparation_ticket(store,job):
    """RESOLVER recupera una preparación ya autorizada; nunca autoriza otro envío."""
    from autojob.matching.engine import digest
    if store.duplicate(job):raise ValueError('Resultado final existente; solo se puede revisar.')
    with closing(store.db.connect()) as db:
        records=[dict(r) for r in db.execute('SELECT * FROM submission_authorizations WHERE revoked=0 ORDER BY created_at DESC')]
    old=next(((r,json.loads(r['scope'])[job['id']]) for r in records if job['id'] in json.loads(r['scope'])),None)
    if not old or old[1].get('job_hash')!=digest(job) or not old[1].get('upload'):raise ValueError('Pulsa INICIAR para preparar esta candidatura con tus datos confirmados.')
    path=store.prep.compatibility.library.original_path(old[1]['cv_id'],verify=True)
    if sha256(path.read_bytes()).hexdigest()!=old[1]['cv_hash']:raise ValueError('El CV cambió; pulsa INICIAR para preparar su nueva versión.')
    token=begin(store,1,old[0]['mode'],old[0]['mode']=='local')
    with closing(store.db.connect()) as db,db:
        record=db.execute('SELECT scope FROM submission_authorizations WHERE id=?',(token,)).fetchone();scope=json.loads(record['scope']);scope['_prepare_only']=True
        previous_scope=json.loads(old[0]['scope'])
        if previous_scope.get('_consents'):scope['_consents']=previous_scope['_consents']
        db.execute('UPDATE submission_authorizations SET scope=? WHERE id=?',(json.dumps(scope),token))
    store.permission(token,job)
    return token

def state(store,token,value):
    ensure(store)
    if value not in {'EN CURSO','EN ESPERA','PAUSADO','DETENIDO','FINALIZADO','INTERRUMPIDO'}:raise ValueError('Estado inválido.')
    with closing(store.db.connect()) as db,db:db.execute('UPDATE autonomous_executions SET state=?,updated_at=? WHERE authorization_id=?',(value,utc_now(),token))

def recover(store):
    ensure(store)
    with closing(store.db.connect()) as db,db:db.execute("UPDATE autonomous_executions SET state='INTERRUMPIDO',updated_at=? WHERE state IN ('EN CURSO','EN ESPERA')",(utc_now(),))

def close_execution(store,token):
    ensure(store)
    with closing(store.db.connect()) as db,db:db.execute("UPDATE autonomous_executions SET state='INTERRUMPIDO',updated_at=? WHERE authorization_id=? AND state IN ('EN CURSO','EN ESPERA')",(utc_now(),token))

def public_destination(url,mode):
    p=urlsplit(url)
    if p.username or p.password or not p.hostname:raise ValueError('Destino no verificable.')
    if mode=='local':
        if p.scheme!='http' or p.hostname!='127.0.0.1':raise ValueError('La prueba solo puede utilizar localhost.')
        return
    if p.scheme!='https' or p.hostname=='localhost' or p.hostname.endswith(('.invalid','.test','.local')):raise ValueError('El portal de la candidatura debe ser HTTPS público.')
    try:
        if not ipaddress.ip_address(p.hostname).is_global:raise ValueError('Destino privado no permitido.')
    except ValueError as exc:
        if 'privado' in str(exc):raise

def enroll(store,token,record,job):
    from autojob.forms.submissions import UNSAFE,eligible_row
    from autojob.forms.guard import origin
    from autojob.matching.engine import digest
    ensure(store)
    with closing(store.db.connect()) as db:
        run=db.execute('SELECT * FROM autonomous_executions WHERE authorization_id=?',(token,)).fetchone()
        used=db.execute('SELECT COUNT(*) FROM submission_attempts WHERE authorization_id=? AND state IN ('+','.join('?' for _ in UNSAFE)+')',(token,*UNSAFE)).fetchone()[0]
        rejected=db.execute("SELECT COUNT(*) FROM submission_attempts WHERE authorization_id=? AND state='RECHAZADA'",(token,)).fetchone()[0]
    if not run or run['state'] not in {'EN CURSO','EN ESPERA'}:raise ValueError('Pulsa INICIAR para reanudar esta ejecución.')
    scope=json.loads(record['scope']);old=scope.get(job['id'])
    own=old and any(a['authorization_id']==token and a['job_id']==job['id'] and a['state']=='ENVIANDO' for a in store.rows())
    if not own and (used-rejected>=run['target'] or store.duplicate(job)):raise ValueError('Objetivo alcanzado o envío anterior confirmado/incierto.')
    row=next((r for r in store.prep.compatibility.rows() if r['job']['id']==job['id']),{})
    if row.get('stale'):
        store.prep.compatibility.one(job,force=True)
        row=next((r for r in store.prep.compatibility.rows() if r['job']['id']==job['id']),{})
    if not eligible_row(row):raise ValueError('Falta verificar requisitos, geografía, vigencia o CV.')
    url=job.get('application_url') or job['url'];public_destination(url,record['mode'])
    cv=row['evaluation']['resume_selection']['resume_id'];path=store.prep.compatibility.library.original_path(cv,verify=True)
    rule=dict(origin=origin(url),url=url,job_hash=digest(job),cv_id=cv,cv_hash=sha256(path.read_bytes()).hexdigest(),upload=True,execution_authorized=True)
    if scope.get('_prepare_only'):rule['preparation_only']=True
    from autojob.forms.doola import accepts
    if accepts(url):rule['captcha_provider']='hCaptcha'
    from autojob.forms.greenhouse import TARGET,PROCESSORS
    if url==TARGET:rule['processor_origins']=PROCESSORS
    from autojob.forms import fiveca
    if fiveca.accepts(url):
        consent=(scope.get('_consents') or {}).get(job['id'],{})
        if consent.get('job_hash')!=digest(job) or consent.get('values')!=fiveca.consents():raise ValueError('5CA requiere revisar sus consentimientos extraordinarios.')
        rule['specific_consents']=consent['values']
    if old and old!=rule:raise ValueError('La candidatura o el CV cambiaron; revalidar antes de continuar.')
    with closing(store.db.connect()) as db,db:
        fresh=db.execute('SELECT scope,revoked FROM submission_authorizations WHERE id=?',(token,)).fetchone()
        if not fresh or fresh['revoked']:raise ValueError('Ejecución detenida.')
        scope=json.loads(fresh['scope']);scope[job['id']]=rule;db.execute('UPDATE submission_authorizations SET scope=? WHERE id=?',(json.dumps(scope),token))
        db.execute('UPDATE submission_authorizations SET max_count=? WHERE id=?',(run['target']+rejected,token))
    return rule

def approve_extra(store,token,job,values):
    from autojob.forms import fiveca
    from autojob.matching.engine import digest
    if not fiveca.accepts(job.get('application_url') or job['url']) or values!=fiveca.consents() or store.duplicate(job):raise ValueError('Avisos o candidatura no válidos.')
    with closing(store.db.connect()) as db,db:
        row=db.execute('SELECT scope,revoked FROM submission_authorizations WHERE id=?',(token,)).fetchone()
        if not row or row['revoked']:raise ValueError('Pulsa INICIAR para continuar.')
        scope=json.loads(row['scope']);scope.setdefault('_consents',{})[job['id']]={'job_hash':digest(job),'values':values};db.execute('UPDATE submission_authorizations SET scope=? WHERE id=?',(json.dumps(scope),token))
