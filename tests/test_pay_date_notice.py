import json
from datetime import datetime,timezone
from urllib.request import urlopen
import pytest
from autojob.config import Settings
from autojob.profile.application_data import ApplicationData
from autojob.notice_media import NoticeMedia,video_id,video_html

@pytest.mark.parametrize('instant,expected',[('2026-11-07T01:00:00+00:00','2026-11-07'),('2026-12-31T20:00:00+00:00','2027-01-01'),('2028-02-28T20:00:00+00:00','2028-02-29')])
def test_next_day_costa_rica(tmp_path,monkeypatch,instant,expected):
 import autojob.profile.application_data as module
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None):return datetime.fromisoformat(instant).astimezone(tz)
 monkeypatch.setattr(module,'datetime',Clock)
 data=ApplicationData(tmp_path/'data');data.save({'start_next_day':True},confirmed=['start_next_day'])
 assert data.value('start_date')==(expected,'DERIVADA')
 assert ApplicationData(tmp_path/'other').value('start_date')[0] is None


def test_real_bamboo_labels_plan_pay_date_and_customer_cv(tmp_path):
 from test_batch_https import seed
 from docx import Document
 from autojob.extension_fill import ExtensionFill
 store,_=seed(tmp_path);library=store.prep.compatibility.library
 path=tmp_path/'Customer-Service.docx';doc=Document();doc.add_paragraph('Customer Service CV. English. Customer Support.');doc.save(path)
 cv=library.import_document(path);library.update(cv['id'],title='Customer Service',language='en',specialty='customer_service',fields=cv['fields'],reviewed=True,expected_revision=cv['revision'])
 store.prep.compatibility.jobs.add(dict(source='FICTIONAL',source_id='cs',company='Example',title='Customer Service Representative',url='https://jobs.lever.co/example/123',description='Customer service. Remote worldwide. Answer customer inquiries in English.',geography='CONFIRMADO',modality='remote',location='Worldwide',availability='ABIERTA'))
 store.prep.compatibility.batch();job=next(j for j in store.prep.compatibility.jobs.list() if j['source_id']=='cs')
 data=store.prep.data;data.save(dict(main_min='800',main_max='1700',main_currency='USD',main_period='month',start_next_day=True),confirmed=['main_min','main_max','main_currency','main_period','start_next_day'])
 bridge=ExtensionFill(Settings(tmp_path));task=dict(id='t',job=job,url=job['url'],state='FILLING',rounds=0)
 fields=[]
 for selector,label,kind,required in [('#name','First Name','text',True),('#email','Email','email',True),('#date','Date Available','text',False),('#pay','Desired Pay','text',True),('#cv','Resume / CV','file',True)]:
  fields.append(dict(id=selector,selector=selector,label=label,kind=kind,tag='input',required=required,disabled=False,options=[],group='',name='',placeholder='mm/dd/yyyy' if selector=='#date' else '',accept='.pdf,.docx',button_text=''))
 payload=dict(url=job['url'],scan=dict(title='Example — Customer Service Representative',fields=fields,text='Apply for a job',frames=[],password=False,captcha=dict(present=False,solved=False,pending=False)))
 plan=bridge.plan(task,payload);entries={e['selector']:e for e in plan['entries']}
 assert entries['#pay']['answer']=='USD 800–1700 per month'
 expected=datetime.fromisoformat(data.value('start_date')[0]).strftime('%m/%d/%Y')
 assert entries['#date']['answer']==expected
 assert entries['#cv']['file']['name']=='Customer-Service.docx'
 import base64
 assert base64.b64decode(entries['#cv']['file']['data'])==path.read_bytes()
 fields[-1]['has_value']=True
 assert '#cv' not in {e['selector'] for e in bridge.plan(task,payload)['entries']}


def test_video_preference_local_and_optional(tmp_path):
 s=NoticeMedia(tmp_path);assert s.load()==dict(enabled=False,sound=False,url='')
 s.save('https://www.youtube.com/watch?v=ExampleID01',True)
 assert NoticeMedia(tmp_path).load()['enabled']
 assert NoticeMedia(tmp_path/'other').load()['enabled'] is False
 s.save('',False);assert s.load()['enabled'] is False
 assert video_id('https://youtu.be/ExampleID01')=='ExampleID01'
 assert 'mute=0' in video_html('ExampleID01',sound=True)
 assert 'youtube-nocookie.com/embed/ExampleID01' in video_html('ExampleID01')
 for bad in ('https://youtube.com.evil.test/watch?v=ExampleID01','javascript:alert(1)','http://youtube.com/watch?v=ExampleID01'):
  with pytest.raises(ValueError):video_id(bad)


def test_video_page_contains_no_candidate_data(tmp_path,monkeypatch):
 import autojob.extension_fill as module
 monkeypatch.setattr(module,'PORT',0)
 s=Settings(tmp_path);s.data_path.mkdir();bridge=module.ExtensionFill(s);bridge.start()
 try:
  html=urlopen(f'http://127.0.0.1:{bridge.server.server_port}/notice-video/ExampleID01').read().decode()
  assert 'iframe' in html and 'mute=1' in html and 'loop=1' in html
 finally:bridge.close()
