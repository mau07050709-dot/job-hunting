import json,os
import pytest
from autojob.forms.documents import document_kind
from autojob.profile.contact import whatsapp_intent
from autojob.forms.preparation import Preparation,inspect
from autojob.profile.application_data import ApplicationData

QUESTION='Our next step is a phone screening conducted via WhatsApp. Please share your active WhatsApp number (with country code) so we can coordinate the call.'
PHONE='+50683123456'

@pytest.mark.parametrize('field,expected',[
 ({'label':'Choose file','aria_labelledby_text':'Resume'},'cv'),
 ({'label':'Choose file','data_ui':'resume'},'cv'),
 ({'label':'Choose file','group':'Curriculum Vitae'},'cv'),
 ({'label':'Choose file','aria_labelledby_text':'Passport'},'unknown'),
 ({'label':'Choose file','accept':'.pdf,.docx'},'unknown'),
 ({'label':'Choose file','group':'Cover letter'},'letter'),
 ({'label':'CV and national ID'},'unknown'),
])
def test_document_context(field,expected):assert document_kind(field)==expected

def confirmed_profile(path,whatsapp=None):
    prep=Preparation(path);p=prep.data.profile.load();v=p['values'];v['phone']=PHONE
    if whatsapp is not None:v['whatsapp']=whatsapp
    prep.data.profile.save(v,p['revision'],confirmed=['phone']+(['whatsapp'] if whatsapp else []))
    return prep

def test_whatsapp_real_question_same_number_format_no_mutation(tmp_path):
    prep=confirmed_profile(tmp_path,PHONE);prep.data.save({'whatsapp':'+506 8312 3456'},confirmed=[])
    before=prep.data.load();r=prep.resolve(QUESTION);assert r['status']=='CONFIRMADA' and r['answer']==PHONE
    assert prep.data.load()==before and 'whatsapp' not in prep.data.conflicts()

def test_phone_is_not_whatsapp_and_different_numbers_block(tmp_path):
    prep=confirmed_profile(tmp_path);assert prep.resolve(QUESTION)['answer'] is None
    p=prep.data.profile.load();p['values']['whatsapp']=PHONE;prep.data.profile.save(p['values'],p['revision'],confirmed=['whatsapp'])
    prep.data.save({'whatsapp':'+50688888888'},confirmed=['whatsapp']);assert prep.resolve(QUESTION)['status']=='CONFLICTO'

@pytest.mark.parametrize('q',['May we contact you via WhatsApp?','Do you consent to WhatsApp contact?','Do you prefer WhatsApp or email?'])
def test_number_does_not_imply_consent_or_preference(tmp_path,q):
    assert confirmed_profile(tmp_path,PHONE).resolve(q)['answer'] is None

def test_account_confirmation_is_separate(tmp_path):
    p=confirmed_profile(tmp_path,PHONE);assert whatsapp_intent('Do you have WhatsApp?')=='account';assert p.resolve('Do you have WhatsApp?')['answer']=='Yes'

def test_salary_range_keeps_period_and_number_field_requires_review(tmp_path):
    p=Preparation(tmp_path);p.data.save(dict(main_min='1000',main_max='2000',main_currency='USD',main_period='month'),confirmed=['main_min','main_max','main_currency','main_period'])
    r=p.resolve('What is your salary expectation in USD per month?');assert r['answer']=='1000.00–2000.00' and r['status']=='DERIVADA'
    annual=p.resolve('What is your salary expectation in USD per year?');assert annual['answer']=='12000.00–24000.00'

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_pavago_local_eight_known_fields_cv_intervention_and_single_post(tmp_path,monkeypatch):
    from test_submissions9b import portal
    from autojob.forms.submissions import SubmissionStore,SubmissionEngine,DeliveryGuard
    from autojob.browser import BraveSession
    from autojob.live import wait_prepared,command,active
    with portal(tmp_path) as lab:
        store=SubmissionStore(lab['settings'].data_path);j=lab['job'];p=store.prep.data.profile.load();v=p['values'];v.update(phone=PHONE,whatsapp=PHONE,linkedin='https://www.linkedin.com/in/local-fictional-profile/')
        store.prep.data.profile.save(v,p['revision'],confirmed=['phone','whatsapp','linkedin']);store.prep.data.save(dict(first_name='Alex',last_name='Rivera',main_min='1000',main_max='2000',main_currency='USD',main_period='month'),confirmed=['first_name','last_name','main_min','main_max','main_currency','main_period'])
        store.prep.compatibility.one(j,force=True);authorization=store.authorize([j['id']],1,True,True,'local',True)
        with BraveSession(lab['settings']) as browser:
            _,rule=store.permission(authorization,j);guard=DeliveryGuard(browser,rule['origin'],lambda:store.permission(authorization,j),rule);page=guard.page(rule['url'])
            page.locator('[name=name]').evaluate('(e)=>e.parentElement.remove()');page.locator('[name=cv]').evaluate('(e)=>e.parentElement.remove()')
            html='<label>First name<input name=first required></label><label>Last name<input name=last required></label><label>Phone<input name=phone type=tel></label><label>LinkedIn<input name=linkedin></label><label>'+QUESTION+'<input name=whatsapp required></label><label>Salary in USD per month<input name=salary required></label><span id=resume-label>Resume</span><label for=upload>Choose file</label><input id=upload name=cv type=file required aria-labelledby=resume-label><label>Unknown mandatory code<input name=unknown required></label>'
            page.locator('form').evaluate('(e,html)=>e.insertAdjacentHTML("afterbegin",html)',html)
            seen=[]
            def human(p,state,item):
                seen.append(p)
                assert p.locator('[name=whatsapp]').input_value()==PHONE
                assert p.locator('[name=salary]').input_value()=='1000.00–2000.00'
                assert p.locator('[name=cv]').evaluate('(e)=>e.files.length')==1
                assert any(e.get('document')=='cv' for e in state['preview']['entries'])
                if len(seen)==1:
                    assert {e['label'] for e in state['pending']}=={'Unknown mandatory code'}
                    assert active(j['id']);command(j['id'],'FOCUS');p.locator('[name=unknown]').fill('LOCAL-ONLY');command(j['id'],'CHECK')
                else:assert not state['pending']
            result=wait_prepared(lab['settings'],browser,page,guard,j,authorization,fixture={'origin':rule['origin'],'on_prepared':human},on_ready=lambda:SubmissionEngine(lab['settings']).run(j['id'],authorization,session=(browser,page,guard)))
            assert result['state']=='ENVIADA CONFIRMADA' and seen and all(p is page for p in seen)
        assert sum(m=='POST' for m,p in lab['requests'])==1 and lab['upload_verified']
        assert SubmissionEngine(lab['settings']).run(j['id'],authorization)['state']=='BLOQUEADA'


def test_contact_consent_only_from_specific_approved_answer(tmp_path):
    from autojob.forms.answers9b import ScopedAnswers
    p=confirmed_profile(tmp_path,PHONE);q='May we contact you via WhatsApp?';ctx=dict(job_id='x',company='Example',modality='remote')
    assert p.resolve(q,ctx)['answer'] is None
    ScopedAnswers(tmp_path).save(q,'Yes',scope='job',context=ctx,confirmed=True)
    assert p.resolve(q,ctx)['answer']=='Yes'
    assert p.resolve(q,dict(ctx,job_id='other'))['answer'] is None

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_cv_upload_without_permission_never_sets_file(tmp_path):
    from test_submissions9b import portal
    from autojob.forms.submissions import SubmissionStore,DeliveryGuard
    from autojob.browser import BraveSession
    from autojob.live import prepare
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True)
        with BraveSession(lab['settings']) as b:
            _,rule=s.permission(a,j);rule=dict(rule,upload=False)
            g=DeliveryGuard(b,rule['origin'],lambda:None,rule);page=g.page(rule['url']);state=prepare(page,g,s.prep,j,rule)
            assert page.locator('[name=cv]').evaluate('(e)=>e.files.length')==0
            assert any(x['type']=='AUTORIZACIÓN CV' for x in state['preview']['blocks'])
        assert not any(method=='POST' for method,path in lab['requests'])


def test_intervention_has_resolve_and_later(tmp_path,qt_application_lifetime,await_ui):
    from test_batch_https import seed
    from autojob.config import Settings
    from autojob.ui.main_window import MainWindow
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0];w=MainWindow(Settings(tmp_path));await_ui(lambda:not w._ui_tasks,30000)
    center=w.shell.center;id=w.shell.engine.store.add_intervention(job['id'],job['company'],job['title'],'AUTORIZACIÓN CV','No hay ejecución vigente.',job['application_url']);row=next(r for r in w.shell.engine.store.interventions() if r['id']==id)
    center.show_problem(row,{'notifications':False});buttons={b.text():b for b in center.popup.findChildren(QPushButton)}
    assert set(buttons)=={'RESOLVER AHORA','RESOLVER MÁS TARDE'}
    QTest.mouseClick(buttons['RESOLVER MÁS TARDE'],Qt.MouseButton.LeftButton)
    assert next(r for r in w.shell.engine.store.interventions() if r['id']==id)['state']=='POSPUESTA'
    await_ui(lambda:not w._ui_tasks,30000);w.close()
