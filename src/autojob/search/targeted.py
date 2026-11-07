"""Paginación pública para Costa Rica con caché diaria y límites explícitos."""
from contextlib import closing
from hashlib import sha256
import json,time
from urllib.parse import urlencode
from autojob.search.jobs import Connector

class TargetedPages:
    def __init__(self,jobs,queries,cancel,progress,fetch=None,max_requests=40):
        self.jobs=jobs;self.queries=queries;self.cancel=cancel;self.progress=progress
        self.fetch=fetch or Connector('Himalayas').fetch;self.max_requests=max_requests;self.requests=0;self.errors=[]
        with closing(jobs.db.connect()) as c,c:c.execute('CREATE TABLE IF NOT EXISTS targeted_feed_cache(key TEXT PRIMARY KEY,checked REAL NOT NULL,payload TEXT NOT NULL)')
    def __iter__(self):
        exhausted=set()
        # Primero Costa Rica explícita; después LATAM/global que acepta CR.
        for specific in (True,False):
            for page in range(1,5):
                for query in self.queries:
                    key=(specific,query)
                    if key in exhausted:continue
                    if self.cancel() or self.requests>=self.max_requests:return
                    params=dict(country='CR',q=query,page=page,sort='relevant')
                    if specific:params['exclude_worldwide']='true'
                    url='https://himalayas.app/jobs/api/search?'+urlencode(params)
                    cache_key=sha256(url.encode()).hexdigest();self.requests+=1
                    self.progress(f'Buscando remoto desde Costa Rica: {query} · página {page}')
                    try:
                        with closing(self.jobs.db.connect()) as c:old=c.execute('SELECT checked,payload FROM targeted_feed_cache WHERE key=?',(cache_key,)).fetchone()
                        if old and time.time()-old['checked']<86400:data=json.loads(old['payload'])
                        else:
                            if self.cancel():return
                            data=self.fetch(url)
                            if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):raise ValueError('Respuesta de fuente inválida')
                            with closing(self.jobs.db.connect()) as c,c:c.execute('INSERT OR REPLACE INTO targeted_feed_cache VALUES (?,?,?)',(cache_key,time.time(),json.dumps(data)))
                            if self.cancel():return
                            # Consultas secuenciales y pausa cancelable, sin ciclos de reintento.
                            for _ in range(5):
                                if self.cancel():return
                                time.sleep(.1)
                        rows=data['jobs']
                        if len(rows)<20:exhausted.add(key)
                        yield dict(data,jobs=rows,_country_filter='CR')
                    except Exception as exc:
                        self.errors.append('Himalayas: '+type(exc).__name__);self.progress('Himalayas no disponible: '+type(exc).__name__)
                        return # No insistir ante HTTP 429, acceso restringido o fallo de red.

def queries_for(areas):
    terms={'customer_service':['customer support','night shift customer support','overnight support','customer service','virtual assistant'],
           'it_support':['technical support','help desk'],
           'programming':['junior developer','python'],
           'electronics':['electronics technician','engineering assistant'],
           'qa':['QA tester']}
    return list(dict.fromkeys(q for area in ['customer_service','it_support','programming','electronics','qa'] if area in areas for q in terms[area]))
