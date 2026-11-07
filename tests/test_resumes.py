from hashlib import sha256
import json
from pathlib import Path

from docx import Document
from pypdf import PdfWriter
import pytest

from autojob.resumes.analysis import analyze, detect_language, detect_specialty
from autojob.resumes.extraction import extract_document
from autojob.resumes.models import DuplicateResume, Extraction, ResumeError, TextUnit, empty_fields
from autojob.resumes.selection import ResumeSelector
from autojob.resumes.service import ResumeLibrary
from autojob.storage.database import Database
from resume_fixtures import EN_SERVICE, EN_TECH, ES_TECH, write_docx, write_pdf


@pytest.fixture
def library(tmp_path):
    return ResumeLibrary(tmp_path / "data")


def reviewed(library, item, **changes):
    values = {"title": item["title"], "language": item["language"], "specialty": item["specialty"], "fields": item["fields"], "reviewed": True}
    values.update(changes)
    return library.update(item["id"], expected_revision=item["revision"], **values)


def test_pdf_import_and_all_extracted_fields(tmp_path, library):
    item = library.import_document(write_pdf(tmp_path / "tecnico.pdf"))
    fields = item["fields"]
    assert fields["full_name"] == "Alex Rivera"
    assert fields["email"] == "alex@example.invalid"
    assert fields["phone"] == "+506 8888-7777"
    assert "Ingeniería electrónica" in fields["education"][0]
    assert fields["experience"]
    assert "Laboratorio Ejemplo" in fields["companies"]
    assert "Técnico electrónico" in fields["positions"]
    assert "2022 - 2024" in fields["employment_dates"]
    assert "Arduino" in fields["technical_skills"]
    assert "Python" in fields["programming_languages"]
    assert "Inglés B2" in fields["languages"]
    assert fields["certifications"] and fields["academic_projects"]
    assert item["language"] == "es" and item["specialty"] == "technical"
    assert item["reviewed"] == 0
    assert item["original_analysis"]["evidence"]["email"][0]["location"].startswith("Página 1")


def test_docx_import_and_sources(tmp_path, library):
    source = write_docx(tmp_path / "english.docx")
    item = library.import_document(source)
    assert item["language"] == "en" and item["specialty"] == "technical"
    assert "Example Labs" in item["fields"]["companies"]
    assert "C++" in item["fields"]["programming_languages"]
    assert "C" not in item["fields"]["programming_languages"]
    copy = library.original_path(item["id"])
    assert copy != source and copy.read_bytes() == source.read_bytes()
    assert sha256(copy.read_bytes()).hexdigest() == item["sha256"]
    assert item["source_units"][0]["location"].startswith("Documento")


def test_docx_reads_tables_and_headers(tmp_path, library):
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Full name: Alex Rivera"
    document.add_paragraph("Education:")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Example University"
    document.add_paragraph("Skills: Python, Linux")
    path = tmp_path / "table.docx"
    document.save(path)
    item = library.import_document(path)
    assert item["fields"]["full_name"] == "Alex Rivera"
    assert "Example University" in item["fields"]["education"]
    assert any("celda" in unit["location"] for unit in item["source_units"])


@pytest.mark.parametrize("text,expected", [(EN_TECH, "en"), (ES_TECH, "es"), (EN_SERVICE, "en"), ("Alex Rivera", "unknown"), ("Languages: English, Spanish", "unknown"), ("Junior Python Developer", "en"), ("Electronics Technician", "en"), ("Técnico electrónico", "es")])
def test_language(text, expected):
    assert detect_language(text) == expected


@pytest.mark.parametrize("text,expected", [(EN_TECH, "technical"), (ES_TECH, "technical"), (EN_SERVICE, "customer_service"), ("Unknown opening", "unknown"), ("Python Customer Service", "mixed")])
def test_specialty(text, expected):
    assert detect_specialty(text) == expected


def test_unknown_does_not_invent():
    result = analyze(Extraction([TextUnit("Paragraph", "Python")], []))
    assert result["fields"]["full_name"] is None
    assert result["fields"]["email"] is None
    assert result["fields"]["education"] == []
    assert result["fields"]["languages"] == []
    assert result["fields"]["employment_dates"] == []
    assert result["fields"]["programming_languages"] == ["Python"]


def test_work_dates_are_not_phone():
    result = analyze(Extraction([TextUnit("one", "Experience:"), TextUnit("two", "2022 - 2024")], []))
    assert result["fields"]["phone"] is None
    assert result["fields"]["employment_dates"] == ["2022 - 2024"]


def test_student_identification_is_not_phone():
    result = analyze(Extraction([TextUnit("one", "Student ID: 12345678")], []))
    assert result["fields"]["phone"] is None


@pytest.mark.parametrize("extension,content", [(".pdf", b"not a pdf"), (".docx", b"not a docx"), (".txt", b"text"), (".pdf", b"")])
def test_corrupted_files_do_not_persist(tmp_path, library, extension, content):
    source = tmp_path / ("broken" + extension)
    source.write_bytes(content)
    with pytest.raises(ResumeError):
        library.import_document(source)
    assert library.list() == []
    assert list(library.directory.iterdir()) == []


def test_encrypted_pdf(tmp_path, library):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt("not-a-real-password")
    path = tmp_path / "encrypted.pdf"
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(ResumeError, match="protegido"):
        library.import_document(path)


def test_blank_pdf_is_unknown_not_fabricated(tmp_path, library):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    path = tmp_path / "technical_english.pdf"
    with path.open("wb") as output:
        writer.write(output)
    item = library.import_document(path)
    assert item["fields"] == empty_fields()
    assert item["language"] == "unknown" and item["specialty"] == "unknown"
    assert any("Sin texto" in warning for warning in item["original_analysis"]["warnings"])


def test_duplicate_by_hash_despite_renaming(tmp_path, library):
    source = write_docx(tmp_path / "first.docx")
    first = library.import_document(source)
    renamed = tmp_path / "renamed.docx"
    renamed.write_bytes(source.read_bytes())
    with pytest.raises(DuplicateResume) as duplicate:
        library.import_document(renamed)
    assert duplicate.value.resume_id == first["id"]
    assert len(library.list()) == 1


def test_corrections_persistence_and_original_evidence(tmp_path, library):
    item = library.import_document(write_docx(tmp_path / "cv.docx"))
    fields = {**item["fields"], "full_name": "Corrected by user"}
    edited = reviewed(library, item, fields=fields)
    library.set_default(item["id"])
    reopened = ResumeLibrary(library.data_path)
    saved = reopened.get(item["id"])
    assert saved["fields"]["full_name"] == "Corrected by user"
    assert saved["original_analysis"]["fields"]["full_name"] == "Alex Rivera"
    assert saved["reviewed"] and saved["is_default"]
    assert edited["revision"] == item["revision"] + 1


def test_replace_versions_reset_review_and_preserve_original(tmp_path, library):
    source = write_docx(tmp_path / "old.docx")
    item = reviewed(library, library.import_document(source))
    original_copy = library.original_path(item["id"])
    library.set_default(item["id"])
    replacement = write_pdf(tmp_path / "new.pdf")
    newer = library.import_document(replacement, item["id"], item["revision"])
    assert newer["id"] == item["id"] and newer["reviewed"] == 0 and newer["is_default"]
    assert len(library.versions(item["id"])) == 2
    assert original_copy.exists() and source.exists()
    assert newer["language"] == "es"
    with pytest.raises(DuplicateResume):
        library.import_document(source)


def test_invalid_replacement_keeps_current(tmp_path, library):
    item = library.import_document(write_docx(tmp_path / "ok.docx"))
    corrupt = tmp_path / "bad.pdf"
    corrupt.write_bytes(b"bad")
    with pytest.raises(ResumeError):
        library.import_document(corrupt, item["id"])
    assert library.get(item["id"])["current_version"] == item["current_version"]


def test_delete_managed_versions_only(tmp_path, library):
    source = write_docx(tmp_path / "original.docx")
    item = library.import_document(source)
    managed = library.original_path(item["id"])
    assert library.delete(item["id"], item["revision"]) == 0
    assert source.exists() and not managed.exists()
    assert not library.list()
    assert not library.versions(item["id"])


def test_stale_revision_does_not_overwrite(tmp_path, library):
    item = library.import_document(write_docx(tmp_path / "cv.docx"))
    reviewed(library, item, title="Current")
    with pytest.raises(ResumeError, match="cambió"):
        reviewed(library, item, title="Stale")
    with pytest.raises(ResumeError, match="cambió"):
        library.delete(item["id"], item["revision"])
    assert library.get(item["id"])["title"] == "Current"


def test_migration_preserves_previous_phases(tmp_path):
    data = tmp_path / "data"
    db = Database(data / "autojob.sqlite3")
    db.add_vacancy("Example", "Job", "https://example.invalid/1")
    run = db.start_run("existing")
    db.finish_run(run, True, {"existing": True})
    ResumeLibrary(data)
    assert db.counts() == {"DESCUBIERTA": 1}
    assert db.recent_runs()[0]["id"] == run


@pytest.fixture
def three_cvs(tmp_path, library):
    es = reviewed(library, library.import_document(write_pdf(tmp_path / "tech-es.pdf")))
    en = reviewed(library, library.import_document(write_docx(tmp_path / "tech-en.docx")))
    service = reviewed(library, library.import_document(write_docx(tmp_path / "service-en.docx", EN_SERVICE)))
    return library, es, en, service


@pytest.mark.parametrize("vacancy,language,index", [("Customer Service", "en", 3), ("Junior Python Developer", "auto", 2), ("Electronics Technician", "es", 1), ("Electronics Technician en español", "auto", 1)])
def test_requested_selection_examples(three_cvs, vacancy, language, index):
    library = three_cvs[0]
    result = ResumeSelector(library).select(vacancy, language)
    assert result.resume_id == three_cvs[index]["id"]


def test_default_never_falls_back_to_wrong_language(three_cvs):
    library, es, en, service = three_cvs
    library.set_default(en["id"])
    result = ResumeSelector(library).select("Customer Service", "es")
    assert result.resume_id is None
    assert "No hay" in result.reason


def test_unreviewed_and_ambiguous_stay_pending(tmp_path, library):
    item = library.import_document(write_docx(tmp_path / "tech.docx"))
    selector = ResumeSelector(library)
    assert selector.select("Junior Python Developer").resume_id is None
    reviewed(library, item)
    assert selector.select("Python").resume_id is None
    assert selector.select("Python Customer Service", "en").resume_id is None


def test_multiple_compatible_need_preference(tmp_path, library):
    first = reviewed(library, library.import_document(write_docx(tmp_path / "one.docx")))
    second = reviewed(library, library.import_document(write_docx(tmp_path / "two.docx", EN_TECH + "\nAdditional project")))
    selector = ResumeSelector(library)
    assert selector.select("Junior Python Developer").resume_id is None
    library.set_default(second["id"])
    assert selector.select("Junior Python Developer").resume_id == second["id"]
    library.set_default(first["id"])
    assert sum(item["is_default"] for item in library.list()) == 1


def test_selection_rules_persist(three_cvs):
    library, es, en, service = three_cvs
    selector = ResumeSelector(library)
    rules = selector.load_rules()
    rules["customer_service"].append("MoonDesk assistant")
    selector.save_rules(rules)
    reopened = ResumeSelector(ResumeLibrary(library.data_path))
    assert reopened.select("MoonDesk assistant", "en").resume_id == service["id"]
    with pytest.raises(ResumeError):
        selector.save_rules({"technical": []})


def test_changed_document_is_not_selected(tmp_path, library):
    item = reviewed(library, library.import_document(write_docx(tmp_path / "cv.docx")))
    library.original_path(item["id"]).write_bytes(b"modified")
    assert ResumeSelector(library).select("Junior Python Developer").resume_id is None


def test_sensitive_parser_errors_not_exposed_or_logged(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise ValueError("PRIVATE-DOCUMENT-CONTENT")
    monkeypatch.setattr("autojob.resumes.extraction.PdfReader", fail)
    with pytest.raises(ResumeError) as error:
        extract_document(b"%PDF-private", ".pdf")
    assert "PRIVATE-DOCUMENT-CONTENT" not in str(error.value)
    assert "PRIVATE-DOCUMENT-CONTENT" not in caplog.text
