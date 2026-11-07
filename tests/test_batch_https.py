"""Focused regression for explicit origins and the real Qt authorization dialog."""
from contextlib import closing
import json
import pytest
from autojob.ui.batch_ui import parse_origins


@pytest.mark.parametrize('text,reason',[
    ('','Campo vacío'),('https://','mal formada'),('jobs.lever.co','https://'),
    ('http://jobs.lever.co','HTTP no está permitido'),
    ('https://jobs.lever.co/apply','sin rutas'),
    ('https://jobs.lever.co; https://bad host.com','bad host.com'),
    ('https://jobs.lever.co; https://JOBS.LEVER.CO/','duplicado'),
    ('https://jobs.lever.co; https://jobs.lever.co:443','duplicado'),
    ('https://user:pass@jobs.example.invalid','credenciales'),
    ('https://jobs.lever.co:abc','puerto inválido'),
    ('https://jobs.lever.co:','falta el número'),
    ('https://jobs.lever.co:0','puerto debe'),
    ('https://jobs.lever.co?x=1','sin rutas'),
    ('https://-bad.com','dominio mal formado'),
])
def test_origins_report_exact_problem(text,reason):
    with pytest.raises(ValueError,match=reason):parse_origins(text)


def test_multiple_origins_are_only_the_explicit_entries():
    assert parse_origins(' https://JOBS.LEVER.CO/ ; https://job-boards.greenhouse.io; ') == ['https://jobs.lever.co','https://job-boards.greenhouse.io']


def seed(root):
    from docx import Document
    from autojob.forms.submissions import SubmissionStore
    from autojob.testing.control9a import DESCRIPTION
    store=SubmissionStore(root/'data');library=store.prep.compatibility.library
    doc=Document()
    for text in ['Full name: Alex Rivera','Email: alex@example.invalid','Education:','Bachelor of Electronics, Example University, 2020 - 2024','Work Experience:','Software Developer | Example Labs | 2022 - 2024','Technical Skills:','Python, SQL, Git, Linux','Languages:','English B2','Spanish native']:doc.add_paragraph(text)
    path=root/'fictional.docx';doc.save(path);cv=library.import_document(path)
    library.update(cv['id'],title='CV FICTICIO',language='en',specialty='technical',fields=cv['fields'],reviewed=True,expected_revision=cv['revision']);library.set_default(cv['id'])
    profile=store.prep.compatibility.profile;state=profile.load();values=state['values']
    values.update(full_name='Alex Rivera',email='alex@example.invalid',country='Costa Rica',remote=True,full_time=True,positions=['Software Developer'],experience_records=['Example Labs | Software Developer | 2022-01-01 | 2024-12-31 | Python development'],qualifications=['Bachelor of Electronics'],languages=['English B2'],skills=['Python'],soft_skills=['Communication'])
    profile.save(values,state['revision'],confirmed=['full_name','email','country','remote','full_time','positions','experience_records','qualifications','languages','skills','soft_skills'])
    store.prep.compatibility.jobs.add(dict(source='FICTIONAL',source_id='batch',company='Fictional Labs',title='Junior Python Developer',url='https://jobs.lever.co/fictitious-test',application_url='https://jobs.lever.co/fictitious-test/apply',description=DESCRIPTION,geography='CONFIRMADO',modality='remote',location='Worldwide',availability='ABIERTA'))
    store.prep.compatibility.batch();return store,cv['id']


def test_real_dialog_click_typing_focus_activation_engine_and_revocation(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from autojob.config import Settings
    from autojob.ui.batch_ui import BatchAuthorization
    from autojob.ui.main_window import MainWindow
    store,cv_id=seed(tmp_path);window=MainWindow(Settings(tmp_path));window.show()
    window.shell.timer.stop();window.shell.schedule_timer.stop();await_ui(lambda:not window._ui_tasks,30000)
    shell=window.shell;errors=[];seen=[]
    def interact():
        dialog=QApplication.activeModalWidget()
        if not isinstance(dialog,BatchAuthorization) or not dialog.button.isEnabled():QTimer.singleShot(20,interact);return
        try:
            assert dialog.domains.text()=='' and not dialog.domains.isReadOnly() and dialog.domains.isEnabled()
            QTest.mouseClick(dialog.domains,Qt.MouseButton.LeftButton);QTest.keyClicks(dialog.domains,'http://wrong.example.com')
            QTest.mouseClick(dialog.cvs.viewport(),Qt.MouseButton.LeftButton,pos=dialog.cvs.visualItemRect(dialog.cvs.item(0)).center())
            QTest.mouseClick(dialog.upload,Qt.MouseButton.LeftButton);QTest.mouseClick(dialog.send,Qt.MouseButton.LeftButton)
            QTest.mouseClick(dialog.button,Qt.MouseButton.LeftButton)
            assert 'http://wrong.example.com' in dialog.field_errors['domains'].text()
            assert dialog.domains.hasFocus() and not dialog.authorization
            QTest.keyClick(dialog.domains,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
            QTest.keyClicks(dialog.domains,'https://jobs.lever.co; https://job-boards.greenhouse.io')
            QTest.keyClick(dialog.domains,Qt.Key.Key_Tab)
            assert dialog.domains.text()=='https://jobs.lever.co; https://job-boards.greenhouse.io'
            assert 'Orígenes válidos' in dialog.status.text()
            QTest.mouseClick(dialog.types,Qt.MouseButton.LeftButton);QTest.keyClick(dialog.types,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(dialog.types,'Python Developer')
            QTest.mouseClick(dialog.button,Qt.MouseButton.LeftButton);seen.append(dialog)
        except BaseException as exc:errors.append(exc);dialog.reject()
    QTimer.singleShot(20,interact)
    timeout=QTimer(window);timeout.setSingleShot(True);timeout.timeout.connect(lambda:QApplication.activeModalWidget().reject() if QApplication.activeModalWidget() else None);timeout.start(30000)
    # El componente histórico sigue siendo comprobable, pero ya no activa la
    # ejecución de producción. INICIAR crea su propio permiso interno.
    dialog=BatchAuthorization(shell);dialog.exec();timeout.stop()
    if errors:raise errors[0]
    assert seen and dialog.authorization and shell.delivery_authorization is None
    token=dialog.authorization;assert shell.engine.delivery_authorization is None
    with closing(store.db.connect()) as db:record=dict(db.execute('SELECT * FROM submission_authorizations WHERE id=?',(token,)).fetchone())
    batch=json.loads(record['scope'])['_batch']
    assert batch['domains']==['https://jobs.lever.co','https://job-boards.greenhouse.io'] and batch['cv_ids']==[cv_id]
    assert record['max_count']==3
    job=store.prep.compatibility.jobs.list()[0];_,rule=store.permission(token,job);assert rule['cv_id']==cv_id and rule['upload']
    with pytest.raises(ValueError):store.permission(token,dict(job,application_url='https://outside.example.com/apply'))
    captured=[]
    def run(*args):captured.append(shell.engine.delivery_authorization);return {'state':'FINALIZADO'}
    monkeypatch.setattr(shell.engine,'run',run)
    QTest.mouseClick(shell.home.start,Qt.MouseButton.LeftButton);await_ui(lambda:bool(captured) and not shell.busy(),30000)
    assert captured[0] and captured[0]!=token
    with closing(store.db.connect()) as db:scope=json.loads(db.execute('SELECT scope FROM submission_authorizations WHERE id=?',(captured[0],)).fetchone()[0])
    assert '_execution' in scope and '_batch' not in scope
    store.revoke(token)
    with pytest.raises(ValueError):store.permission(token,job)
    assert not store.rows()
    await_ui(lambda:not window._ui_tasks,30000);window.close()


def test_no_old_batch_reactivated_after_restart(tmp_path,qt_application_lifetime,await_ui):
    from autojob.config import Settings
    from autojob.forms.batches import create
    from autojob.ui.main_window import MainWindow
    store,cv=seed(tmp_path)
    create(store,dict(modalities=['remote'],regions=['Costa Rica'],domains=['https://jobs.lever.co'],cv_ids=[cv],types=['Python Developer'],threshold=70,excluded=[],salary_min=None,salary_currency='USD',salary_period='month'),3,2,True,True)
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    assert w.shell.delivery_authorization is None
    assert not any('AUTORIZAR' in b.text() for b in w.shell.home.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton) if b.isVisibleTo(w.shell.home));w.close()
