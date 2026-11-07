from contextlib import closing
from datetime import datetime,timezone
from urllib.parse import urlsplit
from uuid import uuid4
import ipaddress,json,re,secrets
from autojob.storage.database import Database
from autojob.auth.vault import WindowsVault,Secret,VaultError
from autojob.auth.passwords import generate
from autojob.auth.detection import safe_url

STATES=('NO REGISTRADA','REGISTRO PREPARADO','VERIFICACIÓN PENDIENTE','ACTIVA','SESIÓN EXPIRADA','CREDENCIALES INCORRECTAS','BLOQUEADA','REQUIERE INTERVENCIÓN')
def now():return datetime.now(timezone.utc).isoformat()

def account_origin(url,allow_local=False):
    clean=safe_url(url);p=urlsplit(clean);host=p.hostname
    if allow_local and p.scheme=='http' and host=='127.0.0.1' and p.port:return f'http://127.0.0.1:{p.port}'
    if p.scheme!='https' or p.port not in {None,443}:raise ValueError('Utiliza el sitio oficial HTTPS, sin puerto alternativo.')
    try:ipaddress.ip_address(host)
    except ValueError:pass
    else:raise ValueError('No se admiten direcciones IP como plataformas externas.')
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?',host) or '.' not in host or any(not x or x.startswith('-') or x.endswith('-') for x in host.split('.')) or host.endswith(('.local','.localhost','.internal')):raise ValueError('Dominio inválido; revisa el sitio oficial.')
    return 'https://'+host.lower()

class Accounts:
    def __init__(self,data_path,vault=None):
        self.data_path=data_path;self.db=Database(data_path/'autojob.sqlite3');self._vault=vault
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS work_accounts(id TEXT PRIMARY KEY,platform TEXT NOT NULL,origin TEXT NOT NULL,email TEXT NOT NULL,username TEXT NOT NULL,state TEXT NOT NULL,verification TEXT NOT NULL,method TEXT NOT NULL,notes TEXT NOT NULL,incorporated_at TEXT NOT NULL,created_at TEXT,last_auth_at TEXT,credential_ref TEXT UNIQUE,domain_verified INTEGER NOT NULL,email_confirmed INTEGER NOT NULL,UNIQUE(origin,email))')
            db.execute('CREATE TABLE IF NOT EXISTS account_events(id INTEGER PRIMARY KEY,account_id TEXT,at TEXT NOT NULL,event TEXT NOT NULL,state TEXT NOT NULL,url TEXT,code TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS account_auth_tasks(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,origin TEXT NOT NULL,account_id TEXT,kind TEXT NOT NULL,state TEXT NOT NULL,url TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(job_id,origin))')
            db.execute('CREATE TABLE IF NOT EXISTS account_preparations(account_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,payload TEXT NOT NULL)')
            if 'exists_remotely' not in {r['name'] for r in db.execute('PRAGMA table_info(work_accounts)')}:
                db.execute('ALTER TABLE work_accounts ADD COLUMN exists_remotely INTEGER NOT NULL DEFAULT 0')
                db.execute("UPDATE work_accounts SET exists_remotely=1 WHERE state IN ('ACTIVA','SESIÓN EXPIRADA','CREDENCIALES INCORRECTAS','VERIFICACIÓN PENDIENTE','BLOQUEADA')")
            if 'observation' not in {r['name'] for r in db.execute('PRAGMA table_info(account_auth_tasks)')}:
                db.execute("ALTER TABLE account_auth_tasks ADD COLUMN observation TEXT NOT NULL DEFAULT '{}'")
    @property
    def vault(self):
        if self._vault is None:self._vault=WindowsVault()
        return self._vault
    def list(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM work_accounts ORDER BY platform,origin,email')]
    def get(self,id):
        return next((r for r in self.list() if r['id']==id),None)
    def add(self,platform,url,email='',username='',state='NO REGISTRADA',method='Correo y contraseña',notes='',domain_verified=False,email_confirmed=False,id=None,allow_local=False,exists_remotely=None):
        site=account_origin(url,allow_local)
        if state not in STATES:raise ValueError('Estado de cuenta inválido.')
        if not platform.strip() or len(platform)>160 or len(notes)>2000 or len(username)>200:raise ValueError('Metadatos de cuenta inválidos.')
        if email and (len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email)):raise ValueError('Correo inválido.')
        if method not in {'Correo y contraseña','SSO externo','Sin contraseña','Desconocido'}:raise ValueError('Método de acceso inválido.')
        # Rechazar secretos conocidos pegados accidentalmente en metadatos libres.
        for existing in self.list():
            if not existing['credential_ref']:continue
            protected=self.vault.get(existing['credential_ref'])
            try:
                if protected and any(protected.reveal() in value for value in (platform,url,email,username,notes)):
                    raise ValueError('Se detectó una credencial en los metadatos. Retírala antes de guardar.')
            finally:
                if protected:protected.clear()
        old=self.get(id) if id else None
        if id and not old:raise ValueError('Cuenta inexistente.')
        if old and (old['origin']!=site or old['email']!=email):raise ValueError('El dominio y correo identifican la cuenta; crea otra entrada para cambiarlos.')
        existing=bool(exists_remotely if exists_remotely is not None else old['exists_remotely'] if old else state in {'ACTIVA','SESIÓN EXPIRADA','CREDENCIALES INCORRECTAS','VERIFICACIÓN PENDIENTE','BLOQUEADA'})
        id=id or uuid4().hex
        try:
            with closing(self.db.connect()) as db,db:
                if old:db.execute('UPDATE work_accounts SET platform=?,username=?,state=?,method=?,notes=?,domain_verified=?,email_confirmed=?,exists_remotely=? WHERE id=?',(platform.strip(),username,state,method,notes,int(domain_verified),int(email_confirmed),int(existing),id))
                else:db.execute('INSERT INTO work_accounts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(id,platform.strip(),site,email,username,state,'DESCONOCIDA',method,notes,now(),None,None,None,int(domain_verified),int(email_confirmed),int(existing)))
        except Exception:raise ValueError('No se pudo guardar; comprueba si la cuenta ya está registrada.') from None
        self.event(id,'METADATOS GUARDADOS',state,site);return id
    def event(self,id,event,state,url=None,code=None):
        # Eventos definidos por el programa; nunca mensajes remotos, contraseñas o tokens.
        if state not in STATES or event not in {'METADATOS GUARDADOS','CREDENCIAL GUARDADA','CREDENCIAL ELIMINADA','REGISTRO ELIMINADO','PREPARACIÓN LOCAL','SESIÓN OBSERVADA','ERROR DE NAVEGACIÓN'} or code and not re.fullmatch(r'[A-Z0-9_ ]{1,80}',code):raise ValueError('Evento inválido.')
        with closing(self.db.connect()) as db,db:db.execute('INSERT INTO account_events(account_id,at,event,state,url,code) VALUES (?,?,?,?,?,?)',(id,now(),event,state,safe_url(url) if url else None,code))
    def save_secret(self,id,secret):
        row=self.get(id)
        if not row:raise ValueError('Selecciona una cuenta.')
        if not isinstance(secret,Secret):raise ValueError('Se requiere un secreto protegido.')
        value=secret.reveal()
        if len(value)<12:raise ValueError('La contraseña debe tener al menos 12 caracteres.')
        if any(value in str(v) for k,v in row.items() if k!='credential_ref'):raise ValueError('El secreto aparece en los metadatos; retíralo antes de guardar.')
        for other in self.list():
            if other['id']==id or not other['credential_ref']:continue
            previous=self.vault.get(other['credential_ref'])
            try:
                if previous and secrets.compare_digest(previous.reveal(),value):raise ValueError('No reutilices una contraseña en otra cuenta.')
            finally:
                if previous:previous.clear()
        reference=row['credential_ref'] or 'AutoJob/account/'+uuid4().hex
        self.vault.put(reference,secret)
        try:
            with closing(self.db.connect()) as db,db:db.execute('UPDATE work_accounts SET credential_ref=? WHERE id=?',(reference,id))
        except Exception:
            if not row['credential_ref']:self.vault.delete(reference)
            raise VaultError('No se pudo vincular la credencial al registro.') from None
        self.event(id,'CREDENCIAL GUARDADA',row['state'],row['origin'])
    def generate(self,id,**policy):
        # Comparar con el almacén evita incluso una colisión del generador; no se guarda un hash en SQLite.
        for _ in range(8):
            candidate=generate(**policy)
            duplicate=False
            for row in self.list():
                if not row['credential_ref']:continue
                existing=self.vault.get(row['credential_ref'])
                try:duplicate=duplicate or bool(existing and secrets.compare_digest(existing.reveal(),candidate.reveal()))
                finally:
                    if existing:existing.clear()
            if not duplicate:return candidate
            candidate.clear()
        raise VaultError('No se pudo producir una contraseña nueva; no se reutilizó ninguna.')
    def credential(self,id,url,authorized=False,allow_local=False):
        row=self.get(id)
        if not row or not authorized or not row['domain_verified'] or account_origin(url,allow_local)!=row['origin']:raise VaultError('Recuperación no autorizada para este origen.')
        return self.vault.get(row['credential_ref']) if row['credential_ref'] else None
    def delete_secret(self,id):
        row=self.get(id)
        if not row:return
        if row['credential_ref']:self.vault.delete(row['credential_ref'])
        with closing(self.db.connect()) as db,db:db.execute('UPDATE work_accounts SET credential_ref=NULL WHERE id=?',(id,))
        self.event(id,'CREDENCIAL ELIMINADA',row['state'],row['origin'])
    def remove(self,id):
        self.delete_secret(id)
        with closing(self.db.connect()) as db,db:
            db.execute('DELETE FROM account_preparations WHERE account_id=?',(id,));db.execute('UPDATE account_auth_tasks SET account_id=NULL WHERE account_id=?',(id,));db.execute('DELETE FROM work_accounts WHERE id=?',(id,))
        self.event(id,'REGISTRO ELIMINADO','NO REGISTRADA')
    def prepare(self,id):
        from autojob.profile.application_data import ApplicationData
        row=self.get(id)
        if not row:raise ValueError('Selecciona una cuenta.')
        data=ApplicationData(self.data_path);fields=[];pending=[]
        for key in ('first_name','last_name'):
            value,status=data.value(key);confirmed=status=='CONFIRMADA'
            fields.append(dict(field=key,value=value if confirmed else None,status=status,source='Datos para postulaciones'))
            if not confirmed:pending.append(key)
        email=row['email'] if row['email_confirmed'] else None
        if not email:
            p=data.profile_state()
            if 'email' in p.get('manual',[]):email=p['values'].get('email')
        fields.append(dict(field='email',value=email,status='CONFIRMADA' if email else 'DESCONOCIDA',source='Cuenta confirmada / perfil confirmado'))
        if not email:pending.append('email')
        if not row['domain_verified']:pending.append('DOMINIO POR VALIDAR')
        if row['method']=='Correo y contraseña' and not row['credential_ref'] and row['domain_verified'] and not row['exists_remotely']:
            secret=self.generate(id)
            try:self.save_secret(id,secret)
            finally:secret.clear()
            row=self.get(id)
        if row['method']=='Correo y contraseña' and not row['credential_ref']:pending.append('IMPORTAR CREDENCIAL EXISTENTE' if row['exists_remotely'] else 'CREDENCIAL SEGURA')
        if row['method']!='Correo y contraseña':pending.append('ACCESO EXTERNO RESERVADO PARA 8B')
        tasks=[t for t in self.tasks() if t['origin']==row['origin']]
        observed=json.loads(tasks[0]['observation']) if tasks else {}
        for field in observed.get('fields',[]):
            if field.get('required') and field['role']=='unknown':pending.append('CAMPO ADICIONAL POR IDENTIFICAR')
            if field.get('required') and field['role']=='username' and not row['username']:pending.append('username')
            if field['role']=='terms':pending.append('CONDICIONES: REVISIÓN HUMANA')
            if field['role']=='otp':pending.append('CÓDIGO: INTERVENCIÓN HUMANA')
        # No se recupera la contraseña para la vista previa.
        payload=dict(account_id=id,origin=row['origin'],intent='LOGIN' if row['exists_remotely'] else 'REGISTRO',observed_form=observed,fields=fields,password='GUARDADA EN WINDOWS' if row['credential_ref'] else 'PENDIENTE',pending=pending,terms_accepted=False,external_registration_enabled=False,external_login_enabled=False)
        state='REQUIERE INTERVENCIÓN' if pending or row['exists_remotely'] else 'REGISTRO PREPARADO'
        with closing(self.db.connect()) as db,db:
            db.execute('INSERT OR REPLACE INTO account_preparations VALUES (?,?,?)',(id,now(),json.dumps(payload,ensure_ascii=False)))
            if row['state'] in {'NO REGISTRADA','REGISTRO PREPARADO','REQUIERE INTERVENCIÓN'}:db.execute('UPDATE work_accounts SET state=? WHERE id=?',(state,id))
        self.event(id,'PREPARACIÓN LOCAL',state,row['origin']);return payload
    def observe(self,id,observation):
        row=self.get(id)
        if not row:return
        site=account_origin(observation['url'],row['origin'].startswith('http://127.0.0.1:'))
        if site!=row['origin']:raise ValueError('La sesión pertenece a otro origen.')
        blocks=observation['blocks'];state='BLOQUEADA' if any(b in blocks for b in ['CAPTCHA','CUENTA BLOQUEADA','IDENTIDAD']) else 'CREDENCIALES INCORRECTAS' if 'CREDENCIALES INCORRECTAS' in blocks else 'VERIFICACIÓN PENDIENTE' if any(b in blocks for b in ['CORREO','MFA','OTP','SMS']) else 'SESIÓN EXPIRADA' if 'SESIÓN EXPIRADA' in blocks or observation['kind']=='LOGIN' and row['state']=='ACTIVA' else 'ACTIVA' if observation['authenticated'] else 'REQUIERE INTERVENCIÓN'
        with closing(self.db.connect()) as db,db:
            db.execute('UPDATE work_accounts SET state=?,verification=?,last_auth_at=CASE WHEN ? THEN ? ELSE last_auth_at END WHERE id=?',(state,', '.join(blocks) or 'SIN VERIFICACIÓN OBSERVADA',int(state=='ACTIVA'),now(),id))
            if state=='ACTIVA':db.execute('UPDATE work_accounts SET exists_remotely=1 WHERE id=?',(id,))
        self.event(id,'SESIÓN OBSERVADA',state,observation['url']);return state
    def history(self,id=None):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM account_events'+(' WHERE account_id=?' if id else '')+' ORDER BY id DESC',(id,) if id else ())]
    def tasks(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM account_auth_tasks ORDER BY updated_at DESC')]
    def require_auth(self,job_id,observation):
        url=safe_url(observation['url']);p=urlsplit(url);site=p.scheme+'://'+p.netloc.lower()
        candidates=[a for a in self.list() if a['origin']==site];account=candidates[0] if len(candidates)==1 else None
        kind='VERIFICACIÓN' if any(b in {'CORREO','MFA','OTP','SMS','IDENTIDAD','CAPTCHA'} for b in observation['blocks']) else 'REVISAR BLOQUEO' if 'CUENTA BLOQUEADA' in observation['blocks'] else 'REVISAR CREDENCIALES' if 'CREDENCIALES INCORRECTAS' in observation['blocks'] else 'INICIO DE SESIÓN' if account else 'PREPARAR REGISTRO'
        if account:self.observe(account['id'],observation)
        with closing(self.db.connect()) as db,db:
            db.execute('INSERT INTO account_auth_tasks(id,job_id,origin,account_id,kind,state,url,created_at,updated_at,observation) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,origin) DO UPDATE SET account_id=excluded.account_id,kind=excluded.kind,state=excluded.state,url=excluded.url,updated_at=excluded.updated_at,observation=excluded.observation',(uuid4().hex,job_id,site,account['id'] if account else None,kind,'PENDIENTE',url,now(),now(),json.dumps({k:observation.get(k,[]) for k in ('kind','fields','blocks')},ensure_ascii=False)))
        return dict(origin=site,account_id=account['id'] if account else None,task=kind,blocks=observation['blocks'],external_action_enabled=False)
    def export(self,path):
        allowed=('platform','origin','email','username','state','verification','method','incorporated_at','created_at','last_auth_at')
        payload=dict(accounts=[{k:r[k] for k in allowed} for r in self.list()],events=[{k:r[k] for k in ('at','event','state','code')} for r in self.history()])
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');return payload

def check_session(settings,store,id,path=None):
    from autojob.browser import BraveSession
    from autojob.forms.guard import PreparationGuard
    from autojob.auth.detection import inspect_auth
    row=store.get(id)
    if not row or not row['domain_verified']:raise ValueError('Verifica manualmente el dominio oficial antes de consultarlo.')
    url=path or row['origin']
    if account_origin(url)!=row['origin']:raise ValueError('La consulta debe permanecer en el origen de la cuenta.')
    try:
        with BraveSession(settings) as browser:
            guard=PreparationGuard(browser)
            # Antes de abrir, rechazar redirecciones a otros orígenes, incluso en SSO.
            original=guard.route
            def scoped(route):
                if route.request.is_navigation_request():
                    try:matches=account_origin(route.request.url)==row['origin']
                    except ValueError:matches=False
                    if not matches:route.abort();return
                original(route)
            browser.context.unroute('**/*');browser.context.route('**/*',scoped)
            page=guard.page(url);guard.freeze();observation=inspect_auth(page);store.observe(id,observation);return observation
    except Exception:
        with closing(store.db.connect()) as db,db:db.execute('UPDATE work_accounts SET state=? WHERE id=?',('REQUIERE INTERVENCIÓN',id))
        store.event(id,'ERROR DE NAVEGACIÓN','REQUIERE INTERVENCIÓN',row['origin'],code='NAVIGATION_ERROR')
        raise ValueError('No se pudo comprobar la sesión; no se intentó iniciar sesión ni repetir credenciales.') from None
