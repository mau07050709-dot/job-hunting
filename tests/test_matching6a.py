from copy import deepcopy
from datetime import datetime,timezone
import json
import pytest
from autojob.matching.engine import DEFAULT,evaluate,extract,concepts,candidate,assess
from autojob.matching.service import Compatibility,export,report
from autojob.profile.store import empty

def profile(**values):return dict(values=dict(empty(),**values),manual=list(values),sources={},conflicts={},revision=1)
def job(description='Requirements:\nPython required.\nMinimum 2 years of software development experience.\nCompleted bachelor degree required.\nEnglish B2 required.',**kwargs):return dict(dict(id='job1',title='Junior Python Developer',company='Example',description=description,url='https://example.invalid/jobs/1',source='Test',source_id='1',location='Worldwide',modality='remote',geography='CONFIRMADO',availability='ABIERTA'),**kwargs)
def req(kind,name,**kwargs):return dict(kind=kind,name=name,importance='OBLIGATORIO',evidence='Required '+name,source='https://example.invalid',**kwargs)
def judge(requirement,p):return assess(requirement,candidate(p,[]),deepcopy(DEFAULT),job())

def test_requirements_evidence_and_priority():
 rows=extract(job('Requirements:\nPython required.\nEnglish C1 required.\nNice to have:\nDjango preferred.'),DEFAULT)
 assert any(r['name']=='python' and r['importance']=='OBLIGATORIO' for r in rows)
 assert any(r['name']=='django' and r['importance']=='DESEABLE' for r in rows)
 assert all(r['evidence'] and r['source'] for r in rows)
 assert next(r for r in rows if r['name']=='English')['level']==5

@pytest.mark.parametrize('text,concept',[('Atención al cliente','customer_service'),('Help Desk','it_support'),('Python Development','python'),('Habilidades de comunicación','communication'),('Quality Assurance','qa')])
def test_equivalences(text,concept):assert concept in concepts(text,DEFAULT)

def test_no_wrong_equivalences():
 assert 'django' not in concepts('Python',DEFAULT)
 assert 'software' not in concepts('Customer Service',DEFAULT)
 assert 'java' not in concepts('JavaScript',DEFAULT)

def test_unknown_not_absence():assert judge(req('skill','django'),profile(skills=['Python']))['state']=='POR VERIFICAR'
def test_confirmed_skill():assert judge(req('skill','customer_service'),profile(skills=['Atención al cliente']))['state']=='CUMPLE'
def test_unreviewed_skill():
 p=profile(skills=['Python']);p['manual']=[]
 assert judge(req('skill','python'),p)['state']=='POR VERIFICAR'
def test_incomplete_degree():assert judge(req('education','degree'),profile(degree='Engineering',academic_status='in progress'))['state']=='NO CUMPLE'
def test_equivalent_experience_alternative():assert judge(req('education','degree',alternative=True),profile(academic_status='in progress'))['state']=='POR VERIFICAR'
def test_completed_secondary_not_completed_degree():assert judge(req('education','degree'),profile(education_records=['High school | completed','Bachelor Engineering | in progress']))['state']!='CUMPLE'
def test_degree_obtained():assert judge(req('education','degree'),profile(qualifications=['Bachelor of Engineering']))['state']=='CUMPLE'
def test_students():assert judge(req('education','student'),profile(academic_status='Estudiante en curso'))['state']=='CUMPLE'

@pytest.mark.parametrize('required,state',[(3,'CUMPLE'),(4,'CUMPLE'),(5,'NO CUMPLE')])
def test_language_levels(required,state):assert judge(req('language','English',level=required),profile(languages=['English B2']))['state']==state
def test_certificate_not_inferred():assert judge(req('certification','CCNA'),profile(skills=['Networking']))['state']=='POR VERIFICAR'
def test_projects_not_professional():
 p=profile();cv={'id':'cv','reviewed':True,'fields':{},'structure':{'academic_projects':[dict(name='Python project',description='Software development 2018-2026',start_date='2018',end_date='2026')]}}
 assert assess(req('experience','professional_years',years=3,domain='programming'),candidate(p,[cv]),DEFAULT,job())['state']=='POR VERIFICAR'
def test_insufficient_professional_experience():assert judge(req('experience','professional_years',years=5,domain='programming'),profile(experience_records=['Example | Software Developer | 2024-01-01 | 2025-01-01 | Python']))['state']=='NO CUMPLE'
def test_experience_unrelated():assert judge(req('experience','professional_years',years=2,domain='programming'),profile(experience_records=['Example | Customer Service | 2018 | 2025 | Help customers']))['state']=='POR VERIFICAR'
def test_no_duplicate_experience():
 p=profile(experience_records=['Example | Software Developer | 2024 | 2025 | Python']);cv={'id':'cv','reviewed':True,'fields':{},'structure':{'experience':[dict(company='Example',position='Software Developer',start_date='2024',end_date='2025',description='Python')]}}
 assert len(candidate(p,[cv])['buckets']['experience'])==1

@pytest.mark.parametrize('location,modality,geo,expected',[('US Only','remote','CONFIRMADO','INCOMPATIBLE'),('Heredia, Costa Rica','hybrid','INCOMPATIBLE','INCOMPATIBLE'),('Cartago, Colombia','onsite','CONFIRMADO','INCOMPATIBLE'),('Cartago, Costa Rica','onsite','CONFIRMADO','REQUIERE REVISIÓN'),('Remote','remote','POSIBLE','REQUIERE REVISIÓN')])
def test_geography(location,modality,geo,expected):assert evaluate(job(location=location,modality=modality,geography=geo),profile(),[],DEFAULT)['eligibility']==expected
def test_score_and_confidence_unknown():
 r=evaluate(job('An opportunity with an interesting team. Responsibilities will be discussed.'),profile(),[],DEFAULT)
 assert r['score']<=10 and r['confidence']<=10 and r['eligibility']=='REQUIERE REVISIÓN'
 assert r['automatic_authorized'] is False
def test_obligatory_block_overrides_score():
 p=profile(skills=['Python'],languages=['English B2'],academic_status='in progress',degree='Bachelor of Engineering',experience_records=['Example | Software Developer | 2015-01-01 | 2025-01-01 | Python'])
 r=evaluate(job(),p,[],DEFAULT,dict(resume_id='cv',reason='Fixture'))
 assert r['eligibility']=='INCOMPATIBLE' and r['mandatory_status']=='NO CUMPLE'
def test_manual_empty_protected():
 p=profile(skills=[]);cv={'id':'cv','reviewed':True,'fields':{'technical_skills':['Python']},'structure':{}}
 assert assess(req('skill','python'),candidate(p,[cv]),DEFAULT,job())['state']=='POR VERIFICAR'
def test_schedule_contradiction():assert judge(req('schedule','availability'),profile(schedule='No nights'))['state']=='NO CUMPLE'

def populated(tmp_path):
 service=Compatibility(tmp_path);service.jobs.add(job());return service
def test_persistence_and_staleness(tmp_path):
 service=populated(tmp_path);r=service.batch();assert r['evaluated']==1
 assert len(Compatibility(tmp_path).latest())==1
 stored=service.rows()[0];assert not stored['stale'] and service.batch()['cached']==1
 p=service.profile.load();p['values']['skills']=['Python'];service.profile.save(p['values'],p['revision'])
 assert service.rows()[0]['stale'];service.batch();assert len(service.history(stored['job']['id']))==2
def test_config_stale_and_validation(tmp_path):
 s=populated(tmp_path);s.batch();c=s.config();c['eligible_score']=70;s.save_config(c);assert s.rows()[0]['stale']
 c['weights']['skills']=40
 with pytest.raises(ValueError):s.save_config(c)
def test_job_change_stale(tmp_path):
 s=populated(tmp_path);s.batch();s.jobs.add(job(description='Python Developer. New description with different requirements.'))
 assert s.rows()[0]['stale']
def test_batch_cancel_resume_and_error_recovery(tmp_path,monkeypatch):
 s=populated(tmp_path);s.jobs.add(job(source_id='2',id='job2',url='https://example.invalid/jobs/2'))
 assert s.batch(cancel=lambda:True)['evaluated']==0
 old=s.one
 def fail(j,*args,**kwargs):
  if j['source_id']=='2':raise ValueError('Do not log personal details')
  return old(j,*args,**kwargs)
 monkeypatch.setattr(s,'one',fail);r=s.batch();assert r['evaluated']==1 and len(r['errors'])==1
 monkeypatch.setattr(s,'one',old);r=s.batch();assert r['evaluated']==2 and r['cached']==1
def test_report_export(tmp_path):
 s=populated(tmp_path);s.batch();r=s.rows()[0]['evaluation'];assert 'CONFIANZA' in report(r) and 'Oferta:' in report(r)
 export(s.rows(),tmp_path/'out.xlsx')
 from openpyxl import load_workbook
 assert load_workbook(tmp_path/'out.xlsx').active.max_row==2
def test_gui_and_cancel(tmp_path):
 import os;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from autojob.ui.compatibility_widget import CompatibilityWidget
 from autojob.config import Settings
 app=QApplication.instance() or QApplication([]);w=CompatibilityWidget(Settings(root=tmp_path));w.service.jobs.add(job());w.refresh();assert w.table.rowCount()==1
 w.service.batch();w.refresh();w.filter.setCurrentText('COMPATIBLE');assert w.table.rowCount()==0
 w.filter.setCurrentText('REQUIERE REVISIÓN');assert w.table.rowCount()==1;w.table.selectRow(0);w.details();assert 'COMPATIBILIDAD' in w.analysis.toPlainText();w.stop();assert w.allow_close();w.close();app.processEvents()

def test_positive_score_not_constant():
 p=profile(skills=['Python'],languages=['English B2'],qualifications=['Bachelor of Engineering'],experience_records=['Example | Software Developer | 2015-01-01 | 2025-01-01 | Python'],salary_min='1000',currency='USD')
 r=evaluate(job(schedule='Full-time',salary='2000 monthly',currency='USD'),p,[],DEFAULT,dict(resume_id='cv',language='en',reason='Reviewed fixture'))
 assert r['score']==100 and r['confidence']==100 and r['eligibility']=='COMPATIBLE'
 assert r['automatic_authorized'] is False

def test_require_and_preferred_separated():
 rows=extract(job('Requires high school diploma and minimum 2 years healthcare experience, preferred 3 years of medical billing experience.'),DEFAULT)
 assert next(r for r in rows if r['kind']=='education')['importance']=='OBLIGATORIO'
 assert any(r['kind']=='experience' and r['importance']=='DESEABLE' for r in rows)

def test_company_university_not_candidate_degree():
 assert not any(r['kind']=='education' for r in extract(job('University of Example Medicine is a company. We provide services for our customers.'),DEFAULT))

def test_original_html_preserves_sections():
 j=job('Unstructured fallback',raw={'description':'<h2>Requirements</h2><ul><li>Python required</li></ul><h2>Nice to have</h2><p>Django</p>'})
 rows=extract(j,DEFAULT)
 assert next(r for r in rows if r['name']=='python')['importance']=='OBLIGATORIO'
 assert next(r for r in rows if r['name']=='django')['importance']=='DESEABLE'

def test_cv_language_not_person_language():
 rows=extract(job('Requirements:\nSubmit your CV in English.'),DEFAULT)
 assert any(r['kind']=='document' for r in rows) and not any(r['kind']=='language' for r in rows)

def test_specific_experience_not_general_service():
 p=profile(experience_records=['Hotel | Customer Service | 2010 | 2025 | Help customers'])
 requirement=req('experience','professional_years',years=2,domain='customer_service',sector='healthcare')
 assert judge(requirement,p)['state']=='POR VERIFICAR'

def test_specific_technology_not_generic_software():
 p=profile(experience_records=['Example | Software Developer | 2010 | 2025 | Java development'])
 assert judge(req('experience','professional_years',years=2,domain='programming',technologies=['python']),p)['state']=='POR VERIFICAR'

def test_cv_selection_reuses_selector(tmp_path,monkeypatch):
 s=Compatibility(tmp_path)
 cvs=[dict(id='tech',title='Technical English',language='en',specialty='technical',reviewed=True,is_default=False,fields={'technical_skills':['Python']},structure={}),dict(id='service',title='Service English',language='en',specialty='customer_service',reviewed=True,is_default=False,fields={'technical_skills':['Customer Support']},structure={})]
 class Library:
  data_path=tmp_path
  def list(self):return cvs
  def original_path(self,id):return tmp_path/id
 s.library=Library();snap=dict(cvs=cvs,config=DEFAULT)
 assert s.selection(job(title='Customer Support Representative',description='Customer support with the skills and experience for the company.'),snap)['resume_id']=='service'
 assert s.selection(job(),snap)['resume_id']=='tech'
 cvs[1]['reviewed']=False
 # El rediseño separa el documento autorizado por INICIAR de la revisión de datos.
 assert s.selection(job(title='Customer Support Representative',description='Customer support for the company with experience.'),snap)['resume_id']=='service'
 assert cvs[1]['reviewed'] is False

def test_preferably_and_at_least():
 rows=extract(job('Requirements for the Python Position:\nAt least 2 years of software development experience.\nPreferably 3 years of customer service experience.'),DEFAULT)
 exp=[r for r in rows if r['kind']=='experience']
 assert exp[0]['importance']=='OBLIGATORIO' and exp[1]['importance']=='DESEABLE'

def test_unverified_insufficient_not_half_fulfilled():
 p=profile(experience_records=['Example | Software Developer | 2024 | 2025 | Python']);p['manual']=[]
 r=judge(req('experience','professional_years',years=10,domain='programming'),p)
 assert r['state']=='POR VERIFICAR' and r['support']==0

def test_confirmed_full_time_rejection():
 result=evaluate(job(schedule='Full-time'),profile(full_time=False),[],DEFAULT)
 assert result['eligibility']=='INCOMPATIBLE'

def test_empty_description_partial():
 r=evaluate(job(description=''),profile(),[],DEFAULT)
 assert r['eligibility']=='REQUIERE REVISIÓN' and any('esencial' in w for w in r['warnings'])

def test_education_discipline_not_invented():
 r=judge(req('education','degree',disciplines=['medicine']),profile(qualifications=['Bachelor of Engineering']))
 assert r['state']=='POR VERIFICAR'

def test_partial_batch_cancel_and_resume(tmp_path):
 s=populated(tmp_path);s.jobs.add(job(source_id='2',url='https://example.invalid/jobs/2'));seen=[]
 result=s.batch(cancel=lambda:len(seen)>=1,progress=seen.append)
 assert result['cancelled'] and result['evaluated']==1 and len(s.latest())==1
 resumed=s.batch();assert resumed['evaluated']==2 and resumed['cached']==1 and len(s.latest())==2

def test_custom_weights_percentage():
 config=deepcopy(DEFAULT);config['weights']={key:100 if key=='skills' else 0 for key in config['weights']}
 Compatibility.validate(config)
 r=evaluate(job('Requirements:\nPython required.\nDjango required.'),profile(skills=['Python']),[],config)
 assert r['score']==50 and r['confidence']==50 and r['eligibility']=='REQUIERE REVISIÓN'
