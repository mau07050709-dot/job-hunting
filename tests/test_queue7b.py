import os
from contextlib import closing
from pathlib import Path
import pytest
from autojob.config import Settings
from autojob.forms.queue import PreparationQueue
from autojob.forms.guard import action,origin,PreparationGuard,apply_link,continue_stage
from autojob.forms.runner import fill_field,enrich

@pytest.fixture
def queue(tmp_path):
 q=PreparationQueue(tmp_path)
 for n in range(3):
  q.preparation.compatibility.jobs.add(dict(source='FIXTURE',source_id=str(n),url=f'https://example.invalid/jobs/{n}',company='Fictional',title=f'Support {n}',description='Controlled fixture',location='Worldwide',modality='remote'))
 q.add([j['id'] for j in q.preparation.compatibility.jobs.list()]);return q

@pytest.mark.parametrize('label,kind,expected',[
 ('Submit','button','FINAL O LEGAL'),('Enviar','submit','FINAL O LEGAL'),('Apply','button','APPLY AMBIGUO'),
 ('Next','button','CONTINUAR'),('Continue','submit','AMBIGUA'),('Save and continue','button','CONTINUAR'),
 ('Review','button','CONTINUAR'),('Previous','button','ANTERIOR'),('Accept terms','button','FINAL O LEGAL'),
 ('Sign','button','FINAL O LEGAL'),('Do something','button','AMBIGUA')])
def test_action(label,kind,expected):assert action(label,kind)==expected

@pytest.mark.parametrize('url',['file:///C:/x','javascript:alert(1)','https://user:password@example.com','ftp://example.com'])
def test_origin_rejects_unsafe(url):
 with pytest.raises(ValueError):origin(url)

def test_dedup_priority_persistence(queue):
 rows=queue.list();assert queue.add([r['job_id'] for r in rows])==0
 queue.priority(rows[-1]['job_id'],99999)
 restored=PreparationQueue(queue.data_path);assert len(restored.list())==3
 assert restored.list()[0]['job_id']==rows[-1]['job_id']

def test_states_never_sent(queue):
 with pytest.raises(ValueError):queue.update(queue.list()[0]['job_id'],'ENVIADA','forbidden')
 with closing(queue.db.connect()) as db,pytest.raises(Exception):db.execute("UPDATE preparation_queue SET state='ENVIADA'")

def test_errors_continue_without_sensitive_logs(queue,tmp_path):
 calls=[]
 def processor(q,row,*args):
  calls.append(row['job_id'])
  if len(calls)==1:
   q.update(row['job_id'],'RELLENANDO','checkpoint',dict(row['payload'],filled=[dict(field='saved before failure')]),stage=1)
   raise ValueError('SECRET-PERSONAL-VALUE')
  return dict(state='PREPARADA',stage=2,filled=[dict(field='fictional')])
 result=queue.run(Settings(tmp_path),processor=processor)
 assert result['states']==['ERROR','PREPARADA','PREPARADA']
 assert len(calls)==3
 assert 'SECRET-PERSONAL-VALUE' not in str(queue.list())
 assert next(r for r in queue.list() if r['state']=='ERROR')['payload']['filled']
 assert all(r['attempts']==1 for r in queue.list())

@pytest.mark.parametrize('mode',['pause','stop'])
def test_pause_stop_resume(queue,tmp_path,mode):
 flag=[False]
 def partial(q,row,*args):flag[0]=True;return dict(interrupted=True,filled=[dict(field='saved checkpoint')])
 result=queue.run(Settings(tmp_path),pause=lambda:flag[0] and mode=='pause',stop=lambda:flag[0] and mode=='stop',processor=partial)
 assert result['processed']==1 and result['paused' if mode=='pause' else 'stopped']
 persisted=PreparationQueue(queue.data_path);active=next(r for r in persisted.list() if r['payload'].get('interrupted'))
 assert active['payload']['filled'] and active['state']==('POR PREPARAR' if mode=='pause' else 'PENDIENTE')
 persisted.requeue([active['job_id']],interrupted_only=True)
 assert persisted.run(Settings(tmp_path),processor=lambda *args:dict(state='PREPARADA'))['processed']==3

def test_crash_recovery_and_lock(queue,tmp_path):
 from autojob.browser.lock import ProfileLock
 id=queue.list()[0]['job_id'];queue.update(id,'RELLENANDO','checkpoint',dict(filled=[dict(field='name')]),stage=2)
 lock=ProfileLock(tmp_path/'preparation-queue.lock');lock.acquire()
 try:assert queue.recover()==0
 finally:lock.release()
 restored=PreparationQueue(tmp_path);assert restored.recover()==1
 row=next(r for r in restored.list() if r['job_id']==id)
 assert row['state']=='REQUIERE REVISIÓN' and row['stage']==2 and row['payload']['filled']
 assert row['payload']['interrupted'] and restored.history(id)

def test_active_cannot_be_removed(queue):
 id=queue.list()[0]['job_id'];queue.update(id,'ANALIZANDO','active');queue.remove([r['job_id'] for r in queue.list()]);assert len(queue.list())==1

def test_origin_permission_invalidates_on_change(queue):
 url='https://example.invalid/jobs/0';assert not queue.site_allowed(url)
 queue.allow_site(url,True);assert queue.site_allowed(url)
 queue.preparation.data.save({'own_computer':True},confirmed=['own_computer'])
 assert not queue.site_allowed(url)
 queue.allow_site(url,False);assert not queue.site_allowed(url)

@pytest.mark.parametrize('status',['SUGERIDA','DESCONOCIDA','REVISAR FORMATO'])
def test_unconfirmed_never_touches_page(status):
 assert fill_field(None,dict(kind='text',status=status,answer='not confirmed'),None)['status']=='PENDIENTE'

def test_external_cv_never_selected():
 assert fill_field(None,dict(kind='file'),None)['status']=='PENDIENTE'

def test_tampered_or_outside_fixture_file(tmp_path):
 from hashlib import sha256
 p=tmp_path/'fake.txt';p.write_text('fictional');root=tmp_path/'sub';root.mkdir()
 e=dict(kind='file',document='cv');files={'cv':dict(path=str(p),sha256=sha256(p.read_bytes()).hexdigest())}
 assert fill_field(None,e,None,dict(artifact_root=str(root)),files)['status']=='BLOQUEADO'
 files['cv']['sha256']='changed';assert fill_field(None,e,None,dict(artifact_root=str(tmp_path)),files)['status']=='BLOQUEADO'

def test_unknown_experience_never_derived(queue):
 e=dict(kind='number',semantic='experience',label='Years of programming experience',status='DESCONOCIDA',answer=None)
 assert enrich(queue.preparation,e)['answer'] is None

def test_captcha_blocks_without_navigation(queue,tmp_path,monkeypatch):
 from autojob.forms import runner
 class Browser:
  def __init__(self,*args):pass
  def __enter__(self):return self
  def __exit__(self,*args):pass
 class Page:
  url='https://example.invalid/jobs/0'
  def wait_for_function(self,*args,**kwargs):pass
 class Guard:
  def __init__(self,*args):pass
  def page(self,*args):return Page()
 monkeypatch.setattr(runner,'BraveSession',Browser);monkeypatch.setattr(runner,'PreparationGuard',Guard)
 monkeypatch.setattr(runner,'inspect',lambda page,**kwargs:dict(url=page.url,fields=[],obstacles=[dict(type='CAPTCHA',evidence='fixture')]))
 result=queue.run(Settings(tmp_path));assert result['states']==['BLOQUEADA']*3
 assert all(r['payload']['blocks'][0]['type']=='CAPTCHA' for r in queue.list())

def test_inspection_limits_embedded_frames():
 from autojob.forms.preparation import inspect
 calls=[]
 class Frame:
  url='https://example.invalid'
  def evaluate(self,*args):calls.append(1);return dict(title='',fields=[],text='',frames=[],password=False)
 class Page:url='https://example.invalid';frames=[Frame() for _ in range(40)]
 doc=inspect(Page(),max_frames=12)
 assert len(calls)==12 and any(o['type']=='LÍMITE DE FRAMES' for o in doc['obstacles'])

@pytest.mark.parametrize('block',['VACANTE POR VERIFICAR','CV PROVISIONAL','CV INCOMPATIBLE','DOCUMENTO NO DISPONIBLE','EVALUACIÓN OBSOLETA'])
def test_critical_preparation_blocks_before_fill(queue,tmp_path,monkeypatch,block):
 from autojob.forms import runner
 class Page:
  url='https://example.invalid/jobs/0'
  def wait_for_function(self,*args,**kwargs):pass
 class Browser:
  def __init__(self,*args):pass
  def __enter__(self):return self
  def __exit__(self,*args):pass
 class Guard:
  def __init__(self,*args):pass
  def page(self,*args):return Page()
 monkeypatch.setattr(runner,'BraveSession',Browser);monkeypatch.setattr(runner,'PreparationGuard',Guard)
 monkeypatch.setattr(runner,'inspect',lambda page,**kwargs:dict(url=page.url,fields=[],obstacles=[]))
 monkeypatch.setattr(queue.preparation,'prepare',lambda *args:dict(entries=[],blocks=[dict(type=block,evidence='fixture')]))
 monkeypatch.setattr(queue,'site_allowed',lambda *args:True)
 monkeypatch.setattr(queue.preparation.compatibility,'rows',lambda:[dict(job=j,evaluation=dict(eligibility='COMPATIBLE',geography='CONFIRMADO',availability='ABIERTA'),stale=False) for j in queue.preparation.compatibility.jobs.list()])
 monkeypatch.setattr(runner,'fill_field',lambda *args:pytest.fail('No field may be touched before critical review'))
 result=queue.run(Settings(tmp_path));assert result['states']==['REQUIERE REVISIÓN']*3

def test_confirmed_format_restoration():
 e=dict(kind='radio',status='REVISAR FORMATO',prepared_status='CONFIRMADA',semantic=None)
 assert enrich(None,e)['status']=='CONFIRMADA'
 e['prepared_status']='SUGERIDA';assert enrich(None,e)['status']=='REVISAR FORMATO'

def test_queue_ui(queue,tmp_path,qt_application_lifetime,monkeypatch):
 from PySide6.QtWidgets import QPushButton,QMessageBox
 from autojob.ui.queue_widget import QueueWidget
 # Test storage lives under data_path just like the production widget.
 s=Settings(tmp_path,data_dir='ui-data');w=QueueWidget(s)
 w.queue=queue;w.refresh();assert w.table.rowCount()==3
 w.table.selectRow(0);w.details();assert 'history' in w.output.toPlainText()
 monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.No)
 w.authorize();assert not queue.site_allowed(w.chosen()['url'])
 labels={b.text() for b in w.findChildren(QPushButton)}
 assert {'Iniciar cola','Pausar','Reanudar','Detener','Reintentar','Ver obstáculos'}<=labels
 w.blocks();w.remove();assert w.table.rowCount()==2
 w.close();w.deleteLater()

brave=pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local opt-in')

@brave
def test_brave_barriers_and_controls(tmp_path):
 from autojob.browser import BraveSession
 from autojob.forms.controlled import controlled_site
 from autojob.forms.preparation import inspect
 with controlled_site() as fixture,BraveSession(Settings(tmp_path)) as browser:
  g=PreparationGuard(browser,fixture['origin']);p=g.page(fixture['origin']+'/autojob-test/step2')
  # No final submission via button, native API, POST, GET or beacon.
  g.freeze();p.locator('input,textarea').evaluate_all('(es)=>es.forEach(e=>e.required=false)')
  p.locator('button[type=submit]').click()
  for method in ['submit','requestSubmit']:
   assert p.evaluate('(m)=>{try{document.querySelector("form")[m]();return false}catch(e){return e.message.includes("AUTOJOB_FINAL_SUBMISSION_DISABLED")}}',method)
  for method in ['GET','POST']:
   assert p.evaluate('async m=>{try{await fetch("/autojob-test/submit",{method:m});return false}catch(e){return true}}',method)
  p.evaluate('()=>navigator.sendBeacon("/autojob-test/submit","test")') # delivery is checked server-side
  p.wait_for_timeout(300)
  assert not any('/submit' in r['path'] for r in fixture['requests'])
  assert g.blocked>=2
  with pytest.raises(ValueError):g.navigate(p,fixture['origin']+'/submit')
  # Exact selection and DOM readback; no existing user values overwritten.
  p.set_content('''<label for="text">Name</label><input id="text"><select id="s"><option>A</option><option>B</option></select>
   <select id="m" multiple><option>A</option><option>B</option></select><input id="c" type="checkbox"><input id="r" type="radio" name="r">
   <button id="a" role="checkbox" aria-checked="false" onclick="this.setAttribute('aria-checked','true')">Equipment</button>
   <button id="combo" role="combobox">Choose</button><div role="option" onclick="document.querySelector('#combo').textContent='English'">English</div>''')
  def fill(id,kind,answer,label=''):
   return fill_field(p,dict(selector='#'+id,kind=kind,answer=answer,status='CONFIRMADA',label=label),g,fixture)
  for args in [('text','text','Test'),('s','select','B'),('m','multiple','A|B'),('c','checkbox','Yes'),('r','radio','Remote','Remote'),('a','checkbox','Yes'),('combo','combobox','English')]:
   assert fill(*args)['status']=='VERIFICADO',args
  assert fill('text','text','Different')['status']=='PENDIENTE'
  assert fill('c','checkbox','Yes','I accept terms')['status']=='PENDIENTE'
  assert fill('s','select','Unknown')['status']=='PENDIENTE'
  assert any(f['kind']=='checkbox' and f['selector']=='#a' for f in inspect(p)['fields'])
  p.set_content('<a href="/autojob-test/step1">Apply now</a><form><button>Next</button></form>')
  assert apply_link(p)==fixture['origin']+'/autojob-test/step1'
  assert not continue_stage(p,g)[0]
  g.navigate(p,apply_link(p));assert p.locator('#name').is_visible()

@brave
def test_local_multistage_queue(tmp_path):
 from autojob.forms.lab7b import run_lab
 result=run_lab(Settings(tmp_path))
 assert result['prepared']==2 and result['verified_fields']==[11,11]
 assert result['stages_per_form']==2 and result['pause_verified'] and result['persistence_verified']
 assert not result['submitted'] and all(r['method']=='GET' for r in result['requests'])

@brave
def test_unknown_required_halts_stage_but_continues_queue(tmp_path):
 from autojob.forms.lab7b import run_lab
 result=run_lab(Settings(tmp_path),confirm_unknown=False)
 assert result['processed']==2 and result['prepared']==0
 assert result['states']==['PENDIENTE','PENDIENTE']
 assert result['verified_fields']==[10,10] and not result['submitted']
