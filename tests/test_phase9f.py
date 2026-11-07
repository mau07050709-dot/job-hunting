import os,json
from contextlib import closing
import pytest
from test_phase9e import page
from autojob.forms.submissions import SubmissionStore,SubmissionEngine
from autojob.forms.batches import create
from autojob.forms.guard import origin
from test_submissions9b import portal

def criteria(store,job):
    cv=next(r for r in store.prep.compatibility.rows() if r['job']['id']==job['id'])['evaluation']['resume_selection']['resume_id']
    return dict(modalities=['remote'],regions=['Costa Rica'],domains=[origin(job['application_url'])],cv_ids=[cv],types=['Python Developer'],threshold=0,excluded=[],salary_min=None,salary_currency='USD',salary_period='month')

@pytest.mark.parametrize('change',[dict(modalities=['onsite']),dict(regions=['Cartago, Costa Rica']),dict(types=['Nurse']),dict(excluded=['Python']),dict(salary_min=1000)])
def test_batch_rejects_outside_limits(tmp_path,change):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);c=criteria(s,lab['job']);c.update(change);a=create(s,c,3,1,True,True,'local',True)
        with pytest.raises(ValueError):s.permission(a,lab['job'])
        assert not s.rows()

def test_batch_permission_count_duplicate_revocation_and_expiry(tmp_path):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=create(s,criteria(s,j),1,1,True,True,'local',True)
        attempt=s.claim(a,j);assert s.permission(a,j);assert s.duplicate(j)
        with pytest.raises(ValueError):s.claim(a,j)
        s.finish(attempt,'ENVÍO NO VERIFICADO',{'verified':False})
        with pytest.raises(ValueError):s.permission(a,j)
        s.revoke(a)
        with pytest.raises(ValueError):s.permission(a,j)
        with closing(s.db.connect()) as db,db:db.execute("UPDATE submission_authorizations SET expires_at='2000-01-01',revoked=0 WHERE id=?",(a,))
        with pytest.raises(ValueError):s.permission(a,j)

def test_batch_requires_explicit_permissions_and_reviewed_cvs(tmp_path):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);c=criteria(s,lab['job'])
        for upload,explicit in [(False,True),(True,False)]:
            with pytest.raises(ValueError):create(s,c,3,1,upload,explicit,'local',True)
        c['domains']=['https://example.com']
        with pytest.raises(ValueError):create(s,c,3,1,True,True,'local',True)

def test_information_routes_directly_without_advanced_tools(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.main_window import MainWindow
    from autojob.config import Settings
    from autojob.ui.submission_ui import MissingInformation
    w=MainWindow(Settings(tmp_path));monkeypatch.setattr(w.shell,'open_advanced',lambda *a:pytest.fail('No abrir herramientas avanzadas'))
    w.shell.engine.jobs.add(dict(source='FIXTURE',source_id='route',company='Fictional',title='Support',url='https://example.invalid/job',application_url='https://example.invalid/form',description='Local test context'))
    job=w.shell.engine.jobs.list()[0];w.shell.engine.queue.allow_site(job['application_url'],True);opened=[];monkeypatch.setattr(w.shell,'view_sent',lambda r:opened.append(r))
    row=dict(id='fixture',job_id=job['id'],company='Fictional',title='Support',url=job['application_url'],kind='DATO OBLIGATORIO PENDIENTE',verification_id=None)
    w.shell.center.resolve(row);assert opened[0]['job']['id']==job['id'];assert w.shell.center.popup is None
    await_ui(lambda:not w._ui_tasks);w.close()

def test_generic_intervention_routes_to_exact_context(tmp_path,qt_application_lifetime,monkeypatch,await_ui):
    from autojob.ui.main_window import MainWindow
    from autojob.config import Settings
    w=MainWindow(Settings(tmp_path));calls=[];monkeypatch.setattr(w.shell,'view_sent',lambda r:calls.append(r));monkeypatch.setattr(w.shell,'open_advanced',lambda *a:pytest.fail('Ruta antigua'))
    w.shell.engine.jobs.add(dict(source='FIXTURE',source_id='route',company='Fictional',title='Support',url='https://example.invalid/job',application_url='https://example.invalid/form',description='Local test context'))
    job=w.shell.engine.jobs.list()[0];w.shell.engine.queue.allow_site(job['application_url'],True)
    for kind in ['MFA','VIDEO','VOZ','DOCUMENTO ADICIONAL','FIRMA LEGAL']:
        r=dict(id=kind,job_id=job['id'],kind=kind,verification_id=None,url=job['application_url']);w.shell.center.resolve(r);assert calls[-1]['job']['id']==job['id'] and calls[-1]['job']['application_url']==r['url']
    await_ui(lambda:not w._ui_tasks);w.close()

def test_context_persistence_no_tokens_or_answers(tmp_path):
    from autojob.control import Coordinator
    from autojob.intervention_context import load
    e=Coordinator(__import__('autojob.config',fromlist=['Settings']).Settings(tmp_path));id=e.store.add_intervention('j','Fictional','Support','MFA','Código manual','https://example.invalid/form?token=SECRET')
    ctx=load(e.store,id);assert ctx['job_id']=='j' and ctx['stage']==0 and 'SECRET' not in json.dumps(ctx);assert 'password' not in ctx
    other=Coordinator(e.settings);assert load(other.store,id)==ctx

def test_batch_ui_safe_on_restart(tmp_path,qt_application_lifetime,await_ui):
    from autojob.ui.main_window import MainWindow
    from autojob.ui.batch_ui import BatchAuthorization
    from autojob.config import Settings
    w=MainWindow(Settings(tmp_path));d=BatchAuthorization(w.shell);await_ui(lambda:not w._ui_tasks)
    assert not d.upload.isChecked() and not d.send.isChecked() and not d.cvs.selectedItems();d.save();await_ui(lambda:not w._ui_tasks);assert d.authorization is None
    assert w.shell.delivery_authorization is None and w.main_tabs.count()==4;d.close();w.close()

def test_three_jobs_one_batch_blocked_tasks_do_not_block_c(tmp_path,monkeypatch):
    if os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1':pytest.skip('Brave local separado')
    from autojob.forms.submissions import DeliveryGuard
    from autojob.forms.answers9b import ScopedAnswers
    from autojob.auth.verifications import VerificationStore
    from autojob.interventions import InterventionService
    with portal(tmp_path) as lab:
        engine=lab['engine'];s=SubmissionStore(lab['settings'].data_path);base=lab['job'];jobs={}
        for name in ['A','B','C']:
            engine.jobs.add(dict(base,source_id='9F-'+name,url=origin(base['url'])+'/jobs/'+name,application_url=origin(base['url'])+'/form?job='+name,title='Junior Python Developer '+name,id=None))
            jobs[name]=next(j for j in engine.jobs.list() if j['title']=='Junior Python Developer '+name)
        engine.compatibility.batch(ids=[j['id'] for j in jobs.values()]);a=create(s,criteria(s,jobs['C']),3,1,True,True,'local',True);original=DeliveryGuard.page;solved={'A':False}
        def page(self,url):
            p=original(self,url)
            if url.endswith('job=A') and not solved['A']:p.locator('body').evaluate("e=>e.insertAdjacentHTML('beforeend','<div>CAPTCHA: fictional human challenge</div>')")
            if url.endswith('job=B'):p.locator('form').evaluate("e=>e.insertAdjacentHTML('afterbegin','<label>Fictional project code<input name=code required></label>')")
            return p
        monkeypatch.setattr(DeliveryGuard,'page',page)
        assert SubmissionEngine(lab['settings']).run(jobs['A']['id'],a)['state']=='PENDIENTE'
        assert SubmissionEngine(lab['settings']).run(jobs['B']['id'],a)['state']=='PENDIENTE'
        assert SubmissionEngine(lab['settings']).run(jobs['C']['id'],a)['state']=='ENVIADA CONFIRMADA'
        assert sum(m=='POST' for m,p in lab['requests'])==1
        v=VerificationStore(lab['settings'].data_path);task=next(r for r in v.list() if r['job_id']==jobs['A']['id']);v.update(task['id'],'LISTA PARA CONTINUAR');solved['A']=True
        # Señal controlada local: nunca representa un CAPTCHA externo resuelto.
        service=InterventionService(engine);row=next(r for r in engine.store.interventions() if r['job_id']==jobs['A']['id'] and r['verification_id']);assert service.resume(row['id'])[0]
        before=s.prep.inputs_hash();j=jobs['B'];ScopedAnswers(lab['settings'].data_path).save('Fictional project code','LOCAL','text','job',dict(job_id=j['id'],company=j['company'],position=j['title'],modality='remote'),True)
        s.accept_confirmed_answer(a,j['id'],before);engine.compatibility.batch(ids=[j['id'] for j in jobs.values()])
        for name in ['B','A']:assert SubmissionEngine(lab['settings']).run(jobs[name]['id'],a)['state']=='ENVIADA CONFIRMADA'
        assert sum(m=='POST' for m,p in lab['requests'])==3
        assert SubmissionEngine(lab['settings']).run(jobs['C']['id'],a)['state']=='BLOQUEADA'
        assert len(s.rows())==3 and engine.store.confirmed()==0


def test_threshold_is_inclusive_but_rejects_below(tmp_path,monkeypatch):
 with portal(tmp_path) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];c=criteria(s,j);c['threshold']=100;a=create(s,c,3,1,True,True,'local',True)
  assert s.permission(a,j)  # Fixture acredita exactamente 100: el umbral es inclusivo.
  rows=s.prep.compatibility.rows();row=next(r for r in rows if r['job']['id']==j['id']);row['evaluation']['score']=99
  monkeypatch.setattr(s.prep.compatibility,'rows',lambda:rows)
  with pytest.raises(ValueError):s.permission(a,j)


def test_captcha_completed_or_noninteractive_needs_no_human_task(tmp_path,monkeypatch):
 from autojob.auth import verifications as v
 coordinator=v.CaptchaCoordinator(tmp_path)
 monkeypatch.setattr(v,'captcha_state',lambda *a:dict(completed=True,interactive=False));assert coordinator.wait(None,None,'j','Fictional')
 assert not coordinator.store.list()
 monkeypatch.setattr(v,'captcha_state',lambda *a:dict(completed=False,interactive=False));assert not coordinator.wait(None,None,'j','Fictional')
 assert not coordinator.store.list()


def test_field_focus_reidentifies_name_not_historical_selector(page):
 from autojob.intervention_context import focus
 page.set_content('<label>New label<input name=required_code id=new_id></label>')
 assert focus(page,dict(fields=[dict(name='required_code',label='Old label',selector='#deleted')]))
 assert page.locator('#new_id').evaluate('e=>document.activeElement===e')


def test_batch_limit_blocks_a_different_job_before_filling(tmp_path):
 with portal(tmp_path) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=create(s,criteria(s,j),1,1,True,True,'local',True)
  attempt=s.claim(a,j);s.finish(attempt,'ENVÍO NO VERIFICADO',{'verified':False})
  lab['engine'].jobs.add(dict(j,id=None,source_id='new-limited',title='Junior Python Developer Different',url=origin(j['url'])+'/different',application_url=origin(j['url'])+'/different-form'))
  other=next(r for r in lab['engine'].jobs.list() if r['title'].endswith('Different'));lab['engine'].compatibility.batch(ids=[other['id']])
  with pytest.raises(ValueError,match='Límite'):s.permission(a,other)
  assert len(s.rows())==1


def test_local_captcha_exact_session_human_signal(tmp_path):
 if os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1':pytest.skip('Brave local separado')
 from autojob.auth.local import local_portal
 from autojob.browser import BraveSession
 from autojob.forms.guard import PreparationGuard
 from autojob.auth.verifications import CaptchaCoordinator,captcha_state
 from autojob.config import Settings
 with local_portal() as fixture,BraveSession(Settings(tmp_path)) as browser:
  fixture['human_captcha']=True;guard=PreparationGuard(browser);page=guard.page(fixture['origin']+'/login');initial_url=page.url
  def resolve(p,id,store):
   task=next(t for t in store.list() if t['id']==id);assert task['reserved'] and p.url==initial_url
   store.update(id,command='RESOLVER');p.locator('#human-check').click()
  fixture['on_wait']=resolve
  assert CaptchaCoordinator(tmp_path/'data').wait(page,guard,'A','Fictitious A',seconds=2,fixture=fixture)
  assert captcha_state(page,fixture)['completed']



def test_manual_otp_never_arms_application_or_legal_fields():
 from autojob.manual_stage import otp_form
 base=dict(index=0,method='POST',action='https://example.invalid/auth')
 otp=dict(type='text',label='Verification code',autocomplete='one-time-code')
 assert otp_form([dict(base,fields=[otp])])
 for field in [dict(type='checkbox',label='I accept terms'),dict(type='file',label='Resume'),dict(type='password',label='Password'),dict(type='submit',label='Submit application')]:assert otp_form([dict(base,fields=[otp,field])]) is None
 assert otp_form([dict(base,fields=[otp]),dict(base,index=1,fields=[otp])]) is None
