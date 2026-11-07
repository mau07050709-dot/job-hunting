from dataclasses import dataclass

FIELD_LABELS = {
    "full_name": "Nombre completo", "email": "Correo electrónico", "phone": "Teléfono",
    "phone_e164": "Teléfono internacional validado", "location": "Ubicación", "professional_links": "Enlaces profesionales",
    "education": "Educación", "experience": "Experiencia laboral", "companies": "Empresas anteriores",
    "positions": "Puestos desempeñados", "employment_dates": "Fechas laborales",
    "technical_skills": "Habilidades técnicas", "programming_languages": "Lenguajes de programación",
    "languages": "Idiomas y niveles documentados", "certifications": "Certificaciones",
    "academic_projects": "Proyectos académicos",
}
SCALAR_FIELDS = {"full_name", "email", "phone", "phone_e164", "location"}
LANGUAGES = {"unknown": "Desconocido", "es": "Español", "en": "Inglés"}
SPECIALTIES = {"unknown": "Desconocida", "technical": "Técnico", "customer_service": "Customer Service", "mixed": "Mixta"}


class ResumeError(ValueError):
    """Mensaje operativo sin contenido del CV ni excepciones del parser."""


class DuplicateResume(ResumeError):
    def __init__(self, resume_id):
        self.resume_id = resume_id
        super().__init__("Este documento ya fue importado (o pertenece a una versión anterior).")


def empty_fields():
    return {key: None if key in SCALAR_FIELDS else [] for key in FIELD_LABELS}


@dataclass(frozen=True)
class TextUnit:
    location: str
    text: str
    x0: float | None = None
    top: float | None = None
    x1: float | None = None
    bottom: float | None = None
    size: float | None = None
    bold: bool = False
    lane: str = "body"


@dataclass
class Extraction:
    units: list[TextUnit]
    warnings: list[str]

    @property
    def text(self):
        return "\n".join(unit.text for unit in self.units)
