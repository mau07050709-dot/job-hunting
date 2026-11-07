"""Extracción conservadora por reglas. Cada candidato conserva su línea de origen."""
import re
import unicodedata

from autojob.resumes.models import Extraction, TextUnit, empty_fields


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def has_term(text, term):
    return re.search(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)", normalize(text)) is not None


DEFAULT_RULES = {
    "technical": ["python", "developer", "software", "programming", "programación", "desarrollador", "electronics", "electrónica", "technician", "técnico", "engineering", "ingeniería", "it support", "help desk", "qa testing"],
    "customer_service": ["customer service", "customer support", "chat support", "email support", "call center", "servicio al cliente", "atención al cliente", "back office", "virtual assistant"],
}

HEADINGS = {
    "education": ["education", "academic background", "educación", "formación académica", "estudios"],
    "experience": ["experience", "work experience", "professional experience", "employment history", "experiencia", "experiencia laboral", "experiencia profesional"],
    "technical_skills": ["skills", "technical skills", "habilidades", "habilidades técnicas", "competencias técnicas", "tecnologías"],
    "languages": ["languages", "language skills", "idiomas"],
    "certifications": ["certifications", "certificates", "certificaciones", "cursos", "courses"],
    "academic_projects": ["projects", "academic projects", "proyectos", "proyectos académicos"],
    "other": ["summary", "profile", "professional summary", "perfil", "perfil profesional", "resumen", "contact", "contacto", "references", "referencias", "interests", "intereses", "awards", "premios", "volunteering", "voluntariado", "publications", "publicaciones"],
}
HEADING_LOOKUP = {normalize(alias): field for field, aliases in HEADINGS.items() for alias in aliases}
PROGRAMMING = ["Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "C", "SQL", "HTML", "CSS", "PHP", "Kotlin", "Swift", "Ruby", "Go", "Rust", "MATLAB"]
SKILLS = ["Git", "Linux", "Windows", "Docker", "Kubernetes", "Excel", "Power BI", "Arduino", "Raspberry Pi", "Electrónica", "Electronics", "Troubleshooting", "Networking", "Redes", "Salesforce", "Zendesk", "CRM", "Customer Service", "Customer Support"]
DATE_RANGE = re.compile(r"(?i)\b(?:(?:[A-Za-zÁÉÍÓÚáéíóúñÑ]+|\d{1,2})[ /.-]+)?(?:19|20)\d{2}\s*(?:-|–|—|to|a|hasta)\s*(?:(?:(?:[A-Za-zÁÉÍÓÚáéíóúñÑ]+|\d{1,2})[ /.-]+)?(?:19|20)\d{2}|present|actualidad|presente|current)\b")


def detect_language(text):
    tokens = set(re.findall(r"\b[a-z]+\b", normalize(text)))
    es = len(tokens & {"educacion", "experiencia", "habilidades", "idiomas", "proyectos", "certificaciones", "universidad", "formacion", "desarrollo", "con", "para", "del", "tecnico", "servicio", "cliente"})
    en = len(tokens & {"education", "experience", "skills", "languages", "projects", "certifications", "university", "development", "with", "for", "the", "technical", "customer", "support"})
    if es >= 2 and es >= en + 2:
        return "es"
    if en >= 2 and en >= es + 2:
        return "en"
    # Títulos breves inequívocos; no se usan el nombre del archivo ni los idiomas
    # que la persona dice hablar para determinar el idioma del documento.
    if es == 0 and any(has_term(text, title) for title in ("developer", "technician", "engineer", "customer service", "customer support")):
        return "en"
    if en == 0 and any(has_term(text, title) for title in ("desarrollador", "técnico", "ingeniero", "servicio al cliente", "atención al cliente")):
        return "es"
    return "unknown"


def detect_specialty(text, rules=None):
    rules = rules or DEFAULT_RULES
    scores = {key: sum(has_term(text, term) for term in terms) for key, terms in rules.items()}
    technical, service = scores.get("technical", 0), scores.get("customer_service", 0)
    if technical and service:
        if technical >= service * 2 and technical > service:
            return "technical"
        if service >= technical * 2 and service > technical:
            return "customer_service"
        return "mixed"
    return "technical" if technical else "customer_service" if service else "unknown"


def analyze(extraction: Extraction):
    from autojob.resumes.semantics import analyze_semantic
    return analyze_semantic(extraction)
