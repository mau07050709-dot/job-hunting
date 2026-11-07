"""Contexto persistente mínimo: referencias, nunca cookies, claves o respuestas sensibles."""
from contextlib import closing
from urllib.parse import urlsplit
import json
from autojob.storage.database import utc_now

def ensure(store):
    with closing(store.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS intervention_context(id TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL)')

def capture(store,row,queue):
    ensure(store)
    q=next((r for r in queue.list() if r['job_id']==row['job_id']),{})
    p=q.get('payload',{});stages=p.get('stages') or [];doc=(stages[-1] if stages else {}).get('document') or {}
    fields=[]
    for e in (p.get('preview') or {}).get('entries',[]):
        if e.get('required') and e.get('status') not in {'CONFIRMADA','DERIVADA','DOCUMENTO LOCAL'}:
            fields.append({k:e.get(k) for k in ['label','name','kind','group','semantic','frame_index']})
    job=next((j for j in queue.preparation.compatibility.jobs.list() if j['id']==row['job_id']),{})
    from autojob.auth.detection import safe_url
    from urllib.parse import parse_qs,urlunsplit
    target=job.get('application_url') or row['url'];url=safe_url(target) if target else '';parts=urlsplit(target);public=parse_qs(parts.query).get('gh_jid',[''])[0]
    if public.isdigit():url+='?gh_jid='+public
    value=dict(job_id=row['job_id'],company=row['company'],title=row['title'],portal=urlsplit(url).hostname,url=url,stage=len(stages),fields=fields,kind=row['kind'],session_reference=row.get('verification_id'),answers_reference='approved_form_answers / profile revision',resume_conditions='Reinspeccionar, comprobar respuesta o señal del portal y adjuntos; nunca reenviar un resultado incierto.')
    with closing(store.db.connect()) as db,db:db.execute('INSERT INTO intervention_context VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',(row['id'],json.dumps(value),utc_now()))
    return value

def load(store,id):
    ensure(store)
    with closing(store.db.connect()) as db:r=db.execute('SELECT payload FROM intervention_context WHERE id=?',(id,)).fetchone()
    return json.loads(r[0]) if r else None

def focus(page,context):
    # Reidentificar por nombre/pregunta; los selectores históricos no son autoridad.
    for field in context.get('fields',[]):
        import json
        name=field.get('name');label=field.get('group') or field.get('label')
        for frame in page.frames:
            targets=[]
            if name:targets.append(frame.locator('[name='+json.dumps(name)+']'))
            if label:targets.append(frame.get_by_label(label,exact=True))
            for target in targets:
                if target.count()==1 and target.is_visible():target.scroll_into_view_if_needed();target.evaluate('(e)=>{e.style.outline="3px solid #f5b942";e.style.outlineOffset="3px"}');target.focus();return True
    return False
