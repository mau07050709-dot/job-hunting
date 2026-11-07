import os,sqlite3,shutil,json
from pathlib import Path
import pytest
from PySide6.QtWidgets import QPushButton
from autojob.config import Settings
from autojob.ui.main_window import MainWindow
from autojob.ui.intervention_feedback import ActionRequired,InterventionWorker,plan,display
from autojob.forms.submissions import SubmissionStore
from autojob.live import historical

@pytest.fixture
def persisted(tmp_path):
    env=os.environ.get('AUTOJOB_REAL_COPY_9I')
    if not env:pytest.skip('Copia privada persistida disponible solo en integración 9I')
    source=Path(env);(tmp_path/'data').mkdir();a=sqlite3.connect(source/'autojob.sqlite3');b=sqlite3.connect(tmp_path/'data/autojob.sqlite3');a.backup(b);a.close();b.close();shutil.copytree(source/'resumes',tmp_path/'data/resumes')
    for f in ['compatibility-rules.json','resume-selection-rules.json']:
        if (source/f).exists():shutil.copy2(source/f,tmp_path/'data'/f)
    return Settings(tmp_path)

def row_for(w,kind):return next(r for r in w.shell.engine.store.interventions() if r['company'].lower()=='doola' and r['kind']==kind and r['state']=='PENDIENTE')

@pytest.mark.parametrize('kind',['CAPTCHA PENDIENTE','INFORMACIÓN FALTANTE'])
def test_persisted_doola_button_reports_exact_permission(persisted,qt_application_lifetime,await_ui,monkeypatch,kind):
    monkeypatch.setattr(InterventionWorker,'start',lambda self:pytest.fail('Sin permiso no transmitir datos'))
    w=MainWindow(persisted);w.shell.timer.stop();w.shell.start=lambda *a,**k:None;await_ui(lambda:not w._ui_tasks,timeout=30000);c=w.shell.center;c.refresh();row=row_for(w,kind);index=next(i for i,r in enumerate(c.rows) if r['id']==row['id']);c.table.selectRow(index)
    assert c.selected()['id']==row['id'];next(b for b in c.findChildren(QPushButton) if b.objectName()=='resolve_intervention_button').click()
    assert isinstance(c.popup,ActionRequired) and c.popup.isVisible()
    original=c.popup;next(b for b in c.findChildren(QPushButton) if b.objectName()=='resolve_intervention_button').click();assert c.popup is original
    assert 'Se necesita autorización para adjuntar el CV seleccionado' in c.status.text()
    p=plan(persisted,row,None);assert p['cv_id'] and p['cv_title'] and p['url']=='https://jobs.lever.co/doola/999a0f10-0738-42f7-a9f6-5c7192e74873/apply'
    assert historical(SubmissionStore(persisted.data_path),row['job_id']) is None
    # El caso que faltaba antes: otras candidaturas sí tienen intentos inciertos.
    assert len([a for a in SubmissionStore(persisted.data_path).rows() if a['state']=='ENVÍO NO VERIFICADO'])>=2
    c.popup.close();await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()

def test_persisted_selection_survives_background_refresh(persisted,qt_application_lifetime,await_ui):
    w=MainWindow(persisted);w.shell.timer.stop();w.shell.start=lambda *a,**k:None;await_ui(lambda:not w._ui_tasks,timeout=30000);c=w.shell.center;c.refresh();r=row_for(w,'CAPTCHA PENDIENTE');c.table.selectRow(next(i for i,x in enumerate(c.rows) if x['id']==r['id']))
    c.shell.request_refresh();await_ui(lambda:not w._ui_tasks,timeout=30000);assert c.selected()['id']==r['id'];w.close()

def test_persisted_expired_permission_and_known_cv(persisted,qt_application_lifetime,await_ui):
    w=MainWindow(persisted);w.shell.timer.stop();w.shell.start=lambda *a,**k:None;await_ui(lambda:not w._ui_tasks,timeout=30000);r=row_for(w,'INFORMACIÓN FALTANTE');p=plan(persisted,r,'expired-or-revoked-id')
    assert p['authorization_required'] and 'caducó' in p['message'] and p['cv_title']
    assert display(r)[0]=='AUTORIZACIÓN CV';w.close()

def test_no_selection_has_visible_feedback(tmp_path,qt_application_lifetime,await_ui):
    w=MainWindow(Settings(tmp_path));w.shell.center.resolve(False);assert 'Selecciona una intervención' in w.shell.center.status.text();await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()

def test_unexpected_controller_error_is_visible_without_private_log(tmp_path,qt_application_lifetime,await_ui,monkeypatch,caplog):
    w=MainWindow(Settings(tmp_path));monkeypatch.setattr(w.shell.center,'resolve_selected',lambda *a:(_ for _ in ()).throw(ValueError('PRIVATE_TOKEN_123')))
    w.shell.center.resolve();assert 'I9I_INTERVENTION_ValueError' in w.shell.center.status.text();assert 'PRIVATE_TOKEN_123' not in caplog.text
    assert w.shell.center.popup is None;await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()

def test_worker_error_visible_and_safe(tmp_path,qt_application_lifetime,await_ui,monkeypatch,caplog):
    from autojob.browser import BraveSession
    w=MainWindow(Settings(tmp_path));monkeypatch.setattr('autojob.browser.BraveSession',lambda *a,**kw:(_ for _ in ()).throw(OSError('PRIVATE_PASSWORD')))
    w.shell.view_sent(dict(job=dict(url='https://jobs.lever.co/fixture'),attempt={}))
    await_ui(lambda:'I9I_NAVIGATION_OSError' in w.shell.home.status.text());assert 'PRIVATE_PASSWORD' not in caplog.text and w.shell.center.popup is None
    await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()

def test_new_notification_after_worker_completed_but_not_historical(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.background import snapshot
    from autojob.control import now
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,timeout=30000);c=w.shell.center;shown=[];monkeypatch.setattr(c,'show_problem',lambda r,config:shown.append(r['id']))
    old=w.shell.engine.store.add_intervention('old','Fictitious','Old','VIDEO','Old historical notice','https://example.invalid/old');c.notification_cutoff=now()
    new=w.shell.engine.store.add_intervention('new','Fictitious','New','VIDEO','New blocker','https://example.invalid/new');assert not w.shell.occupied()
    c.apply_snapshot(snapshot(w.settings));assert shown==[new] and old not in shown
    c.quiet.setChecked(True);c.apply_snapshot(snapshot(w.settings));assert shown==[new];w.close()

def test_waiting_reason_is_explicit_and_preserves_search_evaluation(tmp_path):
    from autojob.testing.control9a import fixture_flow
    with fixture_flow(Settings(tmp_path),tmp_path) as lab:
        result=lab['engine'].run(lab['options'],services=lab['services']);latest=lab['engine'].store.latest()
        if result['state']=='ESPERANDO INTERVENCIÓN':assert 'intervenciones pendientes' in latest['operation']
        assert 'BÚSQUEDA' in result['done'] and 'COMPATIBILIDAD' in result['done']

def test_historical_cloudbeds_and_fiveca_cannot_restart(persisted,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.receipt_review import ReceiptReview
    w=MainWindow(persisted);w.shell.timer.stop();w.shell.start=lambda *a,**k:None;await_ui(lambda:not w._ui_tasks,timeout=30000);monkeypatch.setattr(w.shell.center,'open_direct',lambda *a,**k:pytest.fail('No reabrir históricos'))
    for a in SubmissionStore(persisted.data_path).rows():
        if a['state']!='ENVÍO NO VERIFICADO':continue
        w.shell.center.resolve(dict(job_id=a['job_id'],kind='REQUIERE LOGIN',verification_id=None));assert isinstance(w.shell.center.popup,ReceiptReview);w.shell.center.popup.close()
    await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()


def test_stale_snapshot_does_not_repeat_same_notification(tmp_path,qt_application_lifetime,await_ui):
 from autojob.ui.background import snapshot
 w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,timeout=30000);c=w.shell.center
 w.shell.engine.store.add_intervention('fixture','Fictitious','New blocker','VIDEO','Manual video required','https://example.invalid')
 data=snapshot(w.settings);c.apply_snapshot(data);first=c.popup;assert first.isVisible();first.close();c.apply_snapshot(data)
 assert c.popup is first and not first.isVisible();w.close()


def test_invalid_persisted_reference_is_visible_not_silent(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
 w=MainWindow(Settings(tmp_path));id=w.shell.engine.store.add_intervention('removed-job','Fictitious','Support','VIDEO','Manual action','https://example.invalid/form')
 row=next(r for r in w.shell.engine.store.interventions() if r['id']==id);monkeypatch.setattr(w.shell.center,'open_direct',lambda *a:pytest.fail('No abrir referencia inválida'))
 w.shell.center.resolve(row);assert w.shell.center.popup is None;assert 'referencia válida' in w.shell.center.status.text();await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()


def test_permission_review_when_busy_keeps_visible_explanation(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
 w=MainWindow(Settings(tmp_path));monkeypatch.setattr(w.shell,'occupied',lambda:True)
 popup=ActionRequired(w.shell.center,dict(company='Fictional',title='Support',job_id='j'),'Authorization required');popup.show();popup.review()
 assert popup.isVisible() and 'ocupados' in popup.status.text() and w.shell.delivery_authorization is None
 popup.close();await_ui(lambda:not w._ui_tasks,timeout=30000);w.close()


@pytest.mark.parametrize('state,pending,eligible,queued,free,scheduled,expected',[
 ('PAUSADO',2,3,1,True,False,'Pausado por el usuario'),
 ('DETENIDO',2,3,1,True,False,'Detenido por el usuario'),
 ('ESPERANDO INTERVENCIÓN',7,3,0,True,False,'Sin candidaturas procesables actualmente. Hay 7'),
 ('ESPERANDO INTERVENCIÓN',2,0,0,True,False,'No quedan vacantes elegibles'),
 ('ESPERANDO INTERVENCIÓN',2,3,1,False,False,'Brave está reservado'),
 ('ESPERANDO INTERVENCIÓN',2,3,1,True,False,'Se alcanzó el límite'),
 ('ESPERANDO INTERVENCIÓN',2,3,0,True,True,'búsqueda programada pendiente')])
def test_completion_reasons_are_distinct(state,pending,eligible,queued,free,scheduled,expected):
 from autojob.control import completion_text
 assert expected in completion_text(state,pending,eligible,queued,free,scheduled)


def test_local_cv_metadata_does_not_resolve_upload_requirement(tmp_path):
 from test_submissions9b import portal
 from autojob.interventions import InterventionService
 with portal(tmp_path) as lab:
  e=lab['engine'];j=lab['job'];e.queue.add([j['id']]);id=e.store.add_intervention(j['id'],j['company'],j['title'],'INFORMACIÓN FALTANTE','Revisar campos requeridos: Resume/CV',j['application_url'])
  row=next(r for r in e.store.interventions() if r['id']==id)
  assert not InterventionService(e).validate(row)
