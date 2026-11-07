"""Reconoce autenticación sin leer valores ni persistir el texto de la página."""
import re,unicodedata
from urllib.parse import urlsplit,urlunsplit

def norm(value):return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))

def safe_url(url):
    p=urlsplit(url)
    if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password:raise ValueError('URL de autenticación inválida.')
    # Los tokens, enlaces firmados y parámetros de redirección no se guardan.
    return urlunsplit((p.scheme,p.netloc.lower(),p.path,'',''))

SCAN=r'''() => {
const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
const label=e=>(Array.from(e.labels||[]).map(l=>l.innerText).join(' ')||e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.name||'').slice(0,160);
return {text:(document.body?.innerText||'').slice(0,80000),fields:Array.from(document.querySelectorAll('input,select,button')).filter(visible).slice(0,120).map(e=>({type:e.type||e.tagName.toLowerCase(),label:label(e)||(e.innerText||(['submit','button'].includes(e.type)?e.value:'')||'').slice(0,160),autocomplete:e.autocomplete||'',required:e.required||e.getAttribute('aria-required')==='true'})),captcha:!!document.querySelector('iframe[src*="captcha"],[data-sitekey],script[src*="captcha"]')};
}'''

def classify(data,url,expected_protected=False):
    text=norm(data.get('text',''));fields=data.get('fields',[]);blocks=[]
    patterns={
        'CAPTCHA':r'captcha|verify you are human|verifica que eres humano',
        'CORREO':r'verify (?:your )?email|confirm (?:your )?(?:email|account)|verifica.{0,12}correo|confirma.{0,12}cuenta|pending activation|pendiente de activacion',
        'MFA':r'multi.factor|two.factor|authenticator|autenticacion.{0,12}(?:factor|pasos)',
        'OTP':r'one.time (?:password|code)|verification code|codigo de verificacion|\botp\b',
        'SMS':r'code.{0,20}sms|sms.{0,20}code|codigo.{0,20}sms|text message',
        'IDENTIDAD':r'identity verification|verify your identity|verificacion de identidad',
        'CUENTA BLOQUEADA':r'account (?:locked|blocked|suspended)|cuenta (?:bloqueada|suspendida)',
        'CREDENCIALES INCORRECTAS':r'incorrect (?:password|credentials)|invalid (?:password|credentials)|contrasena incorrecta|credenciales incorrectas',
        'SESIÓN EXPIRADA':r'session expired|session has expired|sesion (?:ha )?(?:expirado|caducada)'}
    for kind,pattern in patterns.items():
        if re.search(pattern,text) or kind=='CAPTCHA' and data.get('captcha'):blocks.append(kind)
    passwords=[f for f in fields if f['type']=='password']
    email_first=any(f['type']=='email' for f in fields) and not any(f['type']=='file' for f in fields)
    join_button=any(f['type'] in {'button','submit'} and norm(f.get('label','')).strip() in {'join','unirse'} for f in fields)
    buttons=' '.join(norm(f.get('label','')) for f in fields if f['type'] in {'button','submit'})
    login_cta=bool(re.search(r'log ?in|sign ?in|iniciar sesion',buttons))
    register_cta=bool(re.search(r'sign ?up|create (?:an? )?account|register|registrarse|crear cuenta',buttons) or join_button)
    names=any(re.search(r'full name|first name|last name|nombre|apellido|given-name|family-name',norm(f.get('label','')+' '+f.get('autocomplete',''))) for f in fields)
    body_register=bool(re.search(r'create account|sign up|\bregister\b|registrarse|crear cuenta',text))
    body_login=bool(re.search(r'log in|sign in|iniciar sesion',text))
    registration=bool((passwords or email_first) and (len(passwords)>1 or any(f.get('autocomplete')=='new-password' for f in passwords) or register_cta or names and not login_cta or body_register and not body_login and not login_cta))
    login=bool(passwords or email_first and (login_cta or re.search(r'log in|sign in|iniciar sesion|continue with email',text)))
    recovery=bool(not login_cta and (re.search(r'reset|recover|restablecer|recuperar',buttons) or not passwords and re.search(r'reset password|password recovery|recuperar (?:cuenta|contrasena)|reset link',text)))
    if recovery:registration=False;login=False
    authenticated=bool(not passwords and re.search(r'log out|sign out|cerrar sesion',text) and re.search(r'my account|dashboard|mi cuenta|panel de cuenta|authenticated',text))
    kind='REGISTRO' if registration else 'LOGIN' if login else 'RECUPERACIÓN' if recovery else 'VERIFICACIÓN' if any(k in blocks for k in ['CORREO','MFA','OTP','SMS','IDENTIDAD']) else 'AUTENTICADA' if authenticated else 'ENLACES DE ACCESO' if re.search(r'log in|sign in|sign up|create account|forgot password|continue with email',text) else 'DESCONOCIDO'
    if expected_protected and kind=='LOGIN' and 'SESIÓN EXPIRADA' not in blocks:blocks.append('SESIÓN EXPIRADA')
    # Solo categorías de campos, nunca sus valores ni el cuerpo de la página.
    roles=[]
    for f in fields:
        q=norm(f.get('label','')+' '+f.get('autocomplete',''));t=f['type']
        role='confirm_password' if t=='password' and re.search(r'confirm|repeat|repet',q) else 'password' if t=='password' else 'email' if t=='email' or re.search(r'email|correo',q) else 'otp' if re.search(r'otp|verification code|codigo de verificacion|one-time-code',q) else 'terms' if t=='checkbox' and re.search(r'terms|agree|acepto|terminos',q) else 'last_name' if re.search(r'last name|surname|apellido|family-name',q) else 'first_name' if re.search(r'first name|nombre|given-name',q) else 'username' if re.search(r'username|usuario',q) else 'button' if t in {'submit','button'} else 'unknown'
        roles.append(dict(role=role,type=t,required=bool(f.get('required'))))
    return dict(url=safe_url(url),kind=kind,fields=roles,blocks=list(dict.fromkeys(blocks)),authenticated=authenticated)

def inspect_auth(page,expected_protected=False):
    # La página principal identifica el origen; los iframes no reciben credenciales.
    return classify(page.evaluate(SCAN),page.url,expected_protected)
