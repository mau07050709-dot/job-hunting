from pathlib import Path
from autojob.config import Settings
from autojob.search.onsite import OnsitePreferences
from autojob.notice_media import NoticeMedia
from autojob.profile.application_data import ApplicationData


def test_public_defaults_have_no_applicant_preferences(tmp_path):
 assert OnsitePreferences(tmp_path).load()==dict(localities=[],night_search=False)
 assert ApplicationData(tmp_path).value('main_min')[0] is None
 assert ApplicationData(tmp_path).value('start_date')[0] is None
 assert NoticeMedia(tmp_path).load()==dict(enabled=False,sound=False,url='')


def test_external_submission_is_blocked_before_browser(tmp_path,monkeypatch):
 from test_batch_https import seed
 from autojob.forms.submissions import SubmissionEngine
 store,_=seed(tmp_path);job=store.prep.compatibility.jobs.list()[0]
 engine=SubmissionEngine(Settings(tmp_path))
 monkeypatch.setattr(engine.store,'permission',lambda *a:(dict(mode='real'),{}))
 assert engine.run(job['id'],'fictional')==dict(state='PENDIENTE',reason='Public edition: review and submit the application manually in Brave.')
 assert engine.store.rows()==[]


def test_imported_package_is_this_public_copy():
 import autojob
 assert Path(autojob.__file__).resolve().parents[2]==Path(__file__).resolve().parents[1]
