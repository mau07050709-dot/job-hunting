"""Fondos personales de la interfaz; no modifica documentos ni SQLite."""
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
import json,os
from PySide6.QtGui import QImageReader

class BackgroundImages:
    def __init__(self,data_path):
        self.directory=Path(data_path)/'backgrounds';self.config=Path(data_path)/'section-backgrounds.json'
    def records(self):
        try:
            value=json.loads(self.config.read_text(encoding='utf-8'))
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError):return {}
    def load(self,defaults):
        result=list(defaults)
        for key,name in self.records().items():
            if key not in {'0','1','2','3'} or not isinstance(name,str) or Path(name).name!=name:continue
            path=self.directory/name
            if path.is_file() and QImageReader(str(path)).canRead():result[int(key)]=path
        return tuple(result)
    def save(self,index,source):
        if type(index) is not int or index not in range(4):raise ValueError('Elige una pestaña válida.')
        source=Path(source);reader=QImageReader(str(source));reader.setAutoTransform(True)
        if not reader.canRead() or reader.read().isNull():raise ValueError('La imagen no se puede abrir. Elige un archivo de imagen válido compatible.')
        raw=source.read_bytes();extension=bytes(reader.format()).decode('ascii').lower() or 'img'
        self.directory.mkdir(parents=True,exist_ok=True);name=sha256(raw).hexdigest()+'.'+extension;destination=self.directory/name
        if not destination.exists():destination.write_bytes(raw)
        records=self.records();records[str(index)]=name
        self._save_records(records)
        return destination
    def reset(self,index):
        records=self.records()
        records.pop(str(index),None)
        self._save_records(records)
    def _save_records(self,records):
        self.config.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.config.with_name(self.config.name+'.'+uuid4().hex+'.tmp')
        try:
            temporary.write_text(json.dumps(records,indent=2),encoding='utf-8');os.replace(temporary,self.config)
        finally:
            if temporary.exists():temporary.unlink()
    @staticmethod
    def file_filter():
        formats={bytes(f).decode('ascii').lower() for f in QImageReader.supportedImageFormats()}
        return 'Imágenes ('+' '.join('*.'+f for f in sorted(formats))+');;Todos los archivos (*)'
