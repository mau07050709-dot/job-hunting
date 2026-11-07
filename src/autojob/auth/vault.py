"""Credenciales genéricas del usuario de Windows; sin respaldo en archivos."""
import ctypes as C
from ctypes import wintypes as W
import os,re

class VaultError(RuntimeError):pass

class Secret:
    __slots__=('_value',)
    def __init__(self,value):
        if not isinstance(value,str) or not value or '\x00' in value or len(value.encode('utf-16-le'))>2560:
            raise ValueError('Secreto vacío o longitud inválida.')
        self._value=value
    def reveal(self):return self._value
    def clear(self):self._value=''
    def __repr__(self):return '<Secret protegido>'
    __str__=__repr__

class Credential(C.Structure):
    _fields_=[('Flags',W.DWORD),('Type',W.DWORD),('TargetName',W.LPWSTR),('Comment',W.LPWSTR),('LastWritten',W.FILETIME),('CredentialBlobSize',W.DWORD),('CredentialBlob',C.POINTER(W.BYTE)),('Persist',W.DWORD),('AttributeCount',W.DWORD),('Attributes',C.c_void_p),('TargetAlias',W.LPWSTR),('UserName',W.LPWSTR)]

class WindowsVault:
    def __init__(self):
        if os.name!='nt':raise VaultError('Se requiere el almacén seguro de Windows; no hay alternativa en texto plano.')
        self.api=C.WinDLL('Advapi32.dll',use_last_error=True)
        self.api.CredWriteW.argtypes=[C.POINTER(Credential),W.DWORD];self.api.CredWriteW.restype=W.BOOL
        self.api.CredReadW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.POINTER(C.POINTER(Credential))];self.api.CredReadW.restype=W.BOOL
        self.api.CredDeleteW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD];self.api.CredDeleteW.restype=W.BOOL
        self.api.CredFree.argtypes=[C.c_void_p];self.api.CredFree.restype=None
    def _target(self,reference):
        if not re.fullmatch(r'AutoJob/account/[0-9a-f]{32}',reference or ''):raise VaultError('Referencia fuera del espacio de Job Hunting.')
        return reference
    def put(self,reference,secret):
        target=self._target(reference)
        if not isinstance(secret,Secret):raise VaultError('Se requiere un secreto protegido.')
        raw=secret.reveal().encode('utf-16-le');buf=(W.BYTE*len(raw)).from_buffer_copy(raw)
        cred=Credential(Type=1,TargetName=target,Comment='Job Hunting: credencial local del usuario',CredentialBlobSize=len(raw),CredentialBlob=buf,Persist=2,UserName='Job Hunting')
        try:
            if not self.api.CredWriteW(C.byref(cred),0):raise VaultError('Windows no pudo guardar la credencial (código '+str(C.get_last_error())+').')
        finally:C.memset(buf,0,len(raw))
    def get(self,reference):
        pointer=C.POINTER(Credential)()
        if not self.api.CredReadW(self._target(reference),1,0,C.byref(pointer)):
            if C.get_last_error()==1168:return None
            raise VaultError('Windows no pudo recuperar la credencial.')
        try:
            cred=pointer.contents
            return Secret(C.string_at(cred.CredentialBlob,cred.CredentialBlobSize).decode('utf-16-le'))
        finally:
            if pointer.contents.CredentialBlob:C.memset(pointer.contents.CredentialBlob,0,pointer.contents.CredentialBlobSize)
            self.api.CredFree(pointer)
    def delete(self,reference):
        if not self.api.CredDeleteW(self._target(reference),1,0) and C.get_last_error()!=1168:raise VaultError('Windows no pudo eliminar la credencial.')
