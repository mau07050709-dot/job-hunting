from pathlib import Path
from contextlib import closing
from uuid import uuid4
import os,secrets,json
import pytest
from autojob.auth.vault import Secret,WindowsVault,VaultError
from autojob.auth.passwords import generate
from autojob.auth.service import Accounts,account_origin
from autojob.auth.detection import classify,safe_url
from autojob.config import Settings

class MemoryVault:
    def __init__(self):self.values={};self.fail=False
    def put(self,ref,secret):
        if self.fail:raise VaultError('Controlled failure')
        self.values[ref]=Secret(secret.reveal())
    def get(self,ref):return Secret(self.values[ref].reveal()) if ref in self.values else None
    def delete(self,ref):
        if self.fail:raise VaultError('Controlled failure')
        self.values.pop(ref,None)

@pytest.fixture
def store(tmp_path):return Accounts(tmp_path,MemoryVault())

def add(store,**kw):return store.add('Fictitious Employer','https://careers.example.invalid','candidate@example.invalid',domain_verified=True,email_confirmed=True,**kw)
def contains(secret,text):return secret.reveal() in text

@pytest.mark.parametrize('symbols',[True,False])
def test_password_policy_and_unique(symbols):
    values=[]
    for _ in range(40):
        secret=generate(symbols=symbols);value=secret.reveal();values.append(value)
        assert len(value)==24 and any(c.isupper() for c in value) and any(c.islower() for c in value) and any(c.isdigit() for c in value)
        assert any(not c.isalnum() for c in value)==symbols
        assert repr(secret)=='<Secret protegido>';secret.clear()
    assert len(set(values))==40

@pytest.mark.parametrize('policy',[dict(length=8),dict(length=129),dict(length=True),dict(minimum=30,maximum=20),dict(allowed_symbols='abc'),dict(allowed_symbols='',symbols=True)])
def test_invalid_password_policies(policy):
    with pytest.raises(ValueError):generate(**policy)

def test_documented_symbols_policy():
    secret=generate(length=32,minimum=20,maximum=40,allowed_symbols='-_')
    assert len(secret.reveal())==32 and all(c.isalnum() or c in '-_' for c in secret.reveal());secret.clear()

@pytest.mark.parametrize('url',['http://jobs.example.com','https://user:password@jobs.example.com','file:///C:/x','https://127.0.0.1','https://fake.local','https://-bad.example','https://example.com:444'])
def test_invalid_domains(url):
    with pytest.raises(ValueError):account_origin(url)

def test_exact_origin_and_query_redaction():
    assert account_origin('https://CAREERS.example.com:443/login?token=private')=='https://careers.example.com'
    assert safe_url('https://example.com/login?token=private#secret')=='https://example.com/login'

def test_account_persistence_and_duplicate(store):
    id=add(store);assert Accounts(store.data_path,store.vault).get(id)['state']=='NO REGISTRADA'
    with pytest.raises(ValueError):add(store)
    with pytest.raises(ValueError):store.add('x','https://other.example.invalid','candidate@example.invalid',id=id)

def test_vault_only_reference_and_authorized_origin(store,tmp_path):
    id=add(store);secret=generate();store.save_secret(id,secret)
    with closing(store.db.connect()) as db:dump='\n'.join(db.iterdump())
    assert not contains(secret,dump)
    for kwargs in [dict(authorized=False),dict(authorized=True,url='https://other.example.invalid')]:
        with pytest.raises(VaultError):store.credential(id,kwargs.pop('url','https://careers.example.invalid'),**kwargs)
    retrieved=store.credential(id,'https://careers.example.invalid',authorized=True)
    assert secrets.compare_digest(retrieved.reveal(),secret.reveal());retrieved.clear()
    exported=store.export(tmp_path/'export.json');assert not contains(secret,json.dumps(exported))
    assert 'credential_ref' not in json.dumps(exported) and 'notes' not in json.dumps(exported)
    ref=store.get(id)['credential_ref'];store.delete_secret(id);assert store.vault.get(ref) is None;secret.clear()

def test_password_reuse_and_metadata_leak_rejected(store):
    one=add(store);two=store.add('Second','https://other.example.invalid');secret=generate();store.save_secret(one,secret)
    with pytest.raises(ValueError):store.save_secret(two,secret)
    with pytest.raises(ValueError):store.add('Fictitious Employer','https://careers.example.invalid','candidate@example.invalid',notes=secret.reveal(),id=one)
    with pytest.raises(ValueError):store.event(one,secret.reveal(),'ACTIVA')
    secret.clear()

def test_vault_failure_does_not_create_plaintext_fallback(store):
    id=add(store);store.vault.fail=True;secret=generate()
    with pytest.raises(VaultError):store.save_secret(id,secret)
    assert store.get(id)['credential_ref'] is None;secret.clear()

def test_failed_secret_delete_preserves_account(store):
    id=add(store);secret=generate();store.save_secret(id,secret);secret.clear();store.vault.fail=True
    with pytest.raises(VaultError):store.remove(id)
    assert store.get(id)['credential_ref']
    store.vault.fail=False;store.remove(id);assert store.get(id) is None

def test_unknown_prepare_and_confirmed_prepare(store):
    from autojob.profile.application_data import ApplicationData
    id=add(store);preview=store.prepare(id)
    assert {'first_name','last_name'}<=set(preview['pending'])
    assert not preview['external_registration_enabled'] and not preview['terms_accepted']
    data=ApplicationData(store.data_path);data.save(dict(first_name='Test',last_name='Candidate'),confirmed=['first_name','last_name'])
    preview=store.prepare(id);assert not preview['pending'] and store.get(id)['state']=='REGISTRO PREPARADO'
    assert store.get(id)['created_at'] is None and store.get(id)['last_auth_at'] is None

def test_unverified_domain_does_not_generate(store):
    id=store.add('Unknown','https://unknown.example.invalid');preview=store.prepare(id)
    assert 'DOMINIO POR VALIDAR' in preview['pending'] and store.get(id)['credential_ref'] is None

@pytest.mark.parametrize('text,fields,kind,block',[
 ('Create account',[dict(type='password',label='Password'),dict(type='password',label='Confirm password')],'REGISTRO',None),
 ('Sign in',[dict(type='password',label='Password')],'LOGIN',None),
 ('Continue with email',[dict(type='email',label='Email',autocomplete='username')],'LOGIN',None),
 ('Password recovery — reset password',[dict(type='email',label='Email')],'RECUPERACIÓN',None),
 ('Confirm your account — verify your email',[],'VERIFICACIÓN','CORREO'),
 ('Two-factor authentication OTP verification code',[],'VERIFICACIÓN','MFA'),
 ('Code sent by SMS',[],'VERIFICACIÓN','SMS'),
 ('Identity verification',[],'VERIFICACIÓN','IDENTIDAD'),
 ('Account locked',[],'DESCONOCIDO','CUENTA BLOQUEADA'),
 ('Incorrect password',[],'DESCONOCIDO','CREDENCIALES INCORRECTAS'),
 ('CAPTCHA',[],'DESCONOCIDO','CAPTCHA'),
 ('My account dashboard log out',[],'AUTENTICADA',None),
 ('Apply for job',[dict(type='email',label='Email')],'DESCONOCIDO',None)])
def test_form_classification(text,fields,kind,block):
    obs=classify(dict(text=text,fields=fields),'https://example.invalid/login?token=do-not-store')
    assert obs['kind']==kind
    if block:assert block in obs['blocks']
    assert 'do-not-store' not in json.dumps(obs)

def test_no_values_or_html_captured():
    token=secrets.token_urlsafe(24);observation=classify(dict(text='Sign in',fields=[dict(type='password',label='Password',value=token)]),'https://example.invalid')
    assert token not in json.dumps(observation)

def test_session_states_and_domain_isolation(store):
    id=add(store)
    observed=lambda text,fields=[]:classify(dict(text=text,fields=fields),'https://careers.example.invalid')
    assert store.observe(id,observed('My account dashboard log out'))=='ACTIVA'
    assert store.get(id)['last_auth_at']
    assert store.observe(id,observed('Session expired Sign in',[dict(type='password',label='Password')]))=='SESIÓN EXPIRADA'
    with pytest.raises(ValueError):store.observe(id,classify(dict(text='My account dashboard log out',fields=[]),'https://other.example.invalid'))

def test_queue_auth_task_deduplicates_and_reuses_account(store):
    login=classify(dict(text='Sign in',fields=[dict(type='password',label='Password')]),'https://careers.example.invalid/login')
    assert store.require_auth('job',login)['task']=='PREPARAR REGISTRO'
    id=add(store);assert store.require_auth('job',login)['account_id']==id
    assert len(store.tasks())==1 and store.tasks()[0]['kind']=='INICIO DE SESIÓN'

@pytest.mark.skipif(os.name!='nt',reason='Windows Credential Manager')
@pytest.mark.skipif(__import__('os').environ.get('JOB_HUNTING_TEST_WINDOWS_VAULT')!='1',reason='Opt-in integration writes a fictional credential to the Windows vault')
def test_real_windows_credential_manager():
    vault=WindowsVault();ref='AutoJob/account/'+uuid4().hex;secret=generate()
    try:
        vault.put(ref,secret);restored=WindowsVault().get(ref)
        assert restored is not None and secrets.compare_digest(restored.reveal(),secret.reveal());restored.clear()
    finally:vault.delete(ref);secret.clear()
    assert vault.get(ref) is None
    with pytest.raises(VaultError):vault.get('Microsoft/unrelated')

def test_ui_secret_mask_and_persistence(tmp_path,qt_application_lifetime,monkeypatch):
    from autojob.ui.accounts_widget import AccountsWidget
    from PySide6.QtWidgets import QLineEdit,QMessageBox
    settings=Settings(tmp_path);w=AccountsWidget(settings);w.store=Accounts(settings.data_path,MemoryVault())
    w.platform.setText('Fictional');w.site.setText('https://careers.example.invalid');w.email.setText('candidate@example.invalid');w.domain.setChecked(True);w.email_confirmed.setChecked(True);w.save(True)
    assert w.selected_id and w.table.rowCount()==1
    w.generate();assert w.password.echoMode()==QLineEdit.EchoMode.Password
    secret=Secret(w.password.text());w.save_secret();assert w.password.text()==''
    assert w.store.get(w.selected_id)['credential_ref']
    assert not contains(secret,w.output.toPlainText())
    assert all(not contains(secret,w.table.item(r,c).text()) for r in range(w.table.rowCount()) for c in range(w.table.columnCount()))
    w.prepare();assert 'first_name' in w.output.toPlainText()
    id=w.selected_id;vault=w.store.vault;w.close();again=AccountsWidget(settings);again.store=Accounts(settings.data_path,vault);again.refresh();assert again.table.rowCount()==1
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
    again.selected_id=id;again.delete_secret();assert again.store.get(id)['credential_ref'] is None
    again.remove();assert not again.store.list();secret.clear();again.close();w.deleteLater();again.deleteLater()

brave=pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local opt-in')

@brave
def test_complete_local_authentication(tmp_path):
    from autojob.auth.local import run_local
    result=run_local(Settings(tmp_path));assert result['windows_vault_verified'] and result['test_credential_deleted']
    assert result['session_recovered_after_browser_restart']
    assert result['protected_form_reached'] and result['session_recovered'] and result['logout_verified'] and result['recovery_simulated']
    assert result['application_barrier_verified'] and result['secret_absent_from_exports']
    assert {'CORREO','OTP','MFA','CAPTCHA','IDENTIDAD','SMS','CUENTA BLOQUEADA','SESIÓN EXPIRADA','CREDENCIALES INCORRECTAS'}<=set(result['observations'])
    assert result['external_accounts_created']==0 and result['applications_sent']==0

@brave
def test_authentication_queue_continues(tmp_path):
    from autojob.auth.local import local_portal
    from autojob.forms.queue import PreparationQueue
    with local_portal() as fixture:
        q=PreparationQueue(tmp_path/'data')
        for n,path in enumerate(['/protected','/captcha']):q.preparation.compatibility.jobs.add(dict(source='LOCAL FIXTURE',source_id=str(n),url=fixture['origin']+path,company='Fictional',title='Fictitious role '+str(n),description='Local authentication test',location='Unknown'))
        q.add([j['id'] for j in q.preparation.compatibility.jobs.list()]);result=q.run(Settings(tmp_path))
        assert result['processed']==2 and set(result['states'])=={'PENDIENTE','BLOQUEADA'}
        store=Accounts(tmp_path/'data');assert len(store.tasks())==1 and not store.list()
        assert not any(r['method']=='POST' for r in fixture['requests'])
        assert all(not r['payload'].get('filled') for r in q.list())

def test_navigation_failure_is_sanitized(store,tmp_path,monkeypatch):
    from autojob.auth.service import check_session
    import autojob.browser
    id=add(store)
    class Broken:
        def __init__(self,*args):pass
        def __enter__(self):raise RuntimeError('private-token-must-not-persist')
        def __exit__(self,*args):pass
    monkeypatch.setattr(autojob.browser,'BraveSession',Broken)
    with pytest.raises(ValueError):check_session(Settings(tmp_path),store,id)
    assert 'private-token-must-not-persist' not in json.dumps(store.history())

def test_existing_database_preserved_by_migration(tmp_path):
    from autojob.profile.application_data import ApplicationData
    from autojob.forms.queue import PreparationQueue
    data=ApplicationData(tmp_path);data.save({'own_computer':True},confirmed=['own_computer']);q=PreparationQueue(tmp_path)
    with closing(q.db.connect()) as db:before={r[0]:db.execute('SELECT * FROM "'+r[0]+'"').fetchall() for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    store=Accounts(tmp_path,MemoryVault())
    with closing(store.db.connect()) as db:
        for name,rows in before.items():assert [tuple(r) for r in db.execute('SELECT * FROM "'+name+'"')]==[tuple(r) for r in rows]

def test_existing_account_never_generates_replacement(store):
    id=add(store,state='ACTIVA');assert store.get(id)['exists_remotely']
    preview=store.prepare(id)
    assert preview['intent']=='LOGIN' and 'IMPORTAR CREDENCIAL EXISTENTE' in preview['pending']
    assert store.get(id)['credential_ref'] is None

def test_observed_unknown_and_terms_remain_pending(store):
    id=add(store)
    observed=classify(dict(text='Create account',fields=[dict(type='password',label='Password',autocomplete='new-password'),dict(type='checkbox',label='I agree to terms',required=True),dict(type='text',label='Unknown mandatory field',required=True)]),'https://careers.example.invalid/signup')
    store.require_auth('job',observed);preview=store.prepare(id)
    assert 'CAMPO ADICIONAL POR IDENTIFICAR' in preview['pending'] and 'CONDICIONES: REVISIÓN HUMANA' in preview['pending']
    assert not preview['terms_accepted'] and preview['observed_form']['kind']=='REGISTRO'

def test_generation_collision_is_bounded(store,monkeypatch):
    import autojob.auth.service as service
    id=add(store);secret=generate();store.save_secret(id,secret);calls=[]
    def collision(**kwargs):calls.append(1);return Secret(secret.reveal())
    monkeypatch.setattr(service,'generate',collision)
    with pytest.raises(VaultError):store.generate(id)
    assert len(calls)==8;secret.clear()

@pytest.mark.parametrize('fixture',[dict(origin='https://example.invalid',token='a'*48),dict(origin='http://127.0.0.1:12345',token='wrong')])
def test_local_auth_capability_cannot_be_used_externally(fixture):
    from autojob.auth.local import LocalAuthGuard
    with pytest.raises(ValueError):LocalAuthGuard(None,fixture)

def test_password_absent_from_logs_and_preview(store,caplog):
    import logging
    caplog.set_level(logging.DEBUG);id=add(store);secret=generate();store.save_secret(id,secret);preview=store.prepare(id)
    assert not contains(secret,caplog.text) and not contains(secret,json.dumps(preview)) and not contains(secret,json.dumps(store.history()))
    secret.clear()


@pytest.mark.parametrize('text,fields,expected',[
 ('Continue with email',[dict(type='email',label='Email')],'LOGIN'),
 ('Create account',[dict(type='email',label='Email')],'REGISTRO'),
 ('Join our team — apply now',[dict(type='email',label='Email'),dict(type='file',label='CV')],'DESCONOCIDO')])
def test_email_first_auth_distinguished_from_application(text,fields,expected):
 assert classify(dict(text=text,fields=fields),'https://careers.example.invalid')['kind']==expected
