import json,secrets
from pathlib import Path
from contextlib import closing
import pytest,os
from autojob.auth.identity import IdentityStore,TYPES,validate,question_kind,DPAPI
from autojob.auth.permissions import Permissions,scope
from autojob.auth.external import ExternalAuth,AuthGuard
from autojob.auth.verifications import VerificationStore,captcha_state,CaptchaCoordinator
from autojob.auth.service import Accounts
from autojob.config import Settings

@pytest.fixture
def identity(tmp_path):return IdentityStore(tmp_path/'data',tmp_path/'private')

@pytest.mark.parametrize('raw',['199999999','1-9999-9999','1 9999 9999'])
def test_cedula_format_and_explicit_normalization(identity,raw):
    assert validate(TYPES[0],raw)=='199999999'
    identity.save(TYPES[0],raw,'Costa Rica',confirmed=True)
    secret=identity.reveal(True)
    try:assert secrets.compare_digest(secret.reveal(),raw)
    finally:secret.clear()
    assert 'number' not in identity.summary() and raw not in json.dumps(identity.summary())

@pytest.mark.parametrize('raw',['099999999','123','1-9999-999X','9999999999',''])
def test_invalid_cedula(identity,raw):
    with pytest.raises(ValueError):identity.save(TYPES[0],raw)

@pytest.mark.parametrize('kind,raw',[('DIMEX','199999999999'),('DIMEX','19999999999'),('Pasaporte','TEST9999'),('Otro','TEST-9999')])
def test_identity_types(identity,kind,raw):
    identity.save(kind,raw,confirmed=True);assert identity.summary()['kind']==kind

def test_dpapi_user_roundtrip_and_integrity():
    api=DPAPI();plain=secrets.token_bytes(64);protected=api.protect(plain)
    assert protected!=plain and api.unprotect(protected)==plain
    with pytest.raises(ValueError):api.unprotect(protected[:-10]+b'bad')

def test_identity_cipher_persistence_no_plaintext(identity):
    identity.save(TYPES[0],'1-9999-9999','Costa Rica',confirmed=True)
    with closing(identity.db.connect()) as db:dump='\n'.join(db.iterdump())
    assert '1-9999-9999' not in dump and '199999999' not in dump
    again=IdentityStore(identity.data_path,identity.private_root);assert again.summary()['confirmed']
    with pytest.raises(ValueError):again.reveal()
    again.delete();assert again.summary() is None

def test_identity_file_protected_and_deleted(identity,tmp_path):
    identity.save(TYPES[0],'1-9999-9999')
    original=tmp_path/'fictional.pdf';body=b'%PDF-1.4\nFICTITIOUS DOCUMENT, no personal identification data';original.write_bytes(body);identity.attach(original)
    stored=list(identity.private_root.glob('*.dpapi'));assert len(stored)==1 and stored[0].read_bytes()!=body
    assert identity.crypto.unprotect(stored[0].read_bytes())==body and original.read_bytes()==body
    identity.delete();assert not list(identity.private_root.glob('*.dpapi')) and original.exists()

def test_identity_wrong_type_unconfirmed_and_no_general_answers(identity):
    identity.save(TYPES[0],'1-9999-9999',confirmed=False)
    assert identity.resolve('National ID')['answer'] is None and identity.resolve('National ID')['status']=='DESCONOCIDA'
    identity.confirm();assert identity.resolve('Passport number')['status']=='DESCONOCIDA'
    assert identity.resolve('National ID')['status']=='REQUIERE AUTORIZACIÓN'
    assert identity.resolve('Describe your professional skills') is None

@pytest.mark.parametrize('question',['National ID','Government ID','Identification number','Número de cédula','Número de identificación','Passport number','Issuing country','Tipo de documento'])
def test_identity_questions(question):assert question_kind(question)

def test_permissions_are_separate_exact_revocable(tmp_path):
    p=Permissions(tmp_path);url='https://careers.example.invalid'
    p.set(url,'REGISTRO','account-version',True)
    assert p.allowed(url,'REGISTRO','account-version')
    assert not p.allowed(url,'LOGIN','account-version') and not p.allowed('https://other.example.invalid','REGISTRO','account-version')
    assert not p.allowed(url,'REGISTRO','changed-version')
    p.revoke(url);assert not Permissions(tmp_path).allowed(url,'REGISTRO','account-version')

def test_identity_permission_specific_revision_and_field(identity):
    identity.save(TYPES[0],'1-9999-9999',confirmed=True);r=identity.summary();p=Permissions(identity.data_path)
    p.set('https://example.invalid','IDENTIDAD',r['revision']+':number',True)
    assert not p.allowed('https://example.invalid','IDENTIDAD',r['revision']+':country')
    identity.confirm();assert not p.allowed('https://example.invalid','IDENTIDAD',identity.summary()['revision']+':number')

def test_unauthorized_auth_never_opens_browser(tmp_path,monkeypatch):
    engine=ExternalAuth(tmp_path);id=engine.accounts.add('Fictitious','https://example.invalid','candidate@example.invalid',state='ACTIVA',domain_verified=True,email_confirmed=True)
    import autojob.auth.external as external
    monkeypatch.setattr(external,'BraveSession',lambda *args:pytest.fail('No browser before permission'))
    with pytest.raises(ValueError):engine.run(Settings(tmp_path),id,'LOGIN')

def test_registration_permission_not_login(tmp_path,monkeypatch):
    engine=ExternalAuth(tmp_path);id=engine.accounts.add('Fictitious','https://example.invalid','candidate@example.invalid',state='ACTIVA',domain_verified=True,email_confirmed=True)
    row=engine.accounts.get(id);engine.permissions.set(row['origin'],'REGISTRO',scope(engine.accounts,row,'REGISTRO'),True)
    with pytest.raises(ValueError):engine.run(Settings(tmp_path),id,'LOGIN')

@pytest.mark.parametrize('authorized,site,budget,expected',[(True,'https://example.invalid',1,True),(False,'https://example.invalid',1,False),(True,'https://attacker.invalid',1,False),(True,'https://example.invalid',0,False)])
def test_auth_post_gate(authorized,site,budget,expected):
    guard=object.__new__(AuthGuard);guard.site='https://example.invalid';guard.authorized=lambda:authorized;guard.endpoint=guard.site+'/login';guard.budget=budget;guard.blocked=0
    class Request:method='POST';url=site+'/login'
    class Route:
        request=Request();allowed=False
        def continue_(self):self.allowed=True
        def abort(self):self.allowed=False
    route=Route();guard.route(route);assert route.allowed==expected
    if expected:assert guard.budget==0

def test_verification_persistence_commands_and_recovery(tmp_path):
    s=VerificationStore(tmp_path);id=s.add('job','CAPTCHA PENDIENTE','https://example.invalid/login?token=redact','Fictitious role',True)
    assert 'redact' not in json.dumps(s.list());s.update(id,command='OMITIR');assert VerificationStore(tmp_path).list()[0]['command']=='OMITIR'
    assert s.recover()==1 and s.list()[0]['reserved']==0
    s.update(id,'LISTA PARA CONTINUAR');assert s.list()[0]['state']=='LISTA PARA CONTINUAR'

def test_identity_ui_mask_normalization_delete(tmp_path,qt_application_lifetime,monkeypatch):
    from autojob.ui.identity_widget import IdentityWidget
    from PySide6.QtWidgets import QLineEdit,QMessageBox
    w=IdentityWidget(Settings(tmp_path));w.number.setText('1-9999-9999');w.save();assert w.number.text()=='' and w.mask.text()=='••••9999'
    w.reveal();assert w.number.echoMode()==QLineEdit.EchoMode.Normal
    w.preview();assert w.accept_normal.isEnabled();w.accept_normal.setChecked(True);w.save()
    secret=w.store.reveal(True)
    try:assert secrets.compare_digest(secret.reveal(),'199999999')
    finally:secret.clear()
    w.confirm();assert w.store.summary()['confirmed'];w.hide_number();assert w.number.text()==''
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes);w.remove();assert w.store.summary() is None;w.close();w.deleteLater()

def test_native_notification_and_buttons(tmp_path,qt_application_lifetime,monkeypatch):
    from autojob.ui.notifications_widget import NotificationsWidget
    from autojob.ui.queue_widget import QueueWidget
    from PySide6.QtWidgets import QSystemTrayIcon
    delivered=[];monkeypatch.setattr(QSystemTrayIcon,'showMessage',lambda self,*args:delivered.append(args))
    q=QueueWidget(Settings(tmp_path));w=NotificationsWidget(Settings(tmp_path),q);id=w.store.add('job','CAPTCHA PENDIENTE','https://example.invalid','Fictional company · Support',True)
    w.notice(id,'Job Hunting necesita intervención','Fictitious CAPTCHA');assert delivered and 'Job Hunting' in delivered[0][0]
    w.table.selectRow(0);w.resolve();assert w.store.list()[0]['command']=='RESOLVER'
    w.skip();assert w.store.list()[0]['command']=='OMITIR';w.allow_close();w.close();q.close();w.deleteLater();q.deleteLater()

def test_auth_ui_grants_only_explicit_action(tmp_path,qt_application_lifetime,monkeypatch):
    from autojob.ui.accounts_widget import AccountsWidget
    from PySide6.QtWidgets import QInputDialog,QMessageBox
    w=AccountsWidget(Settings(tmp_path));id=w.store.add('Fictitious','https://example.invalid','candidate@example.invalid',state='ACTIVA',domain_verified=True,email_confirmed=True);w.selected_id=id
    monkeypatch.setattr(QInputDialog,'getItem',lambda *args:('LOGIN',True));monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.No)
    w.authorize_domain();assert not Permissions(w.settings.data_path).list()
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes);w.authorize_domain();assert Permissions(w.settings.data_path).list()[0]['action']=='LOGIN'
    w.revoke_domain();assert not Permissions(w.settings.data_path).list()[0]['allowed'];w.close();w.deleteLater()

brave=pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave controlled opt-in')

@brave
def test_generic_authorized_auth_captcha_resume_and_protected_identity(tmp_path):
    from autojob.auth.lab8b import run_lab
    result=run_lab(Settings(tmp_path))
    assert result['authorized_registration'] and result['authorized_login'] and result['duplicate_prevented']
    assert result['captcha_resumed'] and result['session_reused'] and result['expiry_detected']
    assert result['identity_encrypted'] and result['identity_deleted'] and result['revocation_verified']
    assert result['identities_transmitted']==0 and result['applications_sent']==0 and result['external_accounts_created']==0

@brave
def test_cap_detection_explicit_completion_and_skip(tmp_path):
    from autojob.auth.local import local_portal
    from autojob.browser import BraveSession
    from autojob.forms.guard import PreparationGuard
    with local_portal() as fixture,BraveSession(Settings(tmp_path)) as browser:
        fixture['human_captcha']=True;guard=PreparationGuard(browser);page=guard.page(fixture['origin']+'/login');assert captcha_state(page,fixture)['detected']
        assert not captcha_state(page,fixture)['completed']
        def skip(page,id,store):store.update(id,command='OMITIR')
        fixture['on_wait']=skip
        assert not CaptchaCoordinator(tmp_path/'data').wait(page,guard,'job','Fictitious',seconds=2,fixture=fixture)
        page.locator('#human-check').click();assert captcha_state(page,fixture)['completed']

@brave
def test_identity_dispatch_requires_explicit_domain_and_data(tmp_path):
    from autojob.auth.local import local_portal
    from autojob.browser import BraveSession
    from autojob.forms.guard import PreparationGuard
    from autojob.forms.runner import fill_field
    identity=IdentityStore(tmp_path/'data',tmp_path/'private');identity.save(TYPES[0],'1-9999-9999',confirmed=True)
    with local_portal() as fixture,BraveSession(Settings(tmp_path)) as browser:
        guard=PreparationGuard(browser,fixture['origin']);guard.identity_data_path=tmp_path/'data';page=guard.page(fixture['origin']+'/signup')
        entry=dict(selector='#first',kind='text',label='National ID',**identity.resolve('National ID'))
        assert fill_field(page,entry,guard,fixture)['status']=='PENDIENTE' and not page.locator('#first').input_value()
        Permissions(tmp_path/'data').set(fixture['origin'],'IDENTIDAD',identity.summary()['revision']+':number',True,True)
        outcome=fill_field(page,entry,guard,fixture);assert outcome['status']=='VERIFICADO'
        assert '1-9999-9999' not in json.dumps(outcome) and entry['answer'] is None

@pytest.mark.parametrize('fields,text,kind',[
 ([dict(type='password',label='Password'),dict(type='submit',label='Log in')],'Welcome back Log in Create an account','LOGIN'),
 ([dict(type='password',label='New password',autocomplete='new-password'),dict(type='password',label='Confirm password'),dict(type='submit',label='Reset password')],'Reset password','RECUPERACIÓN')])
def test_active_auth_form_beats_footer_links(fields,text,kind):
    from autojob.auth.detection import classify
    assert classify(dict(fields=fields,text=text),'https://example.invalid')['kind']==kind

def test_login_retry_limit_before_browser(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from uuid import uuid4
    engine=ExternalAuth(tmp_path);id=engine.accounts.add('Fictitious','https://example.invalid','candidate@example.invalid',state='ACTIVA',domain_verified=True,email_confirmed=True);row=engine.accounts.get(id)
    engine.permissions.set(row['origin'],'LOGIN',scope(engine.accounts,row,'LOGIN'),True)
    with closing(engine.db.connect()) as db,db:
        for n in range(3):db.execute('INSERT INTO authentication_attempts VALUES (?,?,?,?,?,1)',(uuid4().hex,id,'LOGIN',datetime.now(timezone.utc).isoformat(),'FAILED'))
    import autojob.auth.external as external
    monkeypatch.setattr(external,'BraveSession',lambda *args:pytest.fail('No browser after retry limit'))
    assert 'Límite' in engine.run(Settings(tmp_path),id,'LOGIN')['reason']

def test_manual_demo_button_and_resource_cleanup(tmp_path,qt_application_lifetime,monkeypatch,await_ui):
    from autojob.ui.accounts_widget import AccountsWidget
    from autojob.ui.auth_demo import ManualDemo
    from PySide6.QtTest import QTest
    calls=[];monkeypatch.setattr(ManualDemo,'start',lambda self:calls.append('started'))
    w=AccountsWidget(Settings(tmp_path));w.manual_demo();await_ui(lambda:calls==['started']);assert calls==['started'] and w.demo.isVisible()
    demo=w.demo;root=demo.root;assert demo.close();QTest.qWait(100);assert not root.exists();w.close();w.deleteLater()

def test_general_excel_export_excludes_identity(identity,tmp_path):
    from autojob.matching.service import export
    from openpyxl import load_workbook
    identity.save(TYPES[0],'1-9999-9999',confirmed=True)
    path=tmp_path/'jobs.xlsx';export([dict(job=dict(company='Fictitious',title='Support'),evaluation=None,stale=False)],path)
    book=load_workbook(path);text=' '.join(str(cell.value) for sheet in book for row in sheet for cell in row)
    assert '1-9999-9999' not in text and '199999999' not in text

@brave
def test_wrong_password_single_post_and_legal_registration_block(tmp_path):
    from hashlib import pbkdf2_hmac
    from autojob.auth.local import local_portal
    from autojob.profile.application_data import ApplicationData
    from autojob.auth.passwords import generate
    with local_portal() as fixture:
        settings=Settings(tmp_path);engine=ExternalAuth(settings.data_path);data=ApplicationData(settings.data_path);data.save({'first_name':'Test','last_name':'Candidate'},confirmed=['first_name','last_name'])
        existing=engine.accounts.add('Existing fixture',fixture['origin'],'existing@example.invalid',state='ACTIVA',domain_verified=True,email_confirmed=True,allow_local=True)
        correct=generate();wrong=generate();salt=secrets.token_bytes(16);fixture['accounts']['existing@example.invalid']=dict(salt=salt,digest=pbkdf2_hmac('sha256',correct.reveal().encode(),salt,60000),verified=True,locked=False)
        try:
            engine.accounts.save_secret(existing,wrong);row=engine.accounts.get(existing);engine.permissions.set(fixture['origin'],'LOGIN',scope(engine.accounts,row,'LOGIN'),True,True)
            result=engine.run(settings,existing,'LOGIN',fixture['origin']+'/login',local=True,fixture=fixture)
            assert result['state']=='CREDENCIALES INCORRECTAS'
            assert sum(r['method']=='POST' and r['path']=='/login' for r in fixture['requests'])==1
            new=engine.accounts.add('New fixture',fixture['origin'],'new@example.invalid',domain_verified=True,email_confirmed=True,allow_local=True)
            engine.accounts.prepare(new);row=engine.accounts.get(new);engine.permissions.set(fixture['origin'],'REGISTRO',scope(engine.accounts,row,'REGISTRO'),True,True);fixture['terms_required']=True
            result=engine.run(settings,new,'REGISTRO',fixture['origin']+'/signup',local=True,fixture=fixture)
            assert result['state']=='REQUIERE INTERVENCIÓN' and not any(r['path']=='/register' and r['method']=='POST' for r in fixture['requests'])
        finally:
            correct.clear();wrong.clear()
            for row in engine.accounts.list():engine.accounts.remove(row['id'])


def test_completed_captcha_marker_does_not_hide_other_verifications(monkeypatch):
 import autojob.auth.external as external
 monkeypatch.setattr(external,'inspect_auth',lambda page:dict(blocks=['CAPTCHA','MFA'],kind='VERIFICACIÓN'))
 monkeypatch.setattr(external,'captcha_state',lambda *args:dict(completed=True))
 assert external.authentication_observation(None)['blocks']==['MFA']
 monkeypatch.setattr(external,'captcha_state',lambda *args:dict(completed=False))
 assert 'CAPTCHA' in external.authentication_observation(None)['blocks']

def test_queue_captcha_resumes_in_same_browser(tmp_path,monkeypatch):
 from autojob.forms.queue import PreparationQueue
 import autojob.forms.runner as runner
 import autojob.auth.verifications as verification
 import autojob.auth.detection as detection
 q=PreparationQueue(tmp_path/'data');q.preparation.compatibility.jobs.add(dict(source='FIXTURE',source_id='human',url='https://example.invalid/form',title='Fictitious Support',company='Fictitious',description='Controlled test'))
 q.add([j['id'] for j in q.preparation.compatibility.jobs.list()]);opened=[]
 class Page:
  url='https://example.invalid/form'
  def wait_for_function(self,*args,**kwargs):pass
 class Browser:
  def __init__(self,*args):pass
  def __enter__(self):opened.append(1);return self
  def __exit__(self,*args):pass
 class Guard:
  context=object()
  def __init__(self,*args):pass
  def page(self,*args):return Page()
 monkeypatch.setattr(runner,'BraveSession',Browser);monkeypatch.setattr(runner,'PreparationGuard',Guard)
 monkeypatch.setattr(runner,'inspect',lambda *args,**kwargs:dict(url=Page.url,fields=[],obstacles=[dict(type='CAPTCHA',evidence='fixture')]))
 monkeypatch.setattr(q.preparation,'prepare',lambda *args:dict(entries=[],blocks=[]))
 monkeypatch.setattr(detection,'inspect_auth',lambda page:dict(kind='DESCONOCIDO',blocks=[]))
 monkeypatch.setattr(verification,'captcha_state',lambda *args:dict(completed=False))
 monkeypatch.setattr(verification.CaptchaCoordinator,'wait',lambda *args,**kwargs:True)
 result=q.run(Settings(tmp_path));assert opened==[1] and result['states']==['REQUIERE REVISIÓN']
 assert q.list()[0]['payload']['verification_status']=='LISTA PARA CONTINUAR'

def test_identity_change_cannot_use_previous_data_authorization(identity):
 identity.save(TYPES[0],'1-9999-9999',confirmed=True);revision=identity.summary()['revision']
 identity.confirm()
 with pytest.raises(ValueError):identity.reveal(True,revision)
