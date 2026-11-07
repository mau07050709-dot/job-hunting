"""Selección local por idioma y familia; no evalúa elegibilidad laboral."""
from dataclasses import dataclass
import json
import re

from autojob.resumes.analysis import DEFAULT_RULES, detect_language, detect_specialty, normalize
from autojob.resumes.models import ResumeError


@dataclass(frozen=True)
class Selection:
    resume_id: str | None
    reason: str
    language: str
    specialty: str


class ResumeSelector:
    def __init__(self, library):
        self.library = library
        self.path = library.data_path / "resume-selection-rules.json"

    def load_rules(self):
        if not self.path.exists():
            return {key: list(value) for key, value in DEFAULT_RULES.items()}
        try:
            rules = json.loads(self.path.read_text(encoding="utf-8-sig"))
            self.validate(rules)
            return rules
        except (ValueError, OSError, TypeError):
            raise ResumeError("Las reglas de selección no son válidas. Corrígelas desde Mis currículums.") from None

    @staticmethod
    def validate(rules):
        if not isinstance(rules, dict) or set(rules) != {"technical", "customer_service"}:
            raise ResumeError("Las reglas requieren las categorías technical y customer_service.")
        if any(not isinstance(values, list) or not values or len(values) > 200 or any(not isinstance(value, str) or not value.strip() or len(value) > 100 for value in values) for values in rules.values()):
            raise ResumeError("Cada categoría necesita entre 1 y 200 palabras o frases válidas.")

    def save_rules(self, rules):
        self.validate(rules)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def select(self, vacancy, language="auto", specialty="auto"):
        if language not in {"auto", "es", "en", "unknown"} or specialty not in {"auto", "technical", "customer_service", "mixed", "unknown"}:
            raise ResumeError("Idioma o especialidad de la vacante inválidos.")
        rules = self.load_rules()
        if language == "auto":
            requested_es = re.search(r"\b(?:en espanol|cv espanol|idioma\s*:\s*espanol)\b", normalize(vacancy))
            requested_en = re.search(r"\b(?:en ingles|cv ingles|idioma\s*:\s*ingles)\b", normalize(vacancy))
            if requested_es and requested_en:
                language = "unknown"
            else:
                language = "es" if requested_es else "en" if requested_en else detect_language(vacancy)
        specialty = detect_specialty(vacancy, rules) if specialty == "auto" else specialty
        if language == "unknown":
            return Selection(None, "Idioma ambiguo: indica explícitamente el idioma del CV solicitado.", language, specialty)
        if specialty in {"unknown", "mixed"}:
            return Selection(None, "Especialidad ambigua: selecciona la familia de la vacante.", language, specialty)
        candidates = [item for item in self.library.list() if item["reviewed"] and item["language"] == language and item["specialty"] in {specialty, "mixed"}]
        available = []
        for item in candidates:
            try:
                self.library.original_path(item["id"])
                available.append(item)
            except ResumeError:
                continue
        exact = [item for item in available if item["specialty"] == specialty]
        available = exact or available
        preferred = [item for item in available if item["is_default"]]
        if len(available) == 1 or len(preferred) == 1:
            chosen = preferred[0] if preferred else available[0]
            return Selection(chosen["id"], "CV revisado compatible con idioma y especialidad" + ("; preferido entre compatibles." if preferred else "."), language, specialty)
        if not available:
            return Selection(None, "No hay un CV revisado y disponible para ese idioma y especialidad. El predeterminado no sustituye un CV incompatible.", language, specialty)
        return Selection(None, "Hay varios CV igualmente compatibles. Marca uno como predeterminado o revisa su clasificación.", language, specialty)
