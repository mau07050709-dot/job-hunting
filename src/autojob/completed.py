"""Historial manual por persona, separado de comprobantes de envío."""
import json
from contextlib import closing
from autojob.storage.database import Database,utc_now


class CompletedApplications:
    def __init__(self,data_path):
        self.db=Database(data_path/'autojob.sqlite3')
        with closing(self.db.connect()) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS manually_completed_jobs(job_id TEXT PRIMARY KEY,payload TEXT NOT NULL,completed_at TEXT NOT NULL)')
    def mark(self,row):
        job=row.get('job') or {}
        if not job.get('id') or not row.get('url'):raise ValueError('Selecciona una postulación.')
        payload={k:row.get(k) for k in ('job','url','score','geography')}
        with closing(self.db.connect()) as c,c:
            c.execute('INSERT OR IGNORE INTO manually_completed_jobs VALUES(?,?,?)',(job['id'],json.dumps(payload,ensure_ascii=False),utc_now()))
    def rows(self):
        with closing(self.db.connect()) as c:
            return [dict(json.loads(r['payload']),completed_at=r['completed_at'],state='HECHA · marcada manualmente') for r in c.execute('SELECT * FROM manually_completed_jobs ORDER BY completed_at DESC')]
    def keys(self):
        from autojob.manual_search import identity_keys
        return {key for r in self.rows() for key in identity_keys(r['job'],r['url'])}
