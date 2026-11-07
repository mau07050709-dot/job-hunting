from pathlib import Path
from contextlib import contextmanager,closing
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from threading import Thread
from dataclasses import replace
import json,os
import pytest
from autojob.config import Settings
from autojob.forms.answers9b import ScopedAnswers
from autojob.forms.submissions import SubmissionStore,SubmissionEngine
from autojob.testing.control9a import fixture_flow,DESCRIPTION

@contextmanager
def portal(tmp_path,unknown=False,unverified=False,multistage=False,prefilled_optional=False,validation_error=False):
    with fixture_flow(Settings(tmp_path),tmp_path) as base:
        engine=base['engine'];requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append(('GET',self.path));title='Junior Python Developer Delivery'
                if self.path.startswith('/receipt'):
                    body='<form><div class="field-error" role="alert">Email is invalid</div><input name="email" required></form>' if validation_error else '<h1 data-application-id="LOCAL-9B-001">Application received</h1>' if not unverified else '<h1>Processing your request</h1>'
                elif self.path=='/start' and multistage:
                    body='<form><label>Full name<input name="name" required></label><label>Email<input name="email" type="email" required></label><button type="button" onclick="location.href=\'/form\'">Next</button></form>'
                else:
                    body='<form action="/submit" method="post" enctype="multipart/form-data"><label>Full name<input name="name" required></label><label>Email<input name="email" type="email" required></label><label>Resume<input name="cv" type="file" required></label>'
                    if prefilled_optional:body+='<label>Optional project code<input name="optional" value="UNCONFIRMED-PORTAL-DEFAULT"></label>'
                    if unknown:body+='<label>Unknown mandatory project code<input name="code" required></label>'
                    body+='<button type="submit">Submit application</button></form>'
                raw=('<html><head><title>Job Hunting Fictional Labs — '+title+'</title></head><body>'+body+'</body></html>').encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']));requests.append(('POST',self.path));base['upload_verified']=b'PK\x03\x04' in raw and b'alex@example.invalid' in raw;self.send_response(303);self.send_header('Location','/receipt/LOCAL-9B-001');self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
        try:
            engine.jobs.add(dict(source='LOCAL 9B',source_id='delivery',company='Job Hunting Fictional Labs',title='Junior Python Developer Delivery',url=origin+'/job',application_url=origin+('/start' if multistage else '/form'),description=DESCRIPTION,geography='CONFIRMADO',modality='remote',location='Worldwide',availability='ABIERTA'))
            job=next(j for j in engine.jobs.list() if j['source']=='LOCAL 9B');engine.compatibility.batch(ids=[job['id']]);base.update(job=job,requests=requests);yield base
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

def test_unknown_values_scopes_and_history(tmp_path):
    s=ScopedAnswers(tmp_path);ctx=dict(job_id='1',company='A',modality='remote')
    s.save('Project code','ABC','text','job',ctx,True)
    assert s.resolve('Project code',ctx)['answer']=='ABC'
    assert s.resolve('Project code',dict(ctx,job_id='2')) is None
    s.save('Project code','DEF','text','job',ctx,True)
    with closing(s.db.connect()) as db:assert db.execute('SELECT COUNT(*) FROM approved_form_answer_history').fetchone()[0]==2
    assert s.resolve('Project code',ctx)['answer']=='DEF'

@pytest.mark.parametrize('question,scope',[('National ID','job'),('Password','personal'),('I accept terms','job'),('Have you worked at this company?','personal'),('Expected salary USD hourly','work')])
def test_restricted_and_contextual_answers(tmp_path,question,scope):
    with pytest.raises(ValueError):ScopedAnswers(tmp_path).save(question,'yes',scope=scope,context=dict(job_id='x'),confirmed=True)

@pytest.mark.parametrize('kind,value,options',[('number','NaN',[]),('date','2026-99-50',[]),('checkbox','Maybe',[]),('select','Other',['Yes','No']),('multiple','A|C',['A','B'])])
def test_typed_validation(tmp_path,kind,value,options):
    with pytest.raises(ValueError):ScopedAnswers(tmp_path).save('Question',value,kind,context=dict(job_id='x'),confirmed=True,options=options)

def test_unconfirmed_answer_not_used(tmp_path):
    s=ScopedAnswers(tmp_path);s.save('Question','value',context=dict(job_id='x'),confirmed=False);assert s.resolve('Question',dict(job_id='x')) is None

def test_confirmed_mis_datos_latest_and_conflicts(tmp_path):
    from autojob.forms.preparation import Preparation
    p=Preparation(tmp_path);p.data.save(dict(ram_gb='16'),confirmed=['ram_gb']);assert p.resolve('RAM')['answer']=='16'
    p.data.save(dict(ram_gb='32'),confirmed=['ram_gb']);assert p.resolve('RAM')['answer']=='32'
    ScopedAnswers(tmp_path).save('RAM','8',context=dict(job_id='x'),confirmed=True)
    assert p.resolve('RAM',dict(job_id='x'))['status']=='CONFLICTO'

def test_visible_identity_and_safe_default(tmp_path,qt_application_lifetime):
    from autojob.ui.main_window import MainWindow
    from PySide6.QtWidgets import QTabWidget
    w=MainWindow(Settings(tmp_path));w.show();assert w.main_tabs.count()==4;assert w.shell.delivery_authorization is None
    w.shell.additional();tabs=w.shell._dialogs[-1].findChild(QTabWidget);tabs.setCurrentWidget(w.shell.identity_widget);qt_application_lifetime.processEvents();assert w.shell.identity_widget.isVisible();assert not w.shell.identity_widget.store.summary();w.close()

def test_authorization_ui_empty_cannot_enable(tmp_path,qt_application_lifetime):
    from autojob.ui.main_window import MainWindow
    from autojob.ui.submission_ui import AuthorizeSubmission
    w=MainWindow(Settings(tmp_path));d=AuthorizeSubmission(w.shell);d.save();assert d.authorization is None;assert d.status.text();d.close();w.close()

@pytest.mark.parametrize('options',[dict(explicit=False,upload=True),dict(explicit=True,upload=False),dict(explicit=True,upload=True,max_count=0)])
def test_authorization_requires_review(tmp_path,options):
    s=SubmissionStore(tmp_path);settings=dict(max_count=1,explicit=True,upload=True);settings.update(options)
    with pytest.raises(ValueError):s.authorize([],**settings)

def test_claim_recovery_duplicate_and_revocation(tmp_path):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);id=s.claim(a,j);assert s.duplicate(j)
        with pytest.raises(ValueError):s.claim(a,j)
        assert s.recover()==1;assert s.rows()[0]['state']=='ENVÍO NO VERIFICADO';s.revoke(a)
        with pytest.raises(ValueError):s.permission(a,j)

def test_authorization_expires_when_data_changes(tmp_path):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);s.prep.data.save(dict(ram_gb='16'),confirmed=['ram_gb'])
        with pytest.raises(ValueError):s.permission(a,j)

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Integración Brave separada; activar AUTOJOB_TEST_BRAVE=1')
@pytest.mark.parametrize('multistage',[False,True])
def test_brave_local_submit_upload_receipt_persistence_and_dedup(tmp_path,multistage):
    with portal(tmp_path,multistage=multistage) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);sender=SubmissionEngine(lab['settings']);result=sender.run(j['id'],a)
        assert result['state']=='ENVIADA CONFIRMADA';assert result['mode']=='local';assert result['evidence']['receipt_id']=='LOCAL-9B-001';assert lab['upload_verified'];assert s.rows()[0]['state']=='ENVIADA CONFIRMADA'
        assert sender.run(j['id'],a)['state']=='BLOQUEADA';assert sum(m=='POST' for m,p in lab['requests'])==1
        from autojob.control import ControlStore
        assert ControlStore(lab['settings'].data_path).confirmed()==0

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Integración Brave separada')
def test_uncertain_never_resubmits(tmp_path):
    with portal(tmp_path,unverified=True) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);e=SubmissionEngine(lab['settings']);assert e.run(j['id'],a)['state']=='ENVÍO NO VERIFICADO';assert e.run(j['id'],a)['state']=='BLOQUEADA';assert sum(m=='POST' for m,p in lab['requests'])==1

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Integración Brave separada')
def test_missing_popup_save_resume_then_submit(tmp_path,qt_application_lifetime,await_ui):
    with portal(tmp_path,unknown=True) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);assert SubmissionEngine(lab['settings']).run(j['id'],a)['state']=='PENDIENTE';assert not any(m=='POST' for m,p in lab['requests'])
        from autojob.ui.main_window import MainWindow
        from autojob.ui.submission_ui import MissingInformation
        w=MainWindow(lab['settings']);w.shell.center.refresh();row=next(r for r in w.shell.center.rows if r['job_id']==j['id']);d=MissingInformation(w.shell.center,row);d.show();assert not d.isModal();await_ui(lambda:not d.loading);assert d.question.currentText()=='Unknown mandatory project code';d.control.setText('LOCAL-APPROVED');d.confirm.setChecked(True);d.save();await_ui(lambda:not d.saving)
        assert w.shell.center.service.validate(row)
        ok,id=w.shell.center.service.resume(row['id']);assert ok and id==j['id'];assert next(r for r in w.shell.engine.queue.list() if r['job_id']==id)['priority']==100000
        # La nueva respuesta invalida el alcance anterior: revisión explícita de la versión nueva.
        b=s.authorize([j['id']],1,True,True,'local',True);result=SubmissionEngine(lab['settings']).run(j['id'],b);assert result['state']=='ENVIADA CONFIRMADA';w.close()


def test_manual_education_and_skills_feed_forms(tmp_path):
    from autojob.forms.preparation import Preparation
    p=Preparation(tmp_path);state=p.data.profile.load();v=state['values'];v.update(university='Fictional University',skills=['Python'],education_records=['Bachelor in progress']);p.data.profile.save(v,state['revision'],confirmed=['university','skills','education_records'])
    assert p.resolve('University')['answer']=='Fictional University'
    assert p.resolve('Technical skills')['status']=='CONFIRMADA'
    assert p.resolve('Education')['answer']=='Bachelor in progress'


def test_local_letter_draft_needs_explicit_approval(tmp_path):
    from autojob.forms.submission_letters import SubmissionLetters
    with portal(tmp_path) as lab:
        service=SubmissionLetters(lab['settings'].data_path);job=lab['job'];cv=lab['engine'].compatibility.latest()[job['id']]['resume_selection']['resume_id'];draft=service.draft(job,cv)
        assert service.artifact(job,cv) is None
        with pytest.raises(ValueError):service.approve(job,draft['id'],draft['body'])
        service.approve(job,draft['id'],draft['body'],True);assert service.artifact(job,cv).read_bytes().startswith(b'%PDF')


def test_legacy_uncertain_prevents_new_send(tmp_path):
    with portal(tmp_path) as lab:
        store=SubmissionStore(lab['settings'].data_path);job=lab['job']
        with closing(store.db.connect()) as db,db:db.execute("INSERT INTO applications(company,title,url,discovered_at,status) VALUES (?,?,?,'test','NO VERIFICADA')",(job['company'],job['title'],job['url']))
        assert store.duplicate(job)


def test_delivery_guard_allows_one_exact_authorized_post():
    from autojob.forms.submissions import DeliveryGuard
    from hashlib import sha256
    cv_digest=sha256(b'FILE').hexdigest()
    class Request:
        method='POST';url='https://portal.example/submit';resource_type='document'
        headers={'content-type':'multipart/form-data; boundary=b9e'}
        post_data_buffer=b'--b9e\r\nContent-Disposition: form-data; name="cv"; filename="cv.pdf"\r\nContent-Type: application/pdf\r\n\r\nFILE\r\n--b9e--\r\n'
    class Route:
        request=Request()
        def continue_(self):self.allowed=True
        def abort(self):self.allowed=False
    g=object.__new__(DeliveryGuard);g.site='https://portal.example';g.final=False;g.endpoint='https://portal.example/submit';g.used=False;g.check=lambda:None;g.blocked=0;g.captcha_provider=None;g.rule={'cv_hash':cv_digest};g.expected_fields=[dict(name='cv',value=None,file=dict(name='cv.pdf',size=4,sha256=cv_digest))]
    r=Route();g.route(r);assert not r.allowed
    g.final=True;g.route(r);assert r.allowed;g.route(r);assert not r.allowed
    g.used=False;r.request.url='https://other.example/submit';g.route(r);assert not r.allowed


def test_new_answer_only_renews_matching_active_scope(tmp_path):
    with portal(tmp_path) as lab:
        s=SubmissionStore(lab['settings'].data_path);j=lab['job'];a=s.authorize([j['id']],1,True,True,'local',True);before=s.prep.inputs_hash();ScopedAnswers(lab['settings'].data_path).save('Question','Answer',context=dict(job_id=j['id'],modality='remote'),confirmed=True);s.accept_confirmed_answer(a,j['id'],before);assert s.permission(a,j)


def test_reserved_brave_still_allows_search_and_evaluation(tmp_path):
    from autojob.browser.lock import ProfileLock
    with portal(tmp_path) as lab:
        engine=lab['engine'];called=[];lock=ProfileLock(lab['settings'].data_path/'browser.lock');lock.acquire()
        def search(*args):called.append('search');return dict(found=0,duplicates=0,errors=[])
        def prepare(*args,**kwargs):raise AssertionError('No debe manipular el navegador reservado')
        try:
            result=engine.run(dict(queries=['Python'],sources=['LOCAL'],limit=1),services=dict(search=search,geography=lambda *a:None,availability=lambda *a:None,prepare=prepare))
            assert called==['search'];assert result['evaluation']['evaluated']+result['evaluation']['cached']>=1;assert not result['prepared_ids'];assert any(r['state']=='POR PREPARAR' for r in engine.queue.list())
        finally:lock.release()


def test_approved_answers_visible_editable_preserves_scope(tmp_path,qt_application_lifetime):
    from autojob.ui.submission_ui import ApprovedAnswersPanel
    store=ScopedAnswers(tmp_path);context=dict(job_id='fixture',modality='remote',position='Role');store.save('Project code','OLD',context=context,confirmed=True)
    panel=ApprovedAnswersPanel(tmp_path);panel.table.selectRow(0);panel.value.setPlainText('NEW');panel.confirm.setChecked(True);panel.save()
    assert store.resolve('Project code',context)['answer']=='NEW'
    assert store.resolve('Project code',dict(context,job_id='another')) is None
    panel.close()


def test_radio_question_keeps_group_and_known_options(tmp_path,qt_application_lifetime,await_ui):
    from autojob.forms.preparation import Preparation
    from autojob.forms.runner import enrich
    from autojob.ui.main_window import MainWindow
    from autojob.ui.submission_ui import MissingInformation
    from autojob.control import ControlStore
    from autojob.forms.queue import PreparationQueue
    with portal(tmp_path) as lab:
        job=lab['job'];prep=Preparation(lab['settings'].data_path);doc=dict(url=job['application_url'],title=job['title'],obstacles=[],fields=[dict(id=str(i),selector='#radio'+str(i),label=label,kind='radio',tag='input',required=True,name='transport',group='Preferred transport',options=[]) for i,label in enumerate(['Bus','Car'])]);preview=prep.prepare(doc,job);q=PreparationQueue(lab['settings'].data_path);q.add([job['id']]);q.update(job['id'],'PENDIENTE','Question pending',dict(company=job['company'],title=job['title'],stages=[dict(document=doc,preview=preview)],pending=[dict(field='Preferred transport',required=True)],blocks=[dict(type='DATO OBLIGATORIO PENDIENTE',evidence='Preferred transport')]))
        w=MainWindow(lab['settings']);w.shell.center.refresh();row=next(r for r in w.shell.center.rows if r['job_id']==job['id']);d=MissingInformation(w.shell.center,row);await_ui(lambda:not d.loading);assert d.control.count()==3;d.control.setCurrentText('Car');d.confirm.setChecked(True);d.save();await_ui(lambda:not d.saving);fresh=prep.prepare(doc,job);assert all(enrich(prep,e)['answer']=='Car' and enrich(prep,e)['status']=='CONFIRMADA' for e in fresh['entries']);assert w.shell.center.service.validate(row);w.close()


def test_sensitive_identifiers_never_enter_plain_answer_bank(tmp_path):
    from autojob.auth.identity import IdentityStore
    from autojob.forms.preparation import Preparation
    for question in ['Social security number','SSN','Tax ID','Identity number','Número de identidad']:
        with pytest.raises(ValueError):ScopedAnswers(tmp_path).save(question,'FICTIONAL',context=dict(job_id='local'),confirmed=True)
    assert IdentityStore(tmp_path).resolve('Identity number')['sensitive_identity'] is True
    assert Preparation(tmp_path).resolve('Social security number')['status']=='SENSIBLE'


@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Integración Brave separada')
def test_optional_unconfirmed_portal_default_never_sent(tmp_path):
    with portal(tmp_path,prefilled_optional=True) as lab:
        s=SubmissionStore(lab['settings'].data_path);job=lab['job'];a=s.authorize([job['id']],1,True,True,'local',True);result=SubmissionEngine(lab['settings']).run(job['id'],a)
        assert result['state']=='PENDIENTE';assert not any(m=='POST' for m,p in lab['requests']);assert not s.rows()
