from types import SimpleNamespace
from hashlib import sha256
import json
import pytest
from autojob.forms.greenhouse import CloudbedsProtocol,TARGET,SUBMIT,UPLOAD,PROCESSORS,enrich_document

def protocol():return CloudbedsProtocol(dict(url=TARGET,processor_origins=PROCESSORS,cv_hash=sha256(b'FAKE CV').hexdigest()),lambda:None)
def upload(content=b'FAKE CV',key='resume/fictional.pdf'):
    body=b'--test\r\nContent-Disposition: form-data; name="key"\r\n\r\n'+key.encode()+b'\r\n--test\r\nContent-Disposition: form-data; name="file"; filename="fictional.pdf"\r\nContent-Type: application/pdf\r\n\r\n'+content+b'\r\n--test--\r\n'
    return SimpleNamespace(url=UPLOAD,method='POST',headers={'content-type':'multipart/form-data; boundary=test'},post_data_buffer=body)
def final(p,**extra):return SimpleNamespace(url=SUBMIT,method='POST',post_data=json.dumps(dict(job_application=dict(resume_url=p.resume_url,**extra))))
def ready():
    p=protocol();p.upload_phase=True;assert p.write(upload(),False);p.response(SimpleNamespace(url=UPLOAD,status=201,request=SimpleNamespace(method='POST')));p.upload_phase=False;return p
def test_processor_scope_required():
    with pytest.raises(ValueError):CloudbedsProtocol(dict(url=TARGET,cv_hash='none'),lambda:None)
def test_cv_only_authorized_bytes_and_upload_phase():
    p=protocol();assert not p.write(upload(),False);p.upload_phase=True;assert not p.write(upload(b'OTHER CV'),False);assert p.write(upload(),False);assert not p.write(upload(),False)
def test_upload_response_required_for_submission():
    p=protocol();p.upload_phase=True;assert p.write(upload(),False);assert not p.write(final(p),True)
def test_one_native_submission_only_after_upload():
    p=ready();assert not p.write(final(p),False);assert p.write(final(p),True);assert not p.write(final(p),True)
@pytest.mark.parametrize('extra',[dict(cover_letter_url='extra'),dict(attachments=['extra']),dict(consent=True),dict(signature='x'),dict(national_id='x'),dict(data_compliance=dict(gdpr_consent=True))])
def test_additional_documents_and_consents_rejected(extra):
    p=ready();assert not p.write(final(p,**extra),True)
def test_different_endpoint_or_resume_rejected():
    p=ready();r=final(p);r.url=SUBMIT+'1';assert not p.write(r,True);r=final(p);r.post_data=json.dumps(dict(job_application=dict(resume_url=UPLOAD+'/other.pdf')));assert not p.write(r,True)
def test_failed_upload_cannot_submit():
    p=ready();p.response(SimpleNamespace(url=UPLOAD,status=403,request=SimpleNamespace(method='POST')));assert not p.write(final(p),True)
def test_demographic_uses_only_explicit_decline_option():
    q=dict(id=1,label='Gender',required=True,type='select',answer_options=[dict(id=2,label='Option'),dict(id=3,label="I don't wish to answer",decline_to_answer=True)])
    native=dict(fields=[dict(label='Gender',kind='combobox',selector='#gender')],obstacles=[])
    d=enrich_document(native,dict(questions=[],demographic_questions=dict(questions=[q])));assert d['fields'][0]['semantic']=='demographic_decline';assert d['fields'][0]['decline_option']=="I don't wish to answer"
    q['answer_options'][1].pop('decline_to_answer');d=enrich_document(dict(fields=[dict(label='Gender',kind='combobox',selector='#gender')],obstacles=[]),dict(questions=[],demographic_questions=dict(questions=[q])));assert 'semantic' not in d['fields'][0]
def test_known_equipment_derived_without_reasking(tmp_path):
    from autojob.forms.preparation import Preparation
    p=Preparation(tmp_path);p.data.save(dict(own_computer=True,webcam=True,microphone=True),confirmed=['own_computer','webcam','microphone']);r=p.resolve('Do you have access to your own computer with video/audio capabilities for conferencing?');assert r['answer']=='Yes';assert r['status']=='DERIVADA'
