import time
import pytest
from autojob.extension_fill import ExtensionFill,allow_entry,allowed_page
from autojob.config import Settings


def test_button_opens_main_brave_even_if_extension_unpaired(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from test_batch_https import seed
    from autojob.ui.main_window import MainWindow
    import autojob.extension_fill as module
    monkeypatch.setattr(module,"PORT",0)
    seed(tmp_path)
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    job=w.shell.engine.jobs.list()[0]
    calls=[];guides=[]
    monkeypatch.setattr(w.shell.manual_browser,"launch",lambda url,announce=False:calls.append(url) or True)
    monkeypatch.setattr(w.shell,"extension_setup",lambda:guides.append(True))
    w.shell.fill_selected(dict(job=job,url=job["application_url"]))
    await_ui(lambda:not w._ui_tasks)
    assert calls==[job["application_url"]]
    assert guides==[True]
    assert next(iter(w.shell.extension_fill.tasks.values()))["state"]=="WAITING"
    assert w.close()


def test_missing_fields_notice_is_modeless_and_not_repeated(tmp_path,qt_application_lifetime,await_ui):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    notice=dict(id="task",job=dict(company="Example",title="Support"),url="https://example.invalid/job/1",pending=["Unknown required field"],message="Completa Unknown required field")
    w.shell.show_fill_notice(notice)
    popup=w.shell._fill_notices["task"]["dialog"]
    assert popup.isVisible() and not popup.isModal()
    popup.close()
    w.shell.show_fill_notice(notice)
    assert not popup.isVisible()
    w.shell.show_fill_notice(dict(notice,pending=["Another mandatory question"]))
    assert popup.isVisible()
    w.shell.show_fill_notice(dict(notice,pending=[]))
    assert not popup.isVisible()
    assert w.close()


def test_entry_only_accepts_known_job_or_matching_ats_company():
    task=dict(url="https://himalayas.app/companies/example/jobs/support",job=dict(company="Example Inc",url="https://himalayas.app/companies/example/jobs/support"))
    assert allow_entry(task,"https://jobs.lever.co/example/12345")
    assert allowed_page(task,"https://jobs.lever.co/example/12345/apply")
    assert not allowed_page(task,"https://jobs.lever.co/another/123")
    assert not allow_entry(task,"https://jobs.lever.co/another/123")
    assert not allow_entry(task,"https://jobs.lever.co.evil.example/example/123")
    assert not allow_entry(task,"https://accounts.google.com/example/123")
    assert not allow_entry(task,"http://jobs.lever.co/example/123")
    assert not allow_entry(task,"https://jobs.lever.co/")


def test_connectivity_notice_does_not_discard_waiting_task(tmp_path):
    settings=Settings(tmp_path)
    settings.data_path.mkdir()
    bridge=ExtensionFill(settings)
    bridge.tasks["one"]=dict(id="one",state="WAITING",created=time.monotonic()-10,url="https://example.invalid/job/1",job=dict(company="Example",title="Support"))
    bridge.expire()
    assert bridge.tasks["one"]["state"]=="WAITING"
    assert bridge.notices.get_nowait()["pending"]
    bridge.handle("/next",{})
    assert bridge.tasks["one"]["state"]=="FILLING"
    bridge.handle("/done",dict(id="one",filled=0,pending=["Unknown field"]))
    bridge.retry("one")
    assert bridge.tasks["one"]["state"]=="WAITING"
