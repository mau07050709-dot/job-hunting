import os,json
from contextlib import closing
import pytest
from test_submissions9b import portal
from autojob.forms.submissions import SubmissionStore,SubmissionEngine,DeliveryGuard
from autojob.forms.answers9b import ScopedAnswers
from autojob.live import prepare,wait_prepared,command,active,historical,reconcile

FIELDS=[('First name','first','Alex'),('Last name','last','Rivera'),('Phone','phone','+506 8888 7777'),('Country of residence','country','Costa Rica'),('City of residence','city','Cartago'),('English proficiency level','english','C1'),('Availability','available','Any day'),('Work experience','experience','Example Labs | Software Developer | 2022-01-01 | 2024-12-31 | Python development')]

def setup(lab,monkeypatch,changed=False):
    s=SubmissionStore(lab['settings'].data_path);job=lab['job'];ctx=dict(job_id=job['id'],company=job['company'],position=job['title'],modality='remote');bank=ScopedAnswers(lab['settings'].data_path)
    for label,name,value in FIELDS+[('Confirmed schedule','dynamic','Flexible')]:bank.save(label,value,'text','job',ctx,True)
    s.prep.compatibility.one(job,force=True);a=s.authorize([job['id']],1,True,True,'local',True);original=DeliveryGuard.page;calls=[]
    def page(self,url):
        p=original(self,url);calls.append(p)
        html=''.join('<label>'+label+'<input name="'+name+'" required></label>' for label,name,value in FIELDS)
        html+='<label>Fictional required code<input name=unknown required></label>'
        if changed:html+='<label>New mandatory code<input name=newcode required></label>'
        p.locator('form').evaluate('(e,html)=>e.insertAdjacentHTML("afterbegin",html)',html)
        p.locator('head').evaluate('(e)=>e.insertAdjacentHTML("beforeend",\'<meta name="autojob-human-fixture" content="local9g">\')')
        p.locator('body').evaluate('(e)=>e.insertAdjacentHTML("afterbegin",\'<div data-captcha="true">CAPTCHA simulated<button id=human-check type=button onclick="this.parentElement.dataset.humanResult=\\\'complete\\\';this.parentElement.innerHTML=\\\'Verification complete\\\'">Local human confirmation</button></div>\')')
        p.locator('input[name=email]').evaluate("e=>e.addEventListener('input',()=>{if(!document.querySelector('[name=dynamic]'))e.form.insertAdjacentHTML('beforeend','<label>Confirmed schedule<input name=dynamic required></label>')})")
        return p
    monkeypatch.setattr(DeliveryGuard,'page',page)
    fixture=dict(origin=job['application_url'].split('/form')[0],token='local9g')
    return s,job,a,ctx,bank,fixture,calls

def assert_prepared(page):
    for label,name,value in FIELDS:assert page.locator('[name='+name+']').input_value()==value
    assert page.locator('[name=email]').input_value()=='alex@example.invalid'
    assert page.locator('[name=name]').input_value()=='Alex Rivera'
    assert page.locator('[name=cv]').evaluate('(e)=>e.files.length')==1

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_prepared_same_session_unknown_captcha_single_post(tmp_path,monkeypatch):
    import autojob.live as live
    from autojob.browser import BraveSession
    with portal(tmp_path) as lab:
        s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch);seen=[];logical=[10.0];monkeypatch.setattr(live,'clock',lambda:logical[0])
        with BraveSession(lab['settings']) as b:
            _,rule=s.permission(a,j);guard=DeliveryGuard(b,rule['origin'],lambda:s.permission(a,j),rule);page=guard.page(rule['url'])
            def human(p,state,item):
                assert_prepared(p);assert p is page;seen.append(state)
                if len(seen)==1:
                    assert any(e['label']=='Fictional required code' for e in state['pending']);assert active(j['id']);command(j['id'],'FOCUS')
                    logical[0]+=600  # Tiempo lógico local: la sesión no depende de un plazo de 30–180 s.
                    p.locator('[name=unknown]').fill('MANUAL-LOCAL')
                    before=s.prep.inputs_hash();bank.save('Fictional required code','MANUAL-LOCAL','text','job',ctx,True);s.prep.compatibility.one(j,force=True);s.accept_confirmed_answer(a,j['id'],before)
                    p.locator('#human-check').click();command(j['id'],'CHECK')
                else:assert not p.is_closed() and p.locator('[name=unknown]').input_value()=='MANUAL-LOCAL'
            fixture['on_prepared']=human
            result=wait_prepared(lab['settings'],b,page,guard,j,a,fixture=fixture,on_ready=lambda:SubmissionEngine(lab['settings']).run(j['id'],a,session=(b,page,guard)))
            assert result['state']=='ENVIADA CONFIRMADA';assert len(calls)==1;assert not active(j['id'])
        assert len(seen)>=2 and sum(m=='POST' for m,p in lab['requests'])==1 and lab['upload_verified']
        assert SubmissionEngine(lab['settings']).run(j['id'],a)['state']=='BLOQUEADA'
        assert len(calls)==1

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_reconstruct_lost_session_preserves_scope_detects_new_field(tmp_path,monkeypatch):
    from autojob.browser import BraveSession
    with portal(tmp_path) as lab:
        s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch,changed=True)
        with BraveSession(lab['settings']) as b:
            _,rule=s.permission(a,j);g=DeliveryGuard(b,rule['origin'],lambda:s.permission(a,j),rule);p=g.page(rule['url']);state=prepare(p,g,s.prep,j,rule);assert_prepared(p)
        assert not s.rows() and not any(m=='POST' for m,p in lab['requests'])
        with BraveSession(lab['settings']) as b:
            _,rule=s.permission(a,j);g=DeliveryGuard(b,rule['origin'],lambda:s.permission(a,j),rule);p=g.page(rule['url'])
            def human(page,state,item):
                assert_prepared(page)
                if state['pending']:
                    assert any(e['label']=='New mandatory code' for e in state['pending'])
                    before=s.prep.inputs_hash()
                    for label,name,value in [('Fictional required code','unknown','LOCAL'),('New mandatory code','newcode','NEW')]:page.locator('[name='+name+']').fill(value);bank.save(label,value,'text','job',ctx,True)
                    s.prep.compatibility.one(j,force=True);s.accept_confirmed_answer(a,j['id'],before);page.locator('#human-check').click();command(j['id'],'CHECK')
            fixture['on_prepared']=human
            result=wait_prepared(lab['settings'],b,p,g,j,a,fixture=fixture,on_ready=lambda:SubmissionEngine(lab['settings']).run(j['id'],a,session=(b,p,g)))
            assert result['state']=='ENVIADA CONFIRMADA'
        assert len(calls)==2 and sum(m=='POST' for m,p in lab['requests'])==1

def test_uncertain_archives_preparation_never_opens_or_changes_evidence(tmp_path,monkeypatch):
    from autojob.forms.runner import process
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);id=s.claim(a,j);s.finish(id,'ENVÍO NO VERIFICADO',dict(verified=False,original='unchanged'));before=s.rows()[0]
        e=lab['engine'];e.queue.add([j['id']]);login=e.store.add_intervention(j['id'],j['company'],j['title'],'REQUIERE LOGIN','Old preparation',j['url']);receipt=e.store.add_intervention(j['id'],j['company'],j['title'],'COMPROBANTE NO VERIFICADO','Legitimate proof only',j['url']);reconcile(e.store,e.queue)
        assert next(r for r in e.store.interventions() if r['id']==login)['state']=='SUPERADA'
        assert next(r for r in e.store.interventions() if r['id']==receipt)['state']=='PENDIENTE'
        monkeypatch.setattr('autojob.forms.submissions.BraveSession',lambda *a:pytest.fail('No reabrir'))
        monkeypatch.setattr('autojob.forms.runner.BraveSession',lambda *a:pytest.fail('No reabrir'))
        assert SubmissionEngine(lab['settings']).run(j['id'],a)['state']=='BLOQUEADA'
        row=next(r for r in e.queue.list() if r['job_id']==j['id']);assert process(e.queue,row,lab['settings'],lambda:False,lambda:False,'local')['state']=='BLOQUEADA'
        assert s.rows()[0]==before and not any(m=='POST' for m,p in lab['requests'])

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_later_releases_session_without_post_or_authorized_upload(tmp_path,monkeypatch):
    from autojob.browser import BraveSession
    from autojob.forms.guard import PreparationGuard
    with portal(tmp_path) as lab:
        s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch);lab['engine'].queue.allow_site(j['application_url'],True)
        with BraveSession(lab['settings']) as b:
            # DeliveryGuard habilita controles nativos, pero no existe permiso de adjunto ni final armado.
            g=DeliveryGuard(b,j['application_url'].split('/form')[0],lambda:None,{});p=g.page(j['application_url'])
            def later(page,state,item):
                assert page.locator('[name=cv]').evaluate('(e)=>e.files.length')==0;assert active(j['id']);command(j['id'],'LATER')
            fixture['on_prepared']=later;result=wait_prepared(lab['settings'],b,p,g,j,fixture=fixture)
            assert result['state']=='PENDIENTE' and not active(j['id'])
        assert not any(m=='POST' for m,p in lab['requests'])

def test_historical_resolve_opens_portal_without_repeating_submission(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.main_window import MainWindow
    from autojob.ui.receipt_review import ReceiptReview
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);id=s.claim(a,j);s.finish(id,'ENVÍO NO VERIFICADO',{'verified':False})
        before=s.rows();opened=[];w=MainWindow(lab['settings']);monkeypatch.setattr(w.shell.center,'open_direct',lambda *a:pytest.fail('No reconstruir ni reenviar'))
        monkeypatch.setattr(w.shell,'view_sent',lambda row:opened.append(row))
        w.shell.center.resolve(dict(job_id=j['id'],kind='REQUIERE LOGIN',verification_id=None))
        assert opened[0]['job']['id']==j['id'] and opened[0]['attempt']['state']=='ENVÍO NO VERIFICADO' and w.shell.center.popup is None
        assert s.rows()==before and not any(m=='POST' for m,p in lab['requests'])
        await_ui(lambda:not w._ui_tasks,30000);w.close()


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_manual_known_value_stays_and_cv_is_not_replaced(tmp_path,monkeypatch):
 from autojob.browser import BraveSession
 with portal(tmp_path) as lab:
  s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch)
  with BraveSession(lab['settings']) as b:
   _,rule=s.permission(a,j);g=DeliveryGuard(b,rule['origin'],lambda:s.permission(a,j),rule);p=g.page(rule['url']);prepare(p,g,s.prep,j,rule)
   p.locator('[name=first]').fill('Alex Javier');original_file=p.locator('[name=cv]').evaluate('(e)=>e.files[0].lastModified');state=prepare(p,g,s.prep,j,rule)
   assert p.locator('[name=first]').input_value()=='Alex Javier';assert any(e['label']=='First name' for e in state['pending'])
   assert p.locator('[name=cv]').evaluate('(e)=>e.files[0].lastModified')==original_file
  assert not any(m=='POST' for m,p in lab['requests'])


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_submission_engine_retains_actual_prepared_page(tmp_path,monkeypatch):
 import autojob.live as live
 with portal(tmp_path) as lab:
  s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch);original=live.wait_prepared
  cv_notice=lab['engine'].store.add_intervention(j['id'],j['company'],j['title'],'INFORMACIÓN FALTANTE','Revisar campos requeridos: Resume/CV',j['application_url'])
  def human(p,state,item):
   assert_prepared(p)
   assert next(r for r in lab['engine'].store.interventions() if r['id']==cv_notice)['state']=='RESUELTA'
   if state['pending']:
    before=s.prep.inputs_hash();p.locator('[name=unknown]').fill('CONFIRMED');bank.save('Fictional required code','CONFIRMED','text','job',ctx,True);s.prep.compatibility.one(j,force=True);s.accept_confirmed_answer(a,j['id'],before);p.locator('#human-check').click();command(j['id'],'CHECK')
  fixture['on_prepared']=human
  def controlled(*args,**kwargs):kwargs['fixture']=fixture;return original(*args,**kwargs)
  monkeypatch.setattr(live,'wait_prepared',controlled)
  result=SubmissionEngine(lab['settings']).run(j['id'],a,retain=True)
  assert result['state']=='ENVIADA CONFIRMADA';assert len(calls)==1;assert sum(m=='POST' for m,p in lab['requests'])==1


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_human_captcha_has_no_deadline_and_pause_does_not_close_it(tmp_path,monkeypatch):
 from autojob.auth.local import local_portal
 from autojob.browser import BraveSession
 from autojob.forms.guard import PreparationGuard
 from autojob.auth.verifications import CaptchaCoordinator
 from autojob.config import Settings
 with local_portal() as fixture,BraveSession(Settings(tmp_path)) as b:
  fixture['human_captcha']=True;g=PreparationGuard(b);p=g.page(fixture['origin']+'/login');ticks=[];original=p.wait_for_timeout
  fixture['on_wait']=lambda page,id,store:store.update(id,command='RESOLVER')
  def tick(ms):
   ticks.append(1);assert not p.is_closed()
   if len(ticks)==2:p.locator('#human-check').click()
   original(20)
  monkeypatch.setattr(p,'wait_for_timeout',tick)
  assert CaptchaCoordinator(tmp_path/'data').wait(p,g,'fake','Local only',pause=lambda:True,seconds=0,manual_start=True,fixture=fixture)
  assert len(ticks)>=2 and not p.is_closed()


def test_inflight_captcha_keeps_owner_instead_of_receipt_or_reopen(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
 from autojob.ui.main_window import MainWindow
 from autojob.auth.verifications import VerificationStore
 with portal(tmp_path) as lab:
  w=MainWindow(lab['settings']);s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);attempt=s.claim(a,j)
  v=VerificationStore(lab['settings'].data_path);id=v.add(j['id'],'CAPTCHA PENDIENTE',j['application_url'],j['title'],True)
  monkeypatch.setattr(w.shell.center,'open_direct',lambda *a:pytest.fail('No reconstruir mientras hay un propietario'))
  monkeypatch.setattr('autojob.live.command',lambda job,action:job==j['id'] and action=='FOCUS')
  assert historical(s,j['id'])=='INFLIGHT'
  w.shell.center.resolve(dict(job_id=j['id'],kind='CAPTCHA PENDIENTE',verification_id=id))
  assert next(r for r in v.list() if r['id']==id)['command']=='RESOLVER'
  assert not w.shell.center.popup
  s.finish(attempt,'NO TRANSMITIDA',dict(verified=False,final_request_released=False));v.update(id,reserved=False)
  await_ui(lambda:not w._ui_tasks);w.close()


def test_approved_answer_does_not_hide_profile_conflict(tmp_path):
 from autojob.forms.preparation import Preparation
 p=Preparation(tmp_path);p.data.save(dict(ram_gb='32'),confirmed=['ram_gb'])
 ScopedAnswers(tmp_path).save('RAM','8','text','job',dict(job_id='j'),True)
 doc=dict(url='https://example.invalid',title='Fixture',obstacles=[],fields=[dict(kind='text',label='RAM',selector='#ram',required=True,options=[],group='',name='ram')])
 entry=p.prepare(doc,dict(id='j'))['entries'][0]
 assert entry['status']=='CONFLICTO' and entry['answer'] is None
