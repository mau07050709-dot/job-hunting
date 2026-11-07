"""Cartas existentes y borradores verificables, aprobados por vacante antes de adjuntar."""
from contextlib import closing
from pathlib import Path
from autojob.profile.letters import Letters
from autojob.forms.submissions import SubmissionStore
from autojob.matching.engine import digest

class SubmissionLetters:
    def __init__(self,data_path):
        self.data_path=data_path;self.letters=Letters(data_path);self.db=self.letters.db
        with closing(self.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS submission_letter_reviews(job_id TEXT PRIMARY KEY,letter_id TEXT NOT NULL,body_hash TEXT NOT NULL,profile_hash TEXT NOT NULL,approved INTEGER NOT NULL)')
    def draft(self,job,cv_id):
        cv=self.letters.library.get(cv_id);language=cv['language'];category=cv['specialty']
        if category not in {'technical','customer_service'} or language not in {'en','es'}:raise ValueError('Selecciona idioma y especialidad antes de generar la carta.')
        with closing(self.db.connect()) as db:review=db.execute('SELECT * FROM submission_letter_reviews WHERE job_id=?',(job['id'],)).fetchone()
        if review:
            existing=next((r for r in self.letters.history() if r['id']==review['letter_id']),None)
            if existing:return existing
        existing=next((r for r in self.letters.history() if r['company']==job['company'] and r['position']==job['title'] and r['cv_id']==cv_id and r['language']==language),None)
        if existing:letter=existing
        else:
            body=self.letters.generate(job['company'],job['title'],job.get('description') or '',language,category,cv_id);id=self.letters.save(job['company'],job['title'],job.get('description') or '',language,category,cv_id,body);letter=next(r for r in self.letters.history() if r['id']==id)
        with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO submission_letter_reviews VALUES (?,?,?,?,0)',(job['id'],letter['id'],digest(letter['body']),SubmissionStore(self.data_path).prep.inputs_hash()))
        return letter
    def approve(self,job,letter_id,body,explicit=False):
        if not explicit:raise ValueError('Revisa y autoriza expresamente la carta para esta vacante.')
        letter=next((r for r in self.letters.history() if r['id']==letter_id),None)
        if not letter or letter['company']!=job['company'] or letter['position']!=job['title']:raise ValueError('La carta no corresponde a la empresa y puesto.')
        self.letters.save(letter['company'],letter['position'],letter['description'],letter['language'],letter['category'],letter['cv_id'],body,letter_id)
        with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO submission_letter_reviews VALUES (?,?,?,?,1)',(job['id'],letter_id,digest(body),SubmissionStore(self.data_path).prep.inputs_hash()))
    def artifact(self,job,cv_id):
        letter=self.draft(job,cv_id)
        with closing(self.db.connect()) as db:r=db.execute('SELECT * FROM submission_letter_reviews WHERE job_id=?',(job['id'],)).fetchone()
        if not r or not r['approved'] or r['body_hash']!=digest(letter['body']) or r['profile_hash']!=SubmissionStore(self.data_path).prep.inputs_hash():return None
        root=self.data_path/'outgoing-letters';root.mkdir(exist_ok=True);path=root/(letter['id']+'.pdf');self.letters.export(letter['body'],path);return path
