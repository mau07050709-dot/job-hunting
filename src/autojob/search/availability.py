from contextlib import closing
from datetime import datetime,timezone
from html.parser import HTMLParser
import json,re,time
from urllib.error import URLError
from urllib.request import Request,urlopen
from urllib.parse import urljoin,urlsplit
from urllib.error import HTTPError
from autojob.search.jobs import canonical
from autojob.search.access_policy import paywall_page

class Page(HTMLParser):
 def __init__(self):super().__init__();self.scripts=[];self.text=[];self.script=None;self.button=None;self.apply=False;self.disabled=False;self.hidden=0
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs)
  if tag in {'script','style'}:self.hidden+=1
  if tag=='script' and attrs.get('type')=='application/ld+json':self.script=[]
  if tag in {'a','button','input'}:self.button=[tag,attrs,[]]
  if tag=='input' and re.search(r'apply|postular|solicitar|enviar candidatura',attrs.get('value',''),re.I):
   self.apply='disabled' not in attrs;self.disabled='disabled' in attrs
 def handle_data(self,data):
  if not self.hidden:self.text.append(data)
  if self.script is not None:self.script.append(data)
  if self.button:self.button[2].append(data)
 def handle_endtag(self,tag):
  if tag in {'script','style'}:self.hidden=max(0,self.hidden-1)
  if tag=='script' and self.script is not None:
   self.scripts.append(''.join(self.script));self.script=None
  if self.button and tag==self.button[0]:
   attrs=self.button[1];label=' '.join(self.button[2])
   if re.search(r'\bapply(?: now)?\b|postular|solicitar|enviar candidatura',label,re.I):
    if 'disabled' in attrs or attrs.get('aria-disabled')=='true':self.disabled=True
    elif tag=='button' or attrs.get('href','').startswith(('https://','/')):self.apply=True
   self.button=None

def inspect_page(job,status,url,body):
 result=lambda state,evidence:dict(state=state,evidence=evidence,url=url)
 if paywall_page(url,body):return dict(result('REQUIERE PAGO','Acceso a la candidatura condicionado a pago; oferta excluida'),application_access='PAGO')
 if status in {404,410}:return result('CERRADA','HTTP '+str(status)+': enlace eliminado o no disponible')
 if status in {401,403,429}:return result('NO VERIFICADA','Acceso restringido HTTP '+str(status)+'; no se intenta evadir')
 if status>=400:return result('ERROR DE VERIFICACIÓN','HTTP '+str(status))
 page=Page();page.feed(body);text=' '.join(page.text)
 if re.search(r'captcha|verify you are human|verifica que eres humano',text,re.I):return result('NO VERIFICADA','CAPTCHA o comprobación humana')
 if re.search(r'job (?:is no longer available|has expired|has been filled)|position (?:has been filled|is closed)|vacante (?:cerrada|finalizada)|this job is not available|no longer accepting applications',text,re.I):return result('CERRADA','Mensaje explícito de cierre en la página')
 expected=' '.join(job['title'].casefold().split());title_found=expected in ' '.join(text.casefold().split())
 if canonical(url)!=canonical(job['url']) and not title_found:return result('NO VERIFICADA','Redirección a una página sin el título esperado')
 if page.disabled and title_found:return result('CERRADA','Control de postulación deshabilitado en la oferta')
 def postings(value):
  if isinstance(value,list):
   for child in value:yield from postings(child)
  elif isinstance(value,dict):
   if value.get('@type')=='JobPosting':yield value
   for key in ('@graph','mainEntity'):yield from postings(value.get(key))
 for script in page.scripts:
  try:data=json.loads(script)
  except ValueError:continue
  for posting in postings(data):
   if ' '.join(str(posting.get('title','')).casefold().split())!=expected:continue
   until=posting.get('validThrough')
   if until:
    try:
     end=datetime.fromisoformat(str(until).replace('Z','+00:00'))
     if end.tzinfo is None:end=end.replace(tzinfo=timezone.utc)
     if end<datetime.now(timezone.utc):return result('CERRADA','JobPosting validThrough vencido: '+str(until))
     if title_found and page.apply:return result('ABIERTA','JobPosting coincidente, validThrough vigente y control de postulación habilitado')
    except ValueError:pass
 # El portal oficial también publica JobPosting mediante microdatos HTML.
 from lxml import etree
 tree=etree.HTML(body)
 if tree is not None:
  nodes=tree.xpath('//*[contains(@itemtype,"schema.org/JobPosting")]')
  for node in nodes:
   titles=node.xpath('.//*[@itemprop="title"]')
   if not titles or ' '.join(''.join(titles[0].itertext()).casefold().split())!=expected:continue
   dates=node.xpath('.//meta[@itemprop="validThrough"]/@content')
   if dates:
    from autojob.search.national import source_date
    iso=source_date(dates[0])
    if iso:
     end=datetime.fromisoformat(iso)
     if end<datetime.now(timezone.utc):return result('CERRADA','Microdatos JobPosting validThrough vencido: '+iso)
     if title_found and page.apply:return result('ABIERTA','Microdatos JobPosting coincidentes, fecha vigente y control de postulación habilitado')
 # La vigencia no exige una fecha de vencimiento: sí identidad y acceso explícito.
 identity=tree is not None and any(expected in ' '.join(''.join(n.itertext()).casefold().split()) for n in tree.xpath('//h1|//h2|//title'))
 if tree is not None and title_found and identity:
  controls=tree.xpath('//input[@type="file"]')
  links=tree.xpath('//a[@href]')
  for link in links:
   label=' '.join(link.itertext()).strip()
   target=urljoin(url,link.get('href'))
   if not re.fullmatch(r'apply(?: now| for (?:this )?(?:job|position))?|postular(?:me)?|aplicar',label,re.I):continue
   parsed=urlsplit(target)
   if parsed.scheme!='https' or parsed.username or parsed.password:continue
   if re.search(r'/(?:jobs|careers|search|remote-jobs)/?$',parsed.path) and not parsed.query:continue
   if re.search(r'login|sign.?in|register|subscribe|pricing',target,re.I):
    return dict(result('ABIERTA','Oferta coincidente; acceso a candidatura requiere autenticación'),application_access='INTERVENCIÓN')
   return dict(result('ABIERTA','Título coincidente y enlace específico de candidatura habilitado'),application_access='ACCESIBLE',application_url=target)
  if controls:return dict(result('ABIERTA','Título coincidente y controles de contacto o CV del formulario presentes'),application_access='ACCESIBLE',application_url=url)
 return result('NO VERIFICADA','No hay evidencia suficiente de vigencia; HTTP 200 no confirma una vacante abierta')

def read_public(url):
 from autojob.forms.execution import public_destination
 public_destination(url,'real')
 request=Request(url,headers={'User-Agent':'JobHunting/0.3 (personal vacancy verification)'})
 try:
  with urlopen(request,timeout=15) as response:
   data=response.read(3_000_001)
   if len(data)>3_000_000:raise ValueError('Respuesta demasiado grande')
   return response.status,response.url,data.decode('utf-8',errors='replace')
 except HTTPError as exc:return exc.code,url,''

class Availability:
 def __init__(self,store):
  self.store=store
  with closing(store.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS job_availability_checks (id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,checked_at REAL NOT NULL,state TEXT NOT NULL,evidence TEXT NOT NULL,url TEXT NOT NULL)')
  with closing(store.db.connect()) as db,db:
   if 'checker_version' not in {r[1] for r in db.execute('PRAGMA table_info(job_availability_checks)')}:db.execute('ALTER TABLE job_availability_checks ADD COLUMN checker_version INTEGER NOT NULL DEFAULT 0')
 def history(self,job_id):
  with closing(self.store.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM job_availability_checks WHERE job_id=? ORDER BY checked_at DESC',(job_id,))]
 def check(self,job,fetch=None,force=False):
  history=self.history(job['id'])
  if not force and history and history[0].get('checker_version')==4 and time.time()-history[0]['checked_at']<(300 if history[0]['state']=='ERROR DE VERIFICACIÓN' else 86400):return dict(history[0],cached=True)
  try:
   target=job.get('application_url') or job['url']
   if re.search(r'/(?:login|sign.?in|register|subscribe|pricing)(?:[/?]|$)',target,re.I):target=job['url']
   reader=fetch or read_public
   for attempt in range(2):
    try:status,url,body=reader(target);break
    except (URLError,TimeoutError):
     if attempt:raise
     time.sleep(1)
   result=inspect_page(job,status,url,body)
   # Verificar el destino, no solo la presencia de un botón en el anuncio.
   next_url=result.get('application_url')
   if next_url and canonical(next_url)!=canonical(url):
    next_status,final_url,next_body=reader(next_url)
    destination=inspect_page(job,next_status,final_url,next_body)
    if destination.get('application_access')=='PAGO':result=destination
    elif destination['state']=='ABIERTA':
     result=dict(destination,application_url=final_url)
    elif next_status in {401,403,429} or re.search(r'captcha|verify you are human|sign in|log in',next_body,re.I):
     result=dict(result,application_url=next_url,application_access='INTERVENCIÓN',evidence='Oferta coincidente; el acceso a la candidatura requiere intervención humana')
    else:result=destination
  except Exception as exc:result=dict(state='ERROR DE VERIFICACIÓN',evidence=type(exc).__name__,url=job['url'])
  now=time.time()
  with closing(self.store.db.connect()) as db,db:
   db.execute('BEGIN IMMEDIATE');db.execute('INSERT INTO job_availability_checks(job_id,checked_at,state,evidence,url,checker_version) VALUES (?,?,?,?,?,4)',(job['id'],now,result['state'],result['evidence'],result['url']))
   row=db.execute('SELECT payload FROM discovered_jobs WHERE id=?',(job['id'],)).fetchone()
   if row:
    payload=json.loads(row[0]);payload.update(availability=result['state'],availability_evidence=result['evidence'],availability_checked_at=datetime.fromtimestamp(now,timezone.utc).isoformat())
    if re.search(r'/(?:login|sign.?in|register|subscribe|pricing)(?:[/?]|$)',payload.get('application_url') or '',re.I) and 'application_url' not in payload.get('manual_fields',[]):payload['application_url']=job['url']
    for key in ('application_access','application_url'):
     if key in result and key not in payload.get('manual_fields',[]):payload[key]=result[key]
    db.execute('UPDATE discovered_jobs SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),job['id']))
  return result
 def batch(self,jobs,cancel=lambda:False,progress=lambda text:None):
  results=[]
  for job in jobs:
   if cancel():break
   progress('Verificando: '+job['title']);results.append(self.check(job))
  return results
