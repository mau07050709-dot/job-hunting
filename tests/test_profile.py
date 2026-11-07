from copy import deepcopy
from datetime import date
import pytest
from autojob.profile.store import ProfileStore,empty,validate
from autojob.resumes.service import ResumeLibrary
from resume_fixtures import write_docx,EN_TECH

def test_create_save_restart_and_unknown(tmp_path):
 s=ProfileStore(tmp_path);assert s.load()['values']==empty()
 values=empty();values.update(full_name='Test User',email='test@example.invalid',birth_date='2000-01-01')
 s.save(values,0);assert ProfileStore(tmp_path).load()['values']==values

@pytest.mark.parametrize('key,value',[('birth_date','2099-01-01'),('birth_date','2020-02-30'),('email','bad'),('phone','123'),('salary_min','NaN'),('currency','dollars'),('linkedin','https://example.invalid')])
def test_validation(key,value):
 values=empty();values[key]=value
 with pytest.raises(ValueError):validate(values)

def test_import_protect_dedupe_conflict(tmp_path):
 library=ResumeLibrary(tmp_path/'data');library.import_document(write_docx(tmp_path/'one.docx'))
 store=ProfileStore(tmp_path/'data');state=store.import_resumes(library)
 assert state['values']['email']=='alex@example.invalid'
 assert state['values']['university'] and state['values']['experience_records']
 once=state['values']['experience_records'];assert store.import_resumes(library)['values']['experience_records']==once
 state=store.load();values=deepcopy(state['values']);values['full_name']='Manual Person';store.save(values,state['revision'])
 library.import_document(write_docx(tmp_path/'two.docx',EN_TECH.replace('alex@example.invalid','other@example.invalid')))
 state=store.import_resumes(library);assert state['values']['full_name']=='Manual Person';assert state['values']['email'] is None;assert 'email' in state['conflicts']

def test_stale_write(tmp_path):
 s=ProfileStore(tmp_path);s.save(empty(),0)
 with pytest.raises(ValueError):s.save(empty(),0)

def test_gui_save_import_reopen(tmp_path):
 import os
 os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
 from PySide6.QtWidgets import QApplication
 from autojob.config import Settings
 from autojob.ui.main_window import MainWindow
 app=QApplication.instance() or QApplication([]);settings=Settings(root=tmp_path)
 library=ResumeLibrary(settings.data_path);library.import_document(write_docx(tmp_path/'cv.docx'))
 w=MainWindow(settings);w.show();p=w.profile_widget;p.import_cvs();p.widgets['full_name'].setText('Manual Person');assert p.save();w.close();app.processEvents()
 second=MainWindow(settings);assert second.profile_widget.widgets['full_name'].text()=='Manual Person';second.close()
