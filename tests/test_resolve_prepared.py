import os,json
from contextlib import closing
from threading import Event
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton,QLineEdit,QApplication
from test_submissions9b import portal
from test_phase9g import setup,assert_prepared
from test_phase9f import criteria
from autojob.forms.batches import create
from autojob.ui.main_window import MainWindow
from autojob.ui.intervention_feedback import plan,open_prepared,ActionRequired
from autojob.forms.submissions import SubmissionStore,DeliveryGuard
import autojob.live as live


@pytest.mark.parametrize('changes,reason',[
    ({'types':['Nurse']},'Tipo de puesto fuera del lote'),
    ({'salary_min':400000,'salary_currency':'CRC'},'Salario mínimo no verificable'),
])
def test_current_batch_scope_failure_is_not_reported_as_expired(tmp_path,changes,reason):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];c=criteria(s,j);c.update(changes)
        a=create(s,c,2,1,True,True,'local',True)
        lab['engine'].queue.allow_site(j['application_url'],True)
        row=dict(id='fixture',job_id=j['id'],kind='CAPTCHA PENDIENTE',company=j['company'],title=j['title'],url=j['application_url'])
        decision=plan(lab['settings'],row,a)
        assert decision['authorization_required'] and reason in decision['message']
        assert 'caducó' not in decision['message']


def test_expired_permission_is_checked_before_creating_browser(tmp_path,monkeypatch):
    with portal(tmp_path) as lab:
        j=lab['job'];row=dict(id='fixture',job_id=j['id'],kind='AUTORIZACIÓN CV',company=j['company'],title=j['title'],url=j['application_url'])
        monkeypatch.setattr('autojob.browser.BraveSession',lambda *a:pytest.fail('No abrir con permiso inválido'))
        result=open_prepared(lab['settings'],row,'not-current',lambda s:None,lambda:False)
        assert result['authorization_required'] and result['state']=='BLOQUEADA' and not lab['requests']


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Brave local separado')
def test_resolve_button_restores_then_focuses_prepared_session_and_resumes(tmp_path,monkeypatch,qt_application_lifetime,await_ui):
    from autojob.ui.submission_ui import MissingInformation
    from autojob.auth.verifications import captcha_state
    from autojob.browser import BraveSession
    with portal(tmp_path) as lab:
        s,j,_,ctx,bank,fixture,calls=setup(lab,monkeypatch)
        a=create(s,criteria(s,j),2,1,True,True,'local',True)
        # First prepared session is deliberately lost. No final request occurred.
        from threading import Thread
        initial_errors=[]
        def initial_session():
            try:
                with BraveSession(lab['settings']) as b:
                    _,rule=s.permission(a,j);g=DeliveryGuard(b,rule['origin'],lambda:s.permission(a,j),rule);p=g.page(rule['url'])
                    live.prepare(p,g,s.prep,j,rule);assert_prepared(p)
            except BaseException as exc:initial_errors.append(exc)
        t=Thread(target=initial_session);t.start();t.join(40)
        assert not t.is_alive()
        if initial_errors:raise initial_errors[0]
        assert not s.rows() and not any(m=='POST' for m,path in lab['requests'])
        prepared=Event();human=Event();owner=[];first_page=[];focuses=[];ready=[]
        native=live.wait_prepared;native_focus=__import__('autojob.intervention_context',fromlist=['focus']).focus
        def focused(page,context):
            assert_prepared(page);focuses.append(native_focus(page,context));return focuses[-1]
        monkeypatch.setattr('autojob.intervention_context.focus',focused)
        def on_wait(page,id,store):
            # Regresses the first-FOCUS bug: this used to happen before filling.
            assert_prepared(page);prepared.set();first_page.append(page)
            if os.environ.get('AUTOJOB_RESOLVE_REPORT'):
                from pathlib import Path
                page.screenshot(path=str(Path(os.environ['AUTOJOB_RESOLVE_REPORT']).with_suffix('.png')),full_page=True)
            original=page.wait_for_timeout
            def tick(ms):
                if human.is_set():
                    if page.locator('#human-check').count() and not captcha_state(page,fixture)['completed']:page.locator('#human-check').click()
                    human.clear()
                original(ms)
            monkeypatch.setattr(page,'wait_for_timeout',tick)
        fixture['on_wait']=on_wait
        def controlled(*args,**kwargs):kwargs['fixture']=fixture;return native(*args,**kwargs)
        monkeypatch.setattr(live,'wait_prepared',controlled)
        w=MainWindow(lab['settings']);w.resize(1280,900);w.show();w.shell.timer.stop();w.shell.schedule_timer.stop();await_ui(lambda:not w._ui_tasks,30000)
        # Exercise the existing dialog. Only this fixture translates its explicit
        # test HTTPS origin to the current localhost HTTP server and local mode.
        from autojob.ui.batch_ui import BatchAuthorization
        from autojob.forms.guard import origin
        def controlled_create(store,c,maximum,hours,upload,explicit):
            assert c['domains']==['https://local.jobmaxxing.test']
            return create(store,dict(c,domains=[origin(j['application_url'])]),maximum,hours,upload,explicit,'local',True)
        monkeypatch.setattr('autojob.forms.batches.create',controlled_create)
        dialog_errors=[]
        def activate():
            d=QApplication.activeModalWidget()
            if not isinstance(d,BatchAuthorization) or not d.button.isEnabled():QTimer.singleShot(20,activate);return
            try:
                QTest.mouseClick(d.domains,Qt.MouseButton.LeftButton);QTest.keyClicks(d.domains,'https://local.jobmaxxing.test')
                QTest.mouseClick(d.types,Qt.MouseButton.LeftButton);QTest.keyClick(d.types,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(d.types,'Python Developer')
                QTest.mouseClick(d.cvs.viewport(),Qt.MouseButton.LeftButton,pos=d.cvs.visualItemRect(d.cvs.item(0)).center())
                QTest.mouseClick(d.upload,Qt.MouseButton.LeftButton);QTest.mouseClick(d.send,Qt.MouseButton.LeftButton);QTest.mouseClick(d.button,Qt.MouseButton.LeftButton)
            except BaseException as exc:dialog_errors.append(exc);d.reject()
        s.revoke(a);QTimer.singleShot(20,activate)
        QTest.mouseClick(w.shell.home.authorize,Qt.MouseButton.LeftButton)
        if dialog_errors:raise dialog_errors[0]
        a=w.shell.delivery_authorization;assert a and w.shell.engine.delivery_authorization==a
        e=w.shell.engine;id=e.store.add_intervention(j['id'],j['company'],j['title'],'CAPTCHA PENDIENTE','Local pending challenge',j['application_url'])
        c=w.shell.center;c.refresh();w.main_tabs.setCurrentIndex(2);w.shell.post_tabs.setCurrentWidget(c)
        def click(kind):
            c.refresh();c.table.selectRow(next(n for n,row in enumerate(c.rows) if row['job_id']==j['id'] and row['kind']==kind))
            QTest.mouseClick(c.findChild(QPushButton,'resolve_intervention_button'),Qt.MouseButton.LeftButton)
        try:
            click('CAPTCHA PENDIENTE');await_ui(prepared.is_set,45000)
            assert live.active(j['id']) and len(calls)==2 and focuses and focuses[0]
            # Repeated RESOLVER AHORA reuses the current page, never another GET.
            before=len(lab['requests']);click('CAPTCHA PENDIENTE');assert len(calls)==2 and len(lab['requests'])==before
            c.refresh();click('INFORMACIÓN FALTANTE');dialog=c.popup
            assert isinstance(dialog,MissingInformation);await_ui(lambda:not dialog.loading,30000)
            assert isinstance(dialog.control,QLineEdit)
            QTest.keyClicks(dialog.control,'LOCAL-CONFIRMED');QTest.mouseClick(dialog.confirm,Qt.MouseButton.LeftButton)
            QTest.mouseClick(next(b for b in dialog.findChildren(QPushButton) if b.text()=='GUARDAR Y CONTINUAR'),Qt.MouseButton.LeftButton)
            await_ui(lambda:not dialog.saving,30000);human.set()
            await_ui(lambda:not c.direct_worker.isRunning(),45000)
            assert len(calls)==2 and sum(m=='POST' for m,path in lab['requests'])==1
            assert lab['upload_verified'] and s.rows()[0]['state']=='ENVIADA CONFIRMADA'
            assert not live.active(j['id'])
            # A historical row must now route to receipts, never a fresh form.
            c.resolve(dict(job_id=j['id'],kind='CAPTCHA PENDIENTE',verification_id=None))
            from autojob.ui.receipt_review import ReceiptReview
            assert isinstance(c.popup,ReceiptReview);c.popup.close();assert len(calls)==2
            out=os.environ.get('AUTOJOB_RESOLVE_REPORT')
            if out:
                from pathlib import Path
                Path(out).write_text(json.dumps(dict(restored=True,known_fields_verified=True,cv_attached=True,focus_after_fill=True,same_session=True,posts=1,receipt=s.rows()[0]['state'],scope='localhost only'),indent=2),encoding='utf-8')
        finally:
            live.cancel_all()
            if getattr(c,'direct_worker',None):c.direct_worker.cancelled.set();await_ui(lambda:not c.direct_worker.isRunning(),30000)
            if getattr(c,'operation_popup',None):c.operation_popup.close()
            await_ui(lambda:not w._ui_tasks,30000);w.close()
