import json,os,time
from pathlib import Path
from threading import Event
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton,QLineEdit
from test_submissions9b import portal
from test_phase9g import setup,assert_prepared
from test_phase9f import criteria
from autojob.forms.batches import create
from autojob.ui.main_window import MainWindow
from autojob.ui.submission_ui import MissingInformation
import autojob.live as live

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_start_button_batch_prepares_intervenes_resumes_one_post(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
 with portal(tmp_path) as lab:
  s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch)
  a=create(s,criteria(s,j),2,1,True,True,'local',True)
  w=MainWindow(lab['settings']);w.resize(1280,900);w.show();await_ui(lambda:not w._ui_tasks,30000)
  w.shell.delivery_authorization=a;w.shell.engine.delivery_authorization=a
  w.shell.engine.store.configure(max_verify=0,max_prepare=2)
  trace=[];prepared=Event();human=Event();focus_seen=Event();original=live.wait_prepared;native_focus=__import__('autojob.intervention_context',fromlist=['focus']).focus
  def focused(page,context):
   result=native_focus(page,context)
   if result:focus_seen.set()
   return result
  monkeypatch.setattr('autojob.intervention_context.focus',focused)
  def observed(page,state,item):
   assert_prepared(page);prepared.set()
  fixture['on_prepared']=observed
  def captcha_human(page,id,store):
   assert_prepared(page);page.locator('#human-check').click();human.set()
  fixture['on_wait']=captcha_human
  def controlled(*args,**kwargs):kwargs['fixture']=fixture;return original(*args,**kwargs)
  monkeypatch.setattr(live,'wait_prepared',controlled)
  run=w.shell.engine.run
  def search(*args):
   # Descubrimiento HTTP real, limitado al portal ficticio local.
   from urllib.request import urlopen
   with urlopen(j['url']) as r:assert r.status==200 and b'Junior Python Developer Delivery' in r.read()
   trace.append('search_local_http');return dict(found=1,duplicates=1,errors=[])
  def evaluate(**kwargs):trace.append('evaluate');return w.shell.engine.compatibility.batch(**kwargs)
  def coordinated(*args,**kwargs):
   kwargs['services']=dict(search=search,geography=lambda *a:None,evaluate=evaluate)
   return run(*args,**kwargs)
  monkeypatch.setattr(w.shell.engine,'run',coordinated)
  monkeypatch.setattr(w.shell,'options_snapshot',lambda:dict(queries=['Python'],sources=['LOCAL 9B'],limit=2))
  beats=[];timer=QTimer(w);timer.timeout.connect(lambda:beats.append(1));timer.start(40)
  QTest.mouseClick(w.shell.home.start,Qt.MouseButton.LeftButton)
  try:
   await_ui(prepared.is_set,45000);await_ui(lambda:len(w.shell.center.rows)>0,30000)
   await_ui(lambda:any(r['kind']=='INFORMACIÓN FALTANTE' for r in w.shell.center.rows),30000)
   w.main_tabs.setCurrentIndex(2);w.shell.post_tabs.setCurrentWidget(w.shell.center)
   if w.shell.center.popup:w.shell.center.popup.close()
   def click_row(kind):
    index=next(n for n,r in enumerate(w.shell.center.rows) if r['kind']==kind);w.shell.center.table.selectRow(index)
    QTest.mouseClick(w.shell.center.findChild(QPushButton,'resolve_intervention_button'),Qt.MouseButton.LeftButton)
   click_row('INFORMACIÓN FALTANTE');d=w.shell.center.popup
   assert isinstance(d,MissingInformation);await_ui(lambda:not d.loading,30000);assert d.entries and isinstance(d.control,QLineEdit)
   QTest.keyClicks(d.control,'LOCAL-CONFIRMED');QTest.mouseClick(d.confirm,Qt.MouseButton.LeftButton)
   save=next(b for b in d.findChildren(QPushButton) if b.text()=='GUARDAR Y CONTINUAR');QTest.mouseClick(save,Qt.MouseButton.LeftButton)
   await_ui(lambda:not d.saving,30000)
   await_ui(lambda:any('CAPTCHA' in r['kind'] for r in w.shell.center.rows),30000)
   click_row('CAPTCHA PENDIENTE');await_ui(human.is_set,30000);await_ui(lambda:not w.shell.worker.isRunning(),45000)
   assert focus_seen.is_set();assert len(beats)>5;assert trace==['search_local_http','evaluate']
   assert sum(method=='POST' for method,path in lab['requests'])==1
   assert lab['upload_verified'] and s.rows()[0]['state']=='ENVIADA CONFIRMADA'
   assert len(calls)==1 and not live.active(j['id'])
   assert w.main_tabs.count()==4 and 'Job Hunting' in w.windowTitle()
   output=os.environ.get('AUTOJOB_9J_GUI_REPORT')
   if output:Path(output).write_text(json.dumps(dict(window=w.windowTitle(),trace=trace,known_fields_verified=True,cv_attached=True,resolve_focused=True,human_fixture_completed=True,heartbeat=len(beats),final_posts=1,receipt=s.rows()[0]['state'],new_name=True,scope='localhost only',visible=os.environ.get('QT_QPA_PLATFORM')!='offscreen'),indent=2),encoding='utf-8')
  finally:
   if w.shell.worker and w.shell.worker.isRunning():w.shell.worker.stopped.set();live.cancel_all();await_ui(lambda:not w.shell.worker.isRunning(),30000)
   timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.close()


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_retained_ordinary_next_stage_is_completed_without_intervention(tmp_path,monkeypatch):
 from autojob.forms.submissions import SubmissionStore,SubmissionEngine,DeliveryGuard
 with portal(tmp_path,multistage=True) as lab:
  s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);native=DeliveryGuard.page;checks=[];original=live.wait_prepared
  def page(guard,url):
   p=native(guard,url);p.locator('button').evaluate("e=>e.addEventListener('click',()=>localStorage.setItem('firstStage',JSON.stringify([document.querySelector('[name=name]').value,document.querySelector('[name=email]').value])),true)");return p
  monkeypatch.setattr(DeliveryGuard,'page',page)
  def inspected(p,state,item):
   assert p.url.endswith('/form');assert p.evaluate("JSON.parse(localStorage.getItem('firstStage'))")==['Alex Rivera','alex@example.invalid'];assert p.locator('[name=cv]').evaluate('(e)=>e.files.length')==1;checks.append(True)
  fixture=dict(origin=j['application_url'].split('/start')[0],token='unused',on_prepared=inspected)
  def controlled(*args,**kwargs):kwargs['fixture']=fixture;return original(*args,**kwargs)
  monkeypatch.setattr(live,'wait_prepared',controlled)
  assert SubmissionEngine(lab['settings']).run(j['id'],a,retain=True)['state']=='ENVIADA CONFIRMADA'
  assert checks and sum(m=='POST' for m,p in lab['requests'])==1


def test_brand_keeps_private_identity_location_and_no_automatic_grant(tmp_path,qt_application_lifetime,await_ui):
 from autojob.auth.identity import IdentityStore
 from autojob.config import Settings
 store=IdentityStore(tmp_path/'data');assert 'Job Hunting' in store.private_root.parts
 w=MainWindow(Settings(tmp_path));assert 'Job Hunting' in w.windowTitle();assert w.shell.home.start.text()=='INICIAR Job Hunting';assert w.shell.delivery_authorization is None;assert w.main_tabs.count()==4
 await_ui(lambda:not w._ui_tasks,30000);w.close()

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
@pytest.mark.parametrize('new_stage',[True,False])
def test_continuation_rechecks_new_stage_but_never_retries_identical_block(tmp_path,monkeypatch,new_stage):
 from autojob.browser import BraveSession
 from autojob.forms.submissions import SubmissionEngine,DeliveryGuard
 with portal(tmp_path) as lab:
  s,j,a,ctx,bank,fixture,calls=setup(lab,monkeypatch);ready=[];ticks=[]
  with BraveSession(lab['settings']) as b:
   _,rule=s.permission(a,j);g=DeliveryGuard(b,rule['origin'],lambda:s.permission(a,j),rule);p=g.page(rule['url'])
   def human(page,state,item):
    ticks.append(1)
    if state['pending']:
     before=s.prep.inputs_hash();page.locator('[name=unknown]').fill('LOCAL');bank.save('Fictional required code','LOCAL','text','job',ctx,True);s.prep.compatibility.one(j,force=True);s.accept_confirmed_answer(a,j['id'],before)
    if page.locator('#human-check').count():page.locator('#human-check').click()
    if not new_stage and len(ticks)>4:live.command(j['id'],'LATER')
   fixture['on_prepared']=human
   def onward():
    ready.append(1)
    if len(ready)==1:
     if new_stage:p.locator('form').evaluate("e=>e.insertAdjacentHTML('beforeend','<label>Confirmed schedule<input name=followup required></label>')")
     return dict(state='PENDIENTE',reason='Nueva etapa ficticia' if new_stage else 'Bloqueo estático ficticio')
    assert p.locator('[name=followup]').input_value()=='Flexible'
    return SubmissionEngine(lab['settings']).run(j['id'],a,session=(b,p,g))
   result=live.wait_prepared(lab['settings'],b,p,g,j,a,fixture=fixture,on_ready=onward)
   assert len(ready)==(2 if new_stage else 1)
   assert result['state']==('ENVIADA CONFIRMADA' if new_stage else 'PENDIENTE')
  assert sum(m=='POST' for m,path in lab['requests'])==(1 if new_stage else 0)
