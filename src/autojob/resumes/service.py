from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from autojob.resumes.analysis import analyze
from autojob.resumes.extraction import MAX_FILE_BYTES, extract_document
from autojob.resumes.models import DuplicateResume, FIELD_LABELS, LANGUAGES, ResumeError, SCALAR_FIELDS, SPECIALTIES, empty_fields
from autojob.storage.database import Database, utc_now


class ResumeLibrary:
    def __init__(self, data_path: Path):
        self.data_path = data_path.resolve()
        self.directory = self.data_path / "resumes"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = Database(self.data_path / "autojob.sqlite3")
        with closing(self.database.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS resumes (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, language TEXT NOT NULL,
                    specialty TEXT NOT NULL, current_version TEXT NOT NULL,
                    fields_json TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
                    is_default INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS single_default_resume
                    ON resumes(is_default) WHERE is_default=1;
                CREATE TABLE IF NOT EXISTS resume_versions (
                    id TEXT PRIMARY KEY, resume_id TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE, original_json TEXT NOT NULL,
                    text_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS resume_versions_resume ON resume_versions(resume_id);
                CREATE TABLE IF NOT EXISTS resume_edits (
                    id INTEGER PRIMARY KEY, resume_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    fields_json TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_version VALUES (2);
                CREATE TABLE IF NOT EXISTS resume_parser_state (
                    resume_id TEXT PRIMARY KEY, version_id TEXT NOT NULL,
                    structure_json TEXT NOT NULL, protected_json TEXT NOT NULL,
                    manual_structure_json TEXT NOT NULL, analysis_json TEXT NOT NULL,
                    text_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resume_analysis_runs (
                    id TEXT PRIMARY KEY, resume_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    analysis_json TEXT NOT NULL, text_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_version VALUES (3);
            """)

    def list(self):
        with closing(self.database.connect()) as db:
            return [dict(row) for row in db.execute("""SELECT r.id,r.title,r.language,r.specialty,
                r.reviewed,r.is_default,r.revision,r.updated_at,v.filename,
                (SELECT COUNT(*) FROM resume_versions WHERE resume_id=r.id) AS version_count
                FROM resumes r JOIN resume_versions v ON v.id=r.current_version
                ORDER BY r.is_default DESC,r.created_at,r.id""")]

    def get(self, resume_id):
        with closing(self.database.connect()) as db:
            row = db.execute("""SELECT r.*,v.filename,v.stored_name,v.sha256,v.original_json,v.text_json
                FROM resumes r JOIN resume_versions v ON v.id=r.current_version WHERE r.id=?""", (resume_id,)).fetchone()
        if row is None:
            raise ResumeError("El currículum ya no está disponible. Actualiza la lista.")
        item = dict(row)
        for old, new in [("fields_json", "fields"), ("original_json", "original_analysis"), ("text_json", "source_units")]:
            item[new] = json.loads(item.pop(old))
        item["fields"] = {**empty_fields(), **item["fields"]}
        protected = self._legacy_protected(item)
        with closing(self.database.connect()) as db:
            state = db.execute("SELECT * FROM resume_parser_state WHERE resume_id=? AND version_id=?", (resume_id, item["current_version"])).fetchone()
        item["latest_analysis"] = item["original_analysis"]
        item["structure"] = item["original_analysis"].get("structure", {"experience": [], "education": [], "academic_projects": []})
        item["manual_structure"] = []
        if state:
            item["structure"] = json.loads(state["structure_json"])
            item["latest_analysis"] = json.loads(state["analysis_json"])
            item["source_units"] = json.loads(state["text_json"])
            item["manual_structure"] = json.loads(state["manual_structure_json"])
            protected = set(json.loads(state["protected_json"]))
        item["manual_fields"] = sorted(protected)
        item["provenance"] = {key: "manual" if key in protected else "automatic" for key in FIELD_LABELS}
        return item

    def _legacy_protected(self, item):
        """Reconstruir cambios anteriores sin suponer que Guardar editó cada campo."""
        previous = {**empty_fields(), **item["original_analysis"]["fields"]}
        protected = set()
        with closing(self.database.connect()) as db:
            edits = db.execute("SELECT fields_json FROM resume_edits WHERE resume_id=? AND version_id=? ORDER BY id", (item["id"], item["current_version"])).fetchall()
        for edit in edits:
            current = {**empty_fields(), **json.loads(edit[0])}
            protected.update(key for key in FIELD_LABELS if previous.get(key) != current.get(key))
            previous = current
        return protected

    def _store_state(self, db, item, structure, protected, manual_structure, analysis, units):
        db.execute("""INSERT OR REPLACE INTO resume_parser_state VALUES (?,?,?,?,?,?,?)""", (
            item["id"], item["current_version"], json.dumps(structure, ensure_ascii=False),
            json.dumps(sorted(protected)), json.dumps(sorted(manual_structure)),
            json.dumps(analysis, ensure_ascii=False), json.dumps(units, ensure_ascii=False)))

    def reprocess(self, resume_id, expected_revision=None):
        """Nueva propuesta de análisis sin alterar originales ni campos manuales."""
        item = self.get(resume_id)
        if expected_revision is not None and item["revision"] != expected_revision:
            raise ResumeError("El currículum cambió. Actualiza antes de reprocesar.")
        path = self.original_path(resume_id)
        content = path.read_bytes()
        if sha256(content).hexdigest() != item["sha256"]:
            raise ResumeError("El documento cambió durante el reprocesamiento.")
        extraction = extract_document(content, path.suffix)
        analysis = analyze(extraction)
        protected = set(item["manual_fields"])
        merged = {key: item["fields"][key] if key in protected else analysis["fields"][key] for key in FIELD_LABELS}
        structure = {key: item["structure"][key] if key in item["manual_structure"] else records for key, records in analysis["structure"].items()}
        units = [asdict(unit) for unit in extraction.units]
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("UPDATE resumes SET fields_json=?,reviewed=0,revision=revision+1,updated_at=? WHERE id=? AND revision=?", (json.dumps(merged, ensure_ascii=False), utc_now(), resume_id, item["revision"]))
            if cursor.rowcount != 1:
                raise ResumeError("El currículum cambió durante el análisis. No se sobrescribieron los cambios.")
            db.execute("INSERT INTO resume_analysis_runs VALUES (?,?,?,?,?,?)", (str(uuid4()), resume_id, item["current_version"], json.dumps(analysis, ensure_ascii=False), json.dumps(units, ensure_ascii=False), utc_now()))
            self._store_state(db, item, structure, protected, item["manual_structure"], analysis, units)
        return self.get(resume_id)

    def versions(self, resume_id):
        with closing(self.database.connect()) as db:
            return [dict(row) for row in db.execute("SELECT id,filename,sha256,created_at FROM resume_versions WHERE resume_id=? ORDER BY created_at DESC", (resume_id,))]

    def original_path(self, resume_id, verify=True):
        item = self.get(resume_id)
        path = (self.directory / item["stored_name"]).resolve()
        if not path.is_relative_to(self.directory.resolve()) or not path.is_file():
            raise ResumeError("La copia del documento no está disponible. Sustitúyela desde la biblioteca.")
        if verify and sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ResumeError("La copia del documento cambió fuera de Job Hunting. Sustitúyela antes de utilizarla.")
        return path

    def import_document(self, source: Path, replace_id=None, expected_revision=None):
        source = Path(source)
        extension = source.suffix.lower()
        if extension not in {".pdf", ".docx"}:
            raise ResumeError("Solo se admiten archivos PDF y DOCX.")
        try:
            with source.open("rb") as stream:
                content = stream.read(MAX_FILE_BYTES + 1)
        except OSError:
            raise ResumeError("No se pudo abrir el documento seleccionado.") from None
        extraction = extract_document(content, extension)
        analysis = analyze(extraction)
        digest = sha256(content).hexdigest()
        resume_id = replace_id or str(uuid4())
        version_id = str(uuid4())
        stored_name = version_id + extension
        target = self.directory / stored_name
        temporary = target.with_suffix(".tmp")
        created = utc_now()
        committed = False
        try:
            with closing(self.database.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                duplicate = db.execute("SELECT resume_id FROM resume_versions WHERE sha256=?", (digest,)).fetchone()
                if duplicate:
                    raise DuplicateResume(duplicate[0])
                if replace_id:
                    previous = db.execute("SELECT revision FROM resumes WHERE id=?", (replace_id,)).fetchone()
                    if previous is None:
                        raise ResumeError("El currículum que intentas sustituir ya no existe.")
                    if expected_revision is not None and previous[0] != expected_revision:
                        raise ResumeError("El currículum cambió en otra ventana. Actualiza antes de sustituirlo.")
                temporary.write_bytes(content)
                temporary.replace(target)
                db.execute("INSERT INTO resume_versions VALUES (?,?,?,?,?,?,?,?)", (
                    version_id, resume_id, digest, source.name, stored_name,
                    json.dumps(analysis, ensure_ascii=False),
                    json.dumps([asdict(unit) for unit in extraction.units], ensure_ascii=False), created))
                if replace_id:
                    db.execute("""UPDATE resumes SET language=?,specialty=?,current_version=?,fields_json=?,
                        reviewed=0,revision=revision+1,updated_at=? WHERE id=?""", (
                        analysis["language"], analysis["specialty"], version_id,
                        json.dumps(analysis["fields"], ensure_ascii=False), created, resume_id))
                else:
                    db.execute("""INSERT INTO resumes(id,title,language,specialty,current_version,fields_json,created_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?)""", (resume_id, source.stem[:200], analysis["language"], analysis["specialty"], version_id, json.dumps(analysis["fields"], ensure_ascii=False), created, created))
            committed = True
        except sqlite3.Error:
            raise ResumeError("No se pudo guardar el currículum. Cierra otras operaciones e inténtalo nuevamente.") from None
        except OSError:
            raise ResumeError("No se pudo conservar la copia local del documento.") from None
        finally:
            temporary.unlink(missing_ok=True)
            if not committed:
                target.unlink(missing_ok=True)
        return self.get(resume_id)

    def update(self, resume_id, *, title, language, specialty, fields, reviewed, expected_revision, structure=None):
        title = title.strip()
        if not title or len(title) > 200 or language not in LANGUAGES or specialty not in SPECIALTIES:
            raise ResumeError("Revisa el nombre, idioma y especialidad del currículum.")
        if set(fields) != set(FIELD_LABELS):
            raise ResumeError("La información del currículum tiene campos inválidos.")
        for key, value in fields.items():
            if key in SCALAR_FIELDS:
                if value is not None and (not isinstance(value, str) or len(value) > 1000):
                    raise ResumeError("Un campo de texto no tiene un formato válido.")
            elif not isinstance(value, list) or len(value) > 500 or any(not isinstance(line, str) or len(line) > 10000 for line in value):
                raise ResumeError("Una lista de información no tiene un formato válido.")
        if reviewed and (language == "unknown" or specialty == "unknown"):
            raise ResumeError("Define idioma y especialidad antes de marcar el CV como revisado.")
        item = self.get(resume_id)
        protected = set(item["manual_fields"])
        protected.update(key for key in FIELD_LABELS if item["fields"][key] != fields[key])
        manual_structure = set(item["manual_structure"])
        if structure is None:
            structure = item["structure"]
        else:
            self._validate_structure(structure)
            for category, records in structure.items():
                if records != item["structure"].get(category, []):
                    manual_structure.add(category)
                    old_records = {row["id"]: row for row in item["structure"].get(category, [])}
                    for row in records:
                        old = old_records.get(row["id"], {})
                        changed = [key for key in row if key not in {"origin", "manual_fields", "incomplete", "incomplete_fields"} and row[key] != old.get(key)]
                        if changed:
                            row["manual_fields"] = sorted(set(old.get("manual_fields", [])) | set(changed))
                            row["origin"] = "manual"
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""UPDATE resumes SET title=?,language=?,specialty=?,fields_json=?,reviewed=?,
                revision=revision+1,updated_at=? WHERE id=? AND revision=?""", (
                title, language, specialty, json.dumps(fields, ensure_ascii=False), int(bool(reviewed)), utc_now(), resume_id, expected_revision))
            if cursor.rowcount != 1:
                raise ResumeError("El currículum cambió en otra ventana. Actualiza la lista para no sobrescribir cambios.")
            db.execute("INSERT INTO resume_edits(resume_id,version_id,fields_json,metadata_json,created_at) VALUES (?,?,?,?,?)", (
                resume_id, item["current_version"], json.dumps(fields, ensure_ascii=False),
                json.dumps({"title": title, "language": language, "specialty": specialty, "reviewed": bool(reviewed)}, ensure_ascii=False), utc_now()))
            self._store_state(db, item, structure, protected, manual_structure, item["latest_analysis"], item["source_units"])
        return self.get(resume_id)

    @staticmethod
    def _validate_structure(structure):
        from autojob.resumes.semantics import STRUCTURE_KEYS
        if not isinstance(structure, dict) or set(structure) != set(STRUCTURE_KEYS):
            raise ResumeError("La estructura de registros no es válida.")
        for category, records in structure.items():
            if not isinstance(records, list) or len(records) > 500:
                raise ResumeError("La lista de registros no es válida.")
            identifiers = set()
            for row in records:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in identifiers:
                    raise ResumeError("Un registro no tiene un identificador válido.")
                identifiers.add(row["id"])
                for key in STRUCTURE_KEYS[category]:
                    value = row.get(key)
                    if key in {"responsibilities", "technologies"}:
                        if not isinstance(value, list) or any(not isinstance(v, str) or len(v) > 10000 for v in value):
                            raise ResumeError("Una lista de un registro no es válida.")
                    elif value is not None and (not isinstance(value, str) or len(value) > 50000):
                        raise ResumeError("Un campo de un registro no es válido.")

    def set_default(self, resume_id):
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM resumes WHERE id=?", (resume_id,)).fetchone():
                raise ResumeError("El currículum ya no existe.")
            db.execute("UPDATE resumes SET is_default=0 WHERE is_default=1")
            db.execute("UPDATE resumes SET is_default=1 WHERE id=?", (resume_id,))

    def delete(self, resume_id, expected_revision):
        names = []
        with closing(self.database.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT revision FROM resumes WHERE id=?", (resume_id,)).fetchone()
            if current is None or current[0] != expected_revision:
                raise ResumeError("El currículum cambió o ya fue eliminado. Actualiza la lista.")
            names = [row[0] for row in db.execute("SELECT stored_name FROM resume_versions WHERE resume_id=?", (resume_id,))]
            db.execute("DELETE FROM resume_edits WHERE resume_id=?", (resume_id,))
            db.execute("DELETE FROM resume_parser_state WHERE resume_id=?", (resume_id,))
            db.execute("DELETE FROM resume_analysis_runs WHERE resume_id=?", (resume_id,))
            db.execute("DELETE FROM resume_versions WHERE resume_id=?", (resume_id,))
            db.execute("DELETE FROM resumes WHERE id=?", (resume_id,))
        not_deleted = 0
        for name in names:
            path = (self.directory / name).resolve()
            if path.is_relative_to(self.directory.resolve()):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    not_deleted += 1
        return not_deleted
