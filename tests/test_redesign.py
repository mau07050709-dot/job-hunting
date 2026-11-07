import json,os
from contextlib import closing
from pathlib import Path
from threading import Event
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog,QPushButton,QDialog
from autojob.config import Settings
from autojob.ui.main_window import MainWindow
from autojob.profile.semantic import intent,equivalent,SemanticAnswers
from autojob.forms import execution
from autojob.forms.submissions import SubmissionStore
from test_batch_https import seed

@pytest.mark.parametrize('a,b',[
 ('Have you worked at this company before?','Did you previously work for our organization?'),
 ('Are you a former employee?','¿Has trabajado antes en esta empresa?'),
 ('ARE YOU A FORMER EMPLOYEE!!!','Are you a former employe?'),
 ('Describe your favorite development project','Describe your favourite development project'),
])
def test_equivalent_intent_and_small_typos(a,b):assert equivalent(a,b)

@pytest.mark.parametrize('a,b',[
 ('Do you need visa sponsorship?','Are you authorized to work?'),
 ('Can you relocate?','Are you available to travel?'),
 ('Are you a current employee?','Are you a former employee?'),
    ('Are you a former employer?','Are you a former employee?'),
 ('Have you worked with HubSpot before?','Have you worked at this company before?'),
 ('What is your expected salary annually?','What is your expected salary monthly?'),
])
def test_semantically_different_questions_never_match(a,b):assert not equivalent(a,b)

def test_partial_answers_persistence_and_company_scope(tmp_path):
    s=SemanticAnswers(tmp_path);s.save('Availability','Any day');s.save('Incomplete question')
    s.save('Have you worked at this company before?','No',company='Example Ltd')
    again=SemanticAnswers(tmp_path);assert len(again.rows())==3
    assert again.resolve('Did you previously work for our organization?',{'company':'Example Ltd'})['answer']=='No'
    assert again.resolve('Are you a former employee?',{'company':'Other Ltd'}) is None
    s.save('Are you a former employee?','Yes')
    assert again.resolve('Are you a former employee?',{'company':'Other Ltd'}) is None

def test_edit_custom_answer_preserves_history(tmp_path):
    s=SemanticAnswers(tmp_path);s.save('Are you willing to travel?','Yes');s.save('Are you willing to travel?','No')
    assert len(s.rows())==1 and s.resolve('¿Puedes viajar?',{})['answer']=='No'
    with closing(s.db.connect()) as db:assert db.execute('SELECT COUNT(*) FROM personal_question_history').fetchone()[0]==2

def test_execution_uses_eligible_job_and_preserves_uncertain_attempts(tmp_path):
    s,cv=seed(tmp_path);job=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1)
    auth,rule=s.permission(token,job);assert rule['cv_id']==cv and rule['upload'];assert '_execution' in json.loads(auth['scope']) and '_batch' not in json.loads(auth['scope'])
    attempt=s.claim(token,job);s.finish(attempt,'ENVÍO NO VERIFICADO',{'verified':False})
    with pytest.raises(ValueError):s.permission(token,job)
    assert s.rows()[0]['state']=='ENVÍO NO VERIFICADO'
    execution.recover(s)
    with pytest.raises(ValueError):s.permission(token,job)

def test_imported_document_needs_no_per_cv_authorization(tmp_path):
    s,cv=seed(tmp_path);library=s.prep.compatibility.library;record=library.get(cv)
    library.update(cv,title=record['title'],language=record['language'],specialty=record['specialty'],fields=record['fields'],reviewed=False,expected_revision=record['revision'])
    s.prep.compatibility.batch();job=s.prep.compatibility.jobs.list()[0]
    token=execution.begin(s,1);auth,rule=s.permission(token,job)
    assert rule['cv_id']==cv and rule['execution_authorized'] and not library.get(cv)['reviewed']
    assert s.prep.data.profile_state()['values']['full_name']=='Alex Rivera'

def test_interface_has_four_pages_background_configuration_and_no_authorization_dialog(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    assert [w.main_tabs.tabText(i) for i in range(w.main_tabs.count())]==['INICIO','MIS DATOS','POSTULACIONES','CONFIGURACIÓN']
    assert [b.text() for b in w.shell.empty_configuration.findChildren(QPushButton)]==['CAMBIAR FONDO'] and w.section_backgrounds[3]==w.section_backgrounds[0]
    w.main_tabs.setCurrentIndex(3);assert w.styleSheet()==w._background_stylesheet(w.section_backgrounds[0])
    assert not w.shell.home.start.isEnabled()
    assert not any('AUTORIZAR' in b.text() or 'MODO PRUEBA' in b.text() for b in w.shell.home.findChildren(QPushButton) if b.isVisibleTo(w.shell.home))
    w.close()

def test_import_from_home_and_restart(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from docx import Document
    p=tmp_path/'candidate.docx';d=Document();d.add_paragraph('Alex Rivera');d.add_paragraph('alex@example.invalid');d.add_paragraph('Python developer');d.save(p)
    w=MainWindow(Settings(tmp_path));w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    monkeypatch.setattr(QFileDialog,'getOpenFileNames',lambda *a:([str(p)],''))
    QTest.mouseClick(w.shell.home.attach,Qt.MouseButton.LeftButton);await_ui(lambda:not w._ui_tasks,30000)
    assert len(w.shell.engine.compatibility.library.list())==1
    w.shell.request_refresh();await_ui(lambda:not w._ui_tasks,30000);assert w.shell.home.start.isEnabled()
    w.close();w2=MainWindow(Settings(tmp_path));w2.shell.timer.stop();await_ui(lambda:not w2._ui_tasks,30000);assert len(w2.shell.engine.compatibility.library.list())==1;assert w2.shell.delivery_authorization is None;w2.close()

def test_start_creates_execution_without_batch_or_confirmation(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    seed(tmp_path);w=MainWindow(Settings(tmp_path));w.show();w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);calls=[]
    def run(*a,**kw):calls.append(w.shell.engine.delivery_authorization);return {'state':'FINALIZADO'}
    monkeypatch.setattr(w.shell.engine,'run',run)
    monkeypatch.setattr('autojob.ui.batch_ui.BatchAuthorization.exec',lambda *a:pytest.fail('No autorización adicional'))
    QTest.mouseClick(w.shell.home.start,Qt.MouseButton.LeftButton);await_ui(lambda:bool(calls) and not w.shell.busy(),30000)
    assert calls[0] and w.shell.delivery_authorization==calls[0]
    await_ui(lambda:not w._ui_tasks,30000);w.close()

def test_delete_only_selected_cv_from_simple_page(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from resume_fixtures import write_docx,EN_SERVICE
    from PySide6.QtWidgets import QMessageBox
    store,first=seed(tmp_path);second=store.prep.compatibility.library.import_document(write_docx(tmp_path/'service.docx',EN_SERVICE))
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);page=w.shell.data_view;page.refresh();page.table.selectRow(next(n for n,r in enumerate(page.rows) if r['id']==second['id']))
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    page.remove();assert [r['id'] for r in store.prep.compatibility.library.list()]==[first]
    assert (tmp_path/'service.docx').exists();w.close()

def test_optional_profile_saves_only_one_value(tmp_path,qt_application_lifetime,await_ui):
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    p=w.profile_widget;p.widgets['full_name'].setText('Alex Rivera');p.confirm('full_name');p.save()
    from autojob.profile.store import ProfileStore
    loaded=ProfileStore(tmp_path/'data').load();assert loaded['values']['full_name']=='Alex Rivera' and loaded['values']['phone'] is None
    w.close()

def test_definite_rejection_does_not_count_as_confirmed_goal(tmp_path):
    s,cv=seed(tmp_path);j=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1)
    first=s.claim(token,j);s.finish(first,'RECHAZADA',{'verified':False})
    s.prep.compatibility.jobs.add(dict(j,id=None,source_id='another',company='Another fictional',url='https://jobs.lever.co/another',application_url='https://jobs.lever.co/another/apply'))
    s.prep.compatibility.batch();other=next(r for r in s.prep.compatibility.jobs.list() if r['company']=='Another fictional')
    assert s.claim(token,other)
    with pytest.raises(ValueError):s.permission(token,j)

def test_queue_has_all_selected_and_processes_beyond_old_limit(tmp_path):
    from autojob.autonomous import AutomaticCoordinator
    s,cv=seed(tmp_path);e=AutomaticCoordinator(Settings(tmp_path));base=e.jobs.list()[0]
    for n in range(12):e.jobs.add(dict(base,id=None,source_id='auto-'+str(n),company='Fictional '+str(n),url='https://jobs.lever.co/fixture-'+str(n),application_url='https://jobs.lever.co/fixture-'+str(n)+'/apply'))
    e.compatibility.batch();token=execution.begin(s,30);e.delivery_authorization=token;seen=[];first_sizes=[]
    def send(id,token,*a,**kw):
        first_sizes.append(len(e.queue.list()));seen.append(id);j=next(j for j in e.jobs.list() if j['id']==id);claim=s.claim(token,j);s.finish(claim,'NO TRANSMITIDA',{'verified':False});return {'state':'PENDIENTE'}
    result=e.run(dict(queries=['Python'],sources=['local'],limit=30),services=dict(search=lambda *a:dict(found=0,errors=[]),geography=lambda *a:None,availability=lambda *a:None,send=send))
    assert first_sizes[0]==len(seen) and len(seen)>10 and len(seen)==len(set(seen)) and result['state']!='ERROR'

def test_confirmed_application_opens_receipt_without_preparing_again(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    s,cv=seed(tmp_path);job=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1);attempt=s.claim(token,job)
    s.finish(attempt,'ENVIADA CONFIRMADA',dict(mode='real',verified=True,evidence_id='LOCAL-UNIT-RECEIPT',confirmation_kind='MENSAJE VISIBLE',final_request_released=True,http_response_statuses=[200],url='https://jobs.lever.co/receipt/unit'))
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();w.shell.posts.table.selectRow(0);opened=[]
    monkeypatch.setattr(w.shell,'view_sent',lambda row:opened.append(row['job']['id']))
    monkeypatch.setattr(w.shell.center,'resolve',lambda *a:pytest.fail('No volver a preparar una candidatura enviada'))
    QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
    assert opened==[job['id']] and len(s.rows())==1;w.close()

def test_confirmed_data_update_revalidates_inside_current_execution(tmp_path):
    s,cv=seed(tmp_path);job=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1)
    s.prep.compatibility.jobs.add(dict(job,id=None,source_id='update-other',company='Other fixture',url='https://jobs.lever.co/update-other',application_url='https://jobs.lever.co/update-other/apply'))
    s.prep.compatibility.batch();other=next(j for j in s.prep.compatibility.jobs.list() if j['company']=='Other fixture')
    before,rule=s.permission(token,job)
    s.prep.data.save({'preferred_schedule':'Any day'},confirmed=['preferred_schedule'])
    after,updated=s.permission(token,job)
    assert after['profile_hash']!=before['profile_hash'] and rule['cv_hash']==updated['cv_hash'] and updated['execution_authorized']
    assert s.permission(token,other)[1]['cv_id']==cv

@pytest.mark.parametrize('state',['ENVÍO NO VERIFICADO','RECHAZADA','NO TRANSMITIDA'])
def test_resolve_always_routes_to_portal_without_receipt_or_missing_info_window(tmp_path,qt_application_lifetime,await_ui,monkeypatch,state):
    s,cv=seed(tmp_path);job=s.prep.compatibility.jobs.list()[0];token=execution.begin(s,1);attempt=s.claim(token,job);s.finish(attempt,state,dict(verified=False))
    before=s.rows();w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.main_tabs.setCurrentIndex(2);w.shell.posts.refresh();w.shell.posts.table.selectRow(0);opened=[]
    monkeypatch.setattr(w.shell,'view_sent',lambda row:opened.append(row))
    if state=='NO TRANSMITIDA':monkeypatch.setattr(w.shell.center,'open_direct',lambda row:opened.append(dict(job=job,restored=True)))
    QTest.mouseClick(w.shell.posts.action,Qt.MouseButton.LeftButton)
    assert opened[0]['job']['id']==job['id'] and w.shell.center.popup is None and s.rows()==before
    if state=='NO TRANSMITIDA':assert opened[0]['restored']  # Se puede recuperar una preparación que nunca transmitió.
    w.close()

def test_choose_each_tab_background_and_persist_after_restart(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from PySide6.QtGui import QImage,QColor
    from PySide6.QtWidgets import QInputDialog
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);w.show();w.main_tabs.setCurrentIndex(3);files=[];copied=[]
    for index,extension in enumerate(['png','jpg','bmp','webp']):
        original=tmp_path/('imagen.'+extension);img=QImage(24,30,QImage.Format.Format_RGB32);img.fill(QColor('blue'));assert img.save(str(original));files.append(original)
        def choose(parent,title,label,items,current,editable,index=index):
            assert title=='Elegir pestaña' and list(items)==['INICIO','MIS DATOS','POSTULACIONES','CONFIGURACIÓN'];return items[index],True
        monkeypatch.setattr(QInputDialog,'getItem',choose);monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args,p=original:(str(p),''))
        QTest.mouseClick(w.shell.change_background_button,Qt.MouseButton.LeftButton);path=w.section_backgrounds[index];assert path.read_bytes()==original.read_bytes() and path!=original;copied.append(path)
    await_ui(lambda:not w._ui_tasks,30000);w.close();again=MainWindow(Settings(tmp_path));again.shell.timer.stop();await_ui(lambda:not again._ui_tasks,30000)
    assert list(again.section_backgrounds)==copied and all(p.is_file() for p in files);again.close()

def test_background_cancel_and_invalid_image_preserve_current_choice(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000);before=w.section_backgrounds
    monkeypatch.setattr(QInputDialog,'getItem',lambda *a:('',False));monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:pytest.fail('Cancelar no abre explorador'))
    w.shell.change_background();assert w.section_backgrounds==before
    broken=tmp_path/'damaged.png';broken.write_text('No es una imagen');monkeypatch.setattr(QInputDialog,'getItem',lambda *a:('MIS DATOS',True));monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(broken),''))
    w.shell.change_background();assert w.section_backgrounds==before and not w.shell.background_images.config.exists() and 'fondo anterior se conserva' in w.shell.background_status.text();w.close()
