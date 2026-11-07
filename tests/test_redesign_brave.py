import os,json
from threading import Event
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton,QLineEdit
from test_submissions9b import portal
from test_phase9g import setup,assert_prepared,FIELDS
from autojob.ui.main_window import MainWindow
from autojob.forms import execution
from autojob.forms.submissions import DeliveryGuard
from autojob.forms.answers9b import ScopedAnswers
import autojob.live as live

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_start_continues_while_pending_and_resolve_preserves_or_restores(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    with portal(tmp_path) as lab:
        store,job,old,ctx,bank,fixture,calls=setup(lab,monkeypatch);store.revoke(old)
        e=lab['engine'];e.jobs.add(dict(job,id=None,source_id='second',company='Fictional Second',url=fixture['origin']+'/job/second',application_url=fixture['origin']+'/form?fixture=second',description=job['description']+'\nNice to have:\nDocker.'))
        second=next(j for j in e.jobs.list() if j['company']=='Fictional Second');context=dict(ctx,job_id=second['id'],company=second['company'])
        for label,name,value in FIELDS+[('Confirmed schedule','dynamic','Flexible')]:bank.save(label,value,'text','job',context,True)
        store.prep.compatibility.batch()
        original_page=DeliveryGuard.page
        def page(guard,url):
            p=original_page(guard,url)
            if 'fixture=second' in url:p.locator('[name=unknown]').evaluate('(e)=>e.parentElement.remove()')
            return p
        monkeypatch.setattr(DeliveryGuard,'page',page)
        first_ready=Event();restored=Event();human=Event();lose=Event();native=live.wait_prepared
        def observe(p,state,item):
            assert_prepared(p)
            if 'fixture=second' in p.url:
                if p.locator('#human-check').count():p.locator('#human-check').click()
            else:
                first_ready.set()
                if len(calls)>=3:restored.set()
                if lose.is_set():lose.clear();p.close();return
                if len(calls)>=3 and human.is_set():
                    p.locator('[name=unknown]').fill('LOCAL-ORDINARY-ANSWER')
                    if p.locator('#human-check').count():p.locator('#human-check').click()
                    human.clear()
        fixture['on_prepared']=observe
        def wait_human(p,id,store):
            assert_prepared(p);original=p.wait_for_timeout
            def tick(ms):
                if human.is_set():
                    if p.locator('[name=unknown]').count():p.locator('[name=unknown]').fill('LOCAL-ORDINARY-ANSWER')
                    if p.locator('#human-check').count():p.locator('#human-check').click()
                    human.clear()
                original(ms)
            monkeypatch.setattr(p,'wait_for_timeout',tick)
        fixture['on_wait']=wait_human
        def retained(*a,**kw):kw['fixture']=fixture;return native(*a,**kw)
        monkeypatch.setattr(live,'wait_prepared',retained)
        begin=execution.begin
        monkeypatch.setattr(execution,'begin',lambda s,target:begin(s,target,'local',True))
        monkeypatch.setattr('autojob.ui.batch_ui.BatchAuthorization.exec',lambda *a:pytest.fail('No pedir lotes'))
        w=MainWindow(lab['settings']);w.resize(1280,900);w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
        shell=w.shell;shell.engine.store.configure(target=2);native_run=shell.engine.run
        def search(*a):
            from urllib.request import urlopen
            with urlopen(job['url']) as r:assert r.status==200
            return dict(found=2,duplicates=0,errors=[])
        def run(*a,**kw):kw['services']=dict(search=search,geography=lambda *a:None,availability=lambda *a:None);return native_run(*a,**kw)
        monkeypatch.setattr(shell.engine,'run',run)
        beats=[]
        from PySide6.QtCore import QTimer
        beat=QTimer(w);beat.timeout.connect(lambda:beats.append(1));beat.start(50)
        try:
            QTest.mouseClick(shell.home.start,Qt.MouseButton.LeftButton)
            await_ui(first_ready.is_set,60000)
            await_ui(lambda:shell.center.popup is not None and shell.center.popup.isVisible(),30000)
            buttons=shell.center.popup.findChildren(QPushButton)
            assert {b.text() for b in buttons}=={'RESOLVER AHORA','RESOLVER MÁS TARDE'}
            # No posponer ni resolver la primera: la segunda debe avanzar por sí sola.
            await_ui(lambda:not shell.busy(),90000)
            await_ui(lambda:any(r['state']=='ENVIADA CONFIRMADA' and r['job_id']==second['id'] for r in store.rows()),60000)
            assert sum(m=='POST' for m,p in lab['requests'])==1 and len(calls)==2
            assert store.rows()[0]['state']=='ENVIADA CONFIRMADA'
            assert live.active(job['id']) and shell.engine.sessions.contains(job['id'])
            QTest.mouseClick(buttons[0],Qt.MouseButton.LeftButton)
            await_ui(lambda:shell.engine.sessions.tasks[job['id']]['focus'] is False,30000)
            assert len(calls)==2  # Enfocar nunca abre otra página ni vacía el CV.
            # Cierre explícito de la persona; recuperación posterior segura.
            lose.set();await_ui(lambda:not shell.engine.sessions.contains(job['id']),30000)
            # User resolves the deferred application through the sole applications table.
            w.main_tabs.setCurrentIndex(2);shell.posts.refresh();n=next(n for n,r in enumerate(shell.posts.rows) if r['job']['id']==job['id']);shell.posts.table.selectRow(n)
            QTest.mouseClick(shell.posts.action,Qt.MouseButton.LeftButton)
            await_ui(restored.is_set,60000)
            from autojob.ui.submission_ui import MissingInformation
            from autojob.ui.receipt_review import ReceiptReview
            assert not any(isinstance(d,(MissingInformation,ReceiptReview)) and d.isVisible() for d in qt_application_lifetime.topLevelWidgets())
            human.set()  # La persona responde directamente en la página del portal.
            await_ui(lambda:not shell.engine.sessions.count(),90000)
            assert sum(m=='POST' for m,p in lab['requests'])==2 and len(calls)==3
            assert len(store.rows())==2 and all(r['state']=='ENVIADA CONFIRMADA' and r['evidence']['verified'] for r in store.rows())
            assert len(beats)>10 and not live.active()
            shell.posts.refresh();assert len(shell.posts.rows)==2 and all(r['confirmed'] for r in shell.posts.rows)
            proof=dict(start_without_authorization_dialog=True,resolve_direct_to_portal=True,no_information_or_receipt_dialog=True,intervention_buttons=['RESOLVER AHORA','RESOLVER MÁS TARDE'],initial_queue=2,known_fields=True,cv_attached=True,continued_while_first_pending=True,same_prepared_session_focused=True,lost_session_restored=True,posts=2,confirmed=2,duplicate_posts=0,ui_heartbeat=len(beats),scope='localhost only')
            out=os.environ.get('AUTOJOB_REDESIGN_REPORT')
            if out:Path(out).write_text(json.dumps(proof,indent=2),encoding='utf-8')
        finally:
            beat.stop();live.cancel_all();shell.engine.sessions.cancel_all();shell.feed_timer.stop();await_ui(lambda:not shell.engine.sessions.count(),30000)
            if shell.worker and shell.worker.isRunning():shell.worker.stopped.set();await_ui(lambda:not shell.busy(),30000)
            if getattr(shell.center,'direct_worker',None):shell.center.direct_worker.cancelled.set();await_ui(lambda:not shell.center.direct_worker.isRunning(),30000)
            if getattr(shell.center,'operation_popup',None):shell.center.operation_popup.close()
            await_ui(lambda:not w._ui_tasks,30000);w.close()
