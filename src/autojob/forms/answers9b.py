"""Respuestas confirmadas con alcance explícito; no reemplaza los datos existentes."""
from contextlib import closing
from datetime import date
from decimal import Decimal,InvalidOperation
from uuid import uuid4
import json,re
from autojob.storage.database import Database,utc_now
from autojob.profile.answers import norm

def restricted(question):
    from autojob.auth.identity import question_kind
    from autojob.profile.answers import SENSITIVE
    return question_kind(question) or any(norm(term) in norm(question) for term in SENSITIVE) or re.search(r'\bssn\b|social security|seguridad social|tax id|identificacion fiscal|driver.{0,10}licen|licencia de conducir|password|contrase|passport|pasaporte|dimex|signature|firma|criminal|background check|antecedentes|accept|agree|acepto|certifico|attest|terms|privacy|privacidad',norm(question))

def validate_answer(value,kind,options=()):
    value=str(value).strip()
    if not value or len(value)>10000:raise ValueError('Introduce una respuesta válida.')
    if kind in {'number','range'}:
        try:
            if not Decimal(value).is_finite():raise ValueError()
        except (ValueError,InvalidOperation):raise ValueError('Introduce un número finito.') from None
    if kind in {'date'}:
        try:date.fromisoformat(value)
        except ValueError:raise ValueError('Fecha: AAAA-MM-DD.') from None
    if kind=='checkbox' and norm(value) not in {'yes','no','si','true','false'}:raise ValueError('Selecciona Sí o No.')
    if kind in {'select','multiple','radio','combobox'} and options:
        values=value.split('|') if kind=='multiple' else [value]
        if any(v not in options for v in values):raise ValueError('Selecciona una opción publicada por el formulario.')
    return value

class ScopedAnswers:
    def __init__(self,data_path):
        self.db=Database(data_path/'autojob.sqlite3')
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS approved_form_answers(id TEXT PRIMARY KEY,question TEXT NOT NULL,kind TEXT NOT NULL,value TEXT NOT NULL,scope TEXT NOT NULL,scope_key TEXT NOT NULL,conditions TEXT NOT NULL,confirmed INTEGER NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL,UNIQUE(question,scope,scope_key,conditions))')
            db.execute('CREATE TABLE IF NOT EXISTS approved_form_answer_history(id INTEGER PRIMARY KEY,answer_id TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL)')
    def rows(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM approved_form_answers ORDER BY updated_at')]
    def save(self,question,value,kind='text',scope='job',context=None,confirmed=False,options=()):
        context=context or {};q=norm(question)
        if restricted(q):raise ValueError('La identidad y los consentimientos requieren sus permisos específicos; no se guardan aquí.')
        if scope not in {'job','company','personal','work'}:raise ValueError('Alcance desconocido.')
        if re.search(r'company|empresa|worked|trabajado|previously',q) and scope not in {'job','company'}:raise ValueError('Esta respuesta debe limitarse a la empresa o vacante.')
        if re.search(r'salary|salario|sueldo',q) and scope not in {'job','company'}:raise ValueError('Guarda el salario general en Mis datos; esta respuesta se limita a su contexto.')
        key=context.get('job_id','') if scope=='job' else norm(context.get('company','')) if scope=='company' else ''
        if scope in {'job','company'} and not key:raise ValueError('Falta el contexto de la respuesta.')
        value=validate_answer(value,kind,options);conditions=json.dumps(dict(modality=context.get('modality'),position=context.get('position') if scope=='job' else None),sort_keys=True)
        with closing(self.db.connect()) as db,db:
            old=db.execute('SELECT id,revision FROM approved_form_answers WHERE question=? AND scope=? AND scope_key=? AND conditions=?',(q,scope,key,conditions)).fetchone();id=old['id'] if old else uuid4().hex;revision=old['revision']+1 if old else 1
            db.execute('INSERT OR REPLACE INTO approved_form_answers VALUES (?,?,?,?,?,?,?,?,?,?)',(id,q,kind,value,scope,key,conditions,int(confirmed),revision,utc_now()))
            db.execute('INSERT INTO approved_form_answer_history(answer_id,payload,at) VALUES (?,?,?)',(id,json.dumps(dict(value=value,scope=scope,scope_key=key,confirmed=confirmed,revision=revision)),utc_now()))
        return id
    def resolve(self,question,context):
        q=norm(question);matches=[]
        for row in self.rows():
            c=json.loads(row['conditions'])
            from autojob.profile.semantic import equivalent
            if not equivalent(row['question'],q) or not row['confirmed'] or c['modality']!=context.get('modality'):continue
            if row['scope']=='job' and row['scope_key']!=context.get('job_id'):continue
            if row['scope']=='company' and row['scope_key']!=norm(context.get('company','')):continue
            matches.append(row)
        if not matches:return None
        priority={'job':0,'company':1,'personal':2,'work':2};rank=min(priority[r['scope']] for r in matches);matches=[r for r in matches if priority[r['scope']]==rank]
        if len({r['value'] for r in matches})!=1:return dict(answer=None,status='CONFLICTO',source='Respuestas aprobadas',reason='Hay respuestas confirmadas contradictorias.',automatic=False)
        return dict(answer=matches[0]['value'],status='CONFIRMADA',source='Respuesta aprobada · '+matches[0]['scope'],reason='Pregunta y contexto coincidentes; historial conservado.',automatic=False)
