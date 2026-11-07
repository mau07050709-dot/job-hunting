from contextlib import closing
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from autojob.config import Settings
from autojob.ui.main_window import MainWindow
from autojob.forms import execution
from autojob.forms.submissions import SubmissionStore
from test_batch_https import seed


def test_every_selected_row_opens_its_own_page_after_restart(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    store,cv=seed(tmp_path);base=store.prep.compatibility.jobs.list()[0]
    for n in range(6):store.prep.compatibility.jobs.add(dict(base,id=None,source_id='button-'+str(n),company='Fixture '+str(n),url='https://jobs.lever.co/button-'+str(n),application_url='https://jobs.lever.co/button-'+str(n)+'/apply'))
    store.prep.compatibility.batch();jobs=store.prep.compatibility.jobs.list()
    token=execution.begin(store,1);attempt=store.claim(token,base);store.finish(attempt,'ENVÍO NO VERIFICADO',{'verified':False});before=store.rows()
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    w.shell.engine.queue.add([j['id'] for j in jobs]);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();opened=[]
    monkeypatch.setattr(w.shell.engine.sessions,'launch',lambda job,auth,**kw:opened.append((job,auth,kw)) or {'ready':True})
    try:
        assert len(w.shell.posts.rows)==7
        for n,row in enumerate(w.shell.posts.rows):
            w.shell.posts.table.selectRow(n);selected=row['job'];w.shell.posts.refresh()
            assert w.shell.posts.selected()['job']['id']==selected['id']
            QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
            assert opened[-1][0]==selected['id'] and opened[-1][2]['url']==selected['application_url']
            assert opened[-1][2]['readonly'] and opened[-1][1] is None
            assert 'Abriendo' in w.shell.posts.message.text()
            assert 'Solo se reanuda' not in w.shell.posts.message.text()
        assert len(opened)==7 and store.rows()==before
    finally:await_ui(lambda:not w._ui_tasks,30000);w.close()


def test_permission_failure_is_visible_and_still_opens_selected_portal(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.shell.engine.queue.add([job['id']]);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();w.shell.posts.table.selectRow(0)
    w.shell.delivery_authorization='missing-execution';opened=[]
    monkeypatch.setattr(w.shell.engine.sessions,'launch',lambda *a,**kw:opened.append((a,kw)) or {})
    try:
        QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
        assert opened[0][1]['readonly'] and opened[0][1]['url']==job['application_url']
        assert 'caducada' in w.shell.posts.message.text() and 'preparación automática' in w.shell.posts.message.text()
    finally:await_ui(lambda:not w._ui_tasks,30000);w.close()


def test_stale_reservation_without_live_owner_does_not_swallow_click(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    from autojob.auth.verifications import VerificationStore
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);v=VerificationStore(w.settings.data_path);vid=v.add(job['id'],'CAPTCHA PENDIENTE',job['application_url'],job['title'],True);opened=[]
    monkeypatch.setattr(w.shell.engine.sessions,'launch',lambda *a,**kw:opened.append((a,kw)) or {})
    try:
        w.shell.center.resolve(dict(job_id=job['id'],kind='CAPTCHA PENDIENTE',verification_id=vid))
        assert opened and opened[0][1]['url']==job['application_url']
        assert 'conserva el formulario preparado' not in w.shell.posts.message.text()
    finally:await_ui(lambda:not w._ui_tasks,30000);w.close()


def test_async_failure_is_reported_in_applications_not_only_home(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    from autojob.forms.submissions import SubmissionEngine
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.shell.engine.queue.add([job['id']]);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();w.shell.posts.table.selectRow(0)
    token=execution.begin(store,1);w.shell.delivery_authorization=token
    def unavailable(*a,**kw):raise OSError('PRIVATE_VALUE_MUST_NOT_APPEAR')
    monkeypatch.setattr(SubmissionEngine,'run',unavailable)
    try:
        QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
        await_ui(lambda:'I9I_NAVIGATION_OSError' in w.shell.posts.message.text(),30000)
        assert 'PRIVATE_VALUE' not in w.shell.posts.message.text() and not w.shell.engine.sessions.count()
    finally:await_ui(lambda:not w._ui_tasks,30000);w.close()


def test_company_exclusion_persists_and_blocks_existing_permission(tmp_path):
    from autojob.control import ControlStore
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0];token=execution.begin(store,1);store.permission(token,job)
    control=ControlStore(store.data_path);control.exclude_company(job['company'])
    assert ControlStore(store.data_path).is_excluded(job)
    with pytest.raises(ValueError,match='descartada'):store.permission(token,job)
    assert not store.rows()
