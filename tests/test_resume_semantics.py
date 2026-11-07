from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from docx import Document
from docx.oxml import parse_xml
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from autojob.resumes.analysis import analyze
from autojob.resumes.extraction import extract_document
from autojob.resumes.models import Extraction, TextUnit
from autojob.resumes.service import ResumeLibrary
from resume_fixtures import EN_TECH, write_docx


def analyze_lines(text):
    return analyze(Extraction([TextUnit(f"Line {i}", line) for i, line in enumerate(text.splitlines())], []))


@pytest.mark.parametrize("name", ["MARÍA JOSÉ LÓPEZ VARGAS", "Alex Rivera", "Juan de la Cruz Pérez"])
def test_name_not_on_first_line(name):
    result = analyze_lines("Curriculum Vitae\n" + name + "\nLocation: San José, Costa Rica\nEmail: example@example.invalid\nEducation:\nExample University")
    assert result["fields"]["full_name"] == name


@pytest.mark.parametrize("phone,expected", [("+506 8888 7777", "+50688887777"), ("+506 8888-7777", "+50688887777"), ("8888-7777", "+50688887777"), ("(506) 8888 7777", "+50688887777"), ("+1 650 253 0000", "+16502530000")])
def test_validated_international_phones(phone, expected):
    result = analyze_lines("Alex Rivera\nUbicación: Heredia, Costa Rica\nTeléfono: " + phone + "\nReferences:\nSomeone Other: +506 8676 9313")
    assert result["fields"]["phone_e164"] == expected
    assert result["fields"]["phone"] != "+506 8676 9313"


def test_no_country_prefix_invented_from_national_number():
    result = analyze_lines("Alex Rivera\nPhone: 8888 7777")
    assert result["fields"]["phone_e164"] is None


def test_reference_name_phone_not_used():
    result = analyze_lines("Curriculum Vitae\nEducation:\nExample University\nReferences:\nJOHN OTHER PERSON\n+506 8676 9313")
    assert result["fields"]["full_name"] is None
    assert result["fields"]["phone"] is None


def test_location_and_professional_links():
    result = analyze_lines("Alex Rivera\nLocation: Cartago, Costa Rica\nlinkedin.com/in/example\nhttps://github.com/example")
    assert result["fields"]["location"] == "Cartago, Costa Rica"
    assert len(result["fields"]["professional_links"]) == 2


def test_multiline_experience_preserves_jobs_and_bullets():
    result = analyze_lines("""Work Experience:
Support Agent
Example Company | 2023 - Present
• Managed customer requests and
maintained complete records.
• Documented support cases and
followed escalation procedures.
Junior Developer
Another Company | 2021 - 2023
• Developed Python tools for testing.
Education:
Bachelor of Engineering (in progress)
Example University | 2024 - Present""")
    rows = result["structure"]["experience"]
    assert len(rows) == 2
    assert rows[0]["company"] == "Example Company"
    assert rows[0]["position"] == "Support Agent"
    assert rows[0]["responsibilities"] == ["Managed customer requests and maintained complete records.", "Documented support cases and followed escalation procedures."]
    assert rows[1]["company"] == "Another Company"
    assert all(row["sources"] and row["raw_text"] for row in rows)
    assert result["structure"]["education"][0]["academic_status"] == "in progress"


def test_education_university_in_progress_and_second_degree():
    result = analyze_lines("""Educación:
Bachillerato en Ingeniería Electrónica (en curso, graduación esperada 2029)
Instituto Tecnológico de Costa Rica (TEC) | 2024 - Actualidad
Bachillerato en Educación Media | Liceo de Ejemplo | 2017 - 2021""")
    rows = result["structure"]["education"]
    assert len(rows) == 2
    assert rows[0]["institution"] == "Instituto Tecnológico de Costa Rica (TEC)"
    assert rows[0]["academic_status"] == "en curso"
    assert rows[0]["end_date"] == "Actualidad"
    assert "2029" in rows[0]["degree"]  # Graduación esperada, no título obtenido.
    assert rows[1]["degree"] == "Bachillerato en Educación Media"
    assert rows[1]["institution"] == "Liceo de Ejemplo"


def test_skills_keep_phrases_and_parentheses():
    result = analyze_lines("""Habilidades clave:
Electrónica e Ingeniería: Análisis de Circuitos, Diseño y Prototipado de Circuitos
Electrónicos, Pruebas y Validación
Computación y Datos: Python (Avanzado), Microsoft Excel (datos, reportes),
Control de Registros""")
    skills = result["fields"]["technical_skills"]
    assert "Diseño y Prototipado de Circuitos Electrónicos" in skills
    assert "Microsoft Excel (datos, reportes)" in skills
    assert not {"de", "y", "en", "Electrónicos", "reportes)"} & set(skills)


def test_projects_keep_description_and_only_local_technologies():
    result = analyze_lines("""Skills: Python, SQL
Academic Projects:
• Monitor de sensores: Desarrollo de un sistema de
mediciones con Arduino y Python.
• Informe de laboratorio: Documentación de mediciones y
resultados técnicos.
Certifications:
• Python Foundations, Example Academy, 2023
• Electronics Certificate, Example Institute, 2024""")
    rows = result["structure"]["academic_projects"]
    assert len(rows) == 2
    assert rows[0]["name"] == "Monitor de sensores"
    assert "sistema de mediciones" in rows[0]["description"]
    assert set(rows[0]["technologies"]) == {"Arduino", "Python"}
    assert rows[1]["technologies"] == [] and rows[1]["incomplete"]
    assert len(result["fields"]["certifications"]) == 2


def test_incomplete_records_preserve_source():
    result = analyze_lines("Experience:\nWorked on support cases without company or dates")
    row = result["structure"]["experience"][0]
    assert row["incomplete"] and row["company"] is None
    assert row["raw_text"] == "Worked on support cases without company or dates"
    assert row["sources"][0]["location"] == "Line 1"


def test_docx_textboxes_and_table_columns(tmp_path):
    document = Document()
    paragraph = document.add_paragraph()
    paragraph._p.append(parse_xml('''<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:pict><w:txbxContent><w:p><w:r><w:t>Full name: Alex Rivera</w:t></w:r></w:p></w:txbxContent></w:pict></w:r>'''))
    table = document.add_table(rows=3, cols=2)
    table.cell(0,0).text = "Skills"
    table.cell(1,0).text = "Python, Git"
    table.cell(2,0).text = "Linux"
    table.cell(0,1).text = "Experience"
    table.cell(1,1).text = "Developer | Example Company | 2022 - 2024"
    table.cell(2,1).text = "• Built useful tools."
    path = tmp_path / "table.docx"
    document.save(path)
    result = analyze(extract_document(path.read_bytes(), ".docx"))
    assert result["fields"]["full_name"] == "Alex Rivera"
    assert result["structure"]["experience"][0]["company"] == "Example Company"
    assert "Python" in result["fields"]["technical_skills"]
    assert "Linux" not in result["structure"]["experience"][0]["raw_text"]


def positioned_pdf(path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    entries = [(40,760,20,"ALEX RIVERA"),(40,720,10,"Skills"),(40,700,10,"Python, Git"),(40,680,10,"Linux"),(40,660,10,"Docker"),
        (320,720,10,"Experience"),(320,700,10,"Developer"),(320,680,10,"Example Company | 2022 - 2024"),(320,660,10,"Built tools for testing.")]
    commands = []
    for x,y,size,text in entries:
        commands.append(f"BT /F1 {size} Tf {x} {y} Td ({text}) Tj ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output: writer.write(output)
    return path


def test_pdf_two_columns_do_not_mix_sections(tmp_path):
    path = positioned_pdf(tmp_path / "columns.pdf")
    extraction = extract_document(path.read_bytes(), ".pdf")
    result = analyze(extraction)
    assert result["fields"]["full_name"] == "ALEX RIVERA"
    assert "Python" in result["fields"]["technical_skills"]
    assert len(result["structure"]["experience"]) == 1
    row = result["structure"]["experience"][0]
    assert row["position"] == "Developer" and row["company"] == "Example Company"
    assert "Docker" not in row["raw_text"]


def test_reprocess_preserves_scalar_list_and_structured_corrections(tmp_path):
    library = ResumeLibrary(tmp_path / "data")
    item = library.import_document(write_docx(tmp_path / "cv.docx"))
    fields = {**item["fields"], "full_name":"Corrected Name", "experience":["Texto manual anterior"], "academic_projects":["Proyecto corregido"]}
    structure = deepcopy(item["structure"])
    structure["experience"][0]["company"] = "Corrected Company"
    item = library.update(item["id"], title=item["title"], language=item["language"], specialty=item["specialty"], fields=fields, reviewed=True, expected_revision=item["revision"], structure=structure)
    before = library.original_path(item["id"]).read_bytes()
    for _ in range(2):
        item = library.reprocess(item["id"])
        assert item["fields"]["full_name"] == "Corrected Name"
        assert item["fields"]["experience"] == ["Texto manual anterior"]
        assert item["fields"]["academic_projects"] == ["Proyecto corregido"]
        assert item["structure"]["experience"][0]["company"] == "Corrected Company"
        assert "email" not in item["manual_fields"]
    assert library.original_path(item["id"]).read_bytes() == before
    assert len(library.versions(item["id"])) == 1
    assert item["original_analysis"]["fields"]["full_name"] == "Alex Rivera"


def test_migrate_old_manual_edits_and_idempotent_provenance(tmp_path):
    library = ResumeLibrary(tmp_path / "data")
    item = library.import_document(write_docx(tmp_path / "cv.docx"))
    old_analysis = deepcopy(item["original_analysis"])
    old_analysis["fields"]["full_name"] = None
    old_analysis["fields"]["experience"] = ["word", "fragments"]
    old_analysis.pop("structure", None)
    old_fields = {**old_analysis["fields"], "experience":["Corrección anterior"]}
    with library.database.connect() as db:
        db.execute("UPDATE resume_versions SET original_json=? WHERE id=?",(json.dumps(old_analysis),item["current_version"]))
        db.execute("UPDATE resumes SET fields_json=? WHERE id=?",(json.dumps(old_fields),item["id"]))
        db.execute("INSERT INTO resume_edits(resume_id,version_id,fields_json,metadata_json,created_at) VALUES (?,?,?,?,?)",(item["id"],item["current_version"],json.dumps(old_fields),"{}","test"))
    item = library.reprocess(item["id"])
    assert item["fields"]["full_name"] == "Alex Rivera"
    assert item["fields"]["experience"] == ["Corrección anterior"]
    assert item["manual_fields"] == ["experience"]
    item = library.update(item["id"], title=item["title"], language=item["language"], specialty=item["specialty"], fields=item["fields"], reviewed=True, expected_revision=item["revision"])
    item = library.reprocess(item["id"])
    assert item["manual_fields"] == ["experience"]
    assert "full_name" not in item["manual_fields"]


def test_pdf_parser_does_not_log_document_text(tmp_path, caplog):
    import logging
    from resume_fixtures import write_pdf
    path = write_pdf(tmp_path / "private.pdf", "PRIVATE DOCUMENT CONTENT\nEmail: private@example.invalid")
    with caplog.at_level(logging.DEBUG):
        result = analyze(extract_document(path.read_bytes(), ".pdf"))
    assert result["fields"]["email"] == "private@example.invalid"
    assert "private@example.invalid" not in caplog.text
    assert "PRIVATE DOCUMENT CONTENT" not in caplog.text
