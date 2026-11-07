"""Barrera de preparación: bloquea envío DOM, nuevas transmisiones y adjuntos externos."""
from urllib.parse import urlsplit,urldefrag
import re

def origin(url):
 p=urlsplit(url)
 if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:raise ValueError('URL HTTP/HTTPS sin credenciales requerida.')
 return p.scheme+'://'+p.netloc.lower()

def action(label,html_type='button'):
 text=' '.join(label.casefold().split())
 if re.search(r'submit|send|enviar|postular|confirm.{0,15}application|finish|finaliz|complete application|acept|accept|firma|sign\b',text):return 'FINAL O LEGAL'
 if html_type=='submit':return 'AMBIGUA'
 if re.fullmatch(r'next|continue|save and continue|siguiente|continuar|guardar y continuar|review|revisar|previous|back|anterior|atr[aá]s',text):return 'ANTERIOR' if re.search(r'previous|back|anterior|atr',text) else 'CONTINUAR'
 if re.search(r'apply|solicitar|candidatura',text):return 'APPLY AMBIGUO'
 return 'AMBIGUA'

SCRIPT=r'''(() => {
 if(window.__autojobGuard)return;window.__autojobGuard=true;
 const stop=e=>{e.preventDefault();e.stopImmediatePropagation();};
 document.addEventListener('submit',stop,true);
 document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target?.tagName!=='TEXTAREA')stop(e);},true);
 for(const name of ['submit','requestSubmit']){try{Object.defineProperty(HTMLFormElement.prototype,name,{value:function(){throw Error('AUTOJOB_FINAL_SUBMISSION_DISABLED');},writable:false,configurable:false});}catch(_){}}
 document.addEventListener('click',e=>{let b=e.target.closest?.('button,input[type=submit],a[role=button]');if(!b)return;let text=(b.innerText||b.value||b.getAttribute('aria-label')||'').toLowerCase();if((b.type==='submit'&&(b.form||b.closest('form')))||/submit|send application|enviar|postular|finish|finaliz|accept|acept|firma|sign\b/.test(text)||(/apply|candidatura/.test(text)&&b.closest('form')))stop(e);},true);
 const external=__EXTERNAL__;
 if(external){
  const disable=()=>document.querySelectorAll('input[type=file]').forEach(e=>{if(!e.disabled)e.disabled=true;});
  document.addEventListener('drop',stop,true);document.addEventListener('dragover',stop,true);
  new MutationObserver(disable).observe(document,{childList:true,subtree:true});document.addEventListener('DOMContentLoaded',disable);disable();
 }
})()'''

class PreparationGuard:
 def __init__(self,browser,controlled_origin=None):
  self.browser=browser;self.context=browser.context;self.controlled_origin=controlled_origin;self.frozen=False;self.allowed_assets=set();self.expected=None;self.nav_budget=0;self.blocked=0
  self.context.add_init_script(SCRIPT.replace('__EXTERNAL__','false' if controlled_origin else 'true'))
  self.context.route('**/*',self.route)
  self.context.route_web_socket('**/*',lambda ws:ws.close())
 def route(self,route):
  r=route.request;url=urldefrag(r.url)[0]
  try:
   allowed=r.method in {'GET','HEAD','OPTIONS'}
   if not self.controlled_origin and (r.resource_type in {'media'} or re.search(r'(^|\.)(doubleclick\.net|googlesyndication\.com|adnxs\.com|rubiconproject\.com|adsrvr\.org|openx\.net|criteo\.com|amazon-adsystem\.com|pubmatic\.com|casalemedia\.com)$',urlsplit(url).hostname or '')):allowed=False
   if self.controlled_origin:allowed=allowed and origin(r.url)==self.controlled_origin
   if r.is_navigation_request():
    direct=url==self.expected and self.nav_budget>0
    allowed=allowed and (direct or (not self.frozen and r.redirected_from is not None))
    if allowed and direct:self.nav_budget-=1
   elif self.frozen:allowed=allowed and url in self.allowed_assets and r.resource_type in {'image','stylesheet','font','script'}
   if allowed:
    if not r.is_navigation_request():self.allowed_assets.add(url)
    route.continue_()
   else:self.blocked+=1;route.abort()
  except Exception:self.blocked+=1;route.abort()
 def page(self,url):
  origin(url);page=self.browser.new_page()
  cdp=self.context.new_cdp_session(page);cdp.send('Network.enable');cdp.send('Network.setBypassServiceWorker',{'bypass':True})
  self.navigate(page,url);return page
 def navigate(self,page,url):
  origin(url)
  if self.controlled_origin and origin(url)!=self.controlled_origin:raise ValueError('Destino fuera de la prueba controlada.')
  if re.search(r'/(?:submit|send|finish|confirm-application)(?:[/?]|$)',url,re.I):raise ValueError('Ruta de envío bloqueada.')
  self.expected=urldefrag(url)[0];self.nav_budget=1;response=page.goto(url,wait_until='domcontentloaded',timeout=20000)
  if response and response.status>=400:raise ValueError('HTTP '+str(response.status))
  page.wait_for_timeout(500)
 def freeze(self):self.frozen=True

def apply_link(page):
 links=page.locator('a[href]').evaluate_all('(es)=>es.slice(0,2000).map(e=>({text:(e.innerText||e.getAttribute("aria-label")||"").trim(),url:e.href}))')
 matches=[]
 for link in links:
  if re.search(r'\bapply(?: now)?\b|postular|solicitar|aplicar|enviar candidatura',link['text'],re.I) and not re.search(r'email|mailto|already applied|status',link['text'],re.I):
   try:origin(link['url'])
   except ValueError:continue
   if link['url'].split('#')[0]!=page.url.split('#')[0]:matches.append(link['url'])
 return next(iter(dict.fromkeys(matches)),None)

def continue_stage(page,guard):
 candidates=[]
 for button in page.locator('button,input[type=button],input[type=submit],a[role=button]').all()[:100]:
  if not button.is_visible() or not button.is_enabled():continue
  label=button.inner_text() or button.get_attribute('value') or button.get_attribute('aria-label') or ''
  kind=action(label,button.get_attribute('type') or ('submit' if button.evaluate('(e)=>e.tagName==="BUTTON"&&!!e.closest("form")') else 'button'))
  if kind=='CONTINUAR':candidates.append(button)
 if len(candidates)!=1:return False,'No hay un único botón de continuación inequívoco; detener antes del envío.'
 button=candidates[0]
 if button.get_attribute('formaction'):return False,'Botón con acción de formulario: requiere revisión.'
 href=button.get_attribute('href') or button.get_attribute('data-next-url')
 if href:
  from urllib.parse import urljoin
  guard.expected=urldefrag(urljoin(page.url,href))[0];guard.nav_budget=1
 button.click(timeout=5000);page.wait_for_timeout(600);return True,'Continuación controlada; los envíos permanecen bloqueados.'
