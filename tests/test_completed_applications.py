from contextlib import closing
from autojob.completed import CompletedApplications
from autojob.config import Settings


def test_done_persists_without_duplicate_or_sent_state(tmp_path):
 from test_batch_https import seed
 store,_=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
 row=dict(job=job,url=job['application_url'],score=90,geography='CONFIRMADO')
 done=CompletedApplications(tmp_path/'data');done.mark(row);done.mark(row)
 saved=CompletedApplications(tmp_path/'data').rows()
 assert len(saved)==1 and saved[0]['job']['id']==job['id'] and saved[0]['completed_at']
 assert CompletedApplications(tmp_path/'other').rows()==[]
 assert store.rows()==[]
 with closing(store.db.connect()) as c:assert c.execute('SELECT COUNT(*) FROM resumes').fetchone()[0]==1


def test_done_button_moves_selected_row_and_survives_restart(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
 from test_batch_https import seed
 from autojob.ui.main_window import MainWindow
 from PySide6.QtWidgets import QPushButton,QTableWidget
 store,_=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
 w=MainWindow(Settings(tmp_path));await_ui(lambda:not w._ui_tasks)
 w.shell.engine.results.save(dict(results=[dict(job=job,url=job['application_url'],score=90,geography='CONFIRMADO')],review=[]))
 w.shell.posts.refresh_manual();w.shell.posts.table.selectRow(0)
 assert w.shell.posts.done_button.isEnabled()
 w.shell.posts.done_button.click();await_ui(lambda:not w._ui_tasks)
 assert not w.shell.posts.rows
 w.shell.show_completed();dialog=w.shell._dialogs[-1];table=dialog.findChild(QTableWidget)
 assert table.rowCount()==1 and table.item(0,0).text()==job['company']
 opened=[];monkeypatch.setattr(w.shell.manual_browser,'open',lambda url:opened.append(url));table.selectRow(0)
 next(b for b in dialog.findChildren(QPushButton) if b.text()=='ABRIR EN BRAVE').click()
 assert opened==[job['application_url']]
 dialog.close();w.close()
 again=MainWindow(Settings(tmp_path));await_ui(lambda:not again._ui_tasks)
 assert not again.shell.posts.read_rows()
 assert any(b.text()=='POSTULACIONES HECHAS' for b in again.shell.data_view.findChildren(QPushButton))
 again.close()


def test_done_stops_only_matching_fill(tmp_path):
 from autojob.extension_fill import ExtensionFill
 s=Settings(tmp_path);s.data_path.mkdir();bridge=ExtensionFill(s)
 bridge.tasks={'a':dict(id='a',state='DONE',url='https://example.invalid/a',job=dict(id='one')),'b':dict(id='b',state='DONE',url='https://example.invalid/b',job=dict(id='two'))}
 assert bridge.finish_manual('one')==['a']
 assert bridge.tasks['a']['state']=='ARCHIVED' and bridge.tasks['b']['state']=='DONE'
 assert not bridge.handle('/scope',dict(id='a',url='https://example.invalid/a'))['allowed']
