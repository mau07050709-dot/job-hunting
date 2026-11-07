import os,json
from pathlib import Path
from hashlib import sha256
import pytest
from autojob.resumes.service import ResumeLibrary
from autojob.resumes.extraction import extract_document
from autojob.resumes.analysis import analyze

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_REAL_CV', os.environ.get('AUTOJOB_TEST_REAL_CV'))!='1',reason='Requiere la referencia privada del CV actual')
def test_current_real_cv():
 library=ResumeLibrary(Path.cwd()/'data')
 ref=json.loads((library.data_path/'quality/real-cv-current-4b.json').read_text(encoding='utf-8'))
 content=library.original_path(ref['resume_id']).read_bytes()
 if sha256(content).hexdigest()!=ref['sha256']: pytest.fail('El CV actual cambió tras la revisión visual.')
 result=analyze(extract_document(content,'.pdf'))
 if any(result['fields'].get(k)!=v for k,v in ref['expected'].items()):pytest.fail('Los datos personales no coinciden con el documento revisado.')
 if ref.get('structure_expected') is not None:assert result['structure']==ref['structure_expected']
