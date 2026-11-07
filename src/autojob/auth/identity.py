"""Identidad separada del perfil, protegida mediante DPAPI del usuario actual."""
from pathlib import Path
from contextlib import closing
from datetime import date,datetime,timezone
from uuid import uuid4
import ctypes as C
from ctypes import wintypes as W
import os,re,json,hashlib
from autojob.storage.database import Database
from autojob.auth.vault import Secret

TYPES=['Cédula de identidad costarricense','DIMEX','Pasaporte','Otro']

class DataBlob(C.Structure):_fields_=[('size',W.DWORD),('data',C.POINTER(W.BYTE))]

class DPAPI:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('Se requiere DPAPI de Windows; no se guarda identidad sin cifrar.')
        self.api=C.WinDLL('Crypt32.dll',use_last_error=True);self.kernel=C.WinDLL('Kernel32.dll',use_last_error=True)
        self.api.CryptProtectData.argtypes=[C.POINTER(DataBlob),W.LPCWSTR,C.POINTER(DataBlob),C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(DataBlob)]
        self.api.CryptUnprotectData.argtypes=[C.POINTER(DataBlob),C.c_void_p,C.POINTER(DataBlob),C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(DataBlob)]
        self.api.CryptProtectData.restype=self.api.CryptUnprotectData.restype=W.BOOL;self.kernel.LocalFree.argtypes=[C.c_void_p];self.kernel.LocalFree.restype=C.c_void_p
    def _call(self,value,encrypt):
        buf=(W.BYTE*len(value)).from_buffer_copy(value);source=DataBlob(len(value),buf);dest=DataBlob()
        fn=self.api.CryptProtectData if encrypt else self.api.CryptUnprotectData
        try:
            if not fn(C.byref(source),None,None,None,None,1,C.byref(dest)):raise ValueError('Windows no pudo proteger o recuperar el dato.')
            return C.string_at(dest.data,dest.size)
        finally:
            C.memset(buf,0,len(value))
            if dest.data:C.memset(dest.data,0,dest.size);self.kernel.LocalFree(dest.data)
    def protect(self,value):return self._call(value,True)
    def unprotect(self,value):return self._call(value,False)

def validate(kind,raw):
    if not isinstance(raw,str) or not raw.strip() or len(raw)>60:raise ValueError('Número vacío o demasiado largo.')
    proposed=re.sub(r'[ -]','',raw.strip())
    if kind==TYPES[0] and not re.fullmatch('[1-9][0-9]{8}',proposed):raise ValueError('Formato de cédula: nueve dígitos, sin validar la identidad de la persona.')
    if kind=='DIMEX' and not re.fullmatch('[1-9][0-9]{10,11}',proposed):raise ValueError('Revisa el formato de DIMEX (11 o 12 dígitos); no se verifica identidad.')
    if kind not in TYPES[:2] and not re.fullmatch('[A-Za-z0-9 -]{4,40}',raw.strip()):raise ValueError('Formato genérico inválido; revisa las reglas del país emisor.')
    return proposed

def question_kind(question):
    import unicodedata
    q=''.join(c for c in unicodedata.normalize('NFKD',question.casefold()) if not unicodedata.combining(c))
    if not re.search(r'national id|government id|identity number|numero de identidad|identification (?:number|document)|numero de (?:cedula|identificacion)|cedula|passport|pasaporte|issuing country|pais emisor|tipo de documento|document type|dimex',q):return None
    return dict(requested='Pasaporte' if re.search(r'passport|pasaporte',q) else TYPES[0] if 'cedula' in q else 'DIMEX' if 'dimex' in q else None,field='country' if re.search(r'issuing country|pais emisor',q) else 'kind' if re.search(r'tipo de documento|document type',q) else 'number')

class IdentityStore:
    def __init__(self,data_path,private_root=None):
        self.data_path=Path(data_path);self.db=Database(self.data_path/'autojob.sqlite3');self.crypto=DPAPI()
        # Fuera del proyecto: los respaldos generales no copian el documento digital.
        self.private_root=Path(private_root) if private_root else Path(os.environ['LOCALAPPDATA'])/'AutoJob'/'private-identity'/hashlib.sha256(str(self.data_path.resolve()).encode()).hexdigest()[:20]
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS protected_identity(id INTEGER PRIMARY KEY CHECK(id=1),cipher BLOB NOT NULL,revision TEXT NOT NULL,updated_at TEXT NOT NULL)')
    def _read(self):
        with closing(self.db.connect()) as db:row=db.execute('SELECT * FROM protected_identity WHERE id=1').fetchone()
        if not row:return None
        value=json.loads(self.crypto.unprotect(bytes(row['cipher'])).decode());value['revision']=row['revision'];return value
    def summary(self):
        row=self._read()
        if not row:return None
        return {k:row.get(k) for k in ('kind','country','expiry','legal_name','confirmed','revision')}|dict(masked='••••'+row['number'][-min(4,max(1,len(row['number'])-4)):] ,document=bool(row.get('document')),format_only=True)
    def save(self,kind,number,country='',expiry='',legal_name='',confirmed=False,normalize=False):
        if not isinstance(kind,str) or not kind.strip() or len(kind)>100:raise ValueError('Selecciona o escribe un tipo de documento.')
        proposed=validate(kind,number)
        if expiry:
            try:date.fromisoformat(expiry)
            except ValueError:raise ValueError('Fecha de vencimiento inválida; usa AAAA-MM-DD.') from None
        if len(country)>100 or len(legal_name)>200:raise ValueError('Metadatos demasiado largos.')
        old=self._read() or {};value=dict(kind=kind,number=proposed if normalize else number.strip(),country=country,expiry=expiry,legal_name=legal_name,confirmed=bool(confirmed),document=old.get('document'))
        cipher=self.crypto.protect(json.dumps(value,ensure_ascii=False).encode())
        with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO protected_identity VALUES (1,?,?,?)',(cipher,uuid4().hex,datetime.now(timezone.utc).isoformat()))
        return self.summary()
    def confirm(self):
        r=self._read()
        if not r:raise ValueError('Guarda primero el documento.')
        return self.save(r['kind'],r['number'],r['country'],r['expiry'],r['legal_name'],True)
    def reveal(self,explicit=False,revision=None):
        if not explicit:raise ValueError('Se necesita una acción explícita para visualizar la identificación.')
        row=self._read()
        if revision is not None and (not row or row['revision']!=revision):raise ValueError('El dato cambió; requiere una autorización para su revisión actual.')
        return Secret(row['number']) if row else None
    def attach(self,path):
        r=self._read()
        if not r:raise ValueError('Guarda primero la identificación.')
        path=Path(path)
        if path.suffix.lower() not in {'.pdf','.png','.jpg','.jpeg'} or path.stat().st_size>10*1024*1024:raise ValueError('Documento PDF o imagen de hasta 10 MB requerido.')
        raw=path.read_bytes()
        if not raw.startswith((b'%PDF-',b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff')):raise ValueError('El contenido no corresponde a un documento admitido.')
        self.private_root.mkdir(parents=True,exist_ok=True);ref=uuid4().hex;target=self.private_root/(ref+'.dpapi');target.write_bytes(self.crypto.protect(raw));old=r.get('document');r['document']=ref
        try:
            with closing(self.db.connect()) as db,db:db.execute('UPDATE protected_identity SET cipher=?,revision=? WHERE id=1',(self.crypto.protect(json.dumps({k:v for k,v in r.items() if k!='revision'},ensure_ascii=False).encode()),uuid4().hex))
        except Exception:target.unlink(missing_ok=True);raise
        if old:self._remove_file(old)
    def _remove_file(self,ref):
        if not re.fullmatch('[0-9a-f]{32}',ref):raise ValueError('Referencia protegida inválida.')
        (self.private_root/(ref+'.dpapi')).unlink(missing_ok=True)
    def delete(self):
        row=self._read()
        if row and row.get('document'):self._remove_file(row['document'])
        with closing(self.db.connect()) as db,db:db.execute('DELETE FROM protected_identity WHERE id=1')
    def resolve(self,question):
        request=question_kind(question)
        if not request:return None
        row=self.summary();compatible=bool(row and row['confirmed'] and (not request['requested'] or request['requested']==row['kind']))
        return dict(answer=None,status='REQUIERE AUTORIZACIÓN' if compatible else 'DESCONOCIDA',source='Identificación personal protegida',reason='Dato reservado; autorización del dominio y del campo exacto requerida.' if compatible else 'Sin identificación confirmada del tipo solicitado.',automatic=False,sensitive_identity=True,identity_field=request['field'],identity_revision=row['revision'] if row else None)
