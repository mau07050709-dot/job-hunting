"""Autenticación HTML explícita, por origen y acción, sin envío de candidaturas."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit,urldefrag
from uuid import uuid4
import json,re,os
from autojob.auth.service import Accounts,account_origin
from autojob.auth.permissions import Permissions,scope
from autojob.auth.detection import inspect_auth,safe_url
from autojob.auth.verifications import CaptchaCoordinator,captcha_state,record_obstacle
from autojob.forms.guard import PreparationGuard,origin
from autojob.browser import BraveSession

FORM_SCAN=r'''() => Array.from(document.forms).filter(f=>f.getClientRects().length>0).map((f,i)=>({index:i,action:f.action,method:f.method,fields:Array.from(f.querySelectorAll('input,select,button,textarea')).filter(e=>e.getClientRects().length>0).map((e,j)=>({index:j,type:e.type,required:e.required,checked:e.checked,autocomplete:e.autocomplete||'',label:(Array.from(e.labels||[]).map(l=>l.innerText).join(' ')||e.getAttribute('aria-label')||e.name||e.innerText||'').slice(0,180)}))}))'''

AUTH_SCRIPT=r'''(()=>{
const stop=e=>{e.preventDefault();e.stopImmediatePropagation()};
const valid=f=>f===window.__ajAuthForm&&window.__ajAuthEnabled===true;
document.addEventListener('submit',e=>{if(!valid(e.target))stop(e)},true);
const submit=HTMLFormElement.prototype.submit,request=HTMLFormElement.prototype.requestSubmit;
HTMLFormElement.prototype.submit=function(){if(!valid(this))throw Error('AUTOJOB_SUBMISSION_DISABLED');return submit.call(this)};
HTMLFormElement.prototype.requestSubmit=function(b){if(!valid(this))throw Error('AUTOJOB_SUBMISSION_DISABLED');return request.call(this,b)};
document.addEventListener('click',e=>{let b=e.target.closest?.('button,input[type=submit]');if(b?.form&&b.type==='submit'&&!valid(b.form))stop(e)},true);
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&!valid(e.target.form))stop(e)},true);
const disable=()=>document.querySelectorAll('input[type=file]').forEach(e=>{if(!e.disabled)e.disabled=true});new MutationObserver(disable).observe(document,{childList:true,subtree:true});document.addEventListener('DOMContentLoaded',disable);
})()'''

class AuthGuard(PreparationGuard):
    def __init__(self,browser,site,authorized):
        # Contexto nuevo; no se retiran ni modifican las barreras de otros modos.
        self.browser=browser;self.context=browser.context;self.site=site;self.authorized=authorized;self.endpoint=None;self.budget=0;self.redirect_budget=0;self.blocked=0;self.frozen=False;self.expected=None;self.nav_budget=0;self.allowed_assets=set();self.controlled_origin=None
        self.context.add_init_script(AUTH_SCRIPT);self.context.route('**/*',self.route);self.context.route_web_socket('**/*',lambda ws:ws.close())
    def route(self,route):
        r=route.request
        try:
            same=origin(r.url)==self.site
            if r.method=='POST':
                if same and self.authorized() and urldefrag(r.url)[0]==self.endpoint and self.budget==1:self.budget=0;route.continue_();return
                self.blocked+=1;route.abort();return
            if r.is_navigation_request() and same and r.redirected_from is not None and self.redirect_budget>0 and r.method=='GET':
                self.redirect_budget-=1;route.continue_();return
            if r.is_navigation_request() and not same:self.blocked+=1;route.abort();return
            super().route(route)
        except Exception:self.blocked+=1;route.abort()
    def arm(self,page,form_index,endpoint):
        if origin(endpoint)!=self.site or not re.search(r'login|log-in|signin|sign-in|session|auth|register|signup|sign-up|account',urlsplit(endpoint).path,re.I):raise ValueError('Acción de autenticación ambigua; se requiere adaptador o revisión.')
        self.endpoint=urldefrag(endpoint)[0];self.budget=1;self.redirect_budget=4;self.frozen=True
        page.evaluate('(i)=>{window.__ajAuthForm=Array.from(document.forms).filter(f=>f.getClientRects().length>0)[i];window.__ajAuthEnabled=true}',form_index)
    def disarm(self,page):
        self.budget=0
        try:page.evaluate('()=>{window.__ajAuthEnabled=false;window.__ajAuthForm=null}')
        except Exception:pass

def authentication_observation(page,fixture=None):
    observation=inspect_auth(page)
    if 'CAPTCHA' in observation['blocks'] and captcha_state(page,fixture)['completed']:
        observation=dict(observation,blocks=[b for b in observation['blocks'] if b!='CAPTCHA'])
    return observation

class ExternalAuth:
    def __init__(self,data_path):
        self.data_path=data_path;self.accounts=Accounts(data_path);self.permissions=Permissions(data_path);self.db=self.accounts.db
        with closing(self.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS authentication_attempts(id TEXT PRIMARY KEY,account_id TEXT NOT NULL,action TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL,submitted INTEGER NOT NULL)')
    def run(self,settings,id,action,url=None,job_id=None,title='Cuenta laboral',pause=lambda:False,stop=lambda:False,local=False,fixture=None):
        row=self.accounts.get(id)
        if action not in {'LOGIN','REGISTRO'} or not row or not row['domain_verified']:raise ValueError('Cuenta, dominio o acción sin confirmar.')
        url=url or row['origin']
        if account_origin(url,local)!=row['origin']:raise ValueError('El enlace no corresponde al origen de la cuenta.')
        if os.environ.get('PWDEBUG') not in {None,'','0'} or 'pw:' in os.environ.get('DEBUG',''):raise ValueError('Desactiva las trazas de Playwright antes de utilizar credenciales.')
        allowed=lambda:self.permissions.allowed(url,action,scope(self.accounts,self.accounts.get(id),action),local)
        if not allowed():raise ValueError('Falta autorización expresa para esta cuenta, dominio y acción.')
        if action=='REGISTRO' and row['exists_remotely']:return dict(state='REQUIERE INTERVENCIÓN',reason='La cuenta ya existe; utiliza login.')
        with closing(self.db.connect()) as db:
            recent=db.execute('SELECT count(*) FROM authentication_attempts WHERE account_id=? AND submitted=1 AND created_at>?',(id,(datetime.now(timezone.utc)-timedelta(minutes=15)).isoformat())).fetchone()[0]
            duplicate=db.execute("SELECT 1 FROM authentication_attempts WHERE account_id=? AND action='REGISTRO' AND submitted=1",(id,)).fetchone()
        if recent>=3 or action=='REGISTRO' and duplicate:return dict(state='REQUIERE INTERVENCIÓN',reason='Límite de intentos o registro ya enviado; no se repite automáticamente.')
        if action=='LOGIN' and not row['exists_remotely']:return dict(state='REQUIERE INTERVENCIÓN',reason='Confirma que la cuenta ya existe antes de preparar login.')
        preview=self.accounts.prepare(id)
        if action=='REGISTRO' and preview['pending']:return dict(state='REQUIERE INTERVENCIÓN',reason='Faltan datos confirmados o hay condiciones que revisar.')
        row=self.accounts.get(id)
        # Preparar puede crear el secreto de un registro nuevo; el permiso debe cubrir esa referencia actual.
        if not allowed():raise ValueError('La preparación cambió; revisa y autoriza la versión actual.')
        attempt=uuid4().hex
        with closing(self.db.connect()) as db,db:db.execute('INSERT INTO authentication_attempts VALUES (?,?,?,?,?,0)',(attempt,id,action,datetime.now(timezone.utc).isoformat(),'ANALIZANDO'))
        submitted=False;out=dict(state='REQUIERE INTERVENCIÓN',reason='No se confirmó el resultado.')
        try:
            with BraveSession(settings) as browser:
                guard=AuthGuard(browser,row['origin'],allowed);guard.defer_interventions=getattr(self,'defer_interventions',False);page=guard.page(url)
                for stage in range(3):
                    if pause() or stop():return dict(state='PENDIENTE',reason='Operación interrumpida antes de continuar.')
                    if captcha_state(page,fixture)['detected'] and not captcha_state(page,fixture)['completed']:
                        if not CaptchaCoordinator(self.data_path).wait(page,guard,job_id or 'account:'+id,title,stop,pause,seconds=(fixture or {}).get('wait_seconds',30),fixture=fixture):return dict(state='PENDIENTE',reason='CAPTCHA PENDIENTE',url=safe_url(page.url))
                    observation=authentication_observation(page,fixture)
                    if observation['authenticated']:
                        state=self.accounts.observe(id,observation);return dict(state=state,reason='Sesión autenticada observada.',url=observation['url'])
                    special=[b for b in observation['blocks'] if b!='SESIÓN EXPIRADA']
                    if special:
                        state=self.accounts.observe(id,observation);record_obstacle(self.data_path,job_id or 'account:'+id,', '.join(special),page.url,title);return dict(state=state,reason=', '.join(special),url=observation['url'])
                    if action=='REGISTRO' and submitted and (observation['kind']=='VERIFICACIÓN' or page.get_by_text(re.compile(r'account (?:created|registered)|cuenta creada',re.I)).count()):
                        with closing(self.db.connect()) as db,db:db.execute('UPDATE work_accounts SET exists_remotely=1,created_at=? WHERE id=?',(datetime.now(timezone.utc).isoformat(),id))
                        return dict(state='VERIFICACIÓN PENDIENTE',reason='Registro observado; revisión o verificación pendiente.')
                    if observation['kind']!=('REGISTRO' if action=='REGISTRO' else 'LOGIN'):return dict(state='REQUIERE INTERVENCIÓN',reason='El formulario no coincide con la acción autorizada.')
                    implicit_terms=page.evaluate(r'()=>/by (?:signing|registering|continuing|creating|clicking)[\s\S]{0,180}(?:agree|accept)|al (?:registrarte|continuar|crear)[\s\S]{0,180}acept/i.test(document.body?.innerText||"")')
                    if action=='REGISTRO' and implicit_terms:return dict(state='REQUIERE INTERVENCIÓN',reason='Continuar implica aceptar condiciones; se requiere revisión humana específica.')
                    forms=page.evaluate(FORM_SCAN)
                    candidates=[f for f in forms if any(x['type']=='password' for x in f['fields']) or any(x['type']=='email' for x in f['fields'])]
                    if len(candidates)!=1:return dict(state='REQUIERE INTERVENCIÓN',reason='Formulario de autenticación ausente o ambiguo.')
                    form=candidates[0]
                    if form['method'].lower()!='post' or any(f['type']=='file' for f in form['fields']):return dict(state='REQUIERE INTERVENCIÓN',reason='Formulario no compatible con autenticación HTML segura.')
                    # Determinar roles sin leer ningún valor de los campos.
                    from autojob.auth.detection import classify
                    classified=classify(dict(text='Create account' if action=='REGISTRO' else 'Sign in',fields=form['fields']),page.url)
                    field_pairs=list(zip(form['fields'],classified['fields']))
                    if any(f['required'] and f['type'] not in {'submit','button'} and r['role'] not in {'email','password','confirm_password','first_name','last_name','username'} for f,r in field_pairs):return dict(state='REQUIERE INTERVENCIÓN',reason='Campo obligatorio o aceptación legal sin autorización.')
                    if any(r['role']=='terms' and (f['required'] or f['checked']) for f,r in field_pairs):return dict(state='REQUIERE INTERVENCIÓN',reason='Condiciones legales requieren consentimiento humano específico.')
                    if action=='LOGIN' and classified['kind']=='REGISTRO':return dict(state='REQUIERE INTERVENCIÓN',reason='Se detectó registro; no se utiliza permiso de login para crear cuenta.')
                    values={f['field']:f['value'] for f in preview['fields']};values['username']=row['username'];values['email']=row['email'] if row['email_confirmed'] else values.get('email')
                    if not values.get('email'):return dict(state='REQUIERE INTERVENCIÓN',reason='Correo sin confirmar.')
                    guard.freeze();secret=None
                    try:
                        if any(r['role'] in {'password','confirm_password'} for f,r in field_pairs):
                            secret=self.accounts.credential(id,url,True,local)
                            if not secret:return dict(state='REQUIERE INTERVENCIÓN',reason='Falta credencial existente en Windows.')
                        form_element=page.locator('form').filter(visible=True).nth(form['index'])
                        controls=form_element.locator('input,select,button,textarea').filter(visible=True)
                        for f,r in field_pairs:
                            role=r['role']
                            if role in {'password','confirm_password'}:value=secret.reveal()
                            else:value=values.get(role)
                            if role not in {'email','password','confirm_password','first_name','last_name','username'}:continue
                            if f['required'] and not value:return dict(state='REQUIERE INTERVENCIÓN',reason='Dato requerido sin confirmar.')
                            if value:
                                target=controls.nth(f['index'])
                                if role not in {'password','confirm_password'} and target.input_value() not in {'',str(value)}:return dict(state='REQUIERE INTERVENCIÓN',reason='Hay otro valor en el formulario; no se sobrescribe sin revisión.')
                                target.fill(str(value));valid=target.evaluate('(e)=>!e.willValidate||e.validity.valid')
                                if not valid:return dict(state='REQUIERE INTERVENCIÓN',reason='El portal no valida un campo conocido.')
                        if not allowed():return dict(state='PENDIENTE',reason='Permiso revocado antes del envío de autenticación.')
                        buttons=[f for f,r in field_pairs if f['type']=='submit']
                        if len(buttons)!=1 or re.search(r'apply|application|postula|candidatura|accept|agree|acepto|firma',buttons[0]['label'],re.I):return dict(state='REQUIERE INTERVENCIÓN',reason='Acción final de autenticación ambigua.')
                        guard.arm(page,form['index'],form['action'])
                        # Marcar antes de la red: un resultado incierto de registro nunca se repite.
                        with closing(self.db.connect()) as db,db:db.execute('UPDATE authentication_attempts SET submitted=1 WHERE id=?',(attempt,))
                        submitted=True;controls.nth(buttons[0]['index']).click(timeout=10000);page.wait_for_load_state('domcontentloaded');page.wait_for_timeout(500)
                    finally:
                        if secret:secret.clear()
                        guard.disarm(page)
                    after=authentication_observation(page,fixture)
                    if 'CAPTCHA' in after['blocks']:
                        completed=CaptchaCoordinator(self.data_path).wait(page,guard,job_id or 'account:'+id,title,stop,pause,seconds=(fixture or {}).get('wait_seconds',30),fixture=fixture)
                        if not completed:return dict(state='PENDIENTE',reason='CAPTCHA PENDIENTE',url=safe_url(page.url))
                        after=authentication_observation(page,fixture)
                        if not after['authenticated']:return dict(state='PENDIENTE',reason='LISTA PARA CONTINUAR: verificación completada; comprobar el resultado sin repetir un registro incierto.',url=safe_url(page.url))
                    if action=='REGISTRO' and any(b in after['blocks'] for b in ['CORREO','OTP','MFA','SMS']):
                        with closing(self.db.connect()) as db,db:db.execute('UPDATE work_accounts SET exists_remotely=1,created_at=? WHERE id=?',(datetime.now(timezone.utc).isoformat(),id))
                    if after['kind']==observation['kind'] and len(after['fields'])==len(observation['fields']) and not after['blocks'] and not after['authenticated']:return dict(state='REQUIERE INTERVENCIÓN',reason='No se confirmó avance; no se vuelve a enviar el mismo formulario.')
                    if after['authenticated'] or after['blocks']:
                        state=self.accounts.observe(id,after)
                        if after['blocks']:record_obstacle(self.data_path,job_id or 'account:'+id,', '.join(after['blocks']),page.url,title)
                        return dict(state=state,reason=', '.join(after['blocks']) or 'Acceso confirmado por la página.',url=after['url'])
                return out
        except Exception:
            self.accounts.event(id,'ERROR DE NAVEGACIÓN','REQUIERE INTERVENCIÓN',row['origin'],code='AUTH_ERROR')
            return dict(state='REQUIERE INTERVENCIÓN',reason='Error de autenticación; no se repite la contraseña automáticamente.')
        finally:
            with closing(self.db.connect()) as db,db:db.execute('UPDATE authentication_attempts SET state=? WHERE id=?',('ENVIADO A AUTENTICACIÓN' if submitted else 'SIN TRANSMISIÓN',attempt))
