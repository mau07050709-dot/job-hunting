"""Reconocimiento local conservador; la similitud nunca inventa una respuesta."""
import re
from difflib import SequenceMatcher
from contextlib import closing
from uuid import uuid4
from autojob.profile.answers import norm
from autojob.storage.database import Database,utc_now

INTENTS={
 'sponsorship':[r'sponsor',r'patrocinio',r'patrocinador'],
 'work_authorization':[r'authorized to work',r'legally.{0,12}work',r'work (?:permit|authorization)',r'permiso.{0,12}trabaj',r'autorizacion laboral'],
 'current_employee':[r'current employee',r'currently work',r'actualmente.{0,20}trabaj',r'empleado actual'],
 'former_employee':[r'former (?:employe|employee|empoyee|emplyee)\b',r'(?:work|employ).{0,55}(?:this company|our organization|our company)',r'(?:trabaj|emplead).{0,45}(?:esta empresa|nuestra empresa|nuestra organizacion)',r'exempleado'],
 'relocation':[r'relocat',r'reubic'], 'travel':[r'travel',r'viajar',r'viajes'],
 'english_level':[r'english.{0,20}(?:level|proficien)',r'(?:level|proficien).{0,20}english',r'nivel.{0,15}ingles'],
}
def clean(q):return ' '.join(re.findall(r'\w+',norm(q)))
def intent(q):
    q=clean(q)
    for key,patterns in INTENTS.items():
        if key=='former_employee' and re.search(r'why|want|interested|por que|quier',q):continue
        if any(re.search(p,q) for p in patterns):return key
    return None
def equivalent(a,b):
    a,b=clean(a),clean(b)
    if a==b:return True
    ia,ib=intent(a),intent(b)
    if ia!=ib and (ia or ib):return False
    units=lambda q:{u for u in ('annual','yearly','monthly','hourly','anual','mensual','hora') if re.search(r'\b'+u+r'\b',q)}
    if units(a)!=units(b):return False
    if ia:return True
    if len(a)<10 or len(b)<10:return False
    if any(word in set(a.split())^set(b.split()) for word in ('not','never','no','nunca','without','sin')):return False
    return SequenceMatcher(None,' '.join(sorted(a.split())),' '.join(sorted(b.split()))).ratio()>=.94
class SemanticAnswers:
    def __init__(self,path):
        self.db=Database(path/'autojob.sqlite3')
        with closing(self.db.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS personal_questions(id TEXT PRIMARY KEY,question TEXT NOT NULL,answer TEXT,language TEXT,category TEXT,company TEXT,updated_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS personal_question_history(id INTEGER PRIMARY KEY,question_id TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL)')
    def rows(self):
        with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM personal_questions ORDER BY updated_at DESC')]
    def save(self,question,answer=None,language='',category='',company='',id=None):
        if len(question)>1000 or len(answer or '')>10000:raise ValueError('Texto demasiado largo.')
        if id is None:id=next((r['id'] for r in self.rows() if clean(r['question'])==clean(question) and norm(r['company'] or '')==norm(company)),None)
        id=id or uuid4().hex;stamp=utc_now();values=(id,question.strip(),(answer or '').strip() or None,language.strip(),category.strip(),company.strip(),stamp)
        import json
        with closing(self.db.connect()) as db,db:
            db.execute('INSERT OR REPLACE INTO personal_questions VALUES (?,?,?,?,?,?,?)',values)
            db.execute('INSERT INTO personal_question_history(question_id,payload,updated_at) VALUES (?,?,?)',(id,json.dumps(values[1:-1],ensure_ascii=False),stamp))
        return id
    def resolve(self,question,context):
        from autojob.forms.answers9b import restricted
        if restricted(question):return None
        candidates=[]
        for row in self.rows():
            if not row['answer'] or not row['question'] or not equivalent(question,row['question']):continue
            if row['company'] and norm(row['company'])!=norm(context.get('company','')):continue
            if intent(question)=='former_employee' and not row['company']:continue
            candidates.append(row)
        if not candidates:return None
        if len({r['answer'] for r in candidates})!=1:return dict(answer=None,status='CONFLICTO',source='Respuestas guardadas',reason='Respuestas incompatibles; revisar.',automatic=False)
        return dict(answer=candidates[0]['answer'],status='CONFIRMADA',source='Información adicional · respuesta guardada',reason='Intención y contexto coincidentes con alta confianza.',automatic=False)
