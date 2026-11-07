from pathlib import Path
from docx import Document
from pypdf import PdfReader
import pytest
from autojob.profile.letters import Letters
from autojob.resumes.service import ResumeLibrary
from resume_fixtures import write_docx

@pytest.fixture
def prepared(tmp_path):
 data=tmp_path/'data';library=ResumeLibrary(data);item=library.import_document(write_docx(tmp_path/'cv.docx'))
 item=library.update(item['id'],title=item['title'],language='en',specialty='technical',fields=item['fields'],reviewed=True,expected_revision=item['revision'])
 return Letters(data),item

@pytest.mark.parametrize('language',['en','es'])
def test_generate_store_export(prepared,tmp_path,language):
 service,cv=prepared;body=service.generate('Example','Developer','Python',language,'technical',cv['id'])
 assert 'Example' in body and 'Developer' in body and 'Python' in body
 key=service.save('Example','Developer','Python',language,'technical',cv['id'],body)
 assert Letters(service.library.data_path).history()[0]['id']==key
 pdf=tmp_path/'letter.pdf';docx=tmp_path/'letter.docx';service.export(body,pdf);service.export(body,docx)
 assert 'Example' in ''.join(page.extract_text() for page in PdfReader(pdf).pages)
 assert 'Example' in '\n'.join(p.text for p in Document(docx).paragraphs)

def test_missing_cv_and_unreviewed(tmp_path):
 service=Letters(tmp_path/'data')
 with pytest.raises(ValueError):service.generate('Example','Developer','','en','technical',None)

def test_custom_template_persists_and_rejects_unsafe_variables(prepared):
 service,cv=prepared
 service.save_template('en','Dear {company}: {position} — {facts} {name}')
 assert 'Dear Example' in Letters(service.library.data_path).generate('Example','Developer','Python','en','technical',cv['id'])
 with pytest.raises(ValueError):service.save_template('en','{name.__class__}')

def test_letter_uses_only_context_relevant_approved_answer(prepared):
 from autojob.profile.answers import AnswerBank
 service,cv=prepared;profile=service.profile.load();bank=AnswerBank(service.library.data_path)
 bank.save('Motivación','en',['Why do you want to work here?'],'Approved reason for Other Company as Developer.',True,profile)
 body=service.generate('Example','Developer','Python','en','technical',cv['id']);assert 'Other Company' not in body
 bank.save('Motivación','es',['¿Por qué quieres trabajar aquí?'],'Razón aprobada para Example como Developer.',True,profile)
 body=service.generate('Example','Developer','Python','es','technical',cv['id']);assert 'Razón aprobada' in body
