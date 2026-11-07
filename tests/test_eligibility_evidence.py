from copy import deepcopy
import pytest
from autojob.matching.engine import evaluate,DEFAULT

def profile():
    return dict(values=dict(skills=['Customer Service','CRM','Microsoft Excel','Email Support','Communication Skills'],soft_skills=['Fast Learner'],languages=['English C1'],experience_records=['Example Hotel | Customer Service Agent | 2021 | 2025 | Follow established procedures and daily checklists; escalation to manager; clear bilingual support.']),manual=['skills','soft_skills','languages','experience_records'],conflicts={},_application_data={k:dict(value=True,confirmed=True) for k in ['own_computer','stable_internet','private_workspace']} | {'accepted_shifts':dict(value='Puedo adaptarme a cualquier horario laboral requerido, cualquier día.',confirmed=True)})

def job(text):return dict(id='local-evidence',company='Example',title='Customer Service Representative',url='https://example.invalid/job/123',description='Requirements:\n'+text,geography='CONFIRMADO',location='Costa Rica',modality='remote',availability='ABIERTA')
def result(text,p=None):return evaluate(job(text),p or profile(),[],deepcopy(DEFAULT),dict(resume_id='cv',confirmed=True,language='en'))

@pytest.mark.parametrize('text',['Experience providing customer support.','Background in customer service.','Previous experience assisting clients.','Experience handling customer inquiries.','Experiencia en servicio al cliente.'])
def test_customer_experience_synonyms_have_employment_evidence(text):
    a=next(a for a in result(text)['assessments'] if a['kind']=='experience');assert a['state']=='CUMPLE' and a['profile_evidence']
@pytest.mark.parametrize('text',['Comfortable using online tools.','Reliable computer and internet connection.','Disponibilidad para horarios flexibles.','Reliable internet connection and a quiet workspace suitable for customer calls.','Ability to work consistently from 9:00 AM to 5:00 PM U.S. Eastern Time.'])
def test_confirmed_additional_and_capabilities(text):
    e=result(text);assert e['mandatory_status']=='CUMPLE';assert all(a['profile_evidence'] for a in e['assessments'] if a['state']=='CUMPLE')
def test_specific_platform_not_inferred_from_generic_tools():
    e=result('Experience with Salesforce required.');assert e['mandatory_status']!='CUMPLE';assert next(a for a in e['assessments'] if a['name']=='salesforce')['state']=='POR VERIFICAR'
def test_technical_experience_not_general_customer_service():
    assert next(a for a in result('Experience providing technical customer support required.')['assessments'] if a['kind']=='experience')['state']!='CUMPLE'
def test_projects_not_counted_as_employment():
    p=profile();p['values']['experience_records']=[];cv=dict(id='cv',reviewed=True,fields={},structure=dict(academic_projects=[dict(name='Customer Service app',description='Customer support',kind='academic')]))
    e=evaluate(job('Experience providing customer support.'),p,[cv],deepcopy(DEFAULT),dict(resume_id='cv',confirmed=True));assert next(a for a in e['assessments'] if a['kind']=='experience')['state']!='CUMPLE'
def test_c1_does_not_prove_other_language_or_completed_degree():
    assert result('French C1 required.')['mandatory_status']!='CUMPLE'
    p=profile();p['values']['education_records']=['Engineering degree in progress'];p['manual'].append('education_records');assert result('Completed bachelor degree required.',p)['mandatory_status']!='CUMPLE'
def test_conflicting_equipment_and_restricted_schedule():
    p=profile();p['_eligibility_answers']=[dict(id='yes',question='Do you have a stable internet connection?',value='Yes',confirmed=True,scope='personal')];p['_application_data']['stable_internet']['value']=False;assert result('Reliable internet connection.',p)['mandatory_status']=='POR VERIFICAR'
    p=profile();p['values']['schedule']='Only weekdays';p['manual'].append('schedule');assert result('Availability for flexible schedules.',p)['mandatory_status']=='POR VERIFICAR'
def test_preferred_unknown_does_not_lower_gate_and_absent_education_not_zero():
    e=result('Experience providing customer support.\nPreferred qualifications:\nFrench C2\nSalesforce');assert e['eligibility']=='COMPATIBLE' and e['score']==100;assert e['desirable_unverified']
def test_exact_approved_answer_is_scoped_and_conflicts_are_retained():
    p=profile();p['_eligibility_answers']=[dict(id='a',question='Knowledge of local products.',value='Yes',confirmed=True,scope='job',scope_key='local-evidence',conditions={'modality':'remote','position':None})]
    e=result('Knowledge of local products.',p);assert e['mandatory_status']=='CUMPLE';assert all(a['profile_evidence'] for a in e['assessments'] if a['state']=='CUMPLE')
    p['_eligibility_answers'][0]['scope_key']='other';assert result('Knowledge of local products.',p)['mandatory_status']=='POR VERIFICAR'
    p['_eligibility_answers'][0]['scope_key']='local-evidence';p['_eligibility_answers'].append(dict(p['_eligibility_answers'][0],id='b',value='No'));assert result('Knowledge of local products.',p)['mandatory_status']=='POR VERIFICAR'


def test_languages_alone_cannot_authorize_unrelated_profession():
    j=job('English C1 required.');j['title']='Country Manager'
    e=evaluate(j,profile(),[],deepcopy(DEFAULT),dict(resume_id='cv',confirmed=True))
    assert e['eligibility']!='COMPATIBLE' and e['score']<100


def test_new_eligible_candidate_appears_en_cola(tmp_path,qt_application_lifetime,await_ui):
    from test_redesign import seed
    from autojob.config import Settings
    from autojob.forms.queue import PreparationQueue
    from autojob.ui.main_window import MainWindow
    store,cv=seed(tmp_path);id=store.prep.compatibility.jobs.list()[0]['id'];PreparationQueue(store.data_path).add([id])
    w=MainWindow(Settings(tmp_path));await_ui(lambda:not w._ui_tasks,30000);w.shell.posts.refresh()
    n=next(n for n,r in enumerate(w.shell.posts.rows) if r['job']['id']==id)
    assert w.shell.posts.table.item(n,3).text()=='EN COLA';w.close()


def test_negative_crm_and_weekend_conflicts_not_overridden():
    p=profile();p['values']['skills']=['No CRM','Email Support','Excel','Customer Service']
    assert result('Familiarity with customer management systems, email, and spreadsheets.',p)['mandatory_status']!='CUMPLE'
    p=profile();p['_application_data']['weekends']=dict(value=False,confirmed=True)
    assert result('Weekends required.',p)['mandatory_status']!='CUMPLE'


def test_hyphenated_preferred_and_must_have_sections():
    e=result('Must have:\nExperience providing customer support.\nNice-to-have:\nSalesforce\nFrench C2')
    assert e['mandatory_status']=='CUMPLE' and e['eligibility']=='COMPATIBLE'
    assert all(a['importance']=='DESEABLE' for a in e['assessments'] if a['name'] in {'salesforce','French'})


def test_generic_english_yes_cannot_attest_explicit_c2():
    p=profile();p['_eligibility_answers']=[dict(id='generic',question='English proficiency required.',value='Yes',scope='personal',confirmed=True)]
    e=result('English proficiency C2 required.',p)
    assert next(a for a in e['assessments'] if a['kind']=='language')['state']=='NO CUMPLE'
