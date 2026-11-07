import pytest
from autojob.testing.simulation_4c import Simulator
from autojob.profile.answers import AnswerBank
from autojob.profile.store import ProfileStore

def test_custom_approval_persistence_and_sensitive_block(tmp_path):
 s=Simulator(tmp_path);r=s.run('Personalizado','Example','Developer',custom_fields=[('What is your full name?','text',True),('CAPTCHA','captcha',True),('Are you legally authorized to work?','text',True)])
 assert r['status']=='PENDIENTE' and 'CV' in r['blockers']
 r=s.update_answer(r['id'],0,'Synthetic Person',True)
 assert r['fields'][0]['status']=='LISTO'
 assert len(AnswerBank(tmp_path).all())==1
 assert Simulator(tmp_path).history()[0]['fields'][0]['answer']=='Synthetic Person'
 with pytest.raises(ValueError):s.update_answer(r['id'],1,'solved',True)
 with pytest.raises(ValueError):s.update_answer(r['id'],2,'yes',True)

def test_empty_custom_form_is_rejected(tmp_path):
 with pytest.raises(ValueError):Simulator(tmp_path).run('Personalizado','Example','Developer',custom_fields=[])

def test_choices_must_match_and_email_validated(tmp_path):
 s=Simulator(tmp_path);r=s.run('Personalizado','Example','Developer',custom_fields=[('Preferred mode','select',True,['Remote','Hybrid']),('Email','email',True,[])])
 with pytest.raises(ValueError):s.update_answer(r['id'],0,'Onsite',True)
 with pytest.raises(ValueError):s.update_answer(r['id'],1,'not-an-email',True)
 r=s.update_answer(r['id'],0,'Remote',True);assert r['fields'][0]['status']=='LISTO'

def test_changed_profile_invalidates_historical_answer(tmp_path):
 s=Simulator(tmp_path);r=s.run('Personalizado','Example','Developer',custom_fields=[('Full name','text',True)])
 s.update_answer(r['id'],0,'Persona Ejemplo',True)
 store=ProfileStore(tmp_path);state=store.load();state['values']['city']='Cartago';store.save(state['values'],state['revision'])
 historical=s.history()[0];assert historical['status']=='PENDIENTE' and historical['fields'][0]['status']=='REVISAR'
 with pytest.raises(ValueError):s.update_answer(r['id'],0,'Persona Ejemplo',True)

def test_changed_cv_invalidates_simulation(tmp_path):
 from autojob.resumes.service import ResumeLibrary
 from resume_fixtures import write_docx
 library=ResumeLibrary(tmp_path);item=library.import_document(write_docx(tmp_path/'cv.docx'))
 item=library.update(item['id'],title=item['title'],language='en',specialty='technical',fields=item['fields'],reviewed=True,expected_revision=item['revision'])
 s=Simulator(tmp_path);report=s.run('Personalizado','Example','Developer',language='en',specialty='technical',custom_fields=[('Full name','text',True)])
 assert report['cv']==item['id']
 library.update(item['id'],title='Título revisado',language='en',specialty='technical',fields=item['fields'],reviewed=True,expected_revision=item['revision'])
 assert s.history()[0]['status']=='PENDIENTE'
 with pytest.raises(ValueError):s.update_answer(report['id'],0,'Persona Ejemplo',True)

def test_experience_uses_selected_cv_without_inventing_exact_numeric_value(tmp_path):
 from autojob.resumes.service import ResumeLibrary
 from resume_fixtures import write_docx
 library=ResumeLibrary(tmp_path);item=library.import_document(write_docx(tmp_path/'cv.docx'))
 library.update(item['id'],title=item['title'],language='en',specialty='technical',fields=item['fields'],reviewed=True,expected_revision=item['revision'])
 result=Simulator(tmp_path).run('Personalizado','Example','Developer',language='en',specialty='technical',custom_fields=[('Years of experience','experience',True)])
 assert result['fields'][0]['answer'] and result['fields'][0]['status']=='REVISAR'
 assert not result['fields'][0]['automatic']

def test_projects_come_only_from_selected_cv(tmp_path):
 from autojob.resumes.service import ResumeLibrary
 from resume_fixtures import write_docx
 library=ResumeLibrary(tmp_path);item=library.import_document(write_docx(tmp_path/'cv.docx'))
 library.update(item['id'],title=item['title'],language='en',specialty='technical',fields=item['fields'],reviewed=True,expected_revision=item['revision'])
 result=Simulator(tmp_path).run('Junior Software Developer','Example','Developer',language='en',specialty='technical')
 project=next(field for field in result['fields'] if field['question']=='Academic projects')
 assert project['status']=='REVISAR' and 'Arduino' in project['answer']
