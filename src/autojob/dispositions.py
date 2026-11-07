"""Descarte y ocultación persistentes, independientes de la evidencia de envío."""
from contextlib import closing
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from autojob.storage.database import Database


def normalized_url(url):
    p=urlsplit(url)
    ignored={'source','ref','referrer','gh_src','lever-source','lever-origin','fbclid','gclid'}
    query=sorted((k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in ignored)
    path=p.path.rstrip('/')
    if path.endswith('/apply'):path=path[:-6]
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),path,urlencode(query),''))


def keys(job,db=None):
    result={'id:'+job['id']}
    if job.get('source') and job.get('source_id'):result.add('source:'+str(job['source'])+':'+str(job['source_id']))
    urls=[job.get('url'),job.get('application_url')]+[r.get('url') for r in job.get('source_links',[])]
    if db and db.execute("SELECT 1 FROM sqlite_master WHERE name='job_sightings'").fetchone():
        for row in db.execute('SELECT source,source_id,url FROM job_sightings WHERE job_id=?',(job['id'],)):
            result.add('source:'+row['source']+':'+row['source_id']);urls.append(row['url'])
    for url in urls:
        if not url:continue
        p=urlsplit(url);query=dict(parse_qsl(p.query));host=(p.hostname or '').lower()
        import re
        generic=not p.path.strip('/') or bool(re.fullmatch(r'/(?:careers|jobs|search|job-search|openings|positions|apply|remote-[^/]+-jobs)/?',p.path,re.I))
        identifying_query=any(k.lower() in {'gh_jid','jobid','job_id','postingid','requisitionid','reqid'} and v for k,v in query.items())
        if not generic or identifying_query:result.add('url:'+normalized_url(url))
        if host.endswith('greenhouse.io'):
            import re
            match=re.search(r'/([^/]+)/jobs/(\d+)',p.path)
            if match:result.add('greenhouse:'+match[1]+':'+match[2])
        if host=='jobs.5ca.com' and query.get('gh_jid','').isdigit():result.add('greenhouse:5ca:'+query['gh_jid'])
        if host=='jobs.lever.co':
            import re
            match=re.match(r'/([^/]+)/([0-9a-f-]{36})(?:/|$)',p.path,re.I)
            if match:result.add('lever:'+match[1].lower()+':'+match[2].lower())
    return result


def decision(db,job):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='job_disposition_keys'").fetchone():return None
    values=keys(job,db)
    rows=db.execute('SELECT d.* FROM job_dispositions d JOIN job_disposition_keys k ON k.job_id=d.job_id WHERE k.identity IN ('+','.join('?' for _ in values)+') ORDER BY d.hidden DESC,d.updated_at DESC',tuple(values)).fetchall()
    return dict(rows[0]) if rows else None


class Dispositions:
    def __init__(self,path):
        self.db=Database(path/'autojob.sqlite3')
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS job_dispositions(job_id TEXT PRIMARY KEY,url TEXT NOT NULL,state TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0,requested_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS job_disposition_keys(job_id TEXT NOT NULL,identity TEXT NOT NULL,PRIMARY KEY(job_id,identity))')
            db.execute('CREATE INDEX IF NOT EXISTS job_disposition_identity ON job_disposition_keys(identity)')

    def get(self,job):
        with closing(self.db.connect()) as db:return decision(db,job)

    def discard(self,job,hide=False):
        stamp=datetime.now(timezone.utc).isoformat()
        with closing(self.db.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            old=decision(db,job)
            identities=keys(job,db);related={job['id']}
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='discovered_jobs'").fetchone():
                for row in db.execute('SELECT id,payload FROM discovered_jobs'):
                    candidate=dict(json.loads(row['payload']),id=row['id'])
                    if identities & keys(candidate,db):related.add(row['id'])
            placeholders=','.join('?' for _ in related)
            attempts=db.execute('SELECT state FROM submission_attempts WHERE job_id IN ('+placeholders+') ORDER BY started_at DESC',tuple(related)).fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE name='submission_attempts'").fetchone() else []
            unsafe=next((r['state'] for r in attempts if r['state'] in {'ENVIANDO','ENVIADA CONFIRMADA','ENVÍO NO VERIFICADO','RECHAZADA'}),None)
            state='RESULTADO FINAL CONSERVADO' if unsafe else 'DESCARTADA POR EL USUARIO'
            db.execute('INSERT INTO job_dispositions VALUES (?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET state=excluded.state,hidden=MAX(job_dispositions.hidden,excluded.hidden),updated_at=excluded.updated_at',(job['id'],job.get('application_url') or job['url'],state,int(hide or bool(old and old['hidden'])),stamp,stamp))
            db.executemany('INSERT OR IGNORE INTO job_disposition_keys VALUES (?,?)',[(job['id'],key) for key in identities])
            db.executemany('INSERT OR REPLACE INTO control_exclusions VALUES (?,?)',[(id,stamp) for id in related])
            db.execute("UPDATE control_interventions SET state='OMITIDA',updated_at=? WHERE job_id IN ("+placeholders+") AND state IN ('PENDIENTE','POSPUESTA')",(stamp,*related))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_queue'").fetchone():
                db.execute("UPDATE preparation_queue SET state='BLOQUEADA',last_action=?,updated_at=? WHERE job_id IN ("+placeholders+")",('Excluida por el usuario; historial y resultado final conservados.' if unsafe else state,stamp,*related))
        return dict(state=state,previous_submission=unsafe,hidden=bool(hide),related_job_ids=sorted(related))
