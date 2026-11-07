from contextlib import closing
from threading import Event
import json
import pytest
from PySide6.QtWidgets import QPushButton
from autojob.config import Settings
from autojob.forms import execution
from autojob.forms.submissions import SubmissionStore
from autojob.form_sessions import FormSessions
from test_batch_https import seed


def test_restore_ticket_reuses_only_prior_cv_and_never_authorizes_post(tmp_path):
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
    token=execution.begin(store,3);store.permission(token,job);execution.close_execution(store,token)
    ticket=execution.preparation_ticket(store,job)
    _,rule=store.permission(ticket,job)
    assert rule['preparation_only'] and rule['cv_id']==cv and rule['upload']
    with pytest.raises(ValueError,match='solo prepara'):store.claim(ticket,job)
    assert not store.rows()


def test_restore_never_opens_uncertain_attempt_or_unapproved_cv(tmp_path):
    store,cv=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
    with pytest.raises(ValueError,match='INICIAR'):execution.preparation_ticket(store,job)
    token=execution.begin(store,1);attempt=store.claim(token,job);store.finish(attempt,'ENVÍO NO VERIFICADO',{'verified':False})
    before=store.rows()
    with pytest.raises(ValueError,match='Resultado final'):execution.preparation_ticket(store,job)
    assert store.rows()==before


def test_pending_session_does_not_block_second_and_workers_are_owned(tmp_path,monkeypatch):
    from autojob.forms.submissions import SubmissionEngine
    finishes={key:Event() for key in ('first','second','third')};entered=[]
    def run(self,job,authorization,**kw):
        assert kw['isolated'] and kw['retain'];entered.append(job);kw['prepared'].set()
        while not finishes[job].wait(.01) and not kw['stop']():pass
        return {'state':'PENDIENTE'}
    monkeypatch.setattr(SubmissionEngine,'run',run)
    pool=FormSessions(Settings(tmp_path),limit=2)
    try:
        assert pool.prepare('first','scope',lambda:False)['state']=='PENDIENTE'
        assert pool.prepare('second','scope',lambda:False)['state']=='PENDIENTE'
        assert entered==['first','second'] and pool.count()==2
        assert pool.launch('first','scope',human=True) is pool.tasks['first']
        assert pool.launch('third','scope') is None and entered==['first','second']
        finishes['first'].set();pool.tasks['first']['thread'].join(3)
        assert pool.launch('third','scope')
    finally:
        pool.cancel_all()
        for task in pool.tasks.values():task['thread'].join(3)
    assert pool.count()==0


def test_isolated_browser_uses_separate_profile_and_lock(tmp_path):
    from autojob.browser import BraveSession
    settings=Settings(tmp_path);a=BraveSession(settings,isolated_key='first');b=BraveSession(settings,isolated_key='second');legacy=BraveSession(settings)
    assert a.profile_path!=b.profile_path and legacy.profile_path==settings.profile_path
    assert a._lock.path!=b._lock.path and a.profile_path.is_relative_to(settings.data_path)


def test_doola_annual_range_keeps_confirmed_conversion_with_explicit_units(tmp_path):
    from autojob.forms.preparation import Preparation
    from autojob.forms.doola import resolve
    prep=Preparation(tmp_path)
    values=dict(main_min='400000',main_max='800000',main_currency='CRC',main_period='month',fx_from='CRC',fx_to='USD',fx_rate='0.002192790106131041')
    prep.data.save(values,confirmed=list(values))
    result=resolve(prep,{'semantic':'doola_salary'}, {})
    assert result['answer']=='USD 10,525.39 - USD 21,050.79 per year'
    assert prep.resolve('Expected salary CRC monthly',{})['answer']=='400000.00–800000.00'


def test_single_button_popup_keeps_pending_on_close(tmp_path,qt_application_lifetime,await_ui):
    from autojob.ui.main_window import MainWindow
    seed(tmp_path);w=MainWindow(Settings(tmp_path));w.shell.timer.stop();await_ui(lambda:not w._ui_tasks,30000)
    store=w.shell.engine.store;job=w.shell.engine.jobs.list()[0]
    id=store.add_intervention(job['id'],job['company'],job['title'],'INFORMACIÓN FALTANTE','Falta una respuesta obligatoria.',job['url'])
    row=next(r for r in store.interventions() if r['id']==id)
    try:
        w.shell.center.show_problem(row,{'notifications':False})
        assert [b.text() for b in w.shell.center.popup.findChildren(QPushButton)]==['RESOLVER AHORA']
        w.shell.center.popup.close()
        assert next(r for r in store.interventions() if r['id']==id)['state']=='PENDIENTE'
    finally:await_ui(lambda:not w._ui_tasks,30000);w.close()
