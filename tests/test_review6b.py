from copy import deepcopy
from pathlib import Path
import json
import pytest
from autojob.profile.review import ReviewStore
from autojob.profile.store import ProfileStore,empty
from autojob.matching.engine import evaluate,DEFAULT,candidate,assess,VERSION
from autojob.matching.service import Compatibility,recommendation

def p(**values):return dict(values=dict(empty(),**values),manual=[],sources={},conflicts={},revision=1)
def job(**values):return dict(dict(id='1',source='Test',source_id='1',url='https://example.invalid/1',title='Customer Support Representative',company='Example',description='Requirements:\nCustomer service required.\nMinimum 1 year of customer service experience.\nEnglish B2 required.',location='Worldwide',modality='remote',geography='CONFIRMADO',availability='NO VERIFICADA'),**values)
def setup_profile(tmp_path):
 store=ProfileStore(tmp_path);state=store.load();values=state['values'];values['skills']=['Customer Support','Excel'];values['languages']=['English B2'];values['experience_records']=['Hotel | Customer Service | 2020 | 2024 | Customer support, communication, resolving customer queries']
 # Simula extracción, sin confirmarla mediante la API de guardado manual.
 state['values']=values;store._save(state);return ReviewStore(tmp_path)
def item(store,field,index=None):return next(r for r in store.inventory() if r['source']=='profile' and r['field']==field and (index is None or r['index']==index))

def test_review_does_not_confirm_on_load(tmp_path):
 r=setup_profile(tmp_path);r.inventory();assert not r.decisions();assert not r.profile.load()['manual']

def test_individual_confirmation_not_siblings(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'skills',0);r.save([a['id']],True);profile,cvs=r.effective(r.profile.load(),[]);b=candidate(profile,cvs)['buckets']['skills']
 assert b[0]['confirmed'] and not b[1]['confirmed'];assert not r.profile.load()['manual']

def test_category_confirmation(tmp_path):
 r=setup_profile(tmp_path);rows=[i for i in r.inventory() if i['category']=='Habilidades técnicas' and i['value'] and not i['conflict']];assert r.save([i['id'] for i in rows],True)==2
 assert len([d for d in r.decisions().values() if d['state']=='CONFIRMADO'])==2

def test_draft_and_restart(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'skills',0);r.save([a['id']],values={a['id']:'Atención al cliente'})
 again=ReviewStore(tmp_path);assert item(again,'skills',0)['value']=='Atención al cliente';effective,_=again.effective(again.profile.load(),[]);assert effective['values']['skills'][0]=='Customer Support'

def test_manual_correction_preserved_while_new_draft(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'skills',0);r.save([a['id']],True,{a['id']:'Atención al cliente'});r.save([a['id']],False,{a['id']:'New unfinished draft'})
 effective,_=r.effective(r.profile.load(),[]);assert effective['values']['skills'][0]=='Atención al cliente'
 assert r.profile.load()['values']['skills'][0]=='Customer Support'

def test_source_change_stales_confirmation(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'skills',0);r.save([a['id']],True);state=r.profile.load();state['values']['skills'][0]='Python';r.profile.save(state['values'],state['revision']);assert item(r,'skills',0)['state'].startswith('OBSOLETO')

def test_unknown_not_filled(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'birth_date');assert r.save([a['id']],True)==0;assert r.profile.load()['values']['birth_date'] is None

def test_invalid_values_and_concurrency(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'email')
 with pytest.raises(ValueError):r.save([a['id']],True,{a['id']:'invalid'})
 a=item(r,'skills',0);r.save([a['id']],True)
 with pytest.raises(ValueError):r.save([a['id']],True,expected={a['id']:(0,a['source_hash'])})

def test_provisional_professional_score_not_halved():
 profile=p(skills=['Customer Support'],languages=['English B2'],experience_records=['Hotel | Customer Service | 2020 | 2024 | Customer support'])
 provisional=evaluate(job(),profile,[],DEFAULT)
 confirmed=deepcopy(profile);confirmed['manual']=['skills','languages','experience_records'];verified=evaluate(job(),confirmed,[],DEFAULT)
 assert provisional['score']==verified['score'] and provisional['score']>=70
 assert provisional['confidence']<verified['confidence'];assert provisional['eligibility']=='REQUIERE REVISIÓN' and not provisional['automatic_authorized']

def test_unknown_mandatory_not_incompatible():
 result=evaluate(job(description='Requirements:\nCISSP required.\nCustomer service required.'),p(skills=['Customer Service']),[],DEFAULT)
 assert result['eligibility']=='REQUIERE REVISIÓN'

def test_known_failure_still_excludes():
 profile=p(languages=['English B1']);profile['manual']=['languages'];result=evaluate(job(),profile,[],DEFAULT);assert result['eligibility']=='INCOMPATIBLE'

def test_transferable_not_software_experience():
 person=candidate(p(experience_records=['Hotel | Bilingual Customer Support | 2010 | 2025 | Customer support and resolving inquiries']),[])
 q=dict(kind='experience',name='professional_years',years=3,domain='programming',importance='OBLIGATORIO',evidence='3 years required',source='test')
 assert assess(q,person,DEFAULT,job())['support']==0
 assert evaluate(job(),p(skills=['Atención al cliente']),[],DEFAULT)['criteria']['skills']==100

def test_recommendation_orthogonal_geography_and_vigency():
 r=dict(score=90,eligibility='REQUIERE REVISIÓN',geography='POSIBLE',availability='NO VERIFICADA',assessments=[dict(importance='OBLIGATORIO',state='POR VERIFICAR',support=1)])
 assert recommendation(r)=='A. Alta compatibilidad';assert recommendation(dict(r,eligibility='INCOMPATIBLE'))=='D. Incompatibles'
 assert recommendation(dict(r,score=65))=='B. Compatibilidad moderada'
 r['assessments'][0]['support']=0;assert recommendation(r)=='C. Requieren verificación'

def test_review_stales_evaluations_and_history(tmp_path):
 r=setup_profile(tmp_path);s=Compatibility(tmp_path);s.jobs.add(job());s.batch();a=item(r,'skills',0);r.save([a['id']],True)
 assert s.rows()[0]['stale'];s.batch();history=s.history(s.jobs.list()[0]['id']);assert len(history)==2 and history[0]['change_from_previous']['engine_before']==VERSION

def test_cv_provisional_and_confirmed(tmp_path):
 s=Compatibility(tmp_path);cv=dict(id='cv',title='Mixed English',language='en',specialty='mixed',reviewed=False,is_default=False,fields={'technical_skills':['Customer Service']},structure={})
 class Library:
  data_path=tmp_path
  def list(self):return [cv]
  def original_path(self,id):return tmp_path/id
 s.library=Library();selection=s.selection(job(),dict(cvs=[cv],config=DEFAULT));assert selection['confirmed'] and selection['resume_id']=='cv'
 assert cv['reviewed'] is False  # Seleccionar un archivo no confirma sus datos extraídos.
 cv['reviewed']=True;selection=s.selection(job(),dict(cvs=[cv],config=DEFAULT));assert selection['resume_id']=='cv' and selection['confirmed'] and selection['status']=='CV confirmado'

def test_gui_confirmation_uses_explicit_dialog(tmp_path,monkeypatch):
 import os;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication,QMessageBox
 from autojob.ui.review_widget import ReviewWidget
 from autojob.config import Settings
 app=QApplication.instance() or QApplication([]);setup_profile(tmp_path/'data');w=ReviewWidget(Settings(root=tmp_path));w.category.setCurrentText('Habilidades técnicas');w.table.selectRow(0)
 monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No);w.confirm_selected();assert not w.store.decisions()
 monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes);w.confirm_selected();assert w.store.decisions();w.close();app.processEvents()

def test_recommendations_gui_export(tmp_path,monkeypatch):
 import os;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication,QFileDialog
 from autojob.ui.compatibility_widget import CompatibilityWidget
 from autojob.config import Settings
 app=QApplication.instance() or QApplication([]);setup_profile(tmp_path/'data');w=CompatibilityWidget(Settings(root=tmp_path));w.service.jobs.add(job());w.service.batch();w.refresh();category_=w.rows[0]['evaluation']['recommendation'];w.filter.setCurrentText(category_);assert w.table.rowCount()==1
 file=tmp_path/'recommendations.xlsx';monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a:(str(file),''));w.export();assert file.exists();w.close();app.processEvents()

def test_conflict_detected_and_explicit_choice(tmp_path):
 r=setup_profile(tmp_path);state=r.profile.load();state['values']['email']='first@example.invalid';state['conflicts']['email']=[{'value':'other@example.invalid'}];r.profile._save(state);a=item(r,'email');assert a['conflict']
 with pytest.raises(ValueError):r.save([a['id']],True)
 r.save([a['id']],True,resolve_conflicts=True);effective,_=r.effective(r.profile.load(),[]);assert effective['values']['email']=='first@example.invalid' and 'email' not in effective['conflicts']

def test_confirm_cv_record_does_not_confirm_document(tmp_path):
 r=setup_profile(tmp_path);record=dict(id='record',company='Example',position='Customer Service',start_date='2020',end_date='2024',responsibilities=['Help customers'],description='Customer support',origin='automatic')
 cv=dict(id='cv',title='Mixed',fields={},structure={'experience':[record]},reviewed=False,manual_fields=[],source_units=[])
 class Library:
  def list(self):return [cv]
  def get(self,id):return cv
 r.library=Library();a=next(i for i in r.inventory() if i['group']=='experience');r.save([a['id']],True)
 effective,docs=r.effective(r.profile.load(),[cv]);person=candidate(effective,docs);assert any(f['confirmed'] and f['record'].get('id')=='record' for f in person['buckets']['experience']);assert not docs[0]['reviewed']

def test_projects_support_skills_never_work_years():
 cv=dict(id='cv',reviewed=False,fields={},source_units=[],structure={'academic_projects':[dict(id='project',name='Python circuit project',description='Python programming and electronic circuits')]})
 person=candidate(p(),[cv]);q=dict(kind='skill',name='python',importance='OBLIGATORIO',evidence='Python required',source='test');assert assess(q,person,DEFAULT,job())['support']==1
 q=dict(kind='experience',name='professional_years',years=2,domain='programming',importance='OBLIGATORIO',evidence='Two professional years',source='test');assert assess(q,person,DEFAULT,job())['support']==0

@pytest.mark.parametrize('specific',['cold calling and SDR-specific activities','B2B sales experience','accounting experience','call center experience','technical customer support experience'])
def test_general_service_does_not_credit_specific_sales_or_accounting(specific):
 result=evaluate(job(title='Sales Representative',description='Requirements:\nExperience: Minimum of 1 year in '+specific+'.'),p(experience_records=['Hotel | Customer Service | 2010 | 2025 | Customer support and inbound calls']),[],DEFAULT)
 years=[r for r in result['assessments'] if r['kind']=='experience'];assert years and years[0]['support']==0 and years[0]['state']=='POR VERIFICAR'

@pytest.mark.parametrize('kind,name,field,text',[('certification','CCNA','certifications','No tengo CCNA'),('skill','python','skills','No Python'),('language','English','languages','No hablo English')])
def test_negative_declaration_not_positive_evidence(kind,name,field,text):
 profile=p(**{field:[text]});person=candidate(profile,[]);q=dict(kind=kind,name=name,importance='OBLIGATORIO',evidence='Required',source='test');assert assess(q,person,DEFAULT,job())['support']==0
 profile['manual']=[field];assert assess(q,candidate(profile,[]),DEFAULT,job())['state']=='NO CUMPLE'

def test_unrecognized_professional_domain_needs_review():
 result=evaluate(job(title='Labeling Project Specialist',description='Requirements:\nAt least 3 years of experience in labeling operations.'),p(experience_records=['Hotel | Customer Service | 2010 | 2025 | Customer support and inbound calls']),[],DEFAULT)
 years=[r for r in result['assessments'] if r['kind']=='experience'];assert years and years[0]['support']==0

def test_clear_wrong_list_value_as_unknown(tmp_path):
 r=setup_profile(tmp_path);a=item(r,'skills',0);r.save([a['id']],True,{a['id']:None});assert item(r,'skills',0)['state']=='DESCONOCIDO REVISADO'
 effective,_=r.effective(r.profile.load(),[]);assert effective['values']['skills'][0]=='' and r.profile.load()['values']['skills'][0]=='Customer Support'
 assert not any(f['text']=='Customer Support' for f in candidate(effective,[])['buckets']['skills'])
