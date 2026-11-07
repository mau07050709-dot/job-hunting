"""Portal ficticio de autenticación; no se usa para dominios externos."""
from contextlib import contextmanager,closing
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from threading import Thread
from urllib.parse import urlsplit,parse_qs
from tempfile import TemporaryDirectory
from pathlib import Path
from hashlib import pbkdf2_hmac
import secrets,hmac,json

@contextmanager
def local_portal():
    token=secrets.token_hex(24);accounts={};sessions={};requests=[];cookie_name='aj_fixture_'+token[:10]
    state=dict(token=token,accounts=accounts,sessions=sessions,requests=requests,posts=0,application_posts=0)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,body,status=200,location=None,cookie=None):
            self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; form-action 'self'; connect-src 'self'")
            if location:self.send_header('Location',location)
            if cookie:self.send_header('Set-Cookie',cookie)
            if state.get('terms_required'):body=body.replace('id="terms" type="checkbox"','id="terms" type="checkbox" required')
            if state.get('human_captcha') and urlsplit(self.path).path in {'/login','/captcha'}:
                body='<meta name="autojob-human-fixture" content="'+token+'"><div data-captcha="true"><h2>CAPTCHA simulado: intervención humana</h2><p>Prueba ficticia, sin desafío real. Marca el botón solo en esta página de laboratorio.</p><button id="human-check" type="button" onclick="this.parentElement.dataset.humanResult=\'complete\';this.parentElement.innerHTML=\'<p>Verificación humana completada</p>\'">He revisado el desafío ficticio</button></div>'+body
            self.end_headers();self.wfile.write(('<html><head><meta name="autojob-auth-fixture" content="'+token+'"><title>Job Hunting fictitious employment portal</title></head><body><h1>PORTAL FICTICIO LOCAL</h1>'+body+'</body></html>').encode())
        def session(self):
            cookies=dict(part.strip().split('=',1) for part in self.headers.get('Cookie','').split(';') if '=' in part)
            return sessions.get(cookies.get(cookie_name))
        def form(self,action,fields,button):
            return '<form data-autojob-auth="true" method="post" action="'+action+'">'+fields+'<button type="submit" id="auth-submit">'+button+'</button></form>'
        def do_GET(self):
            path=urlsplit(self.path).path;requests.append(dict(method='GET',path=path))
            if path=='/signup':
                self.send(self.form('/register','<h2>Create account</h2><label>First name<input id="first" name="first" autocomplete="given-name" required></label><label>Last name<input id="last" name="last" required></label><label>Email<input id="email" name="email" type="email" required></label><label>Password<input id="password" name="password" type="password" autocomplete="new-password" required></label><label>Confirm password<input id="confirm" name="confirm" type="password" required></label><label><input id="terms" type="checkbox">I accept terms (not required; never selected by Job Hunting)</label>','Create fictitious account'))
            elif path=='/login':self.send(self.form('/login','<h2>Sign in</h2>'+('<p>Session expired</p>' if parse_qs(urlsplit(self.path).query).get('expired') else '')+'<label>Email<input id="email" name="email" type="email" autocomplete="username" required></label><label>Password<input id="password" name="password" type="password" autocomplete="current-password" required></label>','Log in')+'<a href="/recover">Forgot password</a>')
            elif path in {'/protected','/dashboard'}:
                if not self.session():self.send('',302,location='/login?expired=1');return
                self.send('<h2>My account dashboard — authenticated</h2>'+self.form('/logout','','Log out')+'<form method="post" action="/application"><label>Full name<input id="app-name"></label><label>Email<input type="email"></label><label>CV<input type="file"></label><button id="apply-submit" type="submit">Submit application</button></form>')
            elif path=='/verify-email':self.send('<h2>Verify your email — confirm your account</h2>'+self.form('/confirm-email','<label>Fictitious email confirmation<input id="code" name="code"></label>','Confirm fictitious email'))
            elif path=='/otp':self.send('<h2>Two-factor authentication — OTP verification code</h2>'+self.form('/otp','<label>Verification code<input id="code" name="code" autocomplete="one-time-code"></label>','Verify fictitious OTP'))
            elif path=='/recover':self.send(self.form('/recover','<h2>Password recovery — reset password</h2><label>Email<input id="email" type="email" name="email"></label>','Send fictitious reset link'))
            elif path=='/captcha':self.send('<h2>CAPTCHA simulado — verify you are human</h2>')
            elif path=='/identity':self.send('<h2>Identity verification</h2>')
            elif path=='/sms':self.send('<h2>Verification code sent by SMS</h2>')
            elif path=='/blocked':self.send('<h2>Account locked</h2>')
            else:self.send('<h2>Not found</h2>',404)
        def do_POST(self):
            path=urlsplit(self.path).path;requests.append(dict(method='POST',path=path));state['posts']+=1
            if path=='/application':state['application_posts']+=1;self.send('Application submission forbidden',403);return
            length=int(self.headers.get('Content-Length','0'))
            if length>10000:self.send('Too large',413);return
            values={k:v[0] for k,v in parse_qs(self.rfile.read(length).decode()).items()};email=values.get('email','')
            if path=='/register':
                if not email.endswith('@example.invalid') or values.get('password')!=values.get('confirm') or len(values.get('password',''))<16:self.send('Invalid fictitious registration',400);return
                if email in accounts:self.send('Account already exists',409);return
                salt=secrets.token_bytes(16);accounts[email]=dict(salt=salt,digest=pbkdf2_hmac('sha256',values['password'].encode(),salt,60000),verified=False,locked=False)
                state['registered_email']=email;state['email_code']=secrets.token_urlsafe(12);self.send('',302,location='/verify-email')
            elif path=='/login':
                account=accounts.get(email)
                if account and account['locked']:self.send('<h2>Account locked</h2>');return
                if not account or not hmac.compare_digest(account['digest'],pbkdf2_hmac('sha256',values.get('password','').encode(),account['salt'],60000)):
                    self.send('<h2>Incorrect password — invalid credentials</h2>');return
                if not account['verified']:self.send('',302,location='/verify-email');return
                if state.get('require_mfa'):state['mfa_email']=email;state['otp']=str(secrets.randbelow(900000)+100000);self.send('',302,location='/otp');return
                session=secrets.token_urlsafe(32);sessions[session]=email;self.send('',302,location='/dashboard',cookie=cookie_name+'='+session+'; Path=/; Max-Age=600; HttpOnly; SameSite=Strict')
            elif path=='/confirm-email':
                if not secrets.compare_digest(values.get('code',''),state.get('email_code','unavailable')):self.send('Wrong fictitious confirmation',400);return
                accounts[state['registered_email']]['verified']=True;self.send('',302,location='/login')
            elif path=='/otp':
                if not secrets.compare_digest(values.get('code',''),state.get('otp','unavailable')):self.send('Wrong fictitious OTP',400);return
                session=secrets.token_urlsafe(32);sessions[session]=state['mfa_email'];self.send('',302,location='/dashboard',cookie=cookie_name+'='+session+'; Path=/; Max-Age=600; HttpOnly; SameSite=Strict')
            elif path=='/logout':sessions.clear();self.send('',302,location='/login',cookie=cookie_name+'=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict')
            elif path=='/recover':self.send('<h2>Verify your email — fictitious reset link prepared</h2>')
            else:self.send('Forbidden',403)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start();state['origin']='http://127.0.0.1:'+str(server.server_port)
    try:yield state
    finally:server.shutdown();server.server_close();thread.join(timeout=2);accounts.clear();sessions.clear()

class LocalAuthGuard:
    """Capacidad de un solo POST, solo al servidor ficticio y para autenticación."""
    paths={'/register','/login','/recover','/confirm-email','/otp','/logout'}
    def __init__(self,browser,fixture):
        from autojob.forms.guard import origin
        if urlsplit(fixture['origin']).hostname!='127.0.0.1' or not re_token(fixture['token']):raise ValueError('Se requiere una capacidad del portal ficticio local.')
        self.fixture=fixture;self.browser=browser;self.permit=None;self.blocked=0
        self.origin=origin(fixture['origin']);browser.context.route('**/*',self.route);browser.context.route_web_socket('**/*',lambda ws:ws.close())
        script=r'''(()=>{const token=__TOKEN__;const allowed=new Set(['/register','/login','/recover','/confirm-email','/otp','/logout']);
         const valid=f=>document.querySelector('meta[name="autojob-auth-fixture"]')?.content===token&&f.dataset.autojobAuth==='true'&&new URL(f.action).origin===location.origin&&allowed.has(new URL(f.action).pathname);
         const stop=e=>{e.preventDefault();e.stopImmediatePropagation()};document.addEventListener('submit',e=>{if(!valid(e.target))stop(e)},true);
         const native=HTMLFormElement.prototype.submit;HTMLFormElement.prototype.submit=function(){if(!valid(this))throw Error('AUTOJOB_APPLICATION_DISABLED');return native.call(this)};
         const request=HTMLFormElement.prototype.requestSubmit;HTMLFormElement.prototype.requestSubmit=function(b){if(!valid(this))throw Error('AUTOJOB_APPLICATION_DISABLED');return request.call(this,b)};
         document.addEventListener('click',e=>{const b=e.target.closest?.('button,input[type=submit]');if(b?.form&&!valid(b.form)&&b.type==='submit')stop(e)},true);
         document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('input[type=file]').forEach(e=>e.disabled=true));})();'''
        browser.context.add_init_script(script.replace('__TOKEN__',json.dumps(fixture['token'])))
    def route(self,route):
        from autojob.forms.guard import origin
        r=route.request;p=urlsplit(r.url)
        allowed=origin(r.url)==self.origin and not p.path.startswith('/application')
        if r.method=='POST':
            allowed=allowed and p.path==self.permit and p.path in self.paths
            if allowed:self.permit=None
        else:allowed=allowed and r.method in {'GET','HEAD'}
        if allowed:route.continue_()
        else:self.blocked+=1;route.abort()
    def page(self,path):
        page=self.browser.new_page();cdp=self.browser.context.new_cdp_session(page);cdp.send('Network.enable');cdp.send('Network.setBypassServiceWorker',{'bypass':True});self.goto(page,path);return page
    def goto(self,page,path):
        if not path.startswith('/') or path.startswith('//') or urlsplit(path).path.startswith('/application'):raise ValueError('Ruta local no autorizada.')
        response=page.goto(self.origin+path,wait_until='domcontentloaded',timeout=10000)
        if response and response.status>=400:raise ValueError('Error del portal ficticio.')
        self.validate(page)
    def validate(self,page):
        from autojob.forms.guard import origin
        if origin(page.url)!=self.origin or page.locator('meta[name="autojob-auth-fixture"]').get_attribute('content')!=self.fixture['token']:raise ValueError('La página no corresponde al portal de pruebas autorizado.')
    def submit(self,page,path):
        self.validate(page)
        if path not in self.paths:raise ValueError('El envío de postulaciones permanece deshabilitado.')
        if page.locator('form[data-autojob-auth=true]').get_attribute('action')!=path:raise ValueError('La acción no coincide con la etapa de autenticación.')
        self.permit=path
        try:page.locator('#auth-submit').click(timeout=5000);page.wait_for_load_state('domcontentloaded');self.validate(page)
        finally:self.permit=None

def re_token(token):
    import re
    return isinstance(token,str) and re.fullmatch('[0-9a-f]{48}',token)

def run_local(settings):
    """Prueba completa, sin devolver secretos, cookies, hashes ni códigos."""
    from dataclasses import replace
    from autojob.auth.service import Accounts
    from autojob.auth.detection import inspect_auth
    from autojob.browser import BraveSession
    with TemporaryDirectory(prefix='autojob-auth8a-') as directory,local_portal() as fixture:
        root=Path(directory);store=Accounts(root);id=store.add('Portal ficticio Job Hunting',fixture['origin'],'candidate@example.invalid',domain_verified=True,email_confirmed=True,allow_local=True)
        secret=store.generate(id);store.save_secret(id,secret);secret.clear()
        report=dict(external_accounts_created=0,applications_sent=0,windows_vault_verified=False,observations=[])
        try:
            restored=Accounts(root);retrieved=restored.credential(id,fixture['origin'],authorized=True,allow_local=True);assert retrieved is not None;retrieved.clear();report['windows_vault_verified']=True
            lab_settings=replace(settings,root=root,data_dir='browser-data')
            with BraveSession(lab_settings) as browser:
                guard=LocalAuthGuard(browser,fixture);page=guard.page('/signup');assert inspect_auth(page)['kind']=='REGISTRO'
                page.locator('#first').fill('Test');page.locator('#last').fill('Candidate');page.locator('#email').fill('candidate@example.invalid')
                secret=store.credential(id,fixture['origin'],True,True)
                try:page.locator('#password').fill(secret.reveal());page.locator('#confirm').fill(secret.reveal())
                finally:secret.clear()
                assert not page.locator('#terms').is_checked();guard.submit(page,'/register')
                observation=inspect_auth(page);assert 'CORREO' in observation['blocks'];store.observe(id,observation);report['observations'].append('CORREO')
                # Códigos ficticios obtenidos del propio servidor de pruebas, nunca del correo o SMS del usuario.
                page.locator('#code').fill(fixture['email_code']);guard.submit(page,'/confirm-email')
                def login():
                    guard.goto(page,'/login');page.locator('#email').fill('candidate@example.invalid');secret=store.credential(id,fixture['origin'],True,True)
                    try:page.locator('#password').fill(secret.reveal())
                    finally:secret.clear()
                    guard.submit(page,'/login')
                login();assert inspect_auth(page)['authenticated'];store.observe(id,inspect_auth(page));guard.goto(page,'/protected');assert inspect_auth(page)['authenticated'];report['protected_form_reached']=True
                page.locator('#apply-submit').click();page.wait_for_timeout(100);assert fixture['application_posts']==0
                assert page.evaluate('()=>{try{document.querySelector("form[action=\'/application\']").submit();return false}catch(e){return true}}')
                # Recargar conserva la sesión del navegador; no se exportan cookies.
                page.reload(wait_until='domcontentloaded');assert inspect_auth(page)['authenticated'];report['session_recovered']=True
                browser.close();browser.start();guard=LocalAuthGuard(browser,fixture);page=guard.page('/protected');assert inspect_auth(page)['authenticated'];report['session_recovered_after_browser_restart']=True
                fixture['sessions'].clear();guard.goto(page,'/protected');expired=inspect_auth(page,True);assert 'SESIÓN EXPIRADA' in expired['blocks'];store.observe(id,expired);report['observations'].append('SESIÓN EXPIRADA')
                page.locator('#email').fill('candidate@example.invalid');wrong=store.generate(id)
                try:page.locator('#password').fill(wrong.reveal())
                finally:wrong.clear()
                guard.submit(page,'/login');incorrect=inspect_auth(page);assert 'CREDENCIALES INCORRECTAS' in incorrect['blocks'];store.observe(id,incorrect);report['observations'].append('CREDENCIALES INCORRECTAS')
                fixture['require_mfa']=True;login();mfa=inspect_auth(page);assert {'MFA','OTP'}<=set(mfa['blocks']);store.observe(id,mfa);report['observations']+=['MFA','OTP']
                page.locator('#code').fill(fixture['otp']);guard.submit(page,'/otp');assert inspect_auth(page)['authenticated']
                guard.submit(page,'/logout');assert inspect_auth(page)['kind']=='LOGIN';report['logout_verified']=True
                guard.goto(page,'/recover');page.locator('#email').fill('candidate@example.invalid');guard.submit(page,'/recover');assert 'CORREO' in inspect_auth(page)['blocks'];report['recovery_simulated']=True
                for path,block in [('/captcha','CAPTCHA'),('/identity','IDENTIDAD'),('/sms','SMS'),('/blocked','CUENTA BLOQUEADA')]:
                    guard.goto(page,path);observation=inspect_auth(page);assert block in observation['blocks'];store.observe(id,observation);report['observations'].append(block)
                report['application_barrier_verified']=fixture['application_posts']==0
            # Verificar que SQLite y la exportación no contienen la contraseña generada.
            exported=root/'safe-export.json';store.export(exported);retrieved=store.credential(id,fixture['origin'],True,True)
            try:
                with closing(store.db.connect()) as db:serialized='\n'.join(db.iterdump())
                assert retrieved.reveal() not in serialized and retrieved.reveal() not in exported.read_text(encoding='utf-8')
            finally:retrieved.clear()
            report['persistence_verified']=Accounts(root).get(id) is not None;report['secret_absent_from_exports']=True
        finally:
            store.delete_secret(id);assert store.get(id)['credential_ref'] is None
            report['test_credential_deleted']=True
        return report
