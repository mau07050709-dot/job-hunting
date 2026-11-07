from pathlib import Path
import time
import pytest
from autojob.config import Settings
from autojob.people import People
from autojob.manual_search import ManualSearch,application_rows
from autojob.search.onsite import OnsitePreferences


def test_registry_preserves_legacy_and_separates_new_person(tmp_path):
    from test_batch_https import seed
    existing,cv=seed(tmp_path)
    people=People(Settings(tmp_path))
    legacy=people.active()
    assert legacy["alias"]=="Alex"
    assert people.settings_for(legacy["id"]).data_path==tmp_path/"data"
    second=people.create(" Otra persona ")
    settings=people.settings_for(second["id"])
    assert settings.data_path!=tmp_path/"data"
    engine=ManualSearch(settings)
    assert not engine.compatibility.library.list()
    assert not engine.compatibility.profile.load()["values"]["full_name"]
    assert not application_rows(engine.results.latest())
    assert existing.prep.compatibility.library.get(cv)["reviewed"]
    assert not engine.compatibility.library.list()
    people.select(second["id"])
    assert People(Settings(tmp_path)).active()==second
    people.rename(second["id"],"Otro alias")
    assert people.settings_for(second["id"]).data_path==settings.data_path
    with pytest.raises(ValueError):people.create("alex")
    with pytest.raises(ValueError):people.rename(second["id"],"Alex")
    with pytest.raises(ValueError):people.create(" ")
    settings.save()
    assert Settings.load(tmp_path).data_dir=="data"


def test_results_preferences_and_cv_selection_are_per_person(tmp_path):
    from test_batch_https import seed
    from autojob.profile.store import ProfileStore
    existing,cv=seed(tmp_path)
    people=People(Settings(tmp_path))
    legacy=people.settings_for("legacy")
    other=people.settings_for(people.create("Otro")["id"])
    first=ManualSearch(legacy)
    second=ManualSearch(other)
    original=first.jobs.list()[0]
    first.results.save(dict(results=[dict(job=original,url=original["application_url"])],review=[]))
    first.results.set_target(7)
    OnsitePreferences(legacy.data_path).save(["Turrialba"])
    OnsitePreferences(other.data_path).save(["Heredia"])
    assert first.results.target()==7 and second.results.target()==30
    assert len(application_rows(first.results.latest()))==1
    assert not application_rows(second.results.latest())
    # La misma oferta podrá encontrarse para ambas personas, con historiales independientes.
    second.jobs.add(original)
    job=second.jobs.list()[0]
    second.results.add(dict(job=job,url=job["application_url"]))
    assert len(application_rows(second.results.latest()))==1
    assert second.compatibility.selection(job,second.compatibility.snapshot())["resume_id"] is None
    assert first.compatibility.library.original_path(cv).exists()
    assert OnsitePreferences(legacy.data_path).load()["localities"]==["Turrialba"]
    assert OnsitePreferences(other.data_path).load()["localities"]==["Heredia"]


def test_switch_updates_all_pages_and_survives_restart(tmp_path,qt_application_lifetime,await_ui):
    from test_search_target import setup
    from autojob.ui.main_window import MainWindow
    e=setup(tmp_path,0)
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    before_rows=w.shell.posts.rows.copy()
    before_found=w.shell.home.cards["found"].text()
    first=w.person["id"]
    second=w.people.create("Segunda persona")
    w.main_tabs.setCurrentIndex(1)
    w.shell.data_view.reload_people()
    w.shell.data_view.person_selector.setCurrentIndex(w.shell.data_view.person_selector.findData(second["id"]))
    await_ui(lambda:not w._ui_tasks)
    assert w.person==second
    assert w.main_tabs.currentIndex()==1
    assert w.shell.posts.rows==[]
    assert w.shell.data_view.rows==[]
    assert w.shell.home.cards["found"].text().endswith("0")
    assert not w.shell.home.start.isEnabled()
    assert "Segunda persona" in w.shell.home.active.text()
    assert "Segunda persona" in w.shell.posts.person_label.text()
    settings=w.settings
    assert w.close()
    again=MainWindow(Settings(tmp_path))
    await_ui(lambda:not again._ui_tasks)
    assert again.person==second
    assert again.settings.data_path==settings.data_path
    assert again.switch_person(first)
    await_ui(lambda:not again._ui_tasks)
    assert again.shell.posts.rows==before_rows
    assert again.shell.home.cards["found"].text()==before_found
    assert len(again.shell.data_view.rows)==1
    assert again.shell.home.start.isEnabled()
    assert again.close()


def test_old_widgets_and_late_callbacks_do_not_leak_personal_data(tmp_path,qt_application_lifetime,await_ui):
    from test_batch_https import seed
    from autojob.ui.main_window import MainWindow
    seed(tmp_path)
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    old_tool=w.profile_widget
    old_settings=old_tool.settings
    person=w.people.create("Otra")
    assert w.switch_person(person["id"])
    await_ui(lambda:not w._ui_tasks)
    assert w.profile_widget is not old_tool
    assert w.profile_widget.settings.data_path!=old_settings.data_path
    assert not w.shell.engine.compatibility.profile.load()["values"]["full_name"]
    assert w.close()


def test_switch_waits_for_worker_refresh_and_extension(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    previous=w.person.copy()
    person=w.people.create("Otra")
    w.shell._fill_request=True
    assert not w.switch_person(person["id"])
    assert w.person==previous and w.people.active()==previous
    w.shell._fill_request=False
    w.shell.extension_fill.tasks["pending"]=dict(state="FILLING")
    assert not w.switch_person(person["id"])
    assert w.person==previous
    w.shell.extension_fill.tasks.clear()
    monkeypatch.setattr(w.shell,"busy",lambda:True)
    assert not w.switch_person(person["id"])
    monkeypatch.setattr(w.shell,"busy",lambda:False)
    assert w.switch_person(person["id"])
    await_ui(lambda:not w._ui_tasks)
    assert w.close()


def test_shared_pairing_never_resumes_previous_person_task(tmp_path):
    from autojob.extension_fill import ExtensionFill
    base=Settings(tmp_path)
    base.data_path.mkdir()
    people=People(base)
    second=people.settings_for(people.create("Otra")["id"])
    second.data_path.mkdir(parents=True)
    first=ExtensionFill(base,pair_data_path=base.data_path)
    first.handle("/ping",dict(fast_wake=True))
    first.tasks["old"]=dict(state="DONE",created=time.monotonic(),url="https://employer.example/job/1",job=dict(id="a"))
    first.retire()
    with pytest.raises(ValueError):first.handle("/resume",dict(id="old",url="https://employer.example/job/1"))
    bridge=ExtensionFill(second,pair_data_path=base.data_path)
    assert bridge.token==first.token and bridge.paired
    assert bridge.settings.data_path==second.data_path
    assert bridge.handle("/next",{})=={}
    with pytest.raises(ValueError):bridge.handle("/resume",dict(id="old",url="https://employer.example/job/1"))


def test_cancel_unsaved_profile_keeps_current_person(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    before=w.person.copy()
    second=w.people.create("Otra")
    monkeypatch.setattr(w.profile_widget,"allow_close",lambda:False)
    assert not w.switch_person(second["id"])
    assert w.person==before and w.people.active()==before
    monkeypatch.setattr(w.profile_widget,"allow_close",lambda:True)
    assert w.close()


def test_search_uses_only_active_person_cv_and_does_not_mix_catalogs(tmp_path):
    from test_batch_https import seed
    from docx import Document
    from autojob.search.jobs import Connector
    seed(tmp_path)
    people=People(Settings(tmp_path))
    tech=ManualSearch(people.settings_for("legacy"))
    support=ManualSearch(people.settings_for(people.create("Support")["id"]))
    doc=Document()
    for text in ["Full name: Morgan Example","Email: morgan@example.invalid","Work Experience:",
                 "Customer Support | Example Hotel | 2022 - 2024","Skills:","Customer Service, Communication",
                 "Languages:","English C1","Spanish native"]:
        doc.add_paragraph(text)
    path=tmp_path/"support.docx"
    doc.save(path)
    cv=support.compatibility.library.import_document(path)
    support.compatibility.library.update(cv["id"],title="Support CV",language="en",specialty="customer_service",
                                         fields=cv["fields"],reviewed=True,expected_revision=cv["revision"])
    support.compatibility.library.set_default(cv["id"])
    for engine,position in [(tech,"Software Developer"),(support,"Customer Support")]:
        profile=engine.compatibility.profile
        state=profile.load()
        values=state["values"]
        values.update(country="Costa Rica",work_authorization=True,positions=[position])
        profile.save(values,state["revision"],confirmed=["country","work_authorization","positions"])
    raw=[dict(title=title,companyName="Example",guid="https://employer.example/job/"+slug,
              description=description,locationRestrictions=["Costa Rica"],timezoneRestrictions=["-6"])
         for title,slug,description in [
             ("Junior Software Developer","python","Develop software with Python. Remote in Costa Rica."),
             ("Customer Support","support","Support customers by email. Remote in Costa Rica.")]]
    for engine in (tech,support):
        for job in Connector("Himalayas").search_jobs([],payload=dict(jobs=raw,_country_filter="CR")):
            engine.jobs.add(job)
        engine.run(dict(target=5,queries=["support","python"],sources=[]),
                   services=dict(search=lambda *a:dict(errors=[]),check=lambda j:None))
    tech_titles={r["job"]["title"] for r in application_rows(tech.results.latest())}
    support_titles={r["job"]["title"] for r in application_rows(support.results.latest())}
    assert "Customer Support" not in tech_titles
    assert "Junior Software Developer" in tech_titles
    assert support_titles=={"Customer Support"}
    selected=support.compatibility.selection(support.jobs.list()[0],support.compatibility.snapshot())
    assert selected["resume_id"] in {None,cv["id"]}


def test_failed_switch_restores_person_and_widgets(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from autojob.ui.main_window import MainWindow
    w=MainWindow(Settings(tmp_path))
    await_ui(lambda:not w._ui_tasks)
    before=w.person.copy()
    original=w.shell
    other=w.people.create("Otra")
    monkeypatch.setattr(w,"_create_workspace",lambda *a:(_ for _ in ()).throw(OSError("fixture failure")))
    assert not w.switch_person(other["id"])
    await_ui(lambda:not w._ui_tasks)
    assert w.person==before and w.people.active()==before and w.shell is original
    assert not w.shell.extension_fill.retired
    assert w.shell.timer.isActive()
    assert w.close()
