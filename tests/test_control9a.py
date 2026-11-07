from pathlib import Path
from contextlib import closing
import json,os,time
import pytest
from autojob.config import Settings
from autojob.control import Coordinator,ControlStore
from autojob.interventions import InterventionService

@pytest.fixture
def engine(tmp_path):return Coordinator(Settings(tmp_path))

OPTIONS=dict(queries=['Python'],sources=['Remotive'],limit=5)

def no_services(engine):
    return dict(search=lambda *args:dict(found=0,duplicates=0,errors=[]),geography=lambda *args:dict(reviewed=0),availability=lambda job:None,evaluate=lambda **kwargs:dict(evaluated=0,cached=0,errors=[]))

def test_four_sections_and_original_tools(tmp_path,qt_application_lifetime,await_ui):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path));w.show();assert [w.main_tabs.tabText(i) for i in range(w.main_tabs.count())]==['INICIO','MIS DATOS','POSTULACIONES','CONFIGURACIÓN']
    assert w.main_tabs.currentIndex()==0 and w.tabs.count()>=16
    cv=w.resumes_widget;w.tabs.setCurrentWidget(cv);assert cv.isVisible() and w.resumes_widget is cv
    for widget in [w.jobs_widget,w.accounts_widget,w.template_widget,w.answers_widget,w.letters_widget,w.simulator_widget,w.queue_widget,w.notifications_widget]:
        w.shell.open_advanced(widget);assert widget.isVisible() and w.main_tabs.count()==4
    w.shell.additional();assert w.profile_widget.findChild(__import__('PySide6.QtWidgets',fromlist=['QTabWidget']).QTabWidget).currentWidget()
    await_ui(lambda:not w._ui_tasks,30000);w.close();w.deleteLater()

def test_goal_persists_and_counts_are_not_faked(engine):
    engine.store.configure(target=42);assert ControlStore(engine.settings.data_path).config()['target']==42
    counts=engine.store.counts(engine.queue);assert counts['sent']==0 and counts['prepared']==0

@pytest.mark.parametrize('options',[dict(target=0),dict(target=True),dict(max_prepare=21),dict(max_verify=-1),dict(popups='yes')])
def test_invalid_limits(engine,options):
    with pytest.raises(ValueError):engine.store.configure(**options)

@pytest.mark.parametrize('confirmation,url,expected',[
 ('','https://careers.example.com/job',0),('{}','https://careers.example.com/job',0),
 (json.dumps(dict(mode='test',verified=True,receipt_id='fixture')),'https://careers.example.com/job',0),
 (json.dumps(dict(mode='real',verified=True,receipt_id='fixture')),'http://127.0.0.1/job',0),
 (json.dumps(dict(mode='real',verified=True,receipt_id='fixture')),'https://careers.example.com/job',1)])
def test_confirmed_submission_requires_evidence(engine,confirmation,url,expected):
    with closing(engine.store.db.connect()) as db,db:db.execute("INSERT INTO applications(company,title,url,discovered_at,status,applied_at,confirmation) VALUES ('Fictitious','Fixture',?,'test','ENVIADA','test',?)",(url,confirmation))
    assert engine.store.confirmed()==expected

def test_pause_resume_search_checkpoint_and_stop(engine):
    flag=[False];services=no_services(engine);calls=[]
    def search(*args):calls.append(1);flag[0]=True;return dict(found=0,duplicates=0,errors=[])
    services['search']=search;result=engine.run(OPTIONS,pause=lambda:flag[0],services=services)
    assert result['state']=='PAUSADO' and engine.store.latest()['state']=='PAUSADO'
    services['search']=lambda *args:dict(found=0,duplicates=0,errors=[])
    result=engine.run(OPTIONS,services=services);assert result['state'] in {'FINALIZADO','ESPERANDO INTERVENCIÓN'}
    assert result['run_id']==engine.store.latest()['id']
    result=engine.run(OPTIONS,stop=lambda:True,services=services);assert result['state']=='DETENIDO'

def test_restart_recovers_only_if_no_active_lock(engine):
    from autojob.browser.lock import ProfileLock
    engine.run(OPTIONS,stop=lambda:True,services=no_services(engine));id=engine.store.latest()['id'];engine.store.save_run(id,state='EN CURSO')
    lock=ProfileLock(engine.settings.data_path/'control.lock');lock.acquire()
    try:assert ControlStore(engine.settings.data_path).recover()==0
    finally:lock.release()
    assert ControlStore(engine.settings.data_path).recover()==1 and engine.store.latest()['state']=='INTERRUMPIDO'

def test_source_failure_continues_and_errors_persist(engine):
    services=no_services(engine);services['search']=lambda *args:dict(found=0,duplicates=0,errors=['unavailable'])
    result=engine.run(OPTIONS,services=services);assert 'COMPATIBILIDAD' in result['done'] and result['errors']==['FUENTE_NO_DISPONIBLE']
    assert ControlStore(engine.settings.data_path).latest()['checkpoint']['errors']

def test_unexpected_error_is_sanitized(engine):
    services=no_services(engine)
    def broken(*args):raise RuntimeError('private-value-not-for-logs')
    services['search']=broken;result=engine.run(OPTIONS,services=services)
    assert result['state']=='ERROR' and 'private-value-not-for-logs' not in json.dumps(engine.store.latest())

def test_intervention_dedup_postpone_and_omit(engine):
    id=engine.store.add_intervention('job','Company','Role','CAPTCHA','Human action','https://example.invalid/form?token=secret')
    assert engine.store.add_intervention('job','Company','Role','CAPTCHA','Human action','https://example.invalid/form')==id
    engine.store.intervention_state(id,'POSPUESTA');assert ControlStore(engine.settings.data_path).interventions()[0]['state']=='POSPUESTA'
    assert 'secret' not in json.dumps(engine.store.interventions());engine.store.omit(id);assert 'job' in engine.store.excluded()

def test_no_unverified_intervention_resolution(engine):
    id=engine.store.add_intervention('job','Company','Role','MFA','Verify on portal','https://example.invalid/form')
    assert InterventionService(engine).resume(id)[0] is False
    assert engine.store.interventions()[0]['state']=='PENDIENTE'

def test_preparation_is_never_counted_as_sent(engine):
    engine.jobs.add(dict(source='FIXTURE',source_id='1',company='Fictitious',title='Role',url='https://example.invalid/1',description='Fictitious controlled metadata'))
    id=engine.jobs.list()[0]['id'];engine.queue.add([id]);engine.queue.update(id,'PREPARADA','Fixture',dict(preview=dict(inputs_hash=engine.queue.preparation.inputs_hash())))
    counts=engine.store.counts(engine.queue);assert counts['prepared']==1 and counts['sent']==0
    engine.queue.preparation.data.faq_save('','Fixture unknown question','Fictitious response',True)
    counts=engine.store.counts(engine.queue);assert counts['prepared']==0 and counts['pending']==1

def test_ui_buttons_work_and_are_nonblocking(tmp_path,qt_application_lifetime,monkeypatch,await_ui):
    from autojob.ui.main_window import MainWindow
    from PySide6.QtTest import QTest
    from test_batch_https import seed
    seed(tmp_path);w=MainWindow(Settings(tmp_path));w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);original=w.shell.engine.run
    def run(options,pause,stop,progress,ids=None):
        services=no_services(w.shell.engine)
        def wait(*args):
            deadline=time.monotonic()+2
            while not pause() and not stop() and time.monotonic()<deadline:time.sleep(.01)
            return dict(found=0,duplicates=0,errors=[])
        services['search']=wait;return original(options,pause,stop,progress,ids,services=services)
    monkeypatch.setattr(w.shell.engine,'run',run);w.shell.home.start.click();await_ui(w.shell.busy);w.shell.home.pause.click();await_ui(lambda:not w.shell.busy(),30000);assert w.shell.engine.store.latest()['state']=='PAUSADO'
    assert w.shell.engine.store.latest()['checkpoint']['deliveries']==[]
    await_ui(lambda:not w._ui_tasks,30000);w.close();w.deleteLater()

def test_popup_is_modeless_deduplicated_and_later_persists(tmp_path,qt_application_lifetime,monkeypatch,await_ui):
    from autojob.ui.main_window import MainWindow
    from PySide6.QtWidgets import QSystemTrayIcon,QPushButton
    delivered=[];monkeypatch.setattr(QSystemTrayIcon,'showMessage',lambda self,*args:delivered.append(args))
    w=MainWindow(Settings(tmp_path));center=w.shell.center;id=w.shell.engine.store.add_intervention('job','Fictitious','Support','VIDEO','Provide a video manually','https://example.invalid')
    row=w.shell.engine.store.interventions()[0];center.show_problem(row);assert center.popup.isVisible() and not center.popup.isModal() and delivered
    assert [b.text() for b in center.popup.findChildren(QPushButton)]==['RESOLVER AHORA']
    center.popup.close();assert w.shell.engine.store.interventions()[0]['state']=='PENDIENTE'
    center.later(row)  # La función de posponer se conserva; el aviso tiene un único botón.
    assert w.shell.engine.store.interventions()[0]['state']=='POSPUESTA' and w.shell.engine.store.interventions()[0]['alerted']==1
    center.refresh();assert len(delivered)==1;await_ui(lambda:not w._ui_tasks,30000);w.close();w.deleteLater()

def test_resolve_all_moves_to_next_without_repeating(tmp_path,qt_application_lifetime):
    from autojob.ui.main_window import MainWindow
    from PySide6.QtTest import QTest
    w=MainWindow(Settings(tmp_path));center=w.shell.center
    for n in range(2):w.shell.engine.store.add_intervention(str(n),'Fictitious','Role '+str(n),'REVIEW','Manual review '+str(n))
    center.resolve_all();first=center.popup;center.later(center.rows[0]);first.close();QTest.qWait(100)
    assert len(center.cycle_seen)==2 and center.popup!=first
    center.popup.close();center.all_mode=False;w.close();w.deleteLater()

@pytest.mark.parametrize('size',[(800,650),(1100,800),(1600,950)])
def test_responsive_home_and_navigation(tmp_path,qt_application_lifetime,size):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path));w.resize(*size);w.show();qt_application_lifetime.processEvents()
    assert w.main_tabs.count()==4 and w.shell.home.start.isVisible()
    for index in range(4):w.main_tabs.setCurrentIndex(index);qt_application_lifetime.processEvents();assert w.main_tabs.currentIndex()==index
    assert w.width()<=max(size[0],900);w.close();w.deleteLater()

def test_search_preferences_survive_restart(tmp_path,qt_application_lifetime):
    from autojob.ui.main_window import MainWindow
    settings=Settings(tmp_path);w=MainWindow(settings);w.jobs_widget.keywords.setPlainText('Python\nCustomer Support')
    for source,box in w.jobs_widget.sources.items():box.setChecked(source=='Remotive')
    w.shell.save_search();w.close();again=MainWindow(settings)
    assert again.jobs_widget.keywords.toPlainText()=='Python\nCustomer Support'
    assert [s for s,b in again.jobs_widget.sources.items() if b.isChecked()]==['Remotive'];again.close();w.deleteLater();again.deleteLater()

brave=pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Local Brave integration opt-in')

@brave
def test_real_local_pipeline_intervention_resume_and_persistence(tmp_path):
    from autojob.testing.control9a import fixture_flow
    with fixture_flow(Settings(tmp_path),tmp_path) as lab:
        e=lab['engine'];result=e.run(lab['options'],services=lab['services']);assert result['eligible']==2
        assert {r['state'] for r in e.queue.list()}=={'PREPARADA','PENDIENTE'}
        intervention=e.store.interventions()[0];assert not InterventionService(e).validate(intervention)
        e.queue.preparation.data.faq_save('','Unknown mandatory project code','FICTIONAL-9A',True)
        ok,id=InterventionService(e).resume(intervention['id']);assert ok and id
        assert next(r for r in e.queue.list() if r['job_id']==id)['priority']==100000
        e.run(lab['options'],resume_ids=[id],services=lab['services']);assert all(r['state']=='PREPARADA' for r in e.queue.list())
        assert len(e.queue.list())==len(e.jobs.list())==2 and e.store.confirmed()==0
        assert all(r['method']=='GET' for r in lab['requests'])
        again=Coordinator(lab['settings']);assert len(again.queue.list())==2 and again.store.latest()['state']=='FINALIZADO'

def test_omitted_job_is_not_processed(engine):
    engine.jobs.add(dict(source='FIXTURE',source_id='omit',company='Fictitious',title='Role',url='https://example.invalid/omit',description='Fictitious controlled metadata'));id=engine.jobs.list()[0]['id'];engine.queue.add([id]);intervention=engine.store.add_intervention(id,'Fictitious','Role','REVIEW','Manual review');engine.store.omit(intervention)
    called=[];result=engine.queue.run(engine.settings,processor=lambda *args:called.append(1) or dict(state='PREPARADA'))
    assert not called and result['processed']==0


def test_moved_original_panels_are_visible(tmp_path,qt_application_lifetime):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path));w.show();w.shell.center.quiet.setChecked(True)
    for widget in [w.resumes_widget,w.profile_widget,w.application_data_widget]:
        w.shell.open(widget);qt_application_lifetime.processEvents();assert widget.isVisible() and widget.width()>200
    for widget in [w.accounts_widget,w.jobs_widget,w.answers_widget]:
        w.shell.open_advanced(widget);qt_application_lifetime.processEvents();assert widget.isVisible() and widget.width()>200
    w.close();w.deleteLater()
