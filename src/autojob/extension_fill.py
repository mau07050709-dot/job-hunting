"""Puente local explícito para rellenar, sin enviar, en el Brave del usuario."""
import json,secrets,time
from pathlib import Path
from hashlib import sha256
from queue import Queue
from threading import Thread,RLock
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from uuid import uuid4

PORT=18746
WAKE_PATH="/jobmaxxing-wake"

def allowed_page(task,url):
    from autojob.forms.guard import origin
    from autojob.search.access_policy import remote_ok,paywall_url
    try:
        p=urlsplit(url)
        if p.username or p.password or remote_ok(url) or paywall_url(url):return False
        if origin(url)==origin(task['url']):return True
        if any(origin(url)==origin(entry) and p.path.rstrip('/')==urlsplit(entry).path.rstrip('/') for entry in task.get('exact_pages',[])):return True
        if any(origin(url)==entry['origin'] and (p.path==entry['prefix'].rstrip('/') or p.path.startswith(entry['prefix'])) for entry in task.get('entry_pages',[])):
            return True
        # Ruta oficial comprobada: anuncio de Lemon -> web -> registro de talento.
        company=''.join(c for c in task['job'].get('company','').lower() if c.isalnum())
        return p.scheme=='https' and company=='lemonio' and p.hostname in {'lemon.io','www.lemon.io','me.lemon.io'}
    except (ValueError,TypeError):return False

def allow_entry(task,url):
    """Seguir Apply solo al anuncio conocido o al ATS verificable de esa empresa."""
    from autojob.forms.guard import origin
    import re
    if allowed_page(task,url):return True
    try:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.username or parsed.password:return False
        host=parsed.hostname
        paths=[p for p in parsed.path.split('/') if p]
        if not paths:return False
        company=task['job'].get('company','')
        def normalized(value):
            words=re.findall(r"[a-z0-9]+",value.casefold())
            while words and words[-1] in {'inc','llc','ltd','co','corp','corporation','company','sa'}:words.pop()
            return ''.join('tech' if w in {'technology','technologies'} else w for w in words)
        known=[task['job'].get('application_url'),task['job'].get('url')]
        known.extend((task['job'].get('raw') or {}).get(k) for k in ('applicationLink','apply_url'))
        expected=any(link and origin(link)==origin(url) and parsed.path.rstrip('/').removesuffix('/apply')==urlsplit(link).path.rstrip('/').removesuffix('/apply') for link in known)
        ats=host in {'jobs.lever.co','apply.workable.com','job-boards.greenhouse.io','boards.greenhouse.io','jobs.ashbyhq.com','jobs.smartrecruiters.com'}
        specific=len(paths)>=2 and (host not in {'job-boards.greenhouse.io','boards.greenhouse.io'} or len(paths)>=3 and paths[1]=='jobs')
        same_company=bool(paths and normalized(company) and normalized(paths[0])==normalized(company))
        bamboo=bool(host and host.endswith('.bamboohr.com') and len(host.split('.'))==3 and len(paths)>=2 and paths[0]=='careers' and paths[1].isdigit() and normalized(host.split('.')[0])==normalized(company))
        if not expected and not bamboo and not (ats and specific and same_company):return False
        prefix='/careers/'+paths[1]+'/' if bamboo else '/'+paths[0]+'/'
        task.setdefault('entry_pages',[]).append(dict(origin=origin(url),prefix=prefix))
        return True
    except (ValueError,TypeError):
        return False


def salary_display(answer,question):
    """Solo presentación mensual/anual: mantener precisión de cálculos y salarios por hora."""
    import re
    from decimal import Decimal,ROUND_HALF_UP
    from autojob.profile.answers import norm
    q=norm(question)
    if re.search(r'\bhour|hora',q) or not re.search(r'month|mensual|mes|year|annual|anual',q):return answer
    text=str(answer)
    if not re.fullmatch(r'\d+(?:\.\d+)?(?:[–—-]\d+(?:\.\d+)?)?',text):return answer
    return re.sub(r'\d+(?:\.\d+)?',lambda m:str(Decimal(m[0]).quantize(Decimal('1'),rounding=ROUND_HALF_UP)),text)

class ExtensionFill:
    def __init__(self,settings,pair_data_path=None):
        self.settings=settings;self.events=Queue();self.notices=Queue();self.tasks={};self.lock=RLock();self.server=None;self.last_seen=0
        self.retired=False
        self.visual=None
        self.owner=sha256(str(settings.data_path).casefold().encode()).hexdigest()
        p=(pair_data_path or settings.data_path)/'extension-pair.json'
        self.pair_path=p
        self.fast_wake=False
        if p.exists():
            saved=json.loads(p.read_text(encoding='utf-8'));self.token=saved['token'];self.paired=saved.get('paired',False);self.fast_wake=saved.get('fast_wake',False)
        else:
            self.paired=False;self.token=secrets.token_urlsafe(32);p.write_text(json.dumps(dict(token=self.token)),encoding='utf-8')
    def start(self):
        if self.server:return
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path.startswith('/notice-video/'):
                    from autojob.notice_media import video_html,NoticeMedia
                    try:body=video_html(self.path.removeprefix('/notice-video/'),sound=NoticeMedia(bridge.pair_path.parent).load()['sound']).encode('utf-8')
                    except ValueError:self.send_error(404);return
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Referrer-Policy','origin');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                if self.path!=WAKE_PATH:
                    self.send_error(404);return
                body=b'<!doctype html><meta charset="utf-8"><title>Job Hunting</title><p>Abriendo la candidatura en Brave. Si esta pantalla sigue abierta, recarga la extension Job Hunting en brave://extensions.</p>'
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_OPTIONS(self):self.reply(403,{'error':'No permitido'})
            def reply(self,status,data):
                body=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                if not self.headers.get('Origin','').startswith('chrome-extension://') or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+bridge.token):self.reply(403,{'error':'Vinculación no válida'});return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=512000:raise ValueError('Tamaño inválido')
                    payload=json.loads(self.rfile.read(size));bridge.last_seen=time.monotonic()
                    self.reply(200,bridge.handle(self.path,payload))
                except Exception as exc:self.reply(400,{'error':str(exc)[:250]})
        self.server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
        Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.05},daemon=True).start()
    def close(self):
        if self.server:self.server.shutdown();self.server.server_close();self.server=None
    def busy(self):
        if not self.lock.acquire(blocking=False):return True
        try:return any(t["state"] in {"WAITING","FILLING"} for t in self.tasks.values())
        finally:self.lock.release()

    def retire(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError("El autorrelleno sigue preparando respuestas. Espera a que termine.")
        try:
            if any(t["state"] in {"WAITING","FILLING"} for t in self.tasks.values()):
                raise ValueError("Termina el autorrelleno actual antes de cambiar de persona.")
            self.retired=True
        finally:self.lock.release()

    def enqueue(self,row):
        from autojob.manual_search import useful_url
        from autojob.forms.submissions import SubmissionStore
        job=row['job'];url=row['url']
        if not useful_url(url):raise ValueError('Selecciona un enlace específico de una oferta.')
        if SubmissionStore(self.settings.data_path).duplicate(job):raise ValueError('Existe un envío confirmado o incierto: no se vuelve a rellenar esta candidatura.')
        with self.lock:
            if self.retired:raise ValueError("La persona activa ha cambiado.")
            if any(t['job']['id']==job['id'] and t['state'] in {'WAITING','FILLING'} for t in self.tasks.values()):raise ValueError('Esta oferta ya se está preparando; revisa su pestaña en Brave.')
            id=uuid4().hex;self.tasks[id]=dict(id=id,job=job,url=url,state='WAITING',created=time.monotonic(),rounds=0)
        return id
    def retry(self,task_id):
        with self.lock:
            task=self.tasks.get(task_id)
            if self.retired or not task:
                raise ValueError("Selecciona de nuevo la oferta de la persona activa.")
            if task["state"] in {"WAITING","FILLING"}:return
            task.update(state="WAITING",created=time.monotonic(),rounds=0)
    def visual_target(self):
        with self.lock:
            v=self.visual
            if self.retired or not v or time.monotonic()-v['seen']>5 or v['captcha']:return None
            return dict(v)
    def visual_detected(self,task_id,url):
        with self.lock:
            t=self.tasks.get(task_id)
            if not t or t['state']!='DONE' or not allowed_page(t,url):return False
            t['visual_wake']=True
            return True
    def finish_manual(self,job_id):
        with self.lock:
            ids=[]
            for task in self.tasks.values():
                if task['job'].get('id')==job_id:task['state']='ARCHIVED';ids.append(task['id'])
            if self.visual and self.visual['id'] in ids:self.visual=None
            return ids
    def abort(self,task_id):
        with self.lock:
            if task_id in self.tasks:self.tasks[task_id]["state"]="ERROR"

    def expire(self):
        if not self.lock.acquire(blocking=False):return
        try:
            for t in self.tasks.values():
                if t['state']=='WAITING' and time.monotonic()-t['created']>8 and not t.get('connection_notice'):
                    t['connection_notice']=True
                    message=t['job']['company']+': la oferta está abierta en Brave, pero la extensión todavía no ha recogido la tarea. Actívala y recárgala en brave://extensions; conserva tu vinculación.'
                    self.events.put(message)
                    self.notices.put(dict(id=t['id'],job=t['job'],url=t['url'],pending=['La extensión todavía no ha recogido la tarea'],message=message))
                if t['state'] in {'WAITING','FILLING'} and time.monotonic()-t.get('claimed',t['created'])>120:
                    t['state']='EXPIRED'
                    message=t['job']['company']+': la extensión no respondió. La oferta permanece abierta en Brave. Revisa que Job Hunting esté activada y vinculada en brave://extensions.'
                    self.events.put(message)
                    self.notices.put(dict(id=t['id'],job=t['job'],url=t['url'],pending=['La extensión no respondió; revisa su activación y vinculación'],message=message))
        finally:self.lock.release()
    def handle(self,path,payload):
        if self.retired:raise ValueError('La persona activa ha cambiado; selecciona su oferta desde Job Hunting.')
        if path=='/ping':
            fast_wake=payload.get('fast_wake') is True
            with self.lock:
                if not self.paired or self.fast_wake!=fast_wake:
                    self.pair_path.write_text(json.dumps(dict(token=self.token,paired=True,fast_wake=fast_wake)),encoding='utf-8')
                    self.paired=True
                    self.fast_wake=fast_wake
            return {'ok':True}
        with self.lock:
            if self.retired:raise ValueError('La persona activa ha cambiado.')
            if path=='/active':
                return [dict(id=t['id'],url=t['url'],owner=self.owner,company=t['job'].get('company',''),title=t['job'].get('title','')) for t in reversed(list(self.tasks.values())) if t['state'] in {'DONE','FILLING'} and time.monotonic()-t['created']<1800][:8]
            if path=='/visual-next':
                return [dict(id=t['id'],url=(self.visual or {}).get('url',t['url'])) for t in self.tasks.values() if t.pop('visual_wake',False) and t['state']=='DONE']
            if path=='/next':
                for t in self.tasks.values():
                    if t['state']=='WAITING':
                        if time.monotonic()-t['created']>120:t['state']='EXPIRED';continue
                        t['state']='FILLING';t['claimed']=time.monotonic();return dict(id=t['id'],url=t['url'],owner=self.owner,company=t['job'].get('company',''),title=t['job'].get('title',''))
                return {}
            t=self.tasks.get(payload.get('id'))
            if t and path=='/adopt':
                from autojob.forms.detection import candidate_form,job_identity,safe_destination
                url=payload.get('url','');scan=payload.get('scan') or {}
                active=t['state'] in {'FILLING','DONE'} and time.monotonic()-t['created']<1800
                bound=allowed_page(t,url)
                parent=payload.get('parent_url','');parent_scan=payload.get('parent_scan') or {}
                inherited=bool(parent and safe_destination(parent) and job_identity(t['job'],parent,parent_scan) and any(urlsplit(f.get('src',''))._replace(fragment='').geturl()==urlsplit(url)._replace(fragment='').geturl() for f in parent_scan.get('frames',[]) if f.get('visible') is not False))
                allowed=active and (candidate_form(scan) or payload.get('landing') is True and not scan.get('password') and job_identity(t['job'],url,scan)) and (bound or safe_destination(url) and (job_identity(t['job'],url,scan) or inherited))
                if allowed and not bound:t.setdefault('exact_pages',[]).append(url)
                if allowed and inherited and not allowed_page(t,parent):t.setdefault('exact_pages',[]).append(parent)
                return {'allowed':bool(allowed)}
            if t and path=='/follow':
                from autojob.forms.detection import safe_destination
                import re
                label=str(payload.get('label','')).strip()
                entry=bool(re.fullmatch(r'(?:apply(?: now| for (?:this )?(?:job|position))?|aplicar(?: ahora)?|postular(?:me| ahora)?|solicitar(?: puesto| empleo| este trabajo)?)\s*(?:→|↗)?',label,re.I))
                allowed=t['state'] in {'FILLING','DONE'} and allowed_page(t,payload.get('from_url','')) and safe_destination(payload.get('url','')) and entry
                if allowed:t.setdefault('exact_pages',[]).append(payload['url'])
                return {'allowed':bool(allowed)}
            if t and path=='/visual':
                if t['state'] not in {'DONE','FILLING'} or not allowed_page(t,payload.get('url','')):return {}
                self.visual=dict(id=t['id'],url=payload['url'],title=str(payload.get('title',''))[:300],height=min(max(int(payload.get('height',0)),0),2400),seen=time.monotonic(),captcha=payload.get('captcha') is True)
                return {}
            if t and path=='/scope':return {'allowed':t['state'] in {'FILLING','DONE'} and allowed_page(t,payload.get('url',''))}
            if t and path=='/entry':
                return {'allowed':t['state'] in {'FILLING','DONE'} and allow_entry(t,payload.get('url',''))}
            if t and path=='/resume':
                if t['state']!='DONE' or time.monotonic()-t['created']>1800 or not allowed_page(t,payload.get('url','')):raise ValueError('Esta página no está vinculada a una preparación vigente; selecciona de nuevo la oferta en Job Hunting.')
                t.update(state='FILLING',claimed=time.monotonic(),rounds=0)
                return dict(id=t['id'],url=t['url'],owner=self.owner,company=t['job'].get('company',''),title=t['job'].get('title',''))
            if not t or t['state']!='FILLING':raise ValueError('Tarea ausente o finalizada; pulsa de nuevo el botón para reanalizar.')
            if path=='/plan':return self.plan(t,payload)
            if path=='/done':
                t['state']='DONE';filled=int(payload.get('filled',0));pending=[str(s)[:180] for s in payload.get('pending',[])[:15]]
                message=f"{t['job']['company']} · {t['job']['title']}: {filled} campos rellenados y verificados. "
                message+=('No pude completar: '+ '; '.join(pending)+'. Continúa en la pestaña abierta de Brave; los valores se conservan.') if pending else 'Revisa la pestaña de Brave y completa tú los adjuntos y el envío final.'
                self.events.put(message)
                self.notices.put(dict(id=t['id'],job=t['job'],url=payload.get('url') if allowed_page(t,payload.get('url','')) else t['url'],pending=pending,message=message))
                return {'message':message}
        raise ValueError('Operación desconocida')
    def plan(self,t,payload):
        from autojob.forms.guard import origin
        from autojob.forms.preparation import inspect,Preparation
        from autojob.forms.runner import enrich
        from autojob.forms.answers9b import restricted
        from autojob.forms.submissions import SubmissionStore
        if not allowed_page(t,payload['url']):raise ValueError('El enlace redirigió a otro dominio no vinculado a esta oferta; continúa manualmente. No se transmitieron respuestas al nuevo dominio.')
        if SubmissionStore(self.settings.data_path).duplicate(t['job']):raise ValueError('Hay un resultado final previo; no se repite la candidatura.')
        t['rounds']+=1
        if t['rounds']>4:raise ValueError('Límite de reanálisis alcanzado; continúa manualmente.')
        data=payload['scan']
        from autojob.search.access_policy import paywall_page
        if paywall_page(payload['url'],data.get('text','')):
            from contextlib import closing
            from autojob.search.jobs import JobStore
            store=JobStore(self.settings.data_path)
            with closing(store.db.connect()) as c,c:
                row=c.execute('SELECT payload FROM discovered_jobs WHERE id=?',(t['job']['id'],)).fetchone()
                if row:
                    job=json.loads(row['payload']);job.update(application_access='PAGO',availability='REQUIERE PAGO',availability_evidence='La página de candidatura exige pago; excluida a petición del usuario')
                    c.execute('UPDATE discovered_jobs SET payload=? WHERE id=?',(json.dumps(job,ensure_ascii=False),t['job']['id']))
            return dict(entries=[],pending=['Esta oferta exige pago y se quitó de los resultados; no se rellenó ningún dato'])
        if not isinstance(data.get('fields'),list) or len(data['fields'])>200:raise ValueError('Demasiados controles')
        class Frame:
            url=payload['url']
            def evaluate(self,script):return data
        class Page:
            url=payload['url'];frames=[Frame()]
        document=inspect(Page(),max_frames=1)
        captcha=data.get('captcha') or {}
        if captcha.get('solved') is True or captcha.get('present') is False:
            document['obstacles']=[o for o in document['obstacles'] if o['type']!='CAPTCHA']
        from autojob.forms.detection import candidate_form
        if candidate_form(data):document['obstacles']=[o for o in document['obstacles'] if o['type']!='FORMULARIO NO IDENTIFICADO COMO POSTULACIÓN']
        import re
        from autojob.profile.answers import norm
        registration=bool(re.search(r'create (?:an? )?account|sign up|crear cuenta|registrar|join lemon',norm(data.get('text',''))))
        identity=any(re.search(r'full.?name|first.?name|nombre',norm(f['label'])) for f in document['fields'])
        mail=any(f['kind']=='email' or re.search(r'email|correo',norm(f['label'])) for f in document['fields'])
        registration=registration and identity and mail
        # Nunca rellenar buscadores, registro ni contraseñas como si fueran candidaturas.
        denied={'SIN FORMULARIO','FORMULARIO NO IDENTIFICADO COMO POSTULACIÓN','AUTENTICACIÓN','ERROR DEL PORTAL'}
        if registration:denied.discard('AUTENTICACIÓN')
        if any(o['type'] in denied for o in document['obstacles']):return dict(entries=[],pending=[o['type'] for o in document['obstacles']],waiting=True)
        prep=Preparation(self.settings.data_path)
        with prep.read_snapshot():
            from autojob.resumes.selection import ResumeSelector
            title=norm(t['job'].get('title',''))
            service=bool(re.search(r'customer (?:care|service|support|experience)|atencion al cliente|servicio al cliente',title))
            chosen=ResumeSelector(prep.compatibility.library).select(t['job'].get('title','')+'\n'+t['job'].get('description',''),specialty='customer_service') if service else None
            preview=prep.prepare(document,t['job'],cv_id=chosen.resume_id if chosen else None)
            fields=[enrich(prep,raw) for raw in preview['entries']]
        entries=[];pending=[]
        present={f['selector']:f for f in data['fields']}
        for e in fields:
            current=present.get(e['selector'],{})
            if current.get('has_value') and current.get('valid') is True and e['kind'] not in {'checkbox','radio','file','button'}:
                continue
            question=e.get('group') or e['label']
            q=norm(question).strip(' *:')
            if not registration and q in {'date available','available date','fecha disponible','fecha de disponibilidad'}:
                answer,status=prep.data.value('start_date')
                if answer and status in {'CONFIRMADA','DERIVADA'}:
                    from datetime import date
                    parsed=date.fromisoformat(answer)
                    hint=current.get('placeholder','').lower()
                    answer=answer if e['kind']=='date' else parsed.strftime('%d/%m/%Y' if hint.startswith('dd') else '%m/%d/%Y')
                    e.update(answer=answer,status=status)
            if not registration and q in {'desired pay','desired salary','salario deseado','remuneracion deseada'} and e['kind'] in {'text','textarea'} and e['status'] not in {'CONFIRMADA','DERIVADA','CONFLICTO','SENSIBLE','BLOQUEADA'}:
                currency,cs=prep.data.value('main_currency');period,ps=prep.data.value('main_period')
                if cs=='CONFIRMADA' and ps=='CONFIRMADA' and period in {'month','year','hour'}:
                    amount,st,_=prep.data.salary('main',period,currency,'expected')
                    if amount is None:
                        lo,ls,_=prep.data.salary('main',period,currency,'min');hi,hs,_=prep.data.salary('main',period,currency,'max')
                        if lo and hi and ls in {'CONFIRMADA','DERIVADA'} and hs in {'CONFIRMADA','DERIVADA'}:amount,st=lo+'–'+hi,'DERIVADA'
                    if amount is not None and st in {'CONFIRMADA','DERIVADA'}:
                        amount=salary_display(amount,'monthly' if period=='month' else 'annual' if period=='year' else 'hourly')
                        e.update(answer=f'{currency} {amount} per {period}',status=st)
            if e['kind']=='file':
                if current.get('has_value'):continue
                if not registration and not (service and not chosen.resume_id) and e.get('document')=='cv' and e.get('answer') and preview.get('cv_confirmed') and not any(b['type'] in {'VACANTE INCOMPATIBLE','CV INCOMPATIBLE'} for b in preview['blocks']):
                    import base64,mimetypes
                    try:
                        path=prep.compatibility.library.original_path(e['answer'])
                        if path.stat().st_size>5*1024*1024:raise ValueError('CV demasiado grande')
                        entries.append(dict(selector=e['selector'],kind='file',document='cv',label=e['label'],file=dict(name=Path(prep.compatibility.library.get(e['answer'])['filename']).name,type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',data=base64.b64encode(path.read_bytes()).decode('ascii'))))
                        continue
                    except (ValueError,OSError):pass
                pending.append(e['label']);continue
            if registration and not re.search(r'name|nombre|apellido|email|correo|phone|telefono|country|pais|linkedin',norm(question)):
                if e.get('required'):pending.append(e['label'])
                continue
            if e.get('sensitive_identity') or e.get('requires_specific_consent') or restricted(question) or e['kind'] in {'file','button','password'} or e['kind'] not in {'text','email','tel','url','number','date','textarea','select','multiple','checkbox','radio','search'}:
                if e.get('required') or e['kind']=='file':pending.append(e['label'])
                continue
            if e['status'] in {'CONFIRMADA','DERIVADA'} and e.get('answer') is not None:
                if e.get('semantic')=='salary' and e['kind'] in {'text','textarea','number'}:
                    e['answer']=salary_display(e['answer'],e['label']+' '+e.get('group',''))
                entries.append({k:e.get(k) for k in ['selector','kind','answer','label','group','required']})
            elif e.get('required'):pending.append(e['label'])
        pending.extend(o['type'] for o in document['obstacles'])
        if registration:pending.append('Registro de cuenta: revisa tú los términos, Google y Crear cuenta. No se ha enviado una candidatura')
        if data.get('frames') and not captcha.get('solved'):
            pending.append('CAPTCHA o formulario incrustado: complétalo en esta pestaña de Brave')
        if captcha.get('pending'):
            pending.append('Resuelve el CAPTCHA en Brave; después volveré a analizar el formulario')
        return dict(entries=entries,pending=list(dict.fromkeys(pending)))
