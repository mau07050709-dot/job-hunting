"""Registro de alias y almacenes locales independientes por persona."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import unicodedata
from uuid import uuid4
import re


def alias_text(value):
    if not isinstance(value,str):
        raise ValueError("Escribe un alias.")
    value=" ".join(value.split())
    if not value or len(value)>60 or any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError("El alias debe tener entre 1 y 60 caracteres.")
    return value


class People:
    def __init__(self,settings):
        self.settings=replace(settings,data_dir=settings.installation_data_dir or settings.data_dir,installation_data_dir=None)
        self.directory=self.settings.data_path
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/"people.sqlite3"
        with closing(self.connect()) as db,db:
            db.execute("CREATE TABLE IF NOT EXISTS people(id TEXT PRIMARY KEY,alias TEXT NOT NULL,alias_key TEXT UNIQUE NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS selected_person(id INTEGER PRIMARY KEY CHECK(id=1),person_id TEXT NOT NULL REFERENCES people(id))")
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM people").fetchone():
                alias=self.legacy_alias()
                db.execute("INSERT INTO people VALUES('legacy',?,?)",(alias,self.key(alias)))
            db.execute("INSERT OR IGNORE INTO selected_person VALUES(1,'legacy')")

    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def key(alias):
        return unicodedata.normalize("NFKC",alias).casefold()

    def legacy_alias(self):
        path=self.directory/"autojob.sqlite3"
        if path.exists():
            with closing(sqlite3.connect(path)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='personal_profile'").fetchone():
                    row=db.execute("SELECT values_json FROM personal_profile WHERE id=1").fetchone()
                    name=json.loads(row[0]).get("full_name") if row else None
                    if name:
                        return alias_text(name.split()[0].title())
        return "Mi perfil"

    def rows(self):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute("SELECT id,alias FROM people ORDER BY rowid")]

    def active(self):
        with closing(self.connect()) as db:
            return dict(db.execute("SELECT p.id,p.alias FROM people p JOIN selected_person s ON s.person_id=p.id WHERE s.id=1").fetchone())

    def get(self,person_id):
        with closing(self.connect()) as db:
            row=db.execute("SELECT id,alias FROM people WHERE id=?",(person_id,)).fetchone()
        if not row:
            raise ValueError("La persona seleccionada ya no está disponible.")
        return dict(row)

    def create(self,alias):
        alias=alias_text(alias)
        person_id=uuid4().hex
        try:
            with closing(self.connect()) as db,db:
                db.execute("INSERT INTO people VALUES(?,?,?)",(person_id,alias,self.key(alias)))
        except sqlite3.IntegrityError:
            raise ValueError("Ya existe una persona con ese alias.") from None
        return self.get(person_id)

    def rename(self,person_id,alias):
        self.get(person_id)
        alias=alias_text(alias)
        try:
            with closing(self.connect()) as db,db:
                db.execute("UPDATE people SET alias=?,alias_key=? WHERE id=?",(alias,self.key(alias),person_id))
        except sqlite3.IntegrityError:
            raise ValueError("Ya existe una persona con ese alias.") from None
        return self.get(person_id)

    def select(self,person_id):
        self.get(person_id)
        with closing(self.connect()) as db,db:
            db.execute("UPDATE selected_person SET person_id=? WHERE id=1",(person_id,))

    def settings_for(self,person_id):
        self.get(person_id)
        if person_id=="legacy":
            return self.settings
        if not re.fullmatch("[0-9a-f]{32}",person_id):
            raise ValueError("Identificador de persona inválido.")
        return replace(self.settings,
                       data_dir=(Path(self.settings.data_dir)/"people"/person_id).as_posix(),
                       installation_data_dir=self.settings.data_dir)
