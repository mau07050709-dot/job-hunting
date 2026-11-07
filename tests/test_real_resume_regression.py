"""Validación local opcional contra el CV real, con expectativas privadas en data/."""
import json
import os
from pathlib import Path

import pytest
from autojob.resumes.analysis import analyze
from autojob.resumes.extraction import extract_document
from autojob.resumes.service import ResumeLibrary
from hashlib import sha256


@pytest.mark.skipif(os.environ.get("JOB_HUNTING_TEST_REAL_CV", os.environ.get("AUTOJOB_TEST_REAL_CV")) != "1", reason="Requiere el CV real y la referencia privada local")
def test_real_cv_matches_manual_visual_review():
    library = ResumeLibrary(Path.cwd() / "data")
    manifest = json.loads((library.data_path / "quality/real-cv-expectations.json").read_text(encoding="utf-8"))
    from autojob.resumes.models import ResumeError
    try:
        path = library.original_path(manifest["resume_id"])
    except ResumeError:
        pytest.skip("CV histórico ausente; se conserva la referencia sin alterar")
    content = path.read_bytes()
    if sha256(content).hexdigest() != manifest["sha256"]:
        pytest.fail("El original cambió respecto a la revisión visual.")
    result = analyze(extract_document(content, path.suffix))
    if any(result["fields"].get(key) != value for key,value in manifest["expected"].items()):
        pytest.fail("Un dato personal no coincide con la fuente real revisada.")
    jobs = result["structure"]["experience"]
    if [row["company"] for row in jobs] != manifest["job_companies"]:
        pytest.fail("La estructura de empresas no coincide con el documento revisado.")
    if [len(row["responsibilities"]) for row in jobs] != manifest["responsibility_counts"]:
        pytest.fail("Faltan responsabilidades presentes en el documento revisado.")
    if len(result["structure"]["education"]) != 2 or len(result["structure"]["academic_projects"]) != 2:
        pytest.fail("Educación o proyectos no coinciden con el documento real.")
    if result["structure"]["education"][0]["academic_status"] != "en curso":
        pytest.fail("El estado académico de la formación en curso no es correcto.")
