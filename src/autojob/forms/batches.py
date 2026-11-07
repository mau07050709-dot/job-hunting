"""Lotes expresamente aprobados: criterios cerrados y vinculación por candidatura."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from urllib.parse import urlsplit
from hashlib import sha256
import json,re,math
from autojob.storage.database import utc_now
from autojob.forms.guard import origin

def create(store,criteria,maximum,hours,upload,explicit,mode='real',controlled=False):
    if not upload or not explicit:raise ValueError('Confirma adjuntos y envío ordinario del lote.')
    if type(maximum) is not int or not 1<=maximum<=100 or type(hours) is not int or not 1<=hours<=12:raise ValueError('Límite: 1–100 candidaturas y 1–12 horas.')
    if mode not in {'real','local'} or mode=='local' and not controlled:raise ValueError('Modo no permitido.')
    c=dict(criteria)
    required={'modalities','regions','domains','cv_ids','types','threshold','excluded','salary_min','salary_currency','salary_period'}
    if set(c)!=required:raise ValueError('Criterios incompletos o desconocidos.')
    if not all(isinstance(c[k],list) and c[k] and all(isinstance(v,str) and v.strip() for v in c[k]) for k in ['modalities','regions','domains','cv_ids','types']):raise ValueError('Define modalidades, regiones, dominios, CV y tipos de puesto.')
    if not set(c['modalities'])<={'remote','onsite','hybrid'} or not set(c['regions'])<={'Costa Rica','Cartago, Costa Rica'}:raise ValueError('Geografía no implementada; utiliza Costa Rica y/o Cartago, Costa Rica.')
    if not isinstance(c['threshold'],(float,int)) or not 0<=c['threshold']<=100 or not isinstance(c['excluded'],list) or not all(isinstance(x,str) for x in c['excluded']):raise ValueError('Umbral o exclusiones inválidos.')
    c['domains']=[origin(u) for u in c['domains']]
    for u in c['domains']:
        p=urlsplit(u)
        if mode=='real' and (p.scheme!='https' or p.hostname in {'127.0.0.1','localhost'} or p.hostname.endswith('.invalid')):raise ValueError('Dominios HTTPS públicos explícitos requeridos.')
        if mode=='local' and (p.scheme!='http' or p.hostname!='127.0.0.1'):raise ValueError('Pruebas limitadas a localhost.')
    if c['salary_min'] is not None:
        if not isinstance(c['salary_min'],(int,float)) or not math.isfinite(c['salary_min']) or c['salary_min']<0 or c['salary_currency'] not in {'USD','CRC'} or c['salary_period'] not in {'month','year','hour'}:raise ValueError('Salario mínimo requiere importe, moneda y período.')
    c['cv_hashes']={}
    for id in c['cv_ids']:
        cv=store.prep.compatibility.library.get(id)
        if not cv['reviewed']:raise ValueError('Todos los CV del lote deben estar revisados.')
        c['cv_hashes'][id]=sha256(store.prep.compatibility.library.original_path(id,verify=True).read_bytes()).hexdigest()
    id=uuid4().hex
    with closing(store.db.connect()) as db,db:db.execute('INSERT INTO submission_authorizations VALUES (?,?,?,0,?,?,?,?)',(id,utc_now(),(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat(),mode,store.prep.inputs_hash(),maximum,json.dumps({'_batch':c})))
    return id

def enroll(store,authorization,record,job):
    from autojob.forms.submissions import eligible_row
    from autojob.matching.engine import digest
    scope=json.loads(record['scope']);c=scope['_batch'];url=job.get('application_url') or job['url']
    row=next((r for r in store.prep.compatibility.rows() if r['job']['id']==job['id']),{})
    if not eligible_row(row) or store.duplicate(job):raise ValueError('Candidatura no elegible o envío anterior incierto/confirmado.')
    e=row['evaluation'];cv=e['resume_selection']['resume_id'];modality=job.get('modality')
    if origin(url) not in c['domains'] or modality not in c['modalities'] or cv not in c['cv_ids']:raise ValueError('Portal, modalidad o CV fuera del lote.')
    if modality=='remote':
        if 'Costa Rica' not in c['regions'] or e.get('geography')!='CONFIRMADO':raise ValueError('Costa Rica no confirmada o fuera del lote.')
    elif 'Cartago, Costa Rica' not in c['regions'] or job.get('country') not in {'Costa Rica','CR'} or job.get('province')!='Cartago':raise ValueError('Presencial/híbrido requiere Cartago, Costa Rica explícito.')
    score=e.get('score',e.get('professional_score'))
    if not isinstance(score,(int,float)) or score<c['threshold']:raise ValueError('Umbral profesional no acreditado.')
    if not any(t.casefold() in job['title'].casefold() for t in c['types']):raise ValueError('Tipo de puesto fuera del lote.')
    text=' '.join(str(job.get(k) or '') for k in ['title','description','mandatory_requirements'])
    if any(x.strip() and x.casefold() in text.casefold() for x in c['excluded']):raise ValueError('Requisito excluido por el lote.')
    if c['salary_min'] is not None:
        # Solo cantidades estructuradas comparables; no convertir ni adivinar salarios.
        raw=job.get('raw') or {};amount=raw.get('salary_min');period=raw.get('salary_period')
        if not isinstance(amount,(int,float)) or job.get('currency')!=c['salary_currency'] or period!=c['salary_period'] or amount<c['salary_min']:raise ValueError('Salario mínimo no verificable dentro del lote.')
    path=store.prep.compatibility.library.original_path(cv,verify=True);hash=sha256(path.read_bytes()).hexdigest()
    if hash!=c['cv_hashes'][cv]:raise ValueError('El CV del lote cambió.')
    rule=dict(origin=origin(url),url=url,job_hash=digest(job),cv_id=cv,cv_hash=hash,upload=True)
    from autojob.forms.doola import accepts
    if accepts(url):rule['captcha_provider']='hCaptcha'
    # Los protocolos con consentimientos extraordinarios conservan autorización individual.
    from autojob.forms import fiveca
    if fiveca.accepts(url):raise ValueError('5CA requiere sus avisos específicos; no se autoriza desde un lote ordinario.')
    from autojob.forms.greenhouse import TARGET,PROCESSORS
    if url==TARGET:rule['processor_origins']=PROCESSORS
    with closing(store.db.connect()) as db,db:
        db.execute('BEGIN IMMEDIATE');fresh=db.execute('SELECT scope,revoked,expires_at FROM submission_authorizations WHERE id=?',(authorization,)).fetchone()
        if not fresh or fresh['revoked'] or fresh['expires_at']<utc_now():raise ValueError('Lote revocado o caducado.')
        scope=json.loads(fresh['scope']);scope[job['id']]=rule;db.execute('UPDATE submission_authorizations SET scope=? WHERE id=?',(json.dumps(scope),authorization))
    return rule
