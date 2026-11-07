"""Preferencias locales y filtros presenciales independientes del país de la empresa."""
from contextlib import closing
import json
import re
from autojob.storage.database import Database
from autojob.search.geography import normalize

DEFAULT_LOCALITIES = ["Turrialba", "Cartago"]
LOCALITIES = ["Turrialba", "Cartago", "Paraíso", "Oreamuno", "El Guarco", "La Unión", "Jiménez", "Alvarado"]


class OnsitePreferences:
    def __init__(self, data_path):
        self.db = Database(data_path / "autojob.sqlite3")
        with closing(self.db.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS onsite_preferences(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)")

    def load(self):
        with closing(self.db.connect()) as db:
            row = db.execute("SELECT payload FROM onsite_preferences WHERE id=1").fetchone()
        return json.loads(row[0]) if row else dict(localities=[],night_search=False)

    def save(self, localities, night_search=True):
        if type(night_search) is not bool or not isinstance(localities, list):
            raise ValueError("Selección de localidades inválida.")
        cleaned = {}
        for place in localities:
            if not isinstance(place, str) or not re.fullmatch(r"[\wáéíóúüñÁÉÍÓÚÜÑ .-]{2,70}",place.strip()):
                raise ValueError("Escribe nombres de localidades de Costa Rica.")
            cleaned.setdefault(normalize(place.strip()), place.strip())
        if len(cleaned)>20:
            raise ValueError("Elige como máximo 20 localidades.")
        result = dict(localities=list(cleaned.values()),night_search=night_search)
        with closing(self.db.connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO onsite_preferences VALUES(1,?)",(json.dumps(result,ensure_ascii=False),))
        return result


def locality_matches(job, enabled):
    if job.get("modality") != "onsite":
        return False
    location = normalize(job.get("location") or "")
    country = normalize(str(job.get("country") or ""))
    if any(term in location for term in ("colombia","valle del cauca")):
        return False
    if country not in {"cr","costa rica"} and "costa rica" not in location:
        return False
    # Usar la ciudad publicada, nunca una provincia coincidente de otra ciudad.
    city = normalize(job.get("locality") or location.split(",")[0].strip())
    return city in {normalize(value) for value in enabled}


def night_status(job):
    text = normalize(" ".join(str(job.get(k) or "") for k in ("title","description","work_hours")))
    if re.search(r"(?:solo|unicamente|exclusivamente) (?:diurno|de dia)|sin (?:turnos? )?nocturn|no (?:se trabaja|laboramos) de noche",text):
        return "DIURNO"
    if re.search(r"nocturn|turno (?:de )?noche|night shift|overnight|cierre (?:a las? )?(?:2[2-3]|0[0-5])[:.]\d{2}",text):
        return "NOCTURNO PUBLICADO"
    if re.search(r"rotativ|horarios? flexibles|disponibilidad de horario",text):
        return "ROTATIVO — NOCHE POR CONFIRMAR"
    return "HORARIO NO PUBLICADO"


def fast_food(job):
    text=normalize((job.get("company") or "")+" "+(job.get("title") or ""))
    return bool(re.search(r"mcdonald|arcos dorados|burger king|\bkfc\b|taco bell|subway|popeyes|pollolandia|pollo granjero|wendy|pizza hut|little caesars|comida rapida|fast food",text))


def service_opportunity(job):
    text=normalize((job.get("title") or "")+" "+(job.get("company") or ""))
    return bool(re.search(r"cajer|dependiente|tienda|gasoliner|estacion de servicio|despachador|pistero|operador de pista|ampm|am/pm|vindi|minimarket|recepcion|atencion|cliente|customer|call center|soporte|help desk|service desk",text))
