"""Intervención humana, estados persistentes y reserva acotada del perfil único."""
from contextlib import closing
from datetime import datetime,timezone
from uuid import uuid4
from urllib.parse import urlsplit
import json,time
from autojob.storage.database import Database
from autojob.auth.detection import safe_url

CAPTCHA_SCAN=r'''() => {
 const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
 const response=Array.from(document.querySelectorAll('[name="g-recaptcha-response"],[name="h-captcha-response"],[name="cf-turnstile-response"]')).some(e=>!!e.value?.trim());
 const markers=Array.from(document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"],.g-recaptcha,.h-captcha,.cf-turnstile,[data-captcha],[data-sitekey]'));
 const text=(document.body?.innerText||'').slice(0,80000);const textual=/captcha|verify (?:you are|that you are) human|verifica que eres humano|security challenge/i.test(text);
 const challenge=markers.some(e=>visible(e)&&/bframe|challenge/.test(e.src||''));
 return {interactive:markers.some(visible),detected:markers.length>0||textual,completed:response&&!challenge,provider:markers.some(e=>/cloudflare|turnstile/.test(e.src||e.className))?'Turnstile':markers.some(e=>/hcaptcha|h-captcha/.test(e.src||e.className))?'hCaptcha':markers.some(e=>/recaptcha/.test(e.src||e.className))?'reCAPTCHA':'Otro'};
}'''

def captcha_state(page,fixture=None):
    state=page.evaluate(CAPTCHA_SCAN)
    if fixture:
        from autojob.forms.guard import origin
        if origin(page.url)==fixture['origin'] and page.locator('meta[name="autojob-human-fixture"]').count() and page.locator('meta[name="autojob-human-fixture"]').get_attribute('content')==fixture['token']:
            state['completed']=page.locator('[data-human-result="complete"]').count()>0
    return state

class VerificationStore:
    def __init__(self,data_path):
        self.data_path=data_path;self.db=Database(data_path/'autojob.sqlite3')
        with closing(self.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS verification_tasks(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,kind TEXT NOT NULL,url TEXT NOT NULL,title TEXT NOT NULL,state TEXT NOT NULL,command TEXT NOT NULL,reserved INTEGER NOT NULL,updated_at TEXT NOT NULL,UNIQUE(job_id,kind,url))')
    def add(self,job_id,kind,url,title='Vacante',reserved=False):
        url=safe_url(url);id=uuid4().hex
        with closing(self.db.connect()) as db,db:
            db.execute("INSERT INTO verification_tasks VALUES (?,?,?,?,?,'PENDIENTE','',?,?) ON CONFLICT(job_id,kind,url) DO UPDATE SET state='PENDIENTE',command='',reserved=excluded.reserved,updated_at=excluded.updated_at",(id,job_id,kind,url,title[:250],int(reserved),datetime.now(timezone.utc).isoformat()))
            row=db.execute('SELECT id FROM verification_tasks WHERE job_id=? AND kind=? AND url=?',(job_id,kind,url)).fetchone()
        return row[0]
    def list(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM verification_tasks ORDER BY updated_at DESC')]
    def update(self,id,state=None,command=None,reserved=None):
        if state not in {None,'PENDIENTE','EN INTERVENCIÓN','LISTA PARA CONTINUAR','OMITIDA','ERROR'} or command not in {None,'RESOLVER','OMITIR',''}:raise ValueError('Estado de verificación inválido.')
        with closing(self.db.connect()) as db,db:db.execute('UPDATE verification_tasks SET state=COALESCE(?,state),command=COALESCE(?,command),reserved=COALESCE(?,reserved),updated_at=? WHERE id=?',(state,command,reserved,datetime.now(timezone.utc).isoformat(),id))
    def recover(self):
        from autojob.browser.lock import ProfileLock
        lock=ProfileLock(self.data_path/'browser.lock')
        try:lock.acquire()
        except Exception:return 0
        try:
            with closing(self.db.connect()) as db,db:return db.execute("UPDATE verification_tasks SET reserved=0,state='PENDIENTE',command='' WHERE reserved=1").rowcount
        finally:lock.release()

_bus=None
def bus():
    global _bus
    if _bus is None:
        from PySide6.QtCore import QObject,Signal
        class Bus(QObject):notice=Signal(str,str,str)
        _bus=Bus()
    return _bus

def notify(id,title,body):
    # El receptor Qt entrega la notificación a Windows desde el hilo gráfico.
    if _bus is not None:_bus.notice.emit(id,title[:100],body[:220])

class CaptchaCoordinator:
    def __init__(self,data_path):self.store=VerificationStore(data_path)
    def wait(self,page,guard,job_id,title,stop=lambda:False,pause=lambda:False,seconds=30,fixture=None,manual_start=False):
        initial=captcha_state(page,fixture)
        if initial.get('completed'):return True
        if not initial.get('interactive') and not fixture:return False
        id=self.store.add(job_id,'CAPTCHA PENDIENTE',page.url,title,True);notify(id,'Job Hunting necesita intervención',f'CAPTCHA en {title}. Abre el centro de notificaciones para resolver en Brave u omitir.')
        if getattr(guard,'defer_interventions',False):self.store.update(id,reserved=False);return False
        if fixture and fixture.get('on_wait'):fixture['on_wait'](page,id,self.store)
        if not captcha_state(page,fixture).get('interactive',False):self.store.update(id,reserved=False);return False
        if manual_start:self.store.update(id,command='RESOLVER')
        original=guard.route;context=guard.context if hasattr(guard,'context') else guard.browser.context;manual=[False]
        def verification_route(route):
            p=urlsplit(route.request.url);host=(p.hostname or '').lower()
            provider=(host in {'www.google.com','www.recaptcha.net'} and p.path.startswith('/recaptcha/')) or host=='hcaptcha.com' or host.endswith('.hcaptcha.com') or host=='challenges.cloudflare.com'
            if manual[0] and provider and route.request.method in {'GET','POST','OPTIONS'}:route.continue_();return
            original(route)
        context.unroute('**/*');context.route('**/*',verification_route)
        deadline=time.monotonic()+max(0,min(seconds,180))
        try:
            while (manual[0] or manual_start or time.monotonic()<deadline) and not stop() and (manual[0] or manual_start or not pause()) and not page.is_closed():
                task=next(r for r in self.store.list() if r['id']==id)
                if task['command']=='OMITIR':self.store.update(id,'OMITIDA',reserved=False);return False
                if task['command']=='RESOLVER' and not manual[0]:
                    manual[0]=True;page.bring_to_front();self.store.update(id,'EN INTERVENCIÓN')
                    # Mantener el iframe y token existentes; solo enfocar la sesión.
                if captcha_state(page,fixture)['completed']:
                    self.store.update(id,'LISTA PARA CONTINUAR',command='',reserved=False);notify(id,'Job Hunting · tarea reanudada',title);return True
                page.wait_for_timeout(250)
            self.store.update(id,'PENDIENTE',command='',reserved=False);return False
        finally:
            context.unroute('**/*');context.route('**/*',original)
            # Una excepción o cierre no deja una reserva falsa.
            self.store.update(id,reserved=False)

def record_obstacle(data_path,job_id,kind,url,title):
    store=VerificationStore(data_path);id=store.add(job_id,kind,url,title);notify(id,'Job Hunting · intervención pendiente',title+' · '+kind);return id
