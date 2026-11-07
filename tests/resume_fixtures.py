"""Documentos sintéticos de pruebas, sin información personal del usuario."""
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

EN_TECH = """Full name: Alex Rivera
Email: alex@example.invalid
Phone: +506 8888-7777
Education:
Bachelor of Electronics, Example University, 2020 - 2024
Work Experience:
Software Developer | Example Labs | 2022 - 2024
Company: Example Labs
Role: Junior Developer
Technical Skills:
Python, SQL, Git, Linux, C++
Languages:
English B2
Spanish native
Certifications:
Python Foundations, Example Academy, 2023
Academic Projects:
Arduino temperature monitoring project, 2024"""

ES_TECH = """Nombre completo: Alex Rivera
Correo: alex@example.invalid
Teléfono: +506 8888-7777
Educación:
Ingeniería electrónica, Universidad de Ejemplo
Experiencia laboral:
Técnico electrónico | Laboratorio Ejemplo | 2022 - 2024
Empresa: Laboratorio Ejemplo
Puesto: Técnico electrónico
Habilidades técnicas:
Python, Arduino, Electrónica, Redes
Idiomas:
Español nativo
Inglés B2
Certificaciones:
Certificación de electrónica
Proyectos académicos:
Sistema de sensores Arduino"""

EN_SERVICE = """Full name: Alex Rivera
Email: alex@example.invalid
Education:
Diploma, Example University
Work Experience:
Customer Service Agent | Example Support | 2022 - Present
Technical Skills:
Customer Service, Customer Support, Zendesk, CRM
Languages:
English B2
Spanish native
Certifications:
Customer Support Foundations
Academic Projects:
Customer service training project"""


def write_docx(path, text=EN_TECH):
    document = Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    document.save(path)
    return path


def write_pdf(path, text=ES_TECH):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    lines = [b"BT /F1 11 Tf 15 TL 40 800 Td"]
    for line in text.splitlines():
        literal = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(b"(" + literal.encode("cp1252") + b") Tj T*")
    lines.append(b"ET")
    stream = DecodedStreamObject()
    stream.set_data(b"\n".join(lines))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)
    return path
