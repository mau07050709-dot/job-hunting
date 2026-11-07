import os
from threading import Event
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_submissions9b import portal
from test_phase9g import setup,assert_prepared,FIELDS
from autojob.ui.main_window import MainWindow
from autojob.config import Settings
from autojob.forms import execution
import autojob.live as live

pytestmark=pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Integración con Brave y formularios localhost separada')


def test_closed_job_http404_keeps_browser_open_for_review(tmp_path):
    from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
    from threading import Thread
    from autojob.form_sessions import FormSessions
    posts=[]
    class Closed(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            body=b'<html><body><h1>This job is not available</h1></body></html>'
            self.send_response(404);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
        def do_POST(self):posts.append(self.path);self.send_error(405)
    server=ThreadingHTTPServer(('127.0.0.1',0),Closed);thread=Thread(target=server.serve_forever,daemon=True);thread.start();pool=FormSessions(Settings(tmp_path))
    task=pool.launch('closed-job',None,readonly=True,url='http://127.0.0.1:'+str(server.server_port)+'/job',mode='local')
    try:
        assert task['ready'].wait(30000/1000) and task['thread'].is_alive()
        assert 'ya no está disponible' in task['message'] and not posts
    finally:
        pool.cancel_all();task['thread'].join(30);server.shutdown();server.server_close();thread.join(2)
    assert not task['thread'].is_alive() and not posts


def close(w,await_ui):
    w.shell.engine.sessions.cancel_all();live.cancel_all();w.shell.feed_timer.stop()
    if w.shell.busy():w.shell.worker.stopped.set();await_ui(lambda:not w.shell.busy(),30000)
    await_ui(lambda:not w.shell.engine.sessions.count(),30000)
    await_ui(lambda:not w._ui_tasks,30000);w.close()


def test_restart_click_restores_prepared_form_and_other_row_opens_without_post(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    with portal(tmp_path) as lab:
        store,job,old,ctx,bank,fixture,calls=setup(lab,monkeypatch)
        e=lab['engine'];e.jobs.add(dict(job,id=None,source_id='consultation',company='Fictional Incompatible',geography='INCOMPATIBLE',url=fixture['origin']+'/other-job',application_url=fixture['origin']+'/form?consultation=1'))
        e.compatibility.batch();other=next(j for j in e.jobs.list() if j['company']=='Fictional Incompatible')
        ready=Event();native=live.wait_prepared
        def observe(page,state,item):assert_prepared(page);ready.set()
        fixture['on_prepared']=observe
        def wait(*a,**kw):kw['fixture']=fixture;return native(*a,**kw)
        monkeypatch.setattr(live,'wait_prepared',wait)
        w=MainWindow(lab['settings']);w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
        real_consult=w.shell.view_sent
        def local_consult(row):
            assert (row['job'].get('application_url') or row['job']['url']).startswith(fixture['origin']+'/')
            return real_consult(dict(row,attempt=dict(row.get('attempt',{}),mode='local')))
        monkeypatch.setattr(w.shell,'view_sent',local_consult)
        w.shell.engine.queue.add([job['id'],other['id']]);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh()
        try:
            assert w.shell.delivery_authorization is None
            w.shell.posts.table.selectRow(next(n for n,r in enumerate(w.shell.posts.rows) if r['job']['id']==job['id']))
            QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton);await_ui(ready.is_set,60000)
            assert len(calls)==1 and not lab['requests'].count(('POST','/submit'))
            w.shell.posts.table.selectRow(next(n for n,r in enumerate(w.shell.posts.rows) if r['job']['id']==other['id']))
            QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
            await_ui(lambda:lab['requests'].count(('GET','/form?consultation=1'))==1,30000)
            await_ui(lambda:'Página seleccionada abierta' in w.shell.posts.message.text(),30000)
            QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
            await_ui(lambda:not w.shell.engine.sessions.tasks[other['id']]['focus'],30000)
            assert lab['requests'].count(('GET','/form?consultation=1'))==1
            assert live.active(job['id']) and len(calls)==1 and not any(m=='POST' for m,p in lab['requests'])
            assert not store.rows()
        finally:close(w,await_ui)


def test_four_preparations_advance_with_one_slot_and_parked_one_restores(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    with portal(tmp_path) as lab:
        store,job,old,ctx,bank,fixture,calls=setup(lab,monkeypatch);store.revoke(old);e=lab['engine']
        for n in range(3):
            e.jobs.add(dict(job,id=None,source_id='idle-'+str(n),company='Fictional Queue '+str(n),url=fixture['origin']+'/job/'+str(n),application_url=fixture['origin']+'/form?candidate='+str(n)))
        for j in e.jobs.list():
            if j['id']==job['id']:continue
            for label,name,value in FIELDS+[('Confirmed schedule','dynamic','Flexible')]:bank.save(label,value,'text','job',dict(ctx,job_id=j['id'],company=j['company']),True)
        e.compatibility.batch();prepared=[];native=live.wait_prepared
        def observe(page,state,item):
            assert_prepared(page)
            if page.url not in prepared:prepared.append(page.url)
        fixture['on_prepared']=observe
        def wait(*a,**kw):kw['fixture']=fixture;return native(*a,**kw)
        monkeypatch.setattr(live,'wait_prepared',wait)
        begin=execution.begin;monkeypatch.setattr(execution,'begin',lambda s,n:begin(s,n,'local',True))
        w=MainWindow(lab['settings']);w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);shell=w.shell;shell.engine.sessions.limit=1;shell.engine.store.configure(target=4)
        run=shell.engine.run
        def controlled(*a,**kw):kw['services']=dict(search=lambda *a:{'found':4},geography=lambda *a:None,availability=lambda *a:None);return run(*a,**kw)
        monkeypatch.setattr(shell.engine,'run',controlled)
        try:
            QTest.mouseClick(shell.home.start,Qt.MouseButton.LeftButton)
            await_ui(lambda:len(prepared)==4 and not shell.busy(),180000)
            assert len(calls)==4 and shell.engine.sessions.preparing_count()==1
            assert len(shell.engine.queue.list())==4 and all(r['payload']['live_snapshot']['cv_attached'] for r in shell.engine.queue.list())
            assert not any(m=='POST' for m,p in lab['requests'])
            # La persona reclama la última sesión: nunca se puede cerrar para liberar espacio.
            active_job=next(j for j,t in shell.engine.sessions.tasks.items() if t['thread'].is_alive());assert live.command(active_job,'FOCUS');assert not shell.engine.sessions.park_idle()
            # Cerrar expresamente esa intervención y recuperar una que se guardó antes.
            live.command(active_job,'CANCEL');await_ui(lambda:not shell.engine.sessions.count(),30000)
            parked=next(j for j,t in shell.engine.sessions.tasks.items() if t.get('parked'))
            w.main_tabs.setCurrentIndex(2);shell.posts.refresh();shell.posts.table.selectRow(next(n for n,r in enumerate(shell.posts.rows) if r['job']['id']==parked))
            QTest.mouseClick(shell.posts.action,Qt.MouseButton.LeftButton)
            await_ui(lambda:len(calls)==5 and live.active(parked),60000)
            await_ui(lambda:shell.engine.sessions.tasks[parked]['ready'].is_set(),30000)
            assert not any(m=='POST' for m,p in lab['requests']) and not store.rows()
        finally:close(w,await_ui)
