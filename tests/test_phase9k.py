from test_submissions9b import portal
from test_phase9f import criteria
from autojob.forms.batches import create
from autojob.forms.submissions import SubmissionStore
from autojob.ui.batch_ui import BatchAuthorization
from autojob.ui.main_window import MainWindow


def test_batch_validation_points_to_missing_domains_and_cv(tmp_path, qt_application_lifetime, await_ui):
    from autojob.config import Settings

    window = MainWindow(Settings(tmp_path))
    dialog = BatchAuthorization(window.shell)
    await_ui(lambda: not window._ui_tasks, 30000)
    dialog.upload.setChecked(True)
    dialog.send.setChecked(True)
    dialog.types.setText('Customer Support')
    dialog.save()
    assert dialog.authorization is None
    assert 'origen HTTPS' in dialog.field_errors['domains'].text()
    assert 'CV revisado' in dialog.field_errors['cv'].text()
    assert 'No se activó el lote' in dialog.status.text()
    dialog.close()
    window.close()


def test_batch_ui_rejects_domain_paths_and_informs_beside_field(tmp_path, qt_application_lifetime, await_ui):
    from autojob.config import Settings

    window = MainWindow(Settings(tmp_path))
    dialog = BatchAuthorization(window.shell)
    await_ui(lambda: not window._ui_tasks, 30000)
    dialog.domains.setText('https://jobs.example.com/apply')
    dialog.save()
    assert dialog.authorization is None
    assert 'sin rutas' in dialog.field_errors['domains'].text()
    dialog.close()
    window.close()


def test_home_does_not_reactivate_or_display_historical_batches(tmp_path, qt_application_lifetime, await_ui):
    from autojob.config import Settings

    with portal(tmp_path) as lab:
        store = SubmissionStore(lab['settings'].data_path)
        token = create(store, criteria(store, lab['job']), 2, 1, True, True, 'local', True)
        window = MainWindow(lab['settings'])
        await_ui(lambda: not window._ui_tasks, 30000)
        window.shell.occupied = lambda: False
        assert window.shell.delivery_authorization is None
        assert window.shell.engine.delivery_authorization is None
        assert not window.shell.home.update_authorization()
        assert not window.shell.home.authorization_status.isVisible()
        assert not lab['requests']
        window.close()


def test_start_from_main_ui_uses_execution_instead_of_batch(tmp_path, qt_application_lifetime, await_ui, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from autojob.ui.batch_ui import BatchAuthorization

    with portal(tmp_path) as lab:
        window = MainWindow(lab['settings'])
        await_ui(lambda: not window._ui_tasks, 30000)
        window.shell.occupied = lambda: False
        import pytest,json
        from contextlib import closing
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        monkeypatch.setattr(BatchAuthorization,'exec',lambda *a:pytest.fail('No solicitar lote'))
        called=[];monkeypatch.setattr(window.shell.engine,'run',lambda *a:called.append(1) or dict(state='FINALIZADO'))
        window.show();QTest.mouseClick(window.shell.home.start,Qt.MouseButton.LeftButton);await_ui(lambda:bool(called) and not window.shell.busy(),30000)
        assert window.shell.delivery_authorization
        assert window.shell.engine.delivery_authorization == window.shell.delivery_authorization
        with closing(SubmissionStore(lab['settings'].data_path).db.connect()) as db:scope=json.loads(db.execute('SELECT scope FROM submission_authorizations WHERE id=?',(window.shell.delivery_authorization,)).fetchone()[0])
        assert '_execution' in scope and '_batch' not in scope
        assert not lab['requests']
        window.close()


def test_intervention_popup_is_visible_immediately(tmp_path, qt_application_lifetime, await_ui):
    from autojob.config import Settings

    window = MainWindow(Settings(tmp_path))
    await_ui(lambda: not window._ui_tasks, 30000)
    center = window.shell.center
    row_id = window.shell.engine.store.add_intervention('fixture-job', 'Fictional employer', 'Support agent', 'CAPTCHA PENDIENTE', 'Resolve the local challenge', 'https://example.invalid/apply')
    row = next(item for item in window.shell.engine.store.interventions() if item['id'] == row_id)
    center.show_problem(row, dict(popups=True, notifications=False))
    assert center.popup.isVisible()
    center.popup.close()
    window.close()
