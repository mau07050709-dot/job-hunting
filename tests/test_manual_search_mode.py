from autojob.manual_search import link_for,useful_url,ManualSearch,ResultsStore
from autojob.config import Settings

def test_manual_link_avoids_register_and_category():
 assert link_for(dict(application_url='https://weworkremotely.com/job-seekers/account/register',url='https://weworkremotely.com/remote-jobs/example-support')) is None
 assert link_for(dict(application_url='https://employer.example/login',url='https://employer.example/job/support'))=='https://employer.example/job/support'
 assert not useful_url('https://workingnomads.com/remote-writing-jobs')

def test_search_keeps_review_and_does_not_authorize_or_send(tmp_path):
 from test_batch_https import seed
 from contextlib import closing
 store,cv=seed(tmp_path)
 profile=store.prep.compatibility.profile;state=profile.load();values=state['values'];values['work_authorization']=True;profile.save(values,state['revision'],confirmed=['work_authorization'])
 engine=ManualSearch(Settings(tmp_path))
 result=engine.run(dict(queries=['Python'],sources=[],limit=None),services=dict(search=lambda *a:dict(found=0),check=lambda *a:None))
 assert result['results'] and not result['review']
 with closing(store.db.connect()) as db:
  assert db.execute('SELECT COUNT(*) FROM submission_authorizations').fetchone()[0]==0
  assert db.execute('SELECT COUNT(*) FROM submission_attempts').fetchone()[0]==0
 assert ResultsStore(engine.jobs.db).latest()['results']==result['results']

def test_manual_start_opens_unified_applications_and_info_button(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
 from test_batch_https import seed
 from autojob.ui.main_window import MainWindow
 from autojob.ui.manual_results import LinksDialog
 from PySide6.QtWidgets import QPushButton
 from PySide6.QtCore import Qt
 from PySide6.QtTest import QTest
 store,cv=seed(tmp_path);w=MainWindow(Settings(tmp_path));await_ui(lambda:not w._ui_tasks,30000)
 job=store.prep.compatibility.jobs.list()[0]
 second=dict(job,url='https://employer.example/job/support',application_url='https://employer.example/job/support',source_id='review2',availability='NO VERIFICADA')
 w.shell.engine.jobs.add(second);second=next(j for j in w.shell.engine.jobs.list() if j['url']==second['url'])
 r=dict(state='FINALIZADO',reason='Dos ofertas',results=[dict(job=job,url=job['application_url'],score=90,geography='CONFIRMADO')],review=[dict(job=second,url=second['url'],score=70,geography='POSIBLE')])
 captured=[]
 def search(options,*a,**kw):captured.append(options);w.shell.engine.results.save(r);return r
 monkeypatch.setattr(w.shell.engine,'run',search)
 assert w.shell.home.search_target.minimum()==1 and w.shell.home.search_target.maximum()==50
 w.shell.home.search_target.setValue(50)
 QTest.mouseClick(w.shell.home.start,Qt.MouseButton.LeftButton)
 await_ui(lambda:not w.shell.busy() and w.shell.main.currentIndex()==2,30000)
 assert captured[0]['target']==50 and w.shell.engine.results.target()==50
 assert len(w.shell.posts.rows)==2
 assert w.shell.home.cards['pending'].isHidden()
 assert not any(isinstance(d,LinksDialog) for d in w.shell._dialogs)
 opened=[];monkeypatch.setattr(w.shell.manual_browser,'open',lambda url:opened.append(url))
 w.shell.posts.table.selectRow(next(i for i,row in enumerate(w.shell.posts.rows) if row['job']['id']==second['id']))
 w.shell.posts.resolve();assert opened==[second['url']]
 assert w.shell.engine.results.latest()['review'][0]['job']['id']==second['id']
 assert w.shell.delivery_authorization is None
 assert any(b.text()=='MI INFORMACIÓN Y PREFERENCIAS' for b in w.shell.posts.findChildren(QPushButton))
 for d in w.shell._dialogs:d.close()
 await_ui(lambda:not w.shell.busy() and not w._ui_tasks,30000);w.close()


def test_combining_saved_groups_does_not_duplicate_jobs():
 from autojob.manual_search import application_rows
 one=dict(job=dict(id='one'),url='https://example.invalid/job/1')
 two=dict(job=dict(id='two'),url='https://example.invalid/job/2')
 assert application_rows(dict(results=[one],review=[one,two]))==[one,two]
