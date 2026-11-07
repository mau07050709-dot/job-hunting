# Carga pública sin autorización de escritura.
import re,json
from urllib.parse import urlsplit,urlunsplit
from hashlib import sha256
PAVAGO='https://apply.workable.com/pavago/j/361F1E680B'
def safe(url):
 p=urlsplit(url);path='/cdn-cgi/challenge-platform/[redacted]' if '/cdn-cgi/challenge-platform/' in p.path else p.path
 return urlunsplit((p.scheme,p.netloc,path,'',''))
def category_url(url):
 p=urlsplit(url)
 return p.hostname in {'workingnomads.com','www.workingnomads.com'} and (p.path.rstrip('/') in {'','/jobs','/remote-jobs'} or bool(re.fullmatch(r'/remote-[^/]+-jobs/?',p.path)))
def public_asset(site,url,method,kind):
 p=urlsplit(url)
 return site=='https://apply.workable.com' and method=='GET' and p.hostname=='dcvxs6ggqztsa.cloudfront.net' and p.scheme=='https' and p.path.startswith('/candidate/releases/') and kind in {'script','stylesheet','other'} and p.path.endswith(('.js','.css'))
def classify(url,status,title,text,controls,identity=True):
 if category_url(url):return 'ENLACE INVÁLIDO'
 if status in {404,410} or re.search(r'this job is not available|no longer accepting|position has been filled',text,re.I):return 'VACANTE CERRADA'
 if re.search(r'captcha|verify you are human|sign in to apply|log in to apply',text,re.I) or status in {401,403,429}:return 'REQUIERE INTERVENCIÓN'
 if not identity:return 'ENLACE INVÁLIDO'
 if re.search(r'we could not load|temporarily unavailable|try again|something went wrong',text,re.I) or status and status>=500:return 'CARGA TEMPORAL FALLIDA'
 return 'FORMULARIO DISPONIBLE' if controls else 'FORMULARIO NO COMPATIBLE'
def observe(page,url,status=None,job=None,failures=(),errors=()):
 title=page.title();text=page.locator('body').inner_text();controls=page.locator('input[type=email]').count()>0 and page.locator('input[type=file],input[autocomplete=given-name]').count()>0
 identity=not job or all(str(job.get(k,'')).casefold() in title.casefold() for k in ('company','title') if job.get(k))
 state=classify(page.url,status,title,text,controls,identity)
 if state=='FORMULARIO NO COMPATIBLE' and not failures:state='CARGA TEMPORAL FALLIDA'
 return dict(original_url=safe(url),final_url=safe(page.url),http_status=status,title=title,identity_matches=identity,controls_detected=controls,state=state,document_state=page.evaluate('document.readyState'),language=page.evaluate('document.documentElement.lang'),translation_detected=page.evaluate("/translated-(ltr|rtl)/.test(document.documentElement.className)"),failed_resources=list(failures)[:20],javascript_errors=list(errors)[:10])
def open_page(guard,page,url,job=None):
 if category_url(url):raise ValueError('ENLACE INVÁLIDO: categoría general sin candidatura identificada.')
 failures=[];errors=[];responses=[]
 page.on('requestfailed',lambda r:failures.append(dict(url=safe(r.url),method=r.method,resource=r.resource_type)))
 page.on('pageerror',lambda e:errors.append(type(e).__name__))
 page.on('response',lambda r:responses.append(dict(url=safe(r.url),status=r.status)) if r.request.resource_type=='document' else None)
 page.add_init_script("document.addEventListener('DOMContentLoaded',()=>{document.documentElement.translate=false;let m=document.createElement('meta');m.name='google';m.content='notranslate';document.head.appendChild(m);})")
 target=PAVAGO if safe(url).rstrip('/')==PAVAGO+'/apply' else url
 guard.navigate(page,target)
 if target==PAVAGO:
  page.wait_for_function("document.title.includes('Customer Service Representative') && document.title.includes('Pavago')",timeout=10000)
  try:page.wait_for_function("Array.from(document.querySelectorAll('a[href]')).some(a=>a.href.includes('/pavago/j/361F1E680B/apply'))",timeout=10000)
  except Exception:pass
  from autojob.forms.guard import apply_link
  link=apply_link(page)
  if link and safe(link).rstrip('/')==PAVAGO+'/apply':guard.navigate(page,link)
 try:page.wait_for_function("!!document.querySelector('input[type=email]') && !!document.querySelector('input[type=file],input[autocomplete=given-name]')",timeout=10000)
 except Exception:pass
 page.wait_for_timeout(500)
 decline=page.get_by_text('Decline all',exact=True)
 if decline.count()==1 and decline.is_visible():decline.click(timeout=2000)
 result=observe(page,url,responses[-1]['status'] if responses else None,job,failures,errors);result['redirects']=responses;return result
def save(data_path,job,result):
 folder=data_path/'navigation-diagnostics';folder.mkdir(exist_ok=True)
 (folder/(sha256(str(job).encode()).hexdigest()+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
