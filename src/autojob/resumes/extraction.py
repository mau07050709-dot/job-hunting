from io import BytesIO
from pathlib import Path
import zipfile
import logging

class _NoDocumentDiagnostics(logging.Filter):
    def filter(self, record):
        return False


# pdfminer emite contenido de operadores/texto cuando se habilita DEBUG global.
# Los errores de lectura ya se traducen abajo a mensajes sin datos personales.
def _silence_pdf_diagnostics():
    for name, logger in logging.Logger.manager.loggerDict.copy().items():
        if name.startswith(("pdfminer", "pdfplumber", "pypdf")) and isinstance(logger, logging.Logger):
            if not any(isinstance(f, _NoDocumentDiagnostics) for f in logger.filters):
                logger.addFilter(_NoDocumentDiagnostics())

from autojob.resumes.models import Extraction, ResumeError, TextUnit

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000


def extract_document(content: bytes, extension: str) -> Extraction:
    if not content or len(content) > MAX_FILE_BYTES:
        raise ResumeError("El documento está vacío o supera el límite de 20 MB.")
    try:
        if extension.lower() == ".pdf":
            result = _pdf(content)
        elif extension.lower() == ".docx":
            result = _docx(content)
        else:
            raise ResumeError("Solo se admiten archivos PDF y DOCX.")
        if len(result.text) > MAX_TEXT_CHARS:
            raise ResumeError("El documento contiene demasiado texto; importa una versión más breve.")
        if not result.text.strip():
            result.warnings.append("Sin texto extraíble. Puede ser un escaneo: se requiere transcripción manual; OCR no incluido.")
        return result
    except ResumeError:
        raise
    except Exception:
        # Los parsers pueden incluir fragmentos o metadatos personales en sus errores.
        raise ResumeError("No se pudo leer el documento. Puede estar dañado, cifrado o no corresponder a su extensión.") from None


def _pdf(content):
    if not content.lstrip().startswith(b"%PDF-"):
        raise ResumeError("El archivo no tiene una cabecera PDF válida.")
    import pdfplumber
    from pypdf import PdfReader
    _silence_pdf_diagnostics()
    reader = PdfReader(BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise ResumeError("El PDF está protegido. Importa una copia sin contraseña.")
    if len(reader.pages) > 100:
        raise ResumeError("El límite es de 100 páginas por CV.")
    units, warnings = [], []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            words = page.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=["fontname", "size"])
            if not words:
                warnings.append(f"Página {page_number}: sin texto extraíble.")
                continue
            rows = []
            for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
                matching = next((row for row in reversed(rows[-4:]) if abs(row[0]["top"] - word["top"]) <= 3), None)
                if matching is None:
                    rows.append([word])
                else:
                    matching.append(word)
            fragments, gaps = [], []
            for row in rows:
                ordered = sorted(row, key=lambda w: w["x0"])
                parts = [[]]
                for word in ordered:
                    if parts[-1] and word["x0"] - parts[-1][-1]["x1"] > max(30, 2.8 * word["size"]):
                        gaps.append((parts[-1][-1]["x1"], word["x0"]))
                        parts.append([])
                    parts[-1].append(word)
                for part in parts:
                    fragments.append({"text": " ".join(w["text"] for w in part), "x0": part[0]["x0"], "x1": part[-1]["x1"],
                        "top": min(w["top"] for w in part), "bottom": max(w["bottom"] for w in part),
                        "size": max(w["size"] for w in part), "bold": any("bold" in w["fontname"].lower() for w in part)})
            # Detectar un canal de separación repetido. Las líneas de ancho completo
            # delimitan bandas; dentro de una banda se lee cada columna completa.
            candidates = [(left + right) / 2 for left, right in gaps if page.width * .15 < (left + right) / 2 < page.width * .85]
            split = max(candidates, key=lambda x: sum(a < x < b for a, b in gaps), default=None)
            if split is not None and sum(a < split < b for a, b in gaps) < 3:
                split = None
            ordered_fragments = []
            if split is not None:
                band = []
                for fragment in sorted(fragments, key=lambda f: (f["top"], f["x0"])):
                    if fragment["x0"] < split < fragment["x1"]:
                        ordered_fragments.extend(sorted(band, key=lambda f: (f["x0"] >= split, f["top"], f["x0"])))
                        band = []
                        fragment["lane"] = "body"
                        ordered_fragments.append(fragment)
                    else:
                        fragment["lane"] = "left" if fragment["x1"] <= split else "right"
                        band.append(fragment)
                ordered_fragments.extend(sorted(band, key=lambda f: (f["x0"] >= split, f["top"], f["x0"])))
            else:
                ordered_fragments = sorted(fragments, key=lambda f: (f["top"], f["x0"]))
            for line_number, fragment in enumerate(ordered_fragments, 1):
                lane = fragment.pop("lane", "body")
                units.append(TextUnit(f"Página {page_number}, línea {line_number} ({lane})", **fragment, lane=f"page-{page_number}-{lane}"))
    return Extraction(units, warnings)


def _docx(content):
    with zipfile.ZipFile(BytesIO(content)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 64 * 1024 * 1024 or len(archive.infolist()) > 5000:
            raise ResumeError("El contenido descomprimido del DOCX supera el límite permitido.")
        if "word/document.xml" not in archive.namelist():
            raise ResumeError("El archivo no contiene un documento Word válido.")
    from docx import Document
    from docx.table import Table
    document = Document(BytesIO(content))
    units = []

    def collect(container, location):
        for index, block in enumerate(container.iter_inner_content(), 1):
            label = f"{location}, bloque {index}"
            if isinstance(block, Table):
                seen = set()
                coordinates = [(r, c, cell) for r, row in enumerate(block.rows, 1) for c, cell in enumerate(row.cells, 1)]
                if len(block.columns) == 2 and block.rows:
                    from autojob.resumes.semantics import heading
                    if all(heading(cell.text.splitlines()[0] if cell.text else "")[0] for cell in block.rows[0].cells):
                        coordinates.sort(key=lambda entry: (entry[1], entry[0]))
                for row_index, column, cell in coordinates:
                        if cell._tc in seen:
                            continue
                        seen.add(cell._tc)
                        collect(cell, f"{label}, fila {row_index}, celda {column}")
            else:
                for line in block.text.splitlines():
                    if line.strip():
                        sizes = [run.font.size.pt for run in block.runs if run.font.size]
                        units.append(TextUnit(label, line.strip(), size=max(sizes, default=None), bold=any(run.bold for run in block.runs), lane=location))
                # python-docx omite el texto de cuadros de texto. Leer w:txbxContent
                # explícitamente, sin duplicarlo como párrafo normal.
                for textbox in block._p.xpath('.//w:txbxContent'):
                    for paragraph in textbox.xpath('.//*[local-name()="p"]'):
                        text = "".join(paragraph.xpath('.//*[local-name()="t"]/text()'))
                        if text.strip():
                            units.append(TextUnit(label + ", cuadro de texto", text.strip(), lane=location))
            if len(units) > 10000:
                raise ResumeError("El DOCX contiene demasiados bloques de texto.")

    # Encabezados y pies pueden contener los datos de contacto.
    for index, section in enumerate(document.sections, 1):
        collect(section.header, f"Encabezado {index}")
        collect(section.first_page_header, f"Encabezado de primera página {index}")
        collect(section.even_page_header, f"Encabezado de página par {index}")
    collect(document, "Documento")
    for index, section in enumerate(document.sections, 1):
        collect(section.footer, f"Pie {index}")
    return Extraction(units, ["DOCX: se leen párrafos, tablas, encabezados, pies y cuadros de texto. Imágenes sin texto requieren transcripción manual."])
