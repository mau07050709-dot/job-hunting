from copy import deepcopy
from pathlib import Path
import pytest
from autojob.matching.engine import extract,evaluate,assess,candidate,DEFAULT
from autojob.forms.greenhouse import enrich_document
from autojob.profile.store import empty


def profile():
 v=empty();v.update(languages=['English C1','Spanish Native'],country='Costa Rica',work_authorization=True)
 return dict(values=v,manual=['languages','country','work_authorization'],sources={})


def job(description):return dict(id='fixture9c',company='Fictional',title='Customer Support',url='https://example.invalid/job',description=description,raw=dict(description=description),modality='remote',location='Costa Rica',geography='CONFIRMADO',availability='ABIERTA')


def test_escaped_html_and_unicode_requirement_heading():
 j=job('&lt;p&gt;𝗪𝗵𝗮𝘁 𝗦𝗲𝘁𝘀 𝗬𝗼𝘂 𝗨𝗽 𝗳𝗼𝗿 𝗦𝘂𝗰𝗰𝗲𝘀𝘀:&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Excellent internet/wifi connection&lt;/li&gt;&lt;li&gt;#LI-DL1&lt;/li&gt;&lt;/ul&gt;')
 reqs=extract(j,DEFAULT);assert any(r['evidence']=='Excellent internet/wifi connection' and r['importance']=='OBLIGATORIO' for r in reqs);assert not any('#LI-' in r['evidence'] for r in reqs)


def test_spanish_portuguese_alternative_does_not_invent_portuguese():
 j=job('Requirements:\nNative or fluent in English and Spanish and/or Portuguese');person=candidate(profile(),[]);reqs=extract(j,DEFAULT)
 evaluated=[assess(r,person,DEFAULT,j) for r in reqs];assert all(r['state']=='CUMPLE' for r in evaluated);assert not any(r['name']=='Portuguese' for r in evaluated);assert 'Portuguese' not in str(profile()['values']['languages'])


def test_explicit_c2_still_rejects_c1():
 j=job('Requirements:\nEnglish C2 required');r=next(r for r in extract(j,DEFAULT) if r['kind']=='language');assert assess(r,candidate(profile(),[]),DEFAULT,j)['state']=='NO CUMPLE'


def test_b2_fluency_unknown_is_not_false_incompatibility():
 p=profile();p['values']['languages']=['English B2+'];j=job('Requirements:\nFluent English');r=next(r for r in extract(j,DEFAULT) if r['kind']=='language');assert assess(r,candidate(p,[]),DEFAULT,j)['state']=='POR VERIFICAR'


def test_public_schema_removes_only_internal_duplicate_input():
 native=dict(fields=[dict(label='First Name*',kind='text',selector='#first',required=True),dict(label='Sin etiqueta',kind='text',selector='#internal',required=True),dict(label='Submit application',kind='button',selector='#submit',action='ENVÍO FINAL')],obstacles=[])
 data=dict(questions=[dict(label='First Name',required=True,fields=[dict(name='first_name',type='input_text',values=[])])]);result=enrich_document(native,data);assert [f['selector'] for f in result['fields']]==['#first','#submit']


def test_missing_published_required_field_blocks_schema():
 native=dict(fields=[],obstacles=[]);data=dict(questions=[dict(label='First Name',required=True,fields=[dict(name='first_name',type='input_text',values=[])])]);assert enrich_document(native,data)['obstacles'][0]['type']=='FORMULARIO CAMBIADO'


def test_phone_call_skill_uses_confirmed_answer_not_phone_number(tmp_path):
 from autojob.forms.preparation import Preparation
 from autojob.forms.answers9b import ScopedAnswers
 p=Preparation(tmp_path);s=p.data.profile.load();s['values']['phone']='+50688887777';p.data.profile.save(s['values'],s['revision'],confirmed=['phone']);q='Are you confident handling a live phone call in English with an upset customer, in real time?';ctx=dict(job_id='fixture',company='Fictional',modality='remote');ScopedAnswers(tmp_path).save(q,'Yes','select','job',ctx,True,['Yes','No']);assert p.resolve(q,ctx)['answer']=='Yes'


def test_computer_video_capability_is_not_video_interview(tmp_path):
 from autojob.forms.preparation import Preparation
 p=Preparation(tmp_path);doc=dict(url='https://example.invalid',title='Fictional',obstacles=[],fields=[dict(label='Do you have access to your own computer with video/audio capabilities for conferencing?',selector='#pc',kind='select',tag='select',required=True,options=[dict(label='Yes',value='1'),dict(label='No',value='0')])]);entry=p.prepare(doc)['entries'][0];assert entry['status']=='DESCONOCIDA';assert entry['status']!='BLOQUEADA'


def test_confirmed_matching_country_reused_over_unreviewed_copy(tmp_path):
 from autojob.forms.preparation import Preparation
 p=Preparation(tmp_path);s=p.data.profile.load();s['values']['country']='Costa Rica';p.data.profile.save(s['values'],s['revision'],confirmed=['country']);p.data.save(dict(country='Costa Rica'),confirmed=[]);assert p.resolve('Country of residence')['status']=='CONFIRMADA'
