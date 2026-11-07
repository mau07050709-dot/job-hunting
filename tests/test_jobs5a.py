import pytest
from autojob.search.jobs import Connector,JobStore,canonical,geography

@pytest.mark.parametrize('location,expected',[('Worldwide','POSIBLE'),('Latin America','CONFIRMADO'),('Costa Rica','CONFIRMADO'),('United States','INCOMPATIBLE'),('Remote','POSIBLE')])
# Worldwide sin países ni condiciones explícitas no confirma contratación desde CR.
def test_geo(location,expected):assert geography(location,'')[0]==expected
def test_onsite_cartago():
 assert geography('Cartago, Costa Rica','',False)[0]=='CONFIRMADO'
 assert geography('Cartago, Colombia','',False)[0]=='INCOMPATIBLE'
def test_canonical():assert canonical('https://example.invalid/jobs/1/?utm_source=x#top')=='https://example.invalid/jobs/1'
def test_parse_and_persist(tmp_path):
 payload={'jobs':[dict(id=1,title='Python Developer',company_name='Example',url='https://example.invalid/jobs/1',candidate_required_location='Worldwide',description='<p>Python skills</p>')]}
 jobs=list(Connector('Remotive').search_jobs(['Python'],payload=payload));assert len(jobs)==1 and jobs[0]['company']=='Example'
 store=JobStore(tmp_path);assert store.add(jobs[0]);assert not store.add(jobs[0]);assert len(JobStore(tmp_path).list())==1;assert jobs[0]['published_at'] is None
def test_cancel(tmp_path):assert JobStore(tmp_path).search(['Python'],['Remotive'],cancel=lambda:True)['cancelled']

def test_same_title_different_jobs_and_cross_source_exact_duplicate(tmp_path):
 s=JobStore(tmp_path);base=dict(source='Remotive',source_id='1',url='https://example.invalid/1',company='Example',title='Developer',location='Worldwide',description='Detailed duties. '*30)
 assert s.add(base)
 other=dict(base,source_id='2',url='https://example.invalid/2');assert s.add(other)
 duplicate=dict(base,source='Remote OK',source_id='3',url='https://remoteok.com/remote-jobs/3');assert not s.add(duplicate)
 assert len(s.list())==2
 assert any(len(j.get('source_links',[]))==2 for j in s.list())

# Remote OK está excluido por el usuario: comprobar recuperación con una fuente habilitada.
def test_failed_source_does_not_stop_others(tmp_path,monkeypatch):
 from urllib.error import HTTPError
 def fetch(self,url):
  if self.name=='Remotive':raise HTTPError(url,403,'Blocked',None,None)
  return [dict(id='x',position='Developer',company='Example',url='https://example.invalid/job',description='Python')]
 monkeypatch.setattr(Connector,'_fetch',fetch)
 result=JobStore(tmp_path).search(['Python'],['Remotive','Himalayas']);assert len(result['errors'])==1 and result['found']==1

def test_contradictory_geo_and_unknown_scope():
 assert geography('Worldwide','US only')[0]=='INCOMPATIBLE'
 assert geography('Some unspecified region','')[0]=='DESCONOCIDO'

def test_gui_results_filters(tmp_path):
 import os
 os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from autojob.config import Settings
 from autojob.ui.main_window import MainWindow
 app=QApplication.instance() or QApplication([]);window=MainWindow(Settings(root=tmp_path));window.show();jobs=window.jobs_widget
 from autojob.search.jobs import ENDPOINTS
 assert jobs.table.columnCount()==8 and jobs.source_filter.count()==len(ENDPOINTS)+1
 jobs.filter.setCurrentText('CONFIRMADO');jobs.refresh();assert jobs.table.rowCount()==0
 window.close();app.processEvents()

def test_himalayas_salary_and_timezone():
 data={'jobs':[dict(guid='https://himalayas.app/companies/example/jobs/developer',title='Developer',companyName='Example',locationRestrictions=['Costa Rica'],timezoneRestrictions=[-6],description='Python',minSalary=1000,maxSalary=2000,currency='USD',salaryPeriod='monthly',pubDate=123)]}
 job=list(Connector('Himalayas').search_jobs(['Python'],payload=data))[0]
 assert job['geography']=='CONFIRMADO' and job['currency']=='USD' and 'monthly' in job['salary']
 assert job['published_at'] is None and job['source_updated_at']==123
 data['jobs'][0]['timezoneRestrictions']=[3]
 assert list(Connector('Himalayas').search_jobs([],payload=data))[0]['geography']=='INCOMPATIBLE'

def test_remoteok_legal_header_not_a_job():
 data=[{'legal':'API terms'},dict(id='1',position='Developer',company='Example',url='https://remoteok.com/remote-jobs/1',description='Python',location='Worldwide',date='2026-10-01')]
 jobs=list(Connector('Remote OK').search_jobs(['Python'],payload=data));assert len(jobs)==1 and jobs[0]['published_at']=='2026-10-01'

def test_requirement_snippets_are_preserved():
 data={'jobs':[dict(id=1,title='Developer',company_name='Example',url='https://example.invalid/job',description='Bachelor degree required. Fluent English required. Python preferred. 2 years of experience.',job_type='contract')]}
 job=list(Connector('Remotive').search_jobs([],payload=data))[0]
 assert job['education']==['Bachelor degree required.'] and job['languages']
 assert job['contract_type']=='contract' and job['experience']=='2 years of experience'
 assert job['desirable_requirements']==['Python preferred.']
