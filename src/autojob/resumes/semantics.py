"""Reconstrucción de bloques y registros con texto y fuentes conservados."""
from hashlib import sha256
import re
from statistics import median

import phonenumbers

from autojob.resumes.analysis import HEADING_LOOKUP, PROGRAMMING, SKILLS, detect_language, detect_specialty, has_term, normalize
from autojob.resumes.models import empty_fields

EXTRA_HEADINGS = {
    "habilidades clave": "technical_skills", "key skills": "technical_skills", "core skills": "technical_skills",
    "proyectos tecnicos": "academic_projects", "technical projects": "academic_projects",
    "formacion": "education", "academic qualifications": "education",
    "employment": "experience", "professional background": "experience",
    "referencias": "references", "references": "references",
}
STRUCTURE_KEYS = {"experience": ["company", "position", "start_date", "end_date", "responsibilities", "description"],
    "education": ["institution", "degree", "academic_status", "start_date", "end_date", "description"],
    "academic_projects": ["name", "description", "technologies"]}
REQUIRED = {"experience": ["company", "position", "start_date", "end_date"], "education": ["institution", "degree", "academic_status"], "academic_projects": ["name", "description", "technologies"]}
FRIENDLY_FIELDS = {"company":"empresa", "position":"puesto", "start_date":"fecha inicial", "end_date":"fecha final", "institution":"institución", "degree":"titulación", "academic_status":"estado académico", "name":"nombre", "description":"descripción", "technologies":"tecnologías"}
FRIENDLY_CATEGORIES = {"experience":"Experiencia", "education":"Educación", "academic_projects":"Proyecto"}
DATE = r"(?:(?:[A-Za-zÀ-ÿ]+|\d{1,2})[ /.-]+)?(?:19|20)\d{2}"
RANGE = re.compile(r"(?i)(?P<start>" + DATE + r")\s*(?:[-–—]|\bto\b|\ba\b|\bhasta\b)\s*(?P<end>" + DATE + r"|present|actualidad|presente|current)\b")
DEGREE = re.compile(r"(?i)\b(?:bachillerato|bachelor|bsc|licenciatura|maestria|master|doctorado|diploma|degree|tecnico medio|ingenieria|engineering)\b")
INSTITUTION = re.compile(r"(?i)\b(?:universidad|university|instituto|institute|liceo|colegio|college|school|academy|academia|tecnologico)\b")
BULLET = re.compile(r"^\s*[•·●▪◦\-\u2022\uf0b7]\s*")


def heading(line):
    prefix, separator, tail = line.partition(":")
    normalized = normalize(prefix.strip())
    key = EXTRA_HEADINGS.get(normalized, HEADING_LOOKUP.get(normalized))
    # Un título de proyecto o una frase dentro de un párrafo no es una sección.
    return (key, tail.strip()) if key else (None, None)


def split_sections(units):
    sections = {key: [] for key in ["preamble", "experience", "education", "academic_projects", "technical_skills", "languages", "certifications", "references", "other"]}
    active = "preamble"
    lanes = {}
    for unit in units:
        key, tail = heading(unit.text)
        if unit.lane != "body":
            # En columnas independientes, no arrastrar una sección de la izquierda
            # a la derecha. En Word, las celdas de una fila comparten contexto.
            lane = unit.lane if unit.lane.startswith("page-") else "word"
            active = lanes.get(lane, "preamble")
        else:
            lane = "body"
        if key:
            active = key
            lanes[lane] = active
            if tail:
                from dataclasses import replace
                sections.setdefault(active, []).append(replace(unit, text=tail))
        else:
            sections.setdefault(active, []).append(unit)
            lanes[lane] = active
    return sections


def source(units):
    return [{"location": unit.location, "text": unit.text} for unit in units]


def joined(units):
    return " ".join(unit.text.strip() for unit in units).strip()


def dates(text):
    found = RANGE.search(text)
    return (found.group("start").strip(), found.group("end").strip()) if found else (None, None)


def strip_dates(text):
    return RANGE.sub("", text).strip(" |,;–—-")


def record(category, units, **values):
    raw = "\n".join(unit.text for unit in units)
    item = {key: [] if key in {"responsibilities", "technologies"} else None for key in STRUCTURE_KEYS[category]}
    item.update(values)
    item.update({"id": sha256((category + "\n" + raw).encode()).hexdigest()[:20], "raw_text": raw, "sources": source(units), "origin": "automatic", "manual_fields": []})
    item["incomplete_fields"] = [key for key in REQUIRED[category] if not item.get(key)]
    item["incomplete"] = bool(item["incomplete_fields"])
    return item


def paragraphs(units):
    """Une líneas de continuación; conserva listas y bloques sin dividir palabras."""
    result, current = [], []
    for unit in units:
        new_bullet = bool(BULLET.match(unit.text))
        vertical_gap = bool(current and unit.top is not None and current[-1].bottom is not None and unit.top - current[-1].bottom > max(6, (unit.size or 10) * .8))
        if current and (new_bullet or vertical_gap):
            result.append(current)
            current = []
        current.append(unit)
    if current:
        result.append(current)
    return result


def experience_records(units):
    if not units:
        return []
    starts = {0}
    for index, unit in enumerate(units):
        if RANGE.search(unit.text):
            start = index
            parts = [part.strip() for part in unit.text.split("|")]
            if len(parts) < 3 and index > 0 and not RANGE.search(units[index-1].text) and not BULLET.match(units[index-1].text):
                previous = units[index-1].text
                if len(previous) < 110 and not re.match(r"(?i)^(?:company|empresa|role|puesto|cargo)\s*:", previous):
                    start = index - 1
            starts.add(start)
    boundaries = sorted(starts) + [len(units)]
    records = []
    for first, last in zip(boundaries, boundaries[1:]):
        group = units[first:last]
        if not group:
            continue
        date_index = next((index for index, u in enumerate(group) if RANGE.search(u.text)), None)
        # Prefacios antes de la primera entrada se conservan como incompletos.
        header_end = date_index + 1 if date_index is not None else len(group)
        headers = group[:header_end]
        company = position = None
        start, end = dates(joined(headers))
        for unit in group:
            for label, key in [(r"company|empresa|employer", "company"), (r"role|puesto|cargo|position|job title", "position")]:
                match = re.match(r"(?i)^(?:" + label + r")\s*:\s*(.+)$", unit.text)
                if match:
                    if key == "company": company = match.group(1)
                    else: position = match.group(1)
        if date_index is not None:
            line = group[date_index].text
            parts = [part.strip() for part in line.split("|") if part.strip()]
            if len(parts) >= 3:
                position = position or parts[0]
                company = company or parts[1]
            elif len(parts) == 2:
                company = company or strip_dates(parts[0]) or None
                if date_index > 0:
                    position = position or joined(group[:date_index])
            elif date_index >= 2:
                position = position or group[0].text
                company = company or joined(group[1:date_index])
            elif date_index == 1:
                position = position or group[0].text
        body = [unit for unit in group[header_end:] if not re.match(r"(?i)^(?:company|empresa|employer|role|puesto|cargo|position|job title)\s*:", unit.text)]
        responsibilities = [BULLET.sub("", joined(block)).strip() for block in paragraphs(body)]
        description = "\n".join(responsibilities) or None
        records.append(record("experience", group, company=company, position=position, start_date=start, end_date=end, responsibilities=responsibilities, description=description))
    return records


def education_records(units):
    groups = []
    current = []
    for unit in units:
        first_part = normalize(unit.text.split("|")[0])
        is_degree = bool(DEGREE.search(first_part)) and (not INSTITUTION.search(first_part) or bool(re.search(r'\b(?:high school diploma|diploma de secundaria)\b', first_part)))
        if current and is_degree and any(DEGREE.search(normalize(u.text)) for u in current):
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    records = []
    for group in groups:
        text = joined(group)
        parts = [part.strip() for unit in group for part in unit.text.split("|") if part.strip()]
        institution = next((strip_dates(part) for part in parts if INSTITUTION.search(normalize(part))), None)
        degree_parts = []
        for unit in group:
            candidate = unit.text.split("|")[0].strip()
            if INSTITUTION.search(normalize(candidate)) and degree_parts:
                break
            if not INSTITUTION.search(normalize(candidate)) and not RANGE.fullmatch(candidate):
                degree_parts.append(candidate)
        degree = " ".join(degree_parts).strip() or None
        if not degree and parts and DEGREE.search(normalize(parts[0])):
            degree = parts[0]
        start, end = dates(text)
        status_match = re.search(r"(?i)\b(en curso|cursando|in progress|currently studying|estudiante|graduad[oa]|completed|graduated|incomplet[oa])\b", text)
        status = status_match.group() if status_match else None
        records.append(record("education", group, institution=institution, degree=degree, academic_status=status, start_date=start, end_date=end, description=text))
    return records


def project_records(units):
    groups, current = [], []
    for unit in units:
        title_colon = ":" in unit.text and len(unit.text.split(":", 1)[0].split()) <= 12
        if current and (BULLET.match(unit.text) or title_colon):
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    records = []
    for group in groups:
        text = BULLET.sub("", joined(group)).strip()
        first, separator, tail = text.partition(":")
        name = first.strip() if separator else (BULLET.sub("", group[0].text).strip() if len(group) > 1 and len(group[0].text) < 110 else None)
        description = tail.strip() if separator else (joined(group[1:]) if name else text)
        technologies = [term for term in [*PROGRAMMING, *SKILLS] if has_term(text, term) and (term not in {"C", "Go"} or re.search(r"(?<![\w+#])"+re.escape(term)+r"(?![\w+#])", text))]
        records.append(record("academic_projects", group, name=name, description=description or None, technologies=technologies))
    return records


def split_outside_parentheses(text):
    # Una coma dentro de una aclaración no separa habilidades.
    result, level, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "(": level += 1
        elif char == ")": level = max(0, level-1)
        elif char in ",;•|" and level == 0:
            result.append(text[start:index].strip())
            start = index + 1
    result.append(text[start:].strip())
    return result


def skill_phrases(units):
    groups, current = [], []
    for unit in units:
        prefix, sep, tail = unit.text.partition(":")
        if current and (sep or BULLET.match(unit.text)):
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    phrases = []
    stop = {"de", "del", "la", "el", "y", "en", "con", "para", "the", "and", "of", "a", "an", "to", "skills", "clave"}
    for group in groups:
        text = BULLET.sub("", joined(group))
        prefix, sep, tail = text.partition(":")
        if sep and len(prefix.split()) <= 8:
            text = tail
        for phrase in split_outside_parentheses(text):
            phrase = phrase.strip(" •;,")
            if phrase and normalize(phrase) not in stop and len(phrase.split()) <= 18:
                phrases.append((phrase, group))
    return phrases


def analyze_semantic(extraction):
    fields = empty_fields()
    evidence = {key: [] for key in fields}
    sections = split_sections(extraction.units)
    warnings = list(extraction.warnings)

    def add(key, value, units):
        if not value:
            return
        if isinstance(fields[key], list):
            if value not in fields[key]: fields[key].append(value)
        elif fields[key] is None:
            fields[key] = value
        else:
            return
        evidence[key].extend({"value": value, "location": u.location, "text": u.text} for u in units)

    # No usar datos de contactos de referencias como datos del candidato.
    contacts = sections["preamble"]
    nonreferences = [u for key, units in sections.items() if key != "references" for u in units]
    candidates = []
    excluded = re.compile(r"\b(?:curriculum|vitae|resume|developer|engineer|technician|customer|service|support|ingeniero|ingenieria|tecnico|perfil|professional|software|contact|contacto|universidad|university|estudiante|student|instituto|educacion|experience|skills|projects|proyectos|datos|santo|costa|heredia|referencias)\b")
    typical_size = median([u.size for u in extraction.units if u.size] or [10])
    for index, unit in enumerate(nonreferences):
        line = unit.text.strip()
        explicit = re.match(r"(?i)^(?:nombre(?: completo)?|full name|name)\s*:\s*(.+)$", line)
        if explicit:
            candidates.append((100, explicit.group(1), unit))
            continue
        words = line.split()
        if not (2 <= len(words) <= 7) or len(line) > 90 or excluded.search(normalize(line)) or heading(line)[0]:
            continue
        if all(re.fullmatch(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", word) for word in words):
            score = (4 if unit in contacts else 0) + (5 if unit.size and unit.size >= typical_size * 1.3 else 0) + (2 if line.isupper() else 0) + (1 if unit.bold else 0)
            if score >= 4:
                candidates.append((score, line, unit))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0] or normalize(candidates[0][1]) == normalize(candidates[1][1])):
        add("full_name", candidates[0][1], [candidates[0][2]])
    elif candidates:
        warnings.append("Nombre ambiguo: hay varios candidatos. Comprueba la fuente y corrígelo manualmente.")

    search_contacts = contacts + [u for u in nonreferences if re.match(r"(?i)^(?:email|correo|phone|telefono|teléfono|tel|celular|ubicacion|ubicación|location)\s*:", u.text)]
    region = "CR" if has_term(joined(nonreferences), "Costa Rica") else None
    for unit in search_contacts:
        for email in re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", unit.text):
            add("email", email.rstrip(".,;"), [unit])
        context = bool(re.search(r"\b(phone|telephone|telefono|tel|celular|movil|whatsapp)\b", normalize(unit.text)))
        for match in phonenumbers.PhoneNumberMatcher(unit.text, region):
            if not context and not match.raw_string.startswith("+") and not region:
                continue
            if phonenumbers.is_valid_number(match.number):
                add("phone", match.raw_string, [unit])
                add("phone_e164", phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164), [unit])
        for part in unit.text.split("|"):
            label = re.match(r"(?i)^(?:location|ubicaci[oó]n|residencia|address|direcci[oó]n)\s*:\s*(.+)$", part.strip())
            if label:
                add("location", label.group(1), [unit])
            elif has_term(part, "Costa Rica") and "@" not in part and not re.search(r"\d{7,}", part) and len(part) < 140:
                add("location", part.strip(), [unit])
        for link in re.findall(r"(?:https?://|www\.)[^\s|<>]+|(?:linkedin\.com|github\.com)/[^\s|<>]+", unit.text, re.I):
            add("professional_links", link.rstrip(".,;)"), [unit])

    structure = {"experience": experience_records(sections["experience"]), "education": education_records(sections["education"]), "academic_projects": project_records(sections["academic_projects"])}
    for category, records in structure.items():
        for item in records:
            record_units = [u for u in sections[category] if any(s["location"] == u.location for s in item["sources"])]
            # Proyección textual compatible, un elemento por registro, nunca palabra.
            add(category, item["raw_text"].replace("\n", " "), record_units)
            if item["incomplete"]:
                warnings.append(f"{FRIENDLY_CATEGORIES[category]}: registro incompleto; faltan {', '.join(FRIENDLY_FIELDS[k] for k in item['incomplete_fields'])}.")
            if category == "experience":
                add("companies", item["company"], record_units)
                add("positions", item["position"], record_units)
                if item["start_date"] and item["end_date"]:
                    add("employment_dates", item["start_date"] + " - " + item["end_date"], record_units)
    for phrase, units in skill_phrases(sections["technical_skills"]):
        add("technical_skills", phrase, units)
    # Los términos canónicos solo complementan habilidades presentes, sin fragmentar
    # las descripciones ni deducir experiencia o dominio.
    for unit in nonreferences:
        for term in PROGRAMMING:
            if has_term(unit.text, term) and (term not in {"C", "Go"} or re.search(r"(?<![\w+#])" + re.escape(term) + r"(?![\w+#])", unit.text)):
                add("programming_languages", term, [unit])
        for term in SKILLS:
            if has_term(unit.text, term): add("technical_skills", term, [unit])
    for key in ["languages", "certifications"]:
        blocks = []
        if key == "languages":
            for unit in sections[key]:
                if not blocks or re.match(r"(?i)^(?:english|spanish|español|ingl[eé]s|franc[eé]s|french|portugu[eé]s|portuguese|german|alem[aá]n)\b", unit.text):
                    blocks.append([unit])
                else:
                    blocks[-1].append(unit)
        else:
            blocks = paragraphs(sections[key])
        for block in blocks:
            for part in (joined(block).split("|") if key == "languages" else [joined(block)]):
                add(key, BULLET.sub("", part.strip()), block)
    for key, label in [("full_name","nombre completo"), ("email","correo"), ("phone","teléfono"), ("location","ubicación")]:
        if not fields[key]: warnings.append(f"Dato personal no identificado: {label}.")
    return {"fields": fields, "evidence": evidence, "structure": structure, "language": detect_language(extraction.text), "specialty": detect_specialty(extraction.text), "warnings": list(dict.fromkeys(warnings)), "parser_version": "3.1"}
