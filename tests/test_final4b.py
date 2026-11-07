from datetime import date
from copy import deepcopy
import pytest
from autojob.profile.experience import calculate_experience
from autojob.profile.answers import resolve_question,AnswerBank
from autojob.profile.store import ProfileStore
from autojob.profile.templates import TemplateStore

def job(start,end,**kw):return dict(start_date=start,end_date=end,position='Developer',**kw)
def test_overlap():
 records=[job('2020-01-01','2020-12-31'),job('2020-06-01','2021-05-31')]
 result=calculate_experience(records,today=date(2022,1,1));assert result['status']=='exact';assert result['minimum']['days']==517
def test_partial_year():
 result=calculate_experience([job('2020','2021')],today=date(2023,1,1));assert result['status']=='range';assert result['minimum']['days']<result['maximum']['days']
def test_partial_month():
 result=calculate_experience([job('2020-01','2020-03')],today=date(2023,1,1));assert result['status']=='range';assert result['maximum']['days']==91
def test_unknown_and_projects():
 assert calculate_experience([job(None,'2020')])['status']=='unknown'
 assert calculate_experience([job('2020','2021',kind='academic_project')])['status']=='unknown'
def test_category():
 result=calculate_experience([job('2020-01-01','2020-12-31'),dict(start_date='2021-01-01',end_date='2021-12-31',position='Customer Support')],category='customer_service',today=date(2023,1,1));assert result['minimum']['days']==365
@pytest.fixture
def state(tmp_path):
 store=ProfileStore(tmp_path);p=store.load();v=deepcopy(p['values']);v.update(full_name='Test Person',skills=['Python'],soft_skills=['Communication'],experience_records=['Developer | Example | Built tools','Customer Service | Support Company | Resolved requests'])
 return store.save(v,p['revision']),AnswerBank(tmp_path),TemplateStore(tmp_path)
@pytest.mark.parametrize('question,language',[('Tell me about yourself','en'),('Háblame de ti','es'),('Why should we hire you?','en'),('¿Por qué deberíamos contratarte?','es'),('Describe your customer service experience','en')])
def test_templates(state,question,language):
 p,bank,templates=state;r=resolve_question(question,{'language':language},p,bank);assert r.answer and not r.automatic and r.category=='SUGERIDA'
def test_context_and_categories(state):
 p,bank,t=state
 r=resolve_question('Why do you want to work here?',{'language':'en','company':'Example','position':'Developer','job_category':'technical'},p,bank);assert 'Example' in r.answer and 'Developer' in r.answer
 r=resolve_question('Describe your professional experience',{'language':'en','job_category':'customer_service'},p,bank);assert 'Built tools' not in r.answer
def test_challenge_unknown(state):
 p,b,t=state;assert resolve_question('Describe a challenging situation at work',{'language':'en'},p,b).answer is None
def test_template_persistence(state,tmp_path):
 p,b,t=state;key=t.save('technical','es','Habilidades: {skills}');other=TemplateStore(tmp_path);assert other.render('technical','es',{'skills':'Python'},key)[0]=='Habilidades: Python'
 with pytest.raises(ValueError):t.save('technical','es','{skills.__class__}')
def test_salary_and_authorization(state):
 p,b,t=state
 a=resolve_question('Are you legally authorized to work in the United States?',{},p,b)
 c=resolve_question('Are you legally authorized to work in Costa Rica?',{},p,b)
 assert a.field!=c.field and not a.automatic and not c.automatic
 assert resolve_question('Hourly salary?',{},p,b).answer is None
def test_name_ambiguity(state):
 p,b,t=state;assert resolve_question('First name and last name',{},p,b).category=='DESCONOCIDA'
def test_approved_priority(state):
 p,b,t=state;b.save('Motivación','en',['Why do you want to work here?'],'Approved by user',True,p)
 assert resolve_question('Why do you want to work here?',{'language':'en'},p,b).answer=='Approved by user'

def test_ambiguous_salary_and_contextual_approval(state):
 p,b,t=state
 assert resolve_question('Monthly or annual salary?',{},p,b).category=='DESCONOCIDA'
 b.save('Motivación','en',['Why do you want to work here?'],'Approved for a different vacancy',True,p)
 assert not resolve_question('Why do you want to work here?',{'language':'en','company':'Another employer'},p,b).automatic

def test_pure_api_templates_without_database(state):
 p,b,t=state
 assert resolve_question('What technical skills do you have?',{'language':'en'},p).answer=='Python.'
