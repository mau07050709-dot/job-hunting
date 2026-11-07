from pathlib import Path
from datetime import date,timedelta
from decimal import Decimal
import os,json
import pytest
from autojob.profile.application_data import ApplicationData
from autojob.forms.preparation import Preparation,obstacles

def data(tmp_path):return ApplicationData(tmp_path)
def confirmed(store,**values):store.save(values,confirmed=values)

def test_data_unknown_false_and_restart(tmp_path):
 s=data(tmp_path);assert s.value('own_computer')==(None,'DESCONOCIDA');confirmed(s,own_computer=False,weekends=True);again=data(tmp_path);assert again.value('own_computer')==(False,'CONFIRMADA') and again.value('weekends')[0] is True

@pytest.mark.parametrize('key,value',[('birth_date','2999-01-01'),('birth_date','2000-99-01'),('main_min','-1'),('main_min','NaN'),('main_currency','dollars'),('main_hours','0'),('weekly_hours','-3'),('timezone','Invalid/Zone'),('whatsapp','123'),('linkedin','http://example.invalid')])
def test_invalid_values(tmp_path,key,value):
 with pytest.raises(ValueError):data(tmp_path).save({key:value})

def test_birthday_and_age(tmp_path):
 s=data(tmp_path);confirmed(s,birth_date='2000-02-03');r=Preparation(tmp_path).resolve('What is your age?');assert r['status']=='DERIVADA' and r['answer'] is not None

def test_salary_periods_and_hours_not_assumed(tmp_path):
 s=data(tmp_path);confirmed(s,main_min='1000',main_expected='1200',main_max='1500',main_currency='USD',main_period='month');assert s.salary(target='year',bound='expected')[0]=='14400.00';assert s.salary(target='hour')[0] is None
 confirmed(s,main_hours='40');assert Decimal(s.salary(target='hour',bound='expected')[0])==Decimal('6.92')

def test_salary_multiple_ranges_and_fx(tmp_path):
 s=data(tmp_path);confirmed(s,part_expected='500',part_currency='USD',part_period='month',contractor_expected='2000',contractor_currency='USD',contractor_period='month')
 assert s.salary('part',bound='expected')[0]=='500.00';assert s.salary('contractor',bound='expected')[0]=='2000.00';assert s.salary('part',currency='CRC',bound='expected')[0] is None
 confirmed(s,fx_from='USD',fx_to='CRC',fx_rate='500');assert s.salary('part',currency='CRC',bound='expected')[0]=='250000.00'

def test_salary_range_and_numeric_expectation(tmp_path):
 s=data(tmp_path);confirmed(s,main_min='1000',main_max='1500',main_currency='USD',main_period='month');r=Preparation(tmp_path).resolve('Expected monthly salary USD');assert r['answer']=='1000.00–1500.00' and r['status']=='DERIVADA'

def test_conflict_preserves_profile(tmp_path):
 s=data(tmp_path);p=s.profile.load();p['values']['nationality']='Costa Rican';s.profile.save(p['values'],p['revision']);confirmed(s,nationality='Canadian')
 assert 'nationality' in s.conflicts();assert s.profile.load()['values']['nationality']=='Costa Rican';assert Preparation(tmp_path).resolve('Nationality')['status']=='CONFLICTO'

def test_confirmed_correction_and_concurrency(tmp_path):
 s=data(tmp_path);confirmed(s,own_computer=True);before=s.load();s.save({'webcam':True});assert s.load()['own_computer']==before['own_computer']
 with pytest.raises(ValueError):s.save({'own_computer':False},expected={'own_computer':0})

def test_delete_removes_history(tmp_path):
 s=data(tmp_path);confirmed(s,address='Fictitious address');s.delete(['address']);assert 'address' not in s.load()
 from contextlib import closing
 with closing(s.db.connect()) as db:assert db.execute('SELECT count(*) FROM application_data_history WHERE key=?',('address',)).fetchone()[0]==0

@pytest.mark.parametrize('question',["Do you have your own computer?",'¿Tienes computadora propia?'])
def test_equipment_question_languages(tmp_path,question):
 s=data(tmp_path);confirmed(s,own_computer=True);r=Preparation(tmp_path).resolve(question);assert r['answer'] in {'Yes','Sí'} and r['status']=='CONFIRMADA' and not r['automatic']

def test_salary_specific_basis_and_currency(tmp_path):
 s=data(tmp_path);confirmed(s,main_expected='1000',main_currency='USD',main_period='month',main_basis='gross');p=Preparation(tmp_path)
 assert p.resolve('Expected monthly gross salary USD')['answer']=='1000.00';assert p.resolve('Expected monthly net salary USD')['answer'] is None
 assert p.resolve('Expected monthly salary EUR')['answer'] is None

def test_prior_employment_is_company_specific(tmp_path):
 s=data(tmp_path);q='Have you worked before at this company?'
 with pytest.raises(ValueError):s.faq_save('',q,'Yes',True)
 s.faq_save('Example',q,'No',True);p=Preparation(tmp_path);assert p.resolve(q,{'company':'Example'})['answer']=='No';assert p.resolve(q,{'company':'Other'})['answer'] is None

def test_unknown_or_unconfirmed_not_ready(tmp_path):
 s=data(tmp_path);s.save({'own_computer':True});p=Preparation(tmp_path);assert p.resolve('Do you have your own computer?')['status']=='SUGERIDA';assert p.resolve('What is your unknown project code?')['answer'] is None

def test_permits_not_transferred_and_legal_not_accepted(tmp_path):
 s=data(tmp_path);confirmed(s,work_authorization_cr=True);p=Preparation(tmp_path)
 assert p.resolve('Are you authorized to work in Costa Rica?')['answer']=='Yes';assert p.resolve('Are you authorized to work in the United States?')['answer'] is None;assert p.resolve('I accept the legal agreement')['status']=='BLOQUEADA'

@pytest.mark.parametrize('text,type_',[('Please verify you are human','CAPTCHA'),('Record a video interview','VIDEO'),('Voice recording required','VOZ'),('Identity verification','IDENTIDAD'),('Electronic signature','FIRMA LEGAL')])
def test_obstacles(text,type_):assert type_ in {r['type'] for r in obstacles(text)}

def test_preparation_required_persistence_and_staleness(tmp_path):
 p=Preparation(tmp_path);doc=dict(url='https://example.invalid/form',fields=[dict(label='Unknown mandatory code',kind='text',required=True,selector='#code',group='')],obstacles=[]);preview=p.prepare(doc);assert preview['state']=='PENDIENTE' and preview['blocks'] and not preview['submission_enabled'];id=p.save(preview);r=p.history()[0];assert r['id']==id and not r['stale'];p.save(r);assert len(p.history())==2
 confirmed(p.data,own_computer=True);assert all(r['stale'] for r in p.history())

def test_blocked_form_and_disallowed_state(tmp_path):
 p=Preparation(tmp_path);doc=dict(url='https://example.invalid/form',fields=[],obstacles=[dict(type='CAPTCHA',evidence='captcha')]);r=p.prepare(doc);assert r['state']=='BLOQUEADA'
 with pytest.raises(ValueError):p.save(dict(r,state='ENVIADA'))

def test_cv_missing_does_not_invent_document(tmp_path):
 p=Preparation(tmp_path);doc=dict(url='https://example.invalid/form',fields=[dict(label='CV',kind='file',document='cv',required=True,selector='#cv')],obstacles=[]);r=p.prepare(doc,cv_id='missing');assert r['entries'][0]['answer'] is None and any(b['type']=='DOCUMENTO NO DISPONIBLE' for b in r['blocks'])

def test_external_filling_refused():
 from autojob.forms.controlled import fill_controlled
 class Page:url='https://example.invalid/form'
 with pytest.raises(ValueError):fill_controlled(Page(),{'origin':'http://127.0.0.1:1234','token':'x'},{'name':'Never sent'})

def test_existing_answer_bank_remains_connected(tmp_path):
 p=Preparation(tmp_path);state=p.data.profile.load();state['values']['full_name']='Fictional Candidate';state=p.data.profile.save(state['values'],state['revision']);p.bank.save('name','en',['Full name'],'Fictional Candidate',True,state)
 r=p.resolve('Full name');assert r['answer']=='Fictional Candidate' and r['status']=='CONFIRMADA'

def test_no_prior_employment_guess_for_named_company(tmp_path):
 p=Preparation(tmp_path)
 with pytest.raises(ValueError):p.data.faq_save('','Have you ever worked at Example?','Yes',True)
 assert p.resolve('Have you ever worked at Example?',{'company':'Other'})['answer'] is None

def test_compound_equipment_not_answered_from_ownership_alone(tmp_path):
 p=Preparation(tmp_path);confirmed(p.data,own_computer=True)
 assert p.resolve('Do you have access to your own computer with video/audio capabilities?')['answer'] is None
 assert p.resolve('Do you have your own laptop?')['answer'] is None

def test_multiple_conditions_do_not_pick_one(tmp_path):
 p=Preparation(tmp_path);confirmed(p.data,own_computer=True)
 assert p.resolve('Do you have your own computer and stable internet?')['answer'] is None

def test_expected_salary_must_fit_declared_range(tmp_path):
 with pytest.raises(ValueError):data(tmp_path).save({'main_min':'1000','main_max':'1500','main_expected':'2000'})

def test_windows_ram_decimal_is_locale_independent(tmp_path,monkeypatch):
 import subprocess
 from autojob.profile.application_data import detect_windows
 monkeypatch.setattr(subprocess,'run',lambda *a,**kw:type('Result',(),{'returncode':0,'stdout':b'{"ram_gb":"15,9","processor":" CPU ","operating_system":" Windows "}'})())
 result=detect_windows();assert result['ram_gb']=='15.9';data(tmp_path).save(result);assert not data(tmp_path).load()['ram_gb']['confirmed']

def test_modality_conditions_are_not_ignored(tmp_path):
 p=Preparation(tmp_path);confirmed(p.data,weekends=True,remote_conditions='No weekends for remote work')
 r=p.resolve('Are you available on weekends?',{'modality':'remote'});assert r['answer'] is None and r['status']=='REQUIERE REVISIÓN'

def test_unidentified_vacancy_not_ready(tmp_path):
 p=Preparation(tmp_path);r=p.prepare(dict(url='https://example.invalid',fields=[],obstacles=[]));assert any(b['type']=='VACANTE SIN EVALUACIÓN' for b in r['blocks']) and r['state']=='PENDIENTE'

def test_explicit_revoke_and_unchanged_save(tmp_path):
 s=data(tmp_path);confirmed(s,own_computer=True);original=s.load()['own_computer'];s.save({'own_computer':True},confirmed=['own_computer']);assert s.load()['own_computer']==original
 s.save({'own_computer':True},confirmed=[]);assert s.value('own_computer')==(True,'SUGERIDA')

def test_phone_group_does_not_fill_country_or_unlabelled_with_full_number(tmp_path):
 p=Preparation(tmp_path);state=p.data.profile.load();state['values']['phone']='+506 8888 8888';p.data.profile.save(state['values'],state['revision'])
 fields=[dict(label='Country*',kind='combobox',required=True,selector='#country',group='Phone*'),dict(label='Sin etiqueta',kind='text',required=True,selector='#internal',group='Phone*')]
 preview=p.prepare(dict(url='https://example.invalid',fields=fields,obstacles=[]));assert all(e['answer'] is None for e in preview['entries'])

def test_windows_detection_is_opt_in(tmp_path,monkeypatch):
 import autojob.ui.application_widgets as ui
 from PySide6.QtWidgets import QApplication,QMessageBox
 from autojob.config import Settings
 app=QApplication.instance() or QApplication([]);calls=[];monkeypatch.setattr(ui,'detect_windows',lambda:calls.append(1) or {'operating_system':'Fictitious OS'});w=ui.ApplicationDataWidget(Settings(root=tmp_path));assert calls==[]
 monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No);w.detect();assert calls==[];w.close()

def test_gui_save_and_restart(tmp_path):
 from PySide6.QtWidgets import QApplication
 from autojob.config import Settings
 from autojob.ui.application_widgets import ApplicationDataWidget
 app=QApplication.instance() or QApplication([]);w=ApplicationDataWidget(Settings(root=tmp_path));w.set_value('birth_date','2000-02-03');w.checks['birth_date'].setChecked(True);w.set_value('own_computer',True);w.checks['own_computer'].setChecked(True);w.save();assert 'Guardado' in w.status.text();w.close();again=ApplicationDataWidget(Settings(root=tmp_path));assert again.read('own_computer') is True and again.checks['own_computer'].isChecked();again.close()

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Integración local con Brave explícitamente habilitada')
def test_brave_controlled_multistage_upload_and_dom(tmp_path):
 from autojob.config import Settings
 from autojob.forms.controlled import run_controlled,controlled_site
 from autojob.forms.preparation import inspect
 from autojob.browser import BraveSession
 settings=Settings(root=tmp_path);r=run_controlled(settings);assert r['stages']==2 and r['fictional_cv_attached'] and r['fictional_letter_attached'] and not r['submitted'] and all(x['method']=='GET' for x in r['requests'])
 with controlled_site() as fixture,BraveSession(settings) as b:
  page=b.new_page(fixture['origin']+'/autojob-test/step1');page.set_content('<form><label for="f">Nombre completo</label><input id="f" required><label for="h">Resume CV</label><input id="h" type="file" style="display:none"><label for="n">Años de experiencia</label><input type="number" id="n"><input type="password"><button type="submit">Siguiente</button><button type="submit">Enviar postulación</button></form><iframe title="captcha" src="about:blank"></iframe>');d=inspect(page)
  assert next(f for f in d['fields'] if f['label']=='Nombre completo')['selector']=='#f';assert any(f['kind']=='file' for f in d['fields']);assert any(f.get('semantic')=='experience' for f in d['fields']);assert {'CONTINUACIÓN','ENVÍO FINAL'}<={f.get('action') for f in d['fields']};assert {'CAPTCHA','AUTENTICACIÓN'}<={o['type'] for o in d['obstacles']}
