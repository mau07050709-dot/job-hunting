import json
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from autojob.browser.discovery import find_brave
from autojob.browser.lock import ProfileLock
from autojob.browser.session import validate_local_endpoint
from autojob.config import Settings
from autojob.errors import BrowserError, ProfileInUse
from autojob.storage.database import Database
from autojob.testing.server import local_server


def test_config_roundtrip(tmp_path):
    settings = Settings(root=tmp_path, browser_transport="cdp")
    settings.save()
    assert Settings.load(tmp_path) == settings
    assert settings.profile_path == tmp_path / "data" / "brave-profile"


@pytest.mark.parametrize("values", [{"mode": "automatic"}, {"browser_transport": "remote"}, {"timeout_ms": 0}, {"timeout_ms": True}, {"headless": "false"}, {"data_dir": ".."}, {"data_dir": "."}, {"data_dir": ""}])
def test_invalid_settings(tmp_path, values):
    with pytest.raises(ValueError):
        Settings(root=tmp_path, **values)


def test_missing_config(tmp_path):
    assert Settings.load(tmp_path).mode == "test"


def test_invalid_brave_path(tmp_path):
    with pytest.raises(BrowserError):
        find_brave(str(tmp_path / "missing.exe"))


def test_lock_release_and_reacquire(tmp_path):
    one = ProfileLock(tmp_path / "lock")
    two = ProfileLock(tmp_path / "lock")
    one.acquire()
    try:
        with pytest.raises(ProfileInUse):
            two.acquire()
    finally:
        one.release()
    two.acquire()
    two.release()


@pytest.mark.parametrize("endpoint", ["http://example.com:9222", "http://localhost:9222", "http://127.0.0.1.evil:9222", "http://user:secret@127.0.0.1:9222", "http://127.0.0.1:9222/path", "http://127.0.0.1:9222?x=1", "http://127.0.0.1:99999", "ws://127.0.0.1:9222", "http://127.0.0.1:0"])
def test_cdp_rejects_nonlocal_or_ambiguous_endpoints(endpoint):
    with pytest.raises(BrowserError):
        validate_local_endpoint(endpoint)


def test_cdp_accepts_loopback():
    assert validate_local_endpoint("http://127.0.0.1:9222") == "http://127.0.0.1:9222"


def test_duplicate_and_persistence(tmp_path):
    path = tmp_path / "history.db"
    db = Database(path)
    assert db.add_vacancy("Example", "Junior", "https://example.invalid/job/1")
    assert not db.add_vacancy("Example", "Junior", "https://example.invalid/job/1")
    assert Database(path).counts() == {"DESCUBIERTA": 1}


def test_runs_and_recovery(tmp_path):
    db = Database(tmp_path / "db")
    done = db.start_run("local")
    db.finish_run(done, True, {"receipt": "LOCAL-1"})
    unfinished = db.start_run("local")
    assert db.recover_runs() == 1
    rows = {row["id"]: row for row in db.recent_runs()}
    assert rows[done]["status"] == "OK"
    assert rows[unfinished]["status"] == "INTERRUMPIDA"
    assert db.recover_runs() == 0


def test_local_server_confirmation_and_validation():
    with local_server() as (url, submissions):
        assert b"Job Hunting" in urllib.request.urlopen(url).read()
        payload = {"name": "Test", "email": "test@example.invalid", "modality": "remote", "file": "test.txt", "consent": True}
        req = urllib.request.Request(url + "submit", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        receipt = json.load(urllib.request.urlopen(req))["receipt"]
        assert submissions[0]["receipt"] == receipt
        assert receipt.startswith("LOCAL-")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url + "submit", data=b"{}"))
        assert error.value.code == 400
        assert len(submissions) == 1
