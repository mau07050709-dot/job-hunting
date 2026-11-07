from datetime import datetime,timezone,timedelta
from pathlib import Path
import json
import pytest
from autojob.search.jobs import Connector,JobStore
from autojob.search.national import parse_detail
from autojob.search.filters import matches,Favorites,export_rows
from autojob.search.availability import inspect_page,Availability

def fixture(mode='Onsite',place='Cartago, CR'):
 html='<div itemscope itemtype="http://schema.org/JobPosting"><h1><span itemprop="title">IT Support</span></h1><span data-careersite-propertyid="customfield1">'+mode+'</span><span class="jobdescription"><p><span>First duty.</span></p><p>Second duty. English required.</p></span><meta itemprop="datePosted" content="Thu Oct 29 00:00:00 UTC 2026"><meta itemprop="validThrough" content="Mon Nov 02 06:00:00 UTC 2099"><a href="/apply/1">Enviar candidatura ahora</a></div>'
 return html,parse_detail(html,'https://example.invalid/job/1/',place)

@pytest.mark.parametrize('mode,expected',[('Onsite','onsite'),('Hybrid','hybrid'),('Remote','remote'),('','unknown')])
def test_national_modes(mode,expected):
 _,row=fixture(mode);job=list(Connector('Boston Scientific CR').search_jobs(['IT'],payload=[row]))[0]
 assert (job['modality'] or 'unknown')==expected
 assert job['company']=='Boston Scientific' and job['country']=='Costa Rica'
 assert job['description']=='First duty. Second duty. English required.'
 assert job['published_at'].startswith('2026-10-29')

@pytest.mark.parametrize('place,status',[('Cartago, CR','CONFIRMADO'),('Cartago, Colombia','INCOMPATIBLE'),('Heredia, Costa Rica','INCOMPATIBLE'),('Turrialba, Costa Rica','CONFIRMADO'),('La Unión, Costa Rica','CONFIRMADO')])
def test_national_geography(place,status):
 _,row=fixture(place=place)
 assert list(Connector('Boston Scientific CR').search_jobs([],payload=[row]))[0]['geography']==status

def test_nomads_mapping():
 row=dict(title='Python Developer',company_name='Example',description='Python required',location='LATAM',pub_date='2026-10-29',url='https://workingnomads.com/job/go/1/')
 job=list(Connector('Working Nomads').search_jobs(['python'],payload=[row]))[0]
 assert job['company']=='Example' and job['modality']=='remote' and job['published_at']=='2026-10-29'

def test_microdata_open_and_closed():
 html,row=fixture();assert inspect_page(row,200,row['url'],html)['state']=='ABIERTA'
 assert inspect_page(row,200,row['url'],html.replace('2099','2020'))['state']=='CERRADA'

def test_combined_filters():
 job=dict(title='Junior IT Support',company='Example',location='Cartago, Costa Rica',modality='onsite',geography='CONFIRMADO',availability='ABIERTA',seniority='Junior',salary='1000',currency='USD',published_at=datetime.now(timezone.utc).isoformat())
 assert matches(job,dict(province='Cartago',modality='onsite',seniority='junior',keywords='IT Support',published_days='7',salary='Publicado',currency='USD',availability='ABIERTA'),False)
 assert not matches(job,dict(modality='remote'),False)
 assert not matches(dict(job,published_at='2020-01-01'),dict(published_days='7'),False)
 assert matches(dict(job,seniority=None),dict(seniority='junior'),True)
 assert not matches(dict(job,seniority=None),dict(seniority='junior'),False)

def test_favorite_restart_and_export(tmp_path):
 s=JobStore(tmp_path);f=Favorites(s);f.save('Cartago',dict(province='Cartago',modality='onsite'),False)
 assert Favorites(JobStore(tmp_path)).list()['Cartago']['filters']['province']=='Cartago'
 rows=[dict(company='=FORMULA',title='IT Support',availability='ABIERTA')];file=tmp_path/'export.xlsx';export_rows(rows,file)
 from openpyxl import load_workbook
 book=load_workbook(file);assert book.active.max_row==2 and book.active['A2'].data_type=='s'

def test_refresh_preserves_manual_and_verification(tmp_path):
 store=JobStore(tmp_path);_,row=fixture();job=list(Connector('Boston Scientific CR').search_jobs([],payload=[row]))[0]
 job.update(title='Corrected',manual_fields=['title']);store.add(job)
 stored=store.list()[0];Availability(store).check(stored,lambda u:(404,u,''))
 store.add(dict(job,title='Feed title',manual_fields=[]))
 saved=store.list()[0];assert saved['title']=='Corrected' and saved['availability']=='CERRADA' and saved['manual_fields']==['title']

def test_gui_combined_saved_export(tmp_path,monkeypatch):
 import os
 os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication,QFileDialog,QInputDialog
 from autojob.ui.jobs_widget import JobsWidget
 from autojob.config import Settings
 app=QApplication.instance() or QApplication([]);widget=JobsWidget(Settings(root=tmp_path));_,row=fixture();widget.store.add(list(Connector('Boston Scientific CR').search_jobs([],payload=[row]))[0]);widget.refresh()
 widget.include_unknown.setChecked(False);widget.advanced['province'].setText('Cartago');widget.mode_filter.setCurrentText('Presencial');assert len(widget.rows)==1
 monkeypatch.setattr(QInputDialog,'getText',lambda *a:('Favorite',True));widget.save_filters();widget.clear_filters();widget.load_filters();assert widget.mode_filter.currentText()=='Presencial' and widget.advanced['province'].text()=='Cartago'
 file=tmp_path/'filtered.xlsx';monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a:(str(file),''));widget.export();assert file.exists()
 widget.table.selectRow(0);widget.show_history();assert 'todavía' in widget.description.toPlainText()
 widget.close();app.processEvents()
