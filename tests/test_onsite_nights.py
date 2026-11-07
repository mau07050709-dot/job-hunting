import json
import pytest
from autojob.search.onsite import OnsitePreferences,locality_matches,night_status,fast_food
from autojob.manual_search import matching_job
from autojob.search.local_jobs import parse_posting,LocalJobs
from autojob.search.jobs import JobStore,Connector


def job(city="Turrialba",**kwargs):
    return dict(title="Cajero nocturno",company="Tienda Ejemplo",location=city+", Costa Rica",
                country="Costa Rica",modality="onsite",geography="CONFIRMADO",description="Atención al cliente",**kwargs)


def test_local_preferences_persist_and_dont_modify_profile(tmp_path):
    from autojob.profile.store import ProfileStore
    before=ProfileStore(tmp_path).load()
    store=OnsitePreferences(tmp_path)
    assert store.load()["localities"]==[]
    assert store.load()["night_search"] is False
    store.save(["Turrialba","turrialba","Paraíso"])
    assert OnsitePreferences(tmp_path).load()["localities"]==["Turrialba","Paraíso"]
    assert ProfileStore(tmp_path).load()==before
    store.save([])
    assert not store.load()["localities"]
    with pytest.raises(ValueError):store.save(["https://example.com"])


def test_city_is_not_province_or_foreign_cartago():
    assert locality_matches(job(),["Turrialba"])
    assert not locality_matches(job(),["Cartago"])
    assert not locality_matches(job("El Guarco"),["Cartago"])
    assert not locality_matches(dict(job(),location="Cartago, Colombia",country="Colombia"),["Cartago"])
    assert not locality_matches(dict(job(),modality="hybrid"),["Turrialba"])
    assert not locality_matches(dict(job(),location="Turrialba",country=None),["Turrialba"])


@pytest.mark.parametrize("text,expected",[
    ("Turno nocturno","NOCTURNO PUBLICADO"),("Overnight support","NOCTURNO PUBLICADO"),
    ("Cierre a las 23:00","NOCTURNO PUBLICADO"),
    ("Horarios rotativos","ROTATIVO — NOCHE POR CONFIRMAR"),
    ("Tienda abierta 24 horas","HORARIO NO PUBLICADO"),
    ("Exclusivamente diurno, sin turnos nocturnos","DIURNO")])
def test_no_invented_night_shift(text,expected):
    assert night_status(dict(title=text))==expected


def test_remote_is_independent_of_local_city_and_fast_food_rejected():
    ev=dict(geography="CONFIRMADO",eligibility="REQUIERE REVISIÓN",score=75,assessments=[])
    assert matching_job(dict(job(),title="Customer Support",location="LATAM",modality="remote"),ev,{"customer_service"},[])
    assert matching_job(job(),ev,{"customer_service"},["Turrialba"])
    assert not matching_job(job(),ev,{"customer_service"},["Cartago"])
    assert not matching_job(dict(job(),company="McDonalds"),ev,{"customer_service"},["Turrialba"])
    assert fast_food(dict(job(),company="KFC"))
    assert not fast_food(dict(job(),company="AMPM"))
    assert not matching_job(job(),dict(ev,assessments=[dict(kind="license",importance="OBLIGATORIO",state="NO CUMPLE")]),{"customer_service"},["Turrialba"])


def posting():
    return dict(**{"@type":"JobPosting"},title="Cajero nocturno",description="Atención al cliente y caja durante turno nocturno.",
                hiringOrganization=dict(name="Tienda Ejemplo"),jobLocation=dict(address=dict(addressCountry="CR",addressLocality="Turrialba")),
                datePosted="2026-11-06",employmentType="FULL_TIME",baseSalary=dict(currency="CRC",value=dict(value=400000,unitText="MONTH")))


def test_structured_source_preserves_data_and_requires_onsite():
    data=posting()
    content='<script type="application/ld+json">'+json.dumps(data)+'</script><p>Modalidad: Presencial · Ubicación: Turrialba</p>'
    row=next(parse_posting(content,"https://saplic.com/empleo/example-1"))
    assert row["locality"]=="Turrialba" and row["date"]=="2026-11-06"
    normalized=next(Connector("Saplic CR").search_jobs([],payload=[row]))
    assert normalized["modality"]=="onsite" and normalized["currency"]=="CRC"
    assert normalized["published_at"]=="2026-11-06"
    assert not list(parse_posting(content.replace("Modalidad: Presencial","Modalidad: Remoto"),row["url"]))
    data["validThrough"]="2020-01-01T00:00:00Z"
    assert not list(parse_posting('<script type="application/ld+json">'+json.dumps(data)+'</script>',row["url"]))


def test_one_city_failure_does_not_block_other_city_and_uses_cache(tmp_path):
    from urllib.error import HTTPError
    calls=[]
    def fetch(url):
        calls.append(url)
        if "Turrialba" in url or "turrialba" in url:raise HTTPError(url,404,"missing",{},None)
        if "/empleo/" not in url:return '<a href="/empleo/cajero-1">Cajero nocturno</a><a href="/empleo/kfc-2">Cajero KFC</a>'
        return '<p>Modalidad: Presencial · Ubicación: Turrialba</p><script type="application/ld+json">'+json.dumps(posting())+'</script>'
    jobs=JobStore(tmp_path)
    loader=LocalJobs(jobs,["Turrialba","Cartago"],fetch=fetch)
    assert len(list(loader.search()))==1 and loader.errors
    assert not any("kfc-2" in url for url in calls)
    before=len(calls)
    assert len(list(LocalJobs(jobs,["Cartago"],fetch=fetch).search()))==1
    assert len(calls)==before


def test_local_query_flows_to_catalog_and_retains_remote_search(tmp_path,monkeypatch):
    from test_search_target import setup,run
    from autojob.manual_search import application_rows
    engine=setup(tmp_path,1)
    OnsitePreferences(engine.settings.data_path).save(["Turrialba"],night_search=True)
    # Esta prueba verifica coordinación y filtros sin cambiar el evaluador real.
    monkeypatch.setattr(engine.compatibility,"one",lambda j,s:dict(score=75,geography="CONFIRMADO",eligibility="REQUIERE REVISIÓN",assessments=[]))
    monkeypatch.setattr("autojob.manual_search.candidate",lambda *a:dict(buckets={"positions":[dict(text="Customer Support"),dict(text="Software Developer")]}))
    raw=dict(title="Cajero nocturno",company="Tienda Ejemplo",id="local1",url="https://saplic.com/empleo/cajero-1",
             description="Atención al cliente y caja, turno nocturno",location="Turrialba, Costa Rica",locality="Turrialba",country="Costa Rica",modality="onsite")
    result=engine.run(dict(target=2,queries=["Python"],sources=[]),services=dict(local_search=lambda cities:[raw,dict(raw,id="other",url="https://saplic.com/empleo/other-2",location="Heredia, Costa Rica",locality="Heredia")],search=lambda *a:dict(errors=[]),check=lambda j:None))
    assert result["new_count"]==2
    local=[r for r in application_rows(result) if r["job"]["source"]=="Saplic CR"]
    assert len(local)==1 and local[0]["night_status"]=="NOCTURNO PUBLICADO"
    assert local[0]["job"]["location"]=="Turrialba, Costa Rica"


def test_locality_button_and_saved_dialog(tmp_path,qt_application_lifetime,await_ui):
    from autojob.config import Settings
    from autojob.ui.main_window import MainWindow
    from PySide6.QtWidgets import QCheckBox,QDialogButtonBox,QPushButton
    w=MainWindow(Settings(tmp_path));await_ui(lambda:not w._ui_tasks)
    assert "ELEGIR LOCALIDAD" in w.shell.data_view.locality_button.text()
    d=w.shell.choose_localities()
    for box in d.findChildren(QCheckBox):box.setChecked(box.text()=="Turrialba")
    buttons=d.findChild(QDialogButtonBox)
    buttons.button(QDialogButtonBox.StandardButton.Save).click()
    assert OnsitePreferences(tmp_path/"data").load()["localities"]==["Turrialba"]
    assert "Turrialba" in w.shell.data_view.locality_summary.text()
    w.close()


def test_gas_station_and_reception_match_service_cv():
    from autojob.matching.engine import family
    from autojob.search.onsite import service_opportunity
    for title in ["Pistero nocturno", "Recepcionista turno noche", "Despachador de combustible", "Cajera de tienda"]:
        assert family(title)=="customer_service"
        assert service_opportunity(dict(title=title))


def test_cancel_does_not_query_sources(tmp_path):
    loader=LocalJobs(JobStore(tmp_path),["Cartago"],cancel=lambda:True,fetch=lambda u:pytest.fail("No consultar tras cancelar"))
    assert list(loader.search())==[]
