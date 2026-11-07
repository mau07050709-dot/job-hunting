from contextlib import closing
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Status(StrEnum):
    DISCOVERED = "DESCUBIERTA"
    EVALUATING = "EN EVALUACIÓN"
    COMPATIBLE = "COMPATIBLE"
    DISCARDED = "DESCARTADA"
    PENDING = "PENDIENTE"
    PROCESSING = "EN PROCESO"
    SENT = "ENVIADA"
    UNVERIFIED = "NO VERIFICADA"
    ERROR = "ERROR"


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES (1);
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY,
                    company TEXT NOT NULL, title TEXT NOT NULL, country TEXT,
                    modality TEXT, schedule TEXT, salary TEXT, url TEXT NOT NULL UNIQUE,
                    discovered_at TEXT NOT NULL, score REAL, cv_path TEXT,
                    status TEXT NOT NULL DEFAULT 'DESCUBIERTA', applied_at TEXT,
                    confirmation TEXT, error_reason TEXT, attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, status TEXT NOT NULL, details TEXT
                );
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def add_vacancy(self, company: str, title: str, url: str) -> bool:
        with closing(self.connect()) as db, db:
            cursor = db.execute("INSERT OR IGNORE INTO applications(company,title,url,discovered_at) VALUES (?,?,?,?)", (company, title, url, utc_now()))
            return cursor.rowcount == 1

    def start_run(self, kind: str) -> str:
        run_id = str(uuid4())
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO runs(id,kind,started_at,status) VALUES (?,?,?,'EN PROCESO')", (run_id, kind, utc_now()))
        return run_id

    def finish_run(self, run_id: str, success: bool, details: dict):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE runs SET finished_at=?,status=?,details=? WHERE id=?", (utc_now(), "OK" if success else "ERROR", json.dumps(details, ensure_ascii=False), run_id))

    def recover_runs(self) -> int:
        """Recuperación manual, con el worker detenido. No reenvía postulaciones."""
        with closing(self.connect()) as db, db:
            cursor = db.execute("UPDATE runs SET status='INTERRUMPIDA',finished_at=? WHERE status='EN PROCESO'", (utc_now(),))
            return cursor.rowcount

    def recent_runs(self, limit=30):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))]

    def counts(self):
        with closing(self.connect()) as db:
            return {row[0]: row[1] for row in db.execute("SELECT status,COUNT(*) FROM applications GROUP BY status")}
