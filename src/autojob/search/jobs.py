"""Conectores públicos y persistencia de descubrimiento, sin postulaciones."""
from contextlib import closing
from datetime import datetime,timezone
from hashlib import sha256
from html import unescape
import json,re,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from autojob.storage.database import Database
from autojob.search.access_policy import excluded_job,blocked_source

ENDPOINTS={'Boston Scientific CR':'https://jobs.bostonscientific.com/search/?q=&locationsearch=Cartago','Working Nomads':'https://www.workingnomads.com/api/exposed_jobs/','Remotive':'https://remotive.com/api/remote-jobs','Himalayas':'https://himalayas.app/jobs/api?limit=20'}
def clean(value):return unescape(re.sub('<[^>]+>',' ',str(value or ''))).strip()
def canonical(url):
 p=urlsplit(url);return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urlencode([(k,v) for k,v in parse_qsl(p.query) if not k.startswith('utm_')]),''))
def geography(location,description,remote=True):
 from autojob.search.geography import classify
 result=classify(location,description,"remote" if remote else "onsite")
 return result["status"],result["evidence"]

class Connector:
 def __init__(self,name,fetch=None,cancel=lambda:False):self.name=name;self.errors=[];self.fetch=fetch or self._fetch;self.cancel=cancel
 def _fetch(self,url):
  if self.name=='Boston Scientific CR':
   from autojob.search.national import fetch_jobs
   return fetch_jobs(self.cancel)
  request=Request(url,headers={'User-Agent':'JobHunting/0.3 (personal job discovery)','Accept':'application/json'})
  with urlopen(request,timeout=25) as response:
   data=response.read(12_000_001)
   if len(data)>12_000_000:raise ValueError('Respuesta demasiado grande')
   if self.name=='We Work Remotely':
    from autojob.search.feeds import parse_wwr
    return parse_wwr(data)
   return json.loads(data)
 def search_jobs(self,query,filters=None,payload=None):
  data=payload if payload is not None else self.fetch(ENDPOINTS[self.name])
  rows=data if isinstance(data,list) else data.get('jobs',[])
  for row in rows:
   if not isinstance(row,dict):continue
   title=row.get('title') or row.get('position');company=row.get('company_name') or row.get('companyName') or row.get('company')
   url=row.get('url') or row.get('guid')
   if not title or not company or not url or not str(url).startswith('https://'):continue
   from autojob.forms.navigation import category_url
   if category_url(url):
    actual=row.get('apply_url') or row.get('applicationLink')
    if actual and str(actual).startswith('https://') and not category_url(actual):url=actual
    else:self.errors.append('Categoría sin publicación individual verificable');continue
   description=clean(row.get('description'));location=row.get('candidate_required_location') or row.get('location') or ', '.join(row.get('locationRestrictions') or [])
   if query and not any(term.casefold() in (title+' '+description).casefold() for term in query):continue
   modality=row.get("modality") if self.name in {"Boston Scientific CR","Saplic CR"} else "remote"
   geo,evidence=geography(location,title+"\n"+description,modality=="remote")
   if self.name=="Boston Scientific CR" and modality is None:geo,evidence="DESCONOCIDO","La fuente publica ubicación pero no modalidad explícita"
   timezone_restrictions=row.get('timezoneRestrictions') or []
   if self.name=='Himalayas' and timezone_restrictions:
    accepted=any(str(offset).strip() in {'-6','-6.0','-06','-06:00','UTC-6','UTC-06:00','-0600'} for offset in timezone_restrictions)
    if not accepted:geo,evidence='INCOMPATIBLE','Restricciones horarias publicadas no incluyen UTC-6: '+str(timezone_restrictions)
   if self.name=='Himalayas':
    countries=row.get('locationRestrictions') or []
    if countries and not any(str(country).casefold() in {'costa rica','cr','costa-rica'} for country in countries):geo,evidence='INCOMPATIBLE','Países admitidos publicados: '+', '.join(countries)
    elif not countries and geo!='INCOMPATIBLE':
     if isinstance(data,dict) and data.get('_country_filter')=='CR':geo,evidence='CONFIRMADO','API oficial filtrada para Costa Rica: sin restricción de países y UTC-6 admitido'
     else:geo,evidence='POSIBLE','La API no publica países admitidos; requiere verificar Costa Rica'
   expiry=row.get('expiryDate')
   if expiry and isinstance(expiry,(int,float)) and expiry<time.time():continue
   salary=row.get('salary') or None
   if not salary and (row.get('salary_min') or row.get('minSalary')):salary=str(row.get('salary_min') or row.get('minSalary'))+'–'+str(row.get('salary_max') or row.get('maxSalary') or '')+' '+str(row.get('salaryPeriod') or '')
   experience=re.search(r'\b\d+\+?\s*(?:years? of experience|años de experiencia)\b',description,re.I)
   sentences=re.split(r'(?<=[.!?])\s+',description)
   snippets=lambda pattern:[sentence for sentence in sentences if re.search(pattern,sentence,re.I)][:10] or None
   education=snippets(r'\b(?:bachelor|degree|diploma|licenciatura|titulaci[oó]n|university)\b')
   mandatory=snippets(r'\b(?:must|required|essential|obligatorio|indispensable)\b')
   desirable=snippets(r'\b(?:preferred|bonus|deseable|nice.to.have)\b')
   languages=snippets(r'(?:fluent|proficien|nivel|dominio|bilingual|bilingüe)[^.!?]{0,100}(?:english|spanish|ingl[eé]s|espa[nñ]ol)|(?:english|spanish|ingl[eé]s|espa[nñ]ol)[^.!?]{0,100}(?:fluent|proficien|nivel|dominio|bilingual|bilingüe)')
   employment=row.get('job_type') or row.get('employmentType')
   contract=employment if employment and re.search(r'contract|freelance|contrat',employment,re.I) else None
   application=row.get('applicationLink') or row.get('apply_url') or url
   if category_url(application):self.errors.append('Enlace Apply de categoría; se conserva la publicación individual');application=url
   yield dict(discovery_url=row.get('url'),source=self.name,source_id=str(row.get('id') or row.get('guid') or url),company=company,title=title,location=location or None,modality=modality,locality=row.get("locality"),work_hours=row.get("work_hours"),night_status=row.get("night_status"),modality_evidence=row.get("modality_evidence"),country=row.get("country"),province=row.get("province"),geography=geo,geography_evidence=evidence,description=description,url=url,application_url=application,published_at=row.get('publication_date') or row.get('pub_date') or row.get('date'),source_updated_at=row.get('pubDate'),schedule=employment,contract_type=contract,seniority=row.get('seniority'),salary=salary,currency=row.get('currency'),company_country=None,experience=experience.group() if experience else None,education=education,languages=languages,published_tags=row.get('tags') or row.get('categories'),mandatory_requirements=mandatory,desirable_requirements=desirable,status='GEOGRAFÍA CONFIRMADA' if geo=='CONFIRMADO' else 'GEOGRAFÍA INCOMPATIBLE' if geo=='INCOMPATIBLE' else 'REQUIERE REVISIÓN',availability='ENCONTRADA',raw=row,structured_discovery_at=datetime.now(timezone.utc).isoformat() if self.name=='Himalayas' and isinstance(data,dict) and data.get('_country_filter')=='CR' else None)

class JobStore:
 def __init__(self,data_path):
  self.data_path=data_path;self.db=Database(data_path/'autojob.sqlite3');self.cache=data_path/'job-feed-cache';self.cache.mkdir(exist_ok=True)
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS discovered_jobs (id TEXT PRIMARY KEY, canonical_url TEXT UNIQUE, payload TEXT NOT NULL, discovered_at TEXT NOT NULL, checked_at TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS job_queries (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, source TEXT NOT NULL, query TEXT NOT NULL, status TEXT NOT NULL, details TEXT)')
   db.execute('CREATE TABLE IF NOT EXISTS job_sightings (source TEXT NOT NULL, source_id TEXT NOT NULL, job_id TEXT NOT NULL, url TEXT NOT NULL, PRIMARY KEY(source,source_id))')
 def add(self,job):
  url=canonical(job['url']);identity=sha256(url.encode()).hexdigest();now=datetime.now(timezone.utc).isoformat()
  with closing(self.db.connect()) as db,db:
   db.execute('BEGIN IMMEDIATE')
   previous=db.execute('SELECT id,payload FROM discovered_jobs WHERE canonical_url=?',(url,)).fetchone()
   if not previous:
    previous=db.execute('SELECT j.id,j.payload FROM discovered_jobs j JOIN job_sightings s ON s.job_id=j.id WHERE s.source=? AND s.source_id=?',(job['source'],job['source_id'])).fetchone()
   if not previous and len(job['description'])>=300:
    marker=lambda item:tuple(' '.join(str(item.get(k) or '').casefold().split()) for k in ('company','title','location','description'))
    for row in db.execute('SELECT id,payload FROM discovered_jobs'):
     candidate=json.loads(row['payload'])
     if candidate['source']!=job['source'] and marker(candidate)==marker(job):previous=row;break
   if previous:
    old=json.loads(previous['payload']);links=old.get('source_links',[{'source':old['source'],'url':old['url']}]);link={'source':job['source'],'url':job['url']}
    if link not in links:links.append(link)
    updated=dict(old)
    if old['source']==job['source']:
     protected={'manual_fields'}|set(old.get('manual_fields',[]))|{k for k in old if k.startswith(('availability','geography_review'))}
     protected|={'geography','geography_evidence','status'} if old.get('geography_reviewed_at') else set()
     if job.get('structured_discovery_at'):
      for field in ('geography','geography_evidence','status'):
       if field not in old.get('manual_fields',[]):protected.discard(field)
     updated.update({k:v for k,v in job.items() if k not in protected})
    updated['source_links']=links
    db.execute('UPDATE discovered_jobs SET payload=?,checked_at=? WHERE id=?',(json.dumps(updated,ensure_ascii=False),now,previous['id']))
    db.execute('INSERT OR REPLACE INTO job_sightings VALUES (?,?,?,?)',(job['source'],job['source_id'],previous['id'],url));return False
   db.execute('INSERT INTO discovered_jobs VALUES (?,?,?,?,?)',(identity,url,json.dumps(job,ensure_ascii=False),now,now))
   db.execute('INSERT OR REPLACE INTO job_sightings VALUES (?,?,?,?)',(job['source'],job['source_id'],identity,url));return True
 def count(self):
  with closing(self.db.connect()) as db:
   return db.execute('SELECT COUNT(*) FROM discovered_jobs').fetchone()[0]
 def list(self,job_id=None):
  sql='SELECT * FROM discovered_jobs'
  args=()
  if job_id is not None:sql+=' WHERE id=?';args=(job_id,)
  with closing(self.db.connect()) as db:rows=[dict(json.loads(r['payload']),id=r['id'],discovered_at=r['discovered_at'],checked_at=r['checked_at']) for r in db.execute(sql+' ORDER BY discovered_at DESC',args)]
  for row in rows:
   expires=row.get('raw',{}).get('expiryDate')
   if isinstance(expires,(int,float)) and expires<time.time():row.update(availability='CERRADA',status='CERRADA')
  return rows
 def log(self,source,query,status,details):
  with closing(self.db.connect()) as db,db:db.execute('INSERT INTO job_queries(started_at,source,query,status,details) VALUES (?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),source,json.dumps(query),status,details))
 def search(self,queries,sources,limit=30,cancel=lambda:False,progress=lambda message:None):
  count=duplicates=0;errors=[]
  for source in sources:
   if blocked_source(source):continue
   if cancel():break
   source_count=0
   progress('Buscando en '+source+'...')
   try:
    cache=self.cache/(source.replace(' ','_')+'.json')
    if cache.exists() and time.time()-cache.stat().st_mtime<(86400 if source=='Himalayas' else 21600):data=json.loads(cache.read_text(encoding='utf-8'))
    else:
     try:data=Connector(source,cancel=cancel).fetch(ENDPOINTS[source])
     except HTTPError:raise
     except (TimeoutError,URLError):
      if cancel():break
      time.sleep(2)
      if cancel():break
      data=Connector(source,cancel=cancel).fetch(ENDPOINTS[source])
     temporary=cache.with_suffix('.tmp');temporary.write_text(json.dumps(data),encoding='utf-8');temporary.replace(cache)
    connector=Connector(source)
    for job in connector.search_jobs(queries,payload=data):
     if excluded_job(job):continue
     if cancel():break
     if limit is not None and source_count>=limit:break
     if self.add(job):count+=1;source_count+=1;progress(f"{source}: {source_count} nuevas · {count} nuevas en total")
     else:duplicates+=1
    for message in connector.errors:self.log(source,queries,'ERROR DE FUENTE',message)
    self.log(source,queries,'OK',str(source_count))
   except Exception as exc:
    message=type(exc).__name__+': '+str(exc)[:200];errors.append(source+': '+message);self.log(source,queries,'ERROR DE CONSULTA',message)
  return dict(found=count,duplicates=duplicates,errors=errors,cancelled=cancel())
