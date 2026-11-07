from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import json
import pytest
from autojob.forms import fiveca
from autojob.forms.preparation import Preparation
from autojob.forms.submissions import SubmissionStore
from autojob.forms.manual_receipts import incorporate
from autojob.matching.engine import extract,DEFAULT
from test_submissions9b import portal
FIX=Path(__file__).parent/'fixtures'/'fiveca9d'
def document():return json.loads((FIX/'form.json').read_text(encoding='utf-8'))
def schema():return json.loads((FIX/'schema.json').read_text(encoding='utf-8'))
def test_public_native_schema_and_unknown_hours(tmp_path):
 d=fiveca.enrich_document(document(),schema());assert not d['obstacles'];p=Preparation(tmp_path);preview=p.prepare(d)
 fields={e.get('public_field_name',e.get('name')):e for e in preview['entries']}
 assert fields['question_7859687101[]']['status']=='DESCONOCIDA'
 assert fields['question_7859688101[]']['status']=='DESCONOCIDA'
 assert fields['question_7859689101']['status']=='DESCONOCIDA'
 assert sum(e.get('requires_specific_consent',False) for e in fields.values())==3
 assert not any(e['label']=='Sin etiqueta' for e in preview['entries'])
@pytest.mark.parametrize('change',['missing','privacy','assessment'])
def test_changed_schema_blocks(change):
 d=document();s=schema()
 if change=='missing':d['fields']=[f for f in d['fields'] if f.get('name')!='question_7859685101']
 elif change=='privacy':next(f for f in d['fields'] if f.get('name')=='data_compliance[gdpr_processing_consent_given]')['label']+=' New terms'
 else:next(q for q in s['questions'] if q['fields'][0]['name']=='question_7859691101')['label']+=' New terms'
 assert fiveca.enrich_document(d,s)['obstacles']
def test_confirmed_c1_maps_published_group_without_claiming_c2(tmp_path):
 p=Preparation(tmp_path);state=p.data.profile.load();state['values']['languages']=['English C1'];p.data.profile.save(state['values'],state['revision'],confirmed=['languages'])
 e=next(e for e in p.prepare(fiveca.enrich_document(document(),schema()))['entries'] if e.get('semantic')=='english_level_5ca')
 assert e['answer']=='Advanced (C1/C2)' and e['status']=='DERIVADA'
 assert p.data.profile_state()['values']['languages']==['English C1']
def test_specific_permissions_are_unchecked_in_ui(tmp_path,qt_application_lifetime):
 from autojob.ui.main_window import MainWindow
 from autojob.config import Settings
 from autojob.ui.submission_ui import AuthorizeSubmission
 w=MainWindow(Settings(tmp_path));d=AuthorizeSubmission(w.shell)
 assert not d.fiveca_processing.isChecked() and not d.fiveca_assessment.isChecked()
 d.close();w.close()
def test_backend_binds_specific_consent_to_exact_job(tmp_path,monkeypatch):
 with portal(tmp_path) as lab:
  store=SubmissionStore(lab['settings'].data_path);rows=store.prep.compatibility.rows();row=next(r for r in rows if r['job']['id']==lab['job']['id']);row=deepcopy(row);row['job'].update(url=fiveca.TARGET,application_url=fiveca.TARGET)
  monkeypatch.setattr(store.prep.compatibility,'rows',lambda:[row])
  with pytest.raises(ValueError,match='avisos'):store.authorize([row['job']['id']],1,True,True)
  a=store.authorize([row['job']['id']],1,True,True,special_consents=fiveca.consents())
  _,rule=store.permission(a,row['job']);assert rule['specific_consents']==fiveca.consents();assert rule['specific_consents'][fiveca.key(fiveca.NEWSLETTER)]=='No'
def test_receipt_requires_explicit_review_and_correct_vacancy(tmp_path):
 with portal(tmp_path) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);attempt=s.claim(a,j);s.finish(attempt,'ENVÍO NO VERIFICADO',dict(mode='local',verified=False));f=tmp_path/'proof.txt';f.write_text('Your application was received by Another Company for Wrong Position')
  now=datetime.now(timezone.utc).isoformat()
  with pytest.raises(ValueError):incorporate(s,attempt,f,now,'Portal',reviewed=False)
  with pytest.raises(ValueError):incorporate(s,attempt,f,now,'Portal',reviewed=True)
  assert s.rows()[0]['state']=='ENVÍO NO VERIFICADO';assert lab['requests']==[]
def test_user_receipt_reconciles_existing_attempt_no_new_request(tmp_path):
 with portal(tmp_path) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);attempt=s.claim(a,j);s.finish(attempt,'ENVÍO NO VERIFICADO',dict(mode='local',verified=False));f=tmp_path/'proof.txt';f.write_text('Your application was received by '+j['company']+' for '+j['title'])
  evidence=incorporate(s,attempt,f,datetime.now(timezone.utc).isoformat(),'Portal',reviewed=True)
  assert evidence['receipt_id'] is None and evidence['source']=='MANUAL_USUARIO'
  assert (s.data_path/evidence['receipt_file']).is_file();assert len(SubmissionStore(s.data_path).rows())==1
  from autojob.control import ControlStore
  assert ControlStore(s.data_path).confirmed()==0;assert lab['requests']==[]
def test_about_you_technical_and_phone_alternatives():
 j=dict(description='About you:\nYou speak English C1.\nTechnical requirements:\nA smartphone usable for two-factor authentication that runs at least:\nAndroid 10 or newer\nApple iOS 16 or newer',title='English Gaming Support Agent',raw={})
 requirements=extract(j,DEFAULT)
 assert any(r['kind']=='language' and r['importance']=='OBLIGATORIO' for r in requirements)
 phone=[r for r in requirements if 'smartphone' in r['evidence'].lower()]
 assert len(phone)==1 and 'Android' in phone[0]['evidence'] and 'iOS' in phone[0]['evidence']

@pytest.mark.skipif(__import__('os').environ.get('AUTOJOB_TEST_BRAVE')!='1',reason='Integración Brave separada')
def test_native_multiple_and_specific_consent_local_fixture(tmp_path):
 from autojob.browser import BraveSession
 from autojob.config import Settings
 from autojob.forms.submissions import GUARD_SCRIPT
 with BraveSession(Settings(tmp_path)) as browser:
  html='''<html><body><form><div><select id="question_7859687101" name="question_7859687101[]" multiple style="display:none"><option value="a">14.00 CET/CEST</option><option value="b">15.00 CET/CEST</option></select><div class="ms-options-wrap"><button onclick="event.preventDefault();this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">Select options</button><div class="ms-options" style="display:none"><label><input type="checkbox" value="a" onchange="document.querySelector('option[value=a]').selected=this.checked">14.00 CET/CEST</label><label><input type="checkbox" value="b" onchange="document.querySelector('option[value=b]').selected=this.checked">15.00 CET/CEST</label></div></div></div><input type="checkbox" id="disabledFieldsetCheck" name="data_compliance[gdpr_processing_consent_given]" style="pointer-events:none"><label for="disabledFieldsetCheck">Privacy processing notice</label></form></body></html>'''
  requests=[]
  def route(r):
   requests.append(r.request.method)
   if r.request.method=='GET':r.fulfill(status=200,content_type='text/html',body=html)
   else:r.abort()
  browser.context.route('**/*',route);browser.context.add_init_script(GUARD_SCRIPT);page=browser.new_page();page.goto(fiveca.TARGET)
  e=dict(selector='#question_7859687101',public_field_name='question_7859687101[]',status='CONFIRMADA',answer='14.00 CET/CEST',options=[dict(label='14.00 CET/CEST',value='a'),dict(label='15.00 CET/CEST',value='b')])
  assert fiveca.fill_multiple(page,e)['status']=='VERIFICADO'
  e=dict(label=fiveca.PROCESSING,kind='checkbox',selector='#disabledFieldsetCheck')
  assert fiveca.fill_consent(page,e,{})['status']=='PENDIENTE';assert not page.locator('#disabledFieldsetCheck').is_checked()
  assert fiveca.fill_consent(page,e,dict(specific_consents=fiveca.consents()))['status']=='VERIFICADO'
  assert all(method=='GET' for method in requests)

def test_confirmed_multiple_answers_reused_without_empty_group_prefix(tmp_path):
 from autojob.forms.answers9b import ScopedAnswers
 p=Preparation(tmp_path);d=fiveca.enrich_document(document(),schema());ctx=dict(job_id='fixture5ca',company='5CA',modality='remote')
 for field in d['fields']:
  if field.get('semantic') in {'shifts_5ca','days_5ca'}:ScopedAnswers(tmp_path).save(field['label'],field['options'][0]['label'],'multiple','job',ctx,True,[o['label'] for o in field['options']])
 entries=p.prepare(d,dict(id='fixture5ca',company='5CA',modality='remote'))['entries']
 assert all(e['status']=='CONFIRMADA' for e in entries if e.get('semantic') in {'shifts_5ca','days_5ca'})
