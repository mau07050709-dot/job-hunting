from contextlib import closing
import json,os
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from autojob.config import Settings
from autojob.control import ControlStore
from autojob.forms import execution
from autojob.forms.submissions import SubmissionStore
from autojob.ui.main_window import MainWindow
from test_batch_https import seed


def test_discard_persists_same_offer_and_cross_source_identifiers_not_company(tmp_path):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];control=ControlStore(s.data_path)
    result=control.dispositions.discard(j)
    assert result['state']=='DESCARTADA POR EL USUARIO'
    again=ControlStore(s.data_path);assert again.is_excluded(j)
    assert again.is_excluded(dict(j,id='other-source-id',source='OTHER',source_id='new',url=j['application_url']+'?utm_source=feed',application_url=j['application_url']+'?utm_source=feed'))
    assert again.is_excluded(dict(j,id='changed-url',url='https://different.invalid/changed',application_url='https://different.invalid/form'))  # Mismo identificador de la fuente.
    assert not again.is_excluded(dict(j,id='different-position',source_id='new-position',url='https://jobs.lever.co/another',application_url='https://jobs.lever.co/another/apply'))
    keys=again.dispositions.get(j)
    assert keys['url']==j['application_url'] and not keys['hidden']


def test_official_greenhouse_id_blocks_alias_across_hosts_and_tracking(tmp_path):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];control=ControlStore(s.data_path)
    j=dict(j,url='https://boards.greenhouse.io/fictional/jobs/12345',application_url='https://boards.greenhouse.io/fictional/jobs/12345?gh_src=original')
    control.dispositions.discard(j)
    alias=dict(j,id='alias',source='another',source_id='another-id',url='https://other.invalid/listing',application_url='https://job-boards.greenhouse.io/fictional/jobs/12345?utm_source=another')
    assert control.is_excluded(alias)
    assert not control.is_excluded(dict(alias,application_url='https://job-boards.greenhouse.io/fictional/jobs/98765'))


def test_shared_careers_homepage_does_not_exclude_other_position(tmp_path):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];control=ControlStore(s.data_path)
    control.dispositions.discard(dict(j,application_url='https://employer.invalid/careers'))
    other=dict(j,id='different-role',source_id='second-official-id',url='https://jobs.lever.co/different-position',application_url='https://employer.invalid/careers')
    assert not control.is_excluded(other)


@pytest.mark.parametrize('state',['ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','ENVIANDO'])
def test_archive_preserves_submission_receipt_events_and_confirmed_counter(tmp_path,state):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1);attempt=s.claim(token,j)
    evidence=dict(verified=state=='ENVIADA CONFIRMADA',mode='real',receipt_id='FICTIONAL-PROOF',original='unchanged')
    if state!='ENVIANDO':s.finish(attempt,state,evidence)
    control=ControlStore(s.data_path);before=s.rows();confirmed=control.confirmed()
    if state=='ENVIADA CONFIRMADA':assert confirmed==1
    with closing(s.db.connect()) as db:events=db.execute('SELECT * FROM submission_events ORDER BY id').fetchall()
    result=control.dispositions.discard(j,hide=True)
    assert result['previous_submission']==state and result['state']=='RESULTADO FINAL CONSERVADO'
    assert s.rows()==before and control.confirmed()==confirmed
    with closing(s.db.connect()) as db:assert events==db.execute('SELECT * FROM submission_events ORDER BY id').fetchall()
    assert ControlStore(s.data_path).dispositions.get(j)['hidden']
    with pytest.raises(ValueError):s.claim(token,j)
    assert s.rows()==before


def test_exclusion_wins_if_recorded_between_permission_and_claim(tmp_path,monkeypatch):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1);permission=s.permission(token,j)
    ControlStore(s.data_path).dispositions.discard(j)
    monkeypatch.setattr(s,'permission',lambda *a:permission)
    with pytest.raises(ValueError,match='descartada'):s.claim(token,j)
    assert not s.rows()


def test_archive_pending_via_button_confirmation_restart_and_rediscovery(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];w=MainWindow(Settings(tmp_path));w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    w.shell.engine.queue.add([j['id']]);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();w.shell.posts.table.selectRow(0)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No)
    QTest.mouseClick(w.shell.posts.remove_button,Qt.MouseButton.LeftButton);assert w.shell.posts.rows
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    QTest.mouseClick(w.shell.posts.remove_button,Qt.MouseButton.LeftButton)
    await_ui(lambda:not w._ui_tasks,30000);assert not w.shell.posts.rows
    assert w.shell.engine.store.is_excluded(j);assert w.shell.engine.queue.list()[0]['state']=='BLOQUEADA'
    w.close();w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    try:
        assert not w.shell.engine.jobs.add(dict(j,id=None))  # El conector devuelve de nuevo la misma oferta.
        w.shell.engine.queue.add([j['id']]);w.shell.posts.refresh();assert not w.shell.posts.rows
        assert len(w.shell.engine.jobs.list())==1
    finally:w.close()


@pytest.mark.parametrize('state',['ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO'])
def test_hide_sent_or_uncertain_using_table_keeps_historical_counter(tmp_path,state,qt_application_lifetime,await_ui,monkeypatch):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1);attempt=s.claim(token,j)
    s.finish(attempt,state,dict(verified=state=='ENVIADA CONFIRMADA',mode='real',receipt_id='LOCAL-UNIT',original='unchanged'))
    before=s.rows();w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    count=w.shell.engine.store.confirmed();w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();w.shell.posts.table.selectRow(0)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    QTest.mouseClick(w.shell.posts.remove_button,Qt.MouseButton.LeftButton)
    await_ui(lambda:not w._ui_tasks,30000)
    assert not w.shell.posts.rows and s.rows()==before and w.shell.engine.store.confirmed()==count
    w.close();w2=MainWindow(Settings(tmp_path));w2.shell.timer.stop();await_ui(lambda:not w2._ui_tasks,30000)
    w2.shell.posts.refresh();assert not w2.shell.posts.rows and w2.shell.engine.store.confirmed()==count;w2.close()


def test_skip_disabled_without_active_job(tmp_path,qt_application_lifetime,await_ui):
    w=MainWindow(Settings(tmp_path));w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    w.shell.session_tick();assert not w.shell.home.skip.isEnabled() and 'No hay' in w.shell.home.active.text();w.close()


def test_skip_failed_navigation_does_not_block_ui_and_requests_next_run(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    from threading import Event
    from autojob.forms.submissions import SubmissionEngine
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];w=MainWindow(Settings(tmp_path));w.show();shell=w.shell;shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    entered=Event();token=execution.begin(s,2);shell.delivery_authorization=token;shell.advance_on_discard=True
    def navigation(self,id,token,**kw):
        entered.set()
        while not kw['stop']():__import__('time').sleep(.01)
        raise TimeoutError('Fictional navigation stopped')
    monkeypatch.setattr(SubmissionEngine,'run',navigation);resumed=[];monkeypatch.setattr(shell,'start',lambda *a,**kw:resumed.append(kw))
    task=shell.engine.sessions.launch(j['id'],token);beats=[];timer=QTimer(w);timer.timeout.connect(lambda:beats.append(1));timer.start(10)
    try:
        await_ui(entered.is_set,30000);shell.session_tick();QTest.mouseClick(shell.home.skip,Qt.MouseButton.LeftButton)
        await_ui(lambda:not task['thread'].is_alive() and bool(resumed),30000)
        assert shell.engine.store.is_excluded(j) and len(beats)>1
        assert resumed==[dict(ids=None,user_initiated=False)] and not s.rows()
    finally:timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.close()


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave real y recepción localhost controlada')
@pytest.mark.parametrize('unverified',[False,True])
def test_skip_after_post_observes_receipt_without_cancelling_or_repeating(tmp_path,monkeypatch,qt_application_lifetime,await_ui,unverified):
    from threading import Event
    from test_submissions9b import portal
    import autojob.forms.confirmations as confirmations
    import autojob.live as live
    with portal(tmp_path,unverified=unverified) as lab:
        s=SubmissionStore(lab['settings'].data_path);job=lab['job'];inflight=Event();release=Event();native=confirmations.collect
        def observe(page,*a):
            inflight.set()
            while not release.is_set():page.wait_for_timeout(50)
            return native(page,*a)
        monkeypatch.setattr(confirmations,'collect',observe)
        w=MainWindow(lab['settings']);w.show();shell=w.shell;shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
        token=execution.begin(s,1,'local',True);shell.delivery_authorization=token;shell.advance_on_discard=True
        # Simular un trabajador final: la recepción real local queda en observación.
        shell.engine.sessions.launch(job['id'],token)
        try:
            await_ui(inflight.is_set,60000);assert lab['requests'].count(('POST','/submit'))==1 and s.rows()[0]['state']=='ENVIANDO'
            shell.session_tick();QTest.mouseClick(shell.home.skip,Qt.MouseButton.LeftButton)
            await_ui(lambda:shell.engine.store.is_excluded(job),30000)
            assert s.rows()[0]['state']=='ENVIANDO'  # Un clic nunca lo clasifica como cancelado.
            shell.advance_on_discard=False;release.set()
            await_ui(lambda:not shell.engine.sessions.count(),60000)
            expected='ENVÍO NO VERIFICADO' if unverified else 'ENVIADA CONFIRMADA'
            assert s.rows()[0]['state']==expected and s.rows()[0]['evidence']['verified'] is (not unverified)
            assert lab['requests'].count(('POST','/submit'))==1 and s.duplicate(job)
            from autojob.forms.submissions import SubmissionEngine
            assert SubmissionEngine(lab['settings']).run(job['id'],token)['state']=='BLOQUEADA'
        finally:
            release.set();shell.advance_on_discard=False;shell.continue_after_discard=None;shell.feed_timer.stop();shell.engine.sessions.cancel_all();live.cancel_all();await_ui(lambda:not shell.engine.sessions.count(),30000);await_ui(lambda:not w._ui_tasks,30000);w.close()


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave real y formularios localhost separados')
def test_three_local_forms_skip_and_continue_archive_restart(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    from threading import Event
    from test_submissions9b import portal
    from test_phase9g import setup,assert_prepared,FIELDS
    import autojob.live as live
    with portal(tmp_path) as lab:
        s,first,old,ctx,bank,fixture,calls=setup(lab,monkeypatch);s.revoke(old);e=lab['engine']
        for n in range(2):e.jobs.add(dict(first,id=None,source_id='skip-'+str(n),company='Fictional '+str(n),url=fixture['origin']+'/job/'+str(n),application_url=fixture['origin']+'/form?candidate='+str(n)))
        for j in e.jobs.list():
            if j['id']==first['id']:continue
            for label,name,value in FIELDS+[('Confirmed schedule','dynamic','Flexible')]:bank.save(label,value,'text','job',dict(ctx,job_id=j['id'],company=j['company']),True)
        e.compatibility.batch();observed=[];native=live.wait_prepared
        def inspect_form(page,state,item):
            assert_prepared(page)
            if not observed:
                owner=next(j['id'] for j in e.jobs.list() if j['application_url']==page.url)
                live.command(owner,'FOCUS')
            if page.url not in observed:observed.append(page.url)
        fixture['on_prepared']=inspect_form
        def wait(*a,**kw):kw['fixture']=fixture;return native(*a,**kw)
        monkeypatch.setattr(live,'wait_prepared',wait)
        begin=execution.begin;monkeypatch.setattr(execution,'begin',lambda s,target,*a:begin(s,target,'local',True))
        w=MainWindow(lab['settings']);w.resize(1150,900);w.show();shell=w.shell;shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
        shell.engine.sessions.limit=1;run=shell.engine.run
        def controlled(*a,**kw):kw['services']=dict(search=lambda *a:dict(found=3,errors=[]),geography=lambda *a:None,availability=lambda *a:None);return run(*a,**kw)
        monkeypatch.setattr(shell.engine,'run',controlled)
        beats=[];timer=QTimer(w);timer.timeout.connect(lambda:beats.append(1));timer.start(25)
        try:
            QTest.mouseClick(shell.home.start,Qt.MouseButton.LeftButton)
            await_ui(lambda:bool(observed),60000)
            id=shell.engine.active_job();j=next(j for j in e.jobs.list() if j['id']==id)
            # La persona tiene esta sesión; impedir que se estacione mientras pulsa saltar.
            assert live.command(id,'FOCUS');shell.session_tick();assert shell.home.skip.isEnabled()
            QTest.mouseClick(shell.home.skip,Qt.MouseButton.LeftButton)
            await_ui(lambda:shell.engine.store.is_excluded(j) and not shell.engine.sessions.contains(id),30000)
            await_ui(lambda:len(observed)>=2,90000)
            assert all(url!=j['application_url'] for url in observed[1:]) and not any(m=='POST' for m,p in lab['requests'])
            await_ui(lambda:len(observed)==3 and not shell.busy(),90000)
            assert len(calls)==3 and len(observed)==3 and len(beats)>50
            assert shell.engine.queue.list() and not s.rows()
            w.main_tabs.setCurrentIndex(2);shell.posts.refresh()
            target=next(r for r in shell.posts.rows if r['job']['id']!=id);target_id=target['job']['id'];shell.posts.table.selectRow(next(n for n,r in enumerate(shell.posts.rows) if r['job']['id']==target_id))
            # Confirmación nativa real, aceptada por el propio laboratorio local.
            def confirm():
                dialog=qt_application_lifetime.activeModalWidget()
                if isinstance(dialog,QMessageBox):QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Yes),Qt.MouseButton.LeftButton)
            QTimer.singleShot(150,confirm);QTest.mouseClick(shell.posts.remove_button,Qt.MouseButton.LeftButton)
            await_ui(lambda:not w._ui_tasks,30000);assert target_id not in [r['job']['id'] for r in shell.posts.rows]
            proof=dict(three_forms_opened=True,skip_button_clicked=True,next_started_without_start=True,duplicates=0,hidden_pending=True,no_external_posts=True,ui_heartbeats=len(beats),qt_platform=qt_application_lifetime.platformName())
            out=os.environ.get('AUTOJOB_SKIP_REPORT')
            if out:
                from pathlib import Path
                Path(out).write_text(json.dumps(proof,indent=2),encoding='utf-8');w.grab().save(str(Path(out).with_suffix('.png')))
        finally:
            timer.stop();shell.advance_on_discard=False;shell.continue_after_discard=None;shell.engine.sessions.cancel_all();live.cancel_all();shell.feed_timer.stop()
            if shell.busy():shell.worker.stopped.set();await_ui(lambda:not shell.busy(),30000)
            await_ui(lambda:not shell.engine.sessions.count(),30000);await_ui(lambda:not w._ui_tasks,30000);w.close()
        w2=MainWindow(lab['settings']);w2.shell.timer.stop();await_ui(lambda:not w2._ui_tasks,30000)
        try:
            assert w2.shell.engine.store.is_excluded(j);assert not w2.shell.engine.jobs.add(dict(j,id=None))
            w2.shell.posts.refresh();assert target_id not in [r['job']['id'] for r in w2.shell.posts.rows]
        finally:w2.close()
