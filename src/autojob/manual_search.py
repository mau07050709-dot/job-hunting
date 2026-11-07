"""Búsqueda asistida: solo devuelve enlaces para postular manualmente."""
import json,re,time
from contextlib import closing
from urllib.parse import urlsplit
from datetime import datetime,timezone
from autojob.autonomous import AutomaticCoordinator,verified_jobs
from autojob.matching.engine import candidate,family
from autojob.search.availability import Availability
from autojob.forms.navigation import category_url
from autojob.search.access_policy import excluded_job,blocked_source,paywall_url

def useful_url(url):
    if blocked_source(url) or paywall_url(url):return False
    try:p=urlsplit(url or '')
    except (ValueError,TypeError):return False
    if p.path.rstrip('/') in {'','/jobs','/careers','/search','/remote-jobs'} and not re.search(r'(?:gh_jid|job_id|requisition|jid)=',p.query):return False
    if p.hostname=='jobs.lever.co' and len(p.path.strip('/').split('/'))<2:return False
    if p.hostname=='apply.workable.com' and '/j/' not in p.path:return False
    return p.scheme=='https' and bool(p.hostname) and not p.username and not p.password and not category_url(url) and not re.search(r'/(?:register|login|sign-in|signup|pricing|subscribe|job-seekers/account)(?:/|$)',p.path,re.I)
def link_for(job):return next((u for u in [job.get('application_url'),job.get('url')] if useful_url(u)),None)

def application_rows(result):
    rows=[];seen=set()
    for row in result.get('results',[])+result.get('review',[]):
        key=row['job'].get('id') or row.get('url')
        if key not in seen:
            seen.add(key);rows.append(row)
    return rows

def identity_keys(job,url=None):
    from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
    keys={'id:'+str(job['id'])} if job.get('id') else set()
    links=[url,job.get('url'),job.get('application_url')]+[x.get('url') for x in job.get('source_links',[])]
    for link in links:
        if not useful_url(link):continue
        p=urlsplit(link);path=p.path.rstrip('/')
        if p.hostname in {'apply.workable.com','jobs.lever.co'}:path=re.sub(r'/apply$','',path)
        query=urlencode(sorted((k,v) for k,v in parse_qsl(p.query) if not k.startswith('utm_') and k.lower() not in {'ref','source','gh_src','referral','trackingid'}))
        keys.add('url:'+urlunsplit((p.scheme.lower(),p.netloc.lower(),path,query,'')))
    return keys

class ResultsStore:
    def __init__(self,db):
        self.db=db
        with closing(db.connect()) as c,c:
            seeded=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_application_catalog'").fetchone()
            c.execute('CREATE TABLE IF NOT EXISTS manual_search_results(id INTEGER PRIMARY KEY,at TEXT NOT NULL,payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS manual_application_catalog(job_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,added_at TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS manual_search_preferences(id INTEGER PRIMARY KEY CHECK(id=1),target INTEGER NOT NULL CHECK(target BETWEEN 1 AND 50))')
            old=c.execute('SELECT payload FROM manual_search_results ORDER BY id DESC LIMIT 1').fetchone() if not seeded else None
        if old:self.merge(json.loads(old[0]))
    def target(self):
        with closing(self.db.connect()) as c:r=c.execute('SELECT target FROM manual_search_preferences WHERE id=1').fetchone()
        return r[0] if r else 30
    def set_target(self,value):
        if type(value) is not int or not 1<=value<=50:raise ValueError('Elige entre 1 y 50 vacantes nuevas.')
        with closing(self.db.connect()) as c,c:c.execute('INSERT OR REPLACE INTO manual_search_preferences VALUES (1,?)',(value,))
    def raw_rows(self):
        with closing(self.db.connect()) as c:return [(r['kind'],json.loads(r['payload'])) for r in c.execute('SELECT kind,payload FROM manual_application_catalog ORDER BY rowid')]
    def known_keys(self):
        rows=self.raw_rows();return set().union(*(identity_keys(r['job'],r.get('url')) for _,r in rows)) if rows else set()
    def add(self,row,kind='review'):
        return bool(self.merge({kind:[row]}))
    def merge(self,result):
        known=self.known_keys();count=0
        with closing(self.db.connect()) as c,c:
            for kind in ('results','review'):
                for row in result.get(kind,[]):
                    if excluded_job(row['job']) or not useful_url(row.get('url')):continue
                    keys=identity_keys(row['job'],row.get('url'))
                    if keys & known:continue
                    c.execute('INSERT OR IGNORE INTO manual_application_catalog VALUES (?,?,?,?)',(row['job']['id'],kind,json.dumps(row,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
                    known.update(keys);count+=1
        return count
    def save(self,result):
        self.merge(result)
        self.record(result)
    def record(self,result):
        with closing(self.db.connect()) as c,c:c.execute('INSERT INTO manual_search_results(at,payload) VALUES (?,?)',(datetime.now(timezone.utc).isoformat(),json.dumps(result,ensure_ascii=False)))
    def latest(self):
        with closing(self.db.connect()) as c:
            old=c.execute('SELECT payload FROM manual_search_results ORDER BY id DESC LIMIT 1').fetchone()
            catalog=c.execute('''SELECT a.kind,a.payload,j.payload AS current
                FROM manual_application_catalog a LEFT JOIN discovered_jobs j ON a.job_id=j.id
                ORDER BY a.rowid''').fetchall()
        result=json.loads(old[0]) if old else {};result['results']=[];result['review']=[]
        for entry in catalog:
            row=json.loads(entry['payload'])
            if not excluded_job(row['job']) and not excluded_job(json.loads(entry['current'] or '{}')) and useful_url(row.get('url')):
                result[entry['kind']].append(row)
        result.setdefault('reason',f"{len(application_rows(result))} ofertas disponibles en POSTULACIONES.")
        return result

def location_priority(job):
    from autojob.search.geography import normalize
    if job.get('modality')=='remote':
        return 0 if 'costa rica' in normalize(job.get('location') or '') else 1
    return 2

def matching_job(job,evaluation,areas,localities=None):
    from autojob.search.geography import classify
    area=family(job['title'])
    # Un título limitado a otro país contradice una etiqueta regional amplia.
    # No contar esa ambigüedad como permiso para trabajar desde Costa Rica.
    foreign=r'mexico|colombia|argentina|philippines|india|usa|united states|canada|uk|bulgaria|brazil|poland|portugal|south africa|bangladesh|indonesia|pakistan'
    from autojob.search.geography import normalize
    title=normalize(job['title'])
    if re.search(r'\(\s*(?:remote[ ,/-]+)?(?:'+foreign+r')\s*\)\s*$|(?: - | – | — )(?:'+foreign+r')\s*$',title):return False
    if area not in areas or evaluation.get('eligibility')=='INCOMPATIBLE' or evaluation.get('score',0)<40:return False
    if job.get('geography')!='CONFIRMADO' or evaluation.get('geography')!='CONFIRMADO':return False
    if job.get('modality')!='remote':
        from autojob.search.onsite import DEFAULT_LOCALITIES,locality_matches,fast_food,night_status
        if not locality_matches(job,DEFAULT_LOCALITIES if localities is None else localities):return False
        if fast_food(job) or night_status(job)=='DIURNO':return False
    if re.search(r'\b(?:director|principal|staff|manager|lead|architect|head of|senior vice)\b',job['title'],re.I):return False
    if area!='customer_service' and re.search(r'\bsenior\b',job['title'],re.I):return False
    for a in evaluation.get('assessments',[]):
        if a['importance']=='OBLIGATORIO' and a['state']=='NO CUMPLE':return False
        if a.get('kind') in {'authorization','residence'} and a['state']!='CUMPLE':return False
    return True

class ManualSearch(AutomaticCoordinator):
    def __init__(self,settings):super().__init__(settings);self.results=ResultsStore(self.jobs.db)
    def run(self,options,pause=lambda:False,stop=lambda:False,progress=lambda s:None,resume_ids=None,services=None):
        from autojob.search.targeted import TargetedPages,queries_for
        from autojob.search.jobs import Connector
        from autojob.forms.submissions import SubmissionStore
        from autojob.profile.answers import norm
        from autojob.search.onsite import OnsitePreferences,locality_matches,fast_food,night_status
        preferences=OnsitePreferences(self.settings.data_path).load()
        services=services or {};target=options.get('target',self.results.target());self.results.set_target(target)
        deadline=time.monotonic()+600;cancel=lambda:pause() or stop() or time.monotonic()>deadline
        new=0;checked=set();errors=[];stats={'considered':0,'duplicates':0,'incompatible':0};known=self.results.known_keys()
        from autojob.completed import CompletedApplications
        known|=CompletedApplications(self.settings.data_path).keys()
        snap=self.compatibility.snapshot();person=candidate(snap['profile'],snap['cvs']);areas={family(f['text']) for group in person['buckets'].values() for f in group if family(f['text'])}
        profile=snap['profile'];values=profile['values']
        legal=norm(str(values.get('country') or ''))=='costa rica' and values.get('work_authorization') is True and ('work_authorization' in profile.get('manual',[]) or bool(profile.get('sources',{}).get('work_authorization')))
        availability=Availability(self.jobs);previous=SubmissionStore(self.settings.data_path)
        def publish(state='EN CURSO',reason=None):
            result=self.results.latest();result.update(state=state,target=target,new_count=new,search=dict(stats,errors=errors),reason=reason or f'{new}/{target} vacantes nuevas guardadas; se conservan las anteriores.')
            self.results.record(result);return result
        if not legal:return publish('FINALIZADO','No se añadieron vacantes: falta confirmar país de residencia y autorización laboral en Costa Rica en MIS DATOS.')
        def process(allow_local=False,local_only=False):
            nonlocal new,known
            jobs=sorted(self.jobs.list(),key=lambda j:(0 if local_only and night_status(j)=="NOCTURNO PUBLICADO" else 1,location_priority(j)))
            for job in jobs:
                if cancel() or new>=target:return
                if job['id'] in checked or (job.get('modality')!='remote' and not allow_local):continue
                if local_only and job.get('modality')=='remote':continue
                if job.get('modality')!='remote':
                    if not locality_matches(job,preferences['localities']) or fast_food(job) or night_status(job)=='DIURNO':continue
                keys=identity_keys(job,link_for(job))
                if keys & known:stats['duplicates']+=1;continue
                if job.get('geography')!='CONFIRMADO' or family(job['title']) not in areas:continue
                if excluded_job(job) or not link_for(job) or self.store.is_excluded(job) or previous.duplicate(job):continue
                checked.add(job['id']);stats['considered']+=1;progress(f'{new}/{target} nuevas · evaluando {job["company"]} · {job["title"]}')
                try:e=self.compatibility.one(job,snap)
                except Exception as exc:errors.append('Evaluación: '+type(exc).__name__);continue
                if not matching_job(job,e,areas,preferences['localities']):stats['incompatible']+=1;continue
                try:
                    if services.get('check'):services['check'](job)
                    elif job['source']=='Saplic CR':
                        job.update(availability='NO VERIFICADA',availability_evidence='Anuncio público leído; comprueba vigencia y horario en el portal')
                    elif job.get('structured_discovery_at') and job['source']=='Himalayas':
                        # La API filtrada devuelve puestos activos y su enlace de postulación original.
                        # Mantener la fecha de publicación independiente de la comprobación.
                        job.update(availability='ABIERTA',availability_evidence='Listada activa en API oficial de Himalayas para Costa Rica; caché de hasta 24 horas',availability_checked_at=datetime.now(timezone.utc).isoformat())
                        with closing(self.jobs.db.connect()) as c,c:
                            record=c.execute('SELECT payload FROM discovered_jobs WHERE id=?',(job['id'],)).fetchone()
                            if record:
                                payload=json.loads(record['payload']);payload.update({k:job[k] for k in ('availability','availability_evidence','availability_checked_at')});c.execute('UPDATE discovered_jobs SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),job['id']))
                    else:availability.check(job)
                except Exception as exc:errors.append('Comprobación: '+type(exc).__name__);continue
                fresh=next(iter(self.jobs.list(job['id'])),None)
                if fresh is None:continue
                if job.get('structured_discovery_at') or job['source']=='Saplic CR':fresh.update(availability=job.get('availability'),availability_evidence=job.get('availability_evidence'))
                if fresh.get('availability') in {'CERRADA','ERROR DE VERIFICACIÓN','REQUIERE PAGO'} or excluded_job(fresh):continue
                url=link_for(fresh)
                if not url or identity_keys(fresh,url)&known:continue
                row=dict(job=fresh,url=url,score=e.get('score'),geography=fresh['geography'],verification=fresh.get('availability'),reason=fresh.get('availability_evidence') or 'Revisa disponibilidad en el portal',night_status=night_status(fresh) if fresh.get('modality')=='onsite' else None,source_url=fresh.get('discovery_url') or fresh['url'])
                kind='results' if fresh.get('availability')=='ABIERTA' else 'review'
                if self.results.add(row,kind):
                    new+=1;known.update(identity_keys(fresh,url));progress(f'{new}/{target} vacantes nuevas añadidas a POSTULACIONES')
        if preferences['night_search'] and preferences['localities'] and not cancel():
            from autojob.search.local_jobs import LocalJobs
            loader=LocalJobs(self.jobs,preferences['localities'],cancel,progress)
            # Las pruebas controladas proveen su propia fuente; nunca consultan Internet implícitamente.
            local_search=services.get('local_search')
            if local_search is not None or not services:
                try:
                    raw_jobs=local_search(preferences['localities']) if local_search else loader.search()
                    for raw in raw_jobs:
                        if cancel():break
                        raw=dict(raw,night_status=night_status(raw))
                        for local_job in Connector('Saplic CR').search_jobs([],payload=[raw]):
                            if locality_matches(local_job,preferences['localities']) and not fast_food(local_job):
                                local_job.update(geography='CONFIRMADO',geography_evidence='Ciudad y país publicados coinciden con la selección presencial')
                                self.jobs.add(local_job)
                except Exception as exc:
                    errors.append('Búsqueda local: '+type(exc).__name__)
                errors.extend(loader.errors)
            process(allow_local=True,local_only=True)
        process()
        if new<target and not cancel():
            if services.get('search'):
                report=services['search'](options['queries'],options['sources'],None,cancel,progress);errors.extend(report.get('errors',[]));process()
            else:
                if 'Himalayas' in options['sources']:
                    pages=TargetedPages(self.jobs,queries_for(areas),cancel,progress,fetch=services.get('fetch'))
                    for data in pages:
                        for job in Connector('Himalayas').search_jobs([],payload=data):
                            if cancel():break
                            if not excluded_job(job):self.jobs.add(job)
                        process()
                        if new>=target or cancel():break
                    errors.extend(pages.errors)
                if new<target and not cancel():
                    report=self.jobs.search(options['queries'],[s for s in options['sources'] if s!='Himalayas'],None,cancel,progress);errors.extend(report.get('errors',[]));process()
        if new<target and not cancel():process(allow_local=True)
        stopped=cancel();reason=f'{new}/{target} vacantes nuevas añadidas a POSTULACIONES; las anteriores se conservan.'
        if new<target:reason+=' '+('Búsqueda pausada o límite de tiempo alcanzado.' if stopped else 'Se agotaron las páginas y fuentes consultadas con coincidencia y geografía verificadas; no se completó el objetivo.')
        if errors:reason+=f' {len(errors)} incidencias de fuentes o evaluación.'
        return publish('PAUSADO' if stopped else 'FINALIZADO',reason)
