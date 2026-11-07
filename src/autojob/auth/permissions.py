from contextlib import closing
from datetime import datetime,timezone
from autojob.storage.database import Database
from autojob.auth.service import account_origin

ACTIONS={'INSPECCIONAR','RELLENAR','LOGIN','REGISTRO','IDENTIDAD'}
class Permissions:
    def __init__(self,data_path):
        self.db=Database(data_path/'autojob.sqlite3')
        with closing(self.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS domain_permissions(origin TEXT NOT NULL,action TEXT NOT NULL,scope TEXT NOT NULL,allowed INTEGER NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(origin,action,scope))')
    def set(self,url,action,scope,allowed,local=False):
        site=account_origin(url,local)
        if action not in ACTIONS or not scope or len(scope)>250:raise ValueError('Permiso o alcance inválido.')
        with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO domain_permissions VALUES (?,?,?,?,?)',(site,action,scope,int(allowed),datetime.now(timezone.utc).isoformat()))
    def allowed(self,url,action,scope,local=False):
        try:site=account_origin(url,local)
        except ValueError:return False
        with closing(self.db.connect()) as db:r=db.execute('SELECT allowed FROM domain_permissions WHERE origin=? AND action=? AND scope=?',(site,action,scope)).fetchone()
        return bool(r and r[0])
    def revoke(self,url,local=False):
        with closing(self.db.connect()) as db,db:db.execute('UPDATE domain_permissions SET allowed=0 WHERE origin=?',(account_origin(url,local),))
    def list(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM domain_permissions')]

def scope(store,row,action):
    if action=='REGISTRO':
        from autojob.forms.preparation import Preparation
        return row['id']+':'+(row['credential_ref'] or '')+':'+Preparation(store.data_path).inputs_hash()
    return row['id']+(':'+str(row['credential_ref'] or '') if action=='LOGIN' else '')
