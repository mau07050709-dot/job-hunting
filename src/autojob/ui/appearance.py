"""Preferencias visuales locales compartidas por la instalación."""
import json
import os
from pathlib import Path
from uuid import uuid4

MODES={"opaque":"Gris opaco","background":"Como el fondo (sin relleno)","translucent":"Gris transparente"}


class Appearance:
    def __init__(self,data_path):
        self.path=Path(data_path)/"appearance.json"

    def load(self):
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"))
            mode=data.get("panels") if isinstance(data,dict) else None
            return mode if mode in MODES else "opaque"
        except (OSError,ValueError,TypeError):
            return "opaque"

    def save(self,mode):
        if mode not in MODES:
            raise ValueError("Elige un estilo de panel válido.")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_name(self.path.name+"."+uuid4().hex+".tmp")
        try:
            temporary.write_text(json.dumps(dict(panels=mode)),encoding="utf-8")
            os.replace(temporary,self.path)
        finally:
            if temporary.exists():temporary.unlink()
