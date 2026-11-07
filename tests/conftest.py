"""Mantener QApplication viva y destruir widgets antes de cerrar Qt al terminar la suite."""
import os
import pytest

@pytest.fixture(scope='session',autouse=True)
def qt_application_lifetime():
 os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from PySide6.QtCore import QCoreApplication,QEvent
 app=QApplication.instance() or QApplication([])
 yield app
 from PySide6.QtTest import QTest
 import time
 deadline=time.monotonic()+20
 while getattr(app,"_background_tasks",set()) and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
 assert not getattr(app,"_background_tasks",set()), "Hay trabajadores de interfaz pendientes al cerrar Qt"
 for widget in app.topLevelWidgets():
  widget.close();widget.deleteLater()
 QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
 app.processEvents()


@pytest.fixture
def await_ui(qt_application_lifetime):
 def wait(predicate,timeout=10000):
  import time
  from PySide6.QtTest import QTest
  deadline=time.monotonic()+timeout/1000
  while not predicate() and time.monotonic()<deadline:qt_application_lifetime.processEvents();time.sleep(.005)
  assert predicate(), 'La operación asíncrona no terminó a tiempo'
 return wait
