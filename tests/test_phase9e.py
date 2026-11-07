import json,time,threading,os
from pathlib import Path
import pytest
from autojob.forms.validation import audit,form_state,visible_errors

@pytest.fixture
def page(tmp_path):
 if os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1':pytest.skip('Integración Brave local separada')
 from autojob.browser import BraveSession
 from autojob.config import Settings
 with BraveSession(Settings(tmp_path)) as browser:yield browser.new_page()

def entry(selector,label,kind='text',answer='Confirmed',**kwargs):return dict(selector=selector,label=label,kind=kind,answer=answer,status='CONFIRMADA',required=True,**kwargs)

def test_actual_dom_and_successful_values_are_checked(page):
 page.set_content('<form><label>Name<input name="name" required value="Confirmed"></label><select name="mode" required><option value="a" selected>Alpha</option><option value="b">Beta</option></select></form><form><input required name="newsletter"></form>')
 entries=[entry('input[name=name]','Name'),entry('select','Mode','select','Alpha')]
 assert audit(page,entries)['valid']
 page.locator('select').select_option('b');assert not audit(page,entries)['valid']
 page.locator('select').select_option('a');page.locator('input[name=name]').fill('Changed by script');result=audit(page,entries);assert not result['valid'];assert 'Changed by script' not in json.dumps(result)

def test_disabled_and_dynamic_required_fields_block(page):
 page.set_content('<form><input name="name" required value="Confirmed"><input name="late" required></form>');e=[entry('input[name=name]','Name')]
 assert not audit(page,e)['valid'];page.locator('input[name=late]').fill('Ready');page.locator('input[name=name]').evaluate('(e)=>e.disabled=true');assert not audit(page,e)['valid']

def test_form_reset_is_observed_without_claiming_receipt(page):
 from autojob.forms.confirmations import detect,response_signal
 page.set_content('<form><input name="name" required><select name="choice" required><option value="">Choose</option><option value="1">One</option></select></form>');page.locator('input').fill('Fictional');page.locator('select').select_option('1');entries=[entry('input','Name',answer='Fictional'),entry('select','Choice','select','One')];before=form_state(page,entries);page.locator('form').evaluate('(f)=>f.reset()');after=form_state(page,entries)
 assert before['invalid_count']==0 and before['nonempty_count']==2;assert after['invalid_count']==2 and after['nonempty_count']==0
 assert detect('Application form','https://portal.invalid',[response_signal(200)],True)['state']=='ENVÍO NO VERIFICADO'

def test_visible_validation_records_no_private_values(page):
 page.set_content('<form><input required name="email"><div class="field-error">Invalid email private@example.invalid</div></form>');notices=visible_errors(page);assert notices[0]['kind']=='VALIDACIÓN VISIBLE';assert 'private' not in json.dumps(notices) and '@' not in json.dumps(notices)

def test_fiveca_phone_hidden_requires_native_keyboard_event(page):
 from autojob.forms.fiveca import TARGET,fill_phone
 html='''<form><div class="iti" data-dial="31"><button class="iti__selected-flag" type="button">Country</button><ul><li class="iti__country" data-country-code="cr" onclick="this.closest('.iti').dataset.dial='506'">Costa Rica</li></ul><input name="phone" required></div><input type="hidden" name="full_phone"></form><script>document.querySelector('input[name=phone]').addEventListener('keyup',e=>{document.querySelector('input[name=full_phone]').value='+'+e.target.closest('.iti').dataset.dial+' '+e.target.value;});</script>'''
 page.route('**/*',lambda r:r.fulfill(status=200,body=html,content_type='text/html'));page.goto(TARGET);e=entry('input[name=phone]','Phone',answer='+50688887777',semantic='phone_5ca')
 page.locator('input[name=phone]').fill(e['answer']);assert page.locator('input[name=full_phone]').input_value()=='';assert not audit(page,[e])['valid']
 assert fill_phone(page,e)['status']=='VERIFICADO';assert audit(page,[e])['valid']

def test_background_callbacks_use_gui_thread_and_do_not_block_controls(tmp_path,qt_application_lifetime,await_ui):
 from PySide6.QtCore import QThread,QTimer
 from PySide6.QtWidgets import QWidget,QCheckBox,QLineEdit,QVBoxLayout
 from autojob.ui.background import submit
 w=QWidget();layout=QVBoxLayout(w);box=QCheckBox();edit=QLineEdit();layout.addWidget(box);layout.addWidget(edit);w.show();gate=threading.Event();called=[];ticks=[]
 timer=QTimer(w);timer.timeout.connect(lambda:ticks.append(time.perf_counter()));timer.start(10)
 def work():assert QThread.currentThread()!=qt_application_lifetime.thread();gate.wait(3);return 'ready'
 def done(value):called.append((value,QThread.currentThread()==qt_application_lifetime.thread()))
 task=submit(w,work,done,lambda m:pytest.fail(m));start=time.perf_counter();box.click();edit.setText('Local answer');elapsed=time.perf_counter()-start
 assert box.isChecked() and edit.text()=='Local answer' and elapsed<.2
 for _ in range(25):qt_application_lifetime.processEvents();time.sleep(.005)
 assert len(ticks)>=5 and not called;gate.set();await_ui(lambda:bool(called));assert called==[('ready',True)];await_ui(lambda:not w._ui_tasks);w.close()

@pytest.mark.parametrize('unknown',[False,True])
def test_dynamic_question_filled_or_blocks_before_claim(tmp_path,monkeypatch,unknown):
 if os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1':pytest.skip('Integración Brave local separada')
 from test_submissions9b import portal
 from autojob.forms.submissions import SubmissionStore,SubmissionEngine,DeliveryGuard
 from autojob.forms.answers9b import ScopedAnswers
 with portal(tmp_path) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];context=dict(job_id=j['id'],company=j['company'],modality='remote')
  if not unknown:ScopedAnswers(lab['settings'].data_path).save('Local dynamic code','KNOWN-9E','text','job',context,True)
  original=DeliveryGuard.page
  def changed(self,url):
   page=original(self,url);page.locator('input[name=name]').evaluate('e=>e.addEventListener("input",()=>{if(!document.querySelector("#dynamic")){const label=document.createElement("label");label.innerHTML="Local dynamic code<input id=dynamic name=dynamic required>";e.form.appendChild(label);}})');return page
  monkeypatch.setattr(DeliveryGuard,'page',changed);s.prep.compatibility.one(j,force=True);a=s.authorize([j['id']],1,True,True,'local',True);result=SubmissionEngine(lab['settings']).run(j['id'],a)
  if unknown:assert result['state']=='PENDIENTE' and not s.rows() and not any(m=='POST' for m,p in lab['requests'])
  else:assert result['state']=='ENVIADA CONFIRMADA' and sum(m=='POST' for m,p in lab['requests'])==1 and result['evidence']['preflight']['valid']

def test_requirement_headings_do_not_become_fake_requirements():
 from autojob.matching.engine import extract,DEFAULT
 for heading in ['Skills and qualifications','Required Experience & Skills']:
  req=extract(dict(title='Customer Support',description=heading+'\nStrong communication skills\nBonus qualifications\nExperience with Zendesk',raw={}),DEFAULT)
  assert any(r['name']=='communication' and r['importance']=='OBLIGATORIO' for r in req)
  assert not any(r['evidence']==heading for r in req)
  assert all(r['importance']=='DESEABLE' for r in req if 'Zendesk' in r['evidence'])

def test_existing_verified_traits_are_reused_but_unknown_is_not_invented():
 from autojob.matching.engine import assess,candidate,DEFAULT
 from autojob.profile.store import empty
 v=empty();v.update(skills=['Multitasking'],soft_skills=['Time Management']);p=dict(values=v,manual=['skills','soft_skills'],sources={})
 for text in ['Ability to stay organized and meet deadlines in a dynamic, often ambiguous environment','Comfortable handling multiple conversations or tasks simultaneously']:
  req=dict(kind='other',name='uninterpreted',evidence=text,importance='OBLIGATORIO')
  assert assess(req,candidate(p,[]),DEFAULT,{})['state']=='CUMPLE'
  assert assess(req,candidate(dict(values=empty(),manual=[],sources={}),[]),DEFAULT,{})['state']=='POR VERIFICAR'

def test_radio_question_cached_only_within_one_preparation(tmp_path,monkeypatch):
 from autojob.forms.preparation import Preparation
 p=Preparation(tmp_path);calls=[]
 def resolve(q,context=None):calls.append(q);return dict(answer='Car',status='CONFIRMADA',source='Fixture',reason='Fixture',automatic=False)
 monkeypatch.setattr(p,'resolve',resolve);doc=dict(url='https://example.invalid',title='Fixture',obstacles=[],fields=[dict(selector='#r'+str(i),label=value,kind='radio',name='transport',group='Transport preference',required=True,options=[]) for i,value in enumerate(['Bus','Car'])])
 assert all(e['status']=='CONFIRMADA' for e in p.prepare(doc)['entries']);assert calls==['Transport preference'];p.prepare(doc);assert len(calls)==2

def test_grouped_checkboxes_verify_actual_submitted_options(page):
 from autojob.forms.runner import fill_field
 page.set_content('<form><label><input type=checkbox name=tools value=one>One</label><label><input type=checkbox name=tools value=other>Other</label></form>');e=entry('input[value=one]','Tools','multiple','Other',checkbox_group=True,options=[dict(label='One',value='one',selector='input[value=one]'),dict(label='Other',value='other',selector='input[value=other]')])
 class Guard:
  def freeze(self):pass
 # audit does not depend on a particular origin or transport.
 page.locator('input[value=other]').set_checked(True);assert audit(page,[e])['valid'];page.locator('input[value=one]').set_checked(True);assert not audit(page,[e])['valid']

def test_wire_rejects_changed_fields_and_file_bytes():
 from autojob.forms.wire import verify
 from hashlib import sha256
 class Request:
  resource_type='document';headers={'content-type':'multipart/form-data; boundary=b'}
  post_data_buffer=b'--b\r\nContent-Disposition: form-data; name="code"\r\n\r\nCHANGED\r\n--b\r\nContent-Disposition: form-data; name="cv"; filename="cv.pdf"\r\n\r\nFILE\r\n--b--\r\n'
 expected=[dict(name='code',value='CONFIRMED',file=None),dict(name='cv',value=None,file=dict(name='cv.pdf',size=4,sha256=sha256(b'FILE').hexdigest()))]
 assert not verify(Request(),expected,sha256(b'FILE').hexdigest())[0]
 expected[0]['value']='CHANGED';assert verify(Request(),expected,sha256(b'FILE').hexdigest())[0];assert not verify(Request(),expected,sha256(b'OTHER').hexdigest())[0]

def test_reserved_captcha_resumes_same_worker_even_when_busy(tmp_path,qt_application_lifetime,monkeypatch,await_ui):
 from autojob.ui.main_window import MainWindow
 from autojob.auth.verifications import VerificationStore
 from autojob.config import Settings
 w=MainWindow(Settings(tmp_path));v=VerificationStore(w.settings.data_path);id=v.add('fixture','CAPTCHA PENDIENTE','https://example.invalid/form','Fictional',True);monkeypatch.setattr(w.shell,'occupied',lambda:True)
 monkeypatch.setattr('autojob.live.command',lambda job,action:job=='fixture' and action=='FOCUS')
 row=dict(verification_id=id,kind='CAPTCHA PENDIENTE');w.shell.center.resolve(row)
 assert next(r for r in v.list() if r['id']==id)['command']=='RESOLVER';assert w.shell.center.pending_manual is None
 await_ui(lambda:not w._ui_tasks);w.close()

def test_blocked_post_is_not_mislabelled_transmitted(tmp_path,monkeypatch):
 if os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1':pytest.skip('Integración Brave local separada')
 from test_submissions9b import portal
 from autojob.forms import wire
 from autojob.forms.submissions import SubmissionStore,SubmissionEngine
 with portal(tmp_path) as lab:
  monkeypatch.setattr(wire,'verify',lambda *args:(False,'CAMBIO DE CONTROL FICTICIO'))
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);r=SubmissionEngine(lab['settings']).run(j['id'],a)
  assert r['state']=='NO TRANSMITIDA';assert not any(m=='POST' for m,p in lab['requests']);assert s.rows()[0]['evidence']['final_request_released'] is False;assert not s.duplicate(j)

def test_http200_with_visible_validation_error_is_rejected(tmp_path):
 if os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1':pytest.skip('Integración Brave local separada')
 from test_submissions9b import portal
 from autojob.forms.submissions import SubmissionStore,SubmissionEngine
 with portal(tmp_path,validation_error=True) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);r=SubmissionEngine(lab['settings']).run(j['id'],a)
  assert r['state']=='RECHAZADA';assert r['evidence']['portal_rejected'];assert s.duplicate(j);assert sum(m=='POST' for m,p in lab['requests'])==1


def test_doola_uncertain_years_cannot_fall_back_to_free_text(tmp_path,monkeypatch):
 from autojob.forms.preparation import Preparation
 from autojob.forms.answers9b import ScopedAnswers
 p=Preparation(tmp_path)
 monkeypatch.setattr(p,'resolve',lambda *args:dict(answer='2 to 5 years',status='DERIVADA',source='Fixture',reason='Fixture',automatic=False))
 doc=dict(url='https://example.invalid',title='Fixture',obstacles=[],fields=[dict(selector='#r'+str(i),label=value,kind='radio',name='years',group='How many years of experience do you have in customer service?',semantic='doola_years',required=True,options=[]) for i,value in enumerate(['1-3 years','3-5 years','5+ years'])])
 assert all(e['status']=='DESCONOCIDA' for e in p.prepare(doc)['entries'])
 ScopedAnswers(tmp_path).save(doc['fields'][0]['group'],'3-5 years','radio','work',{},True,['1-3 years','3-5 years','5+ years'])
 assert all(e['answer']=='3-5 years' and e['status']=='CONFIRMADA' for e in p.prepare(doc)['entries'])

