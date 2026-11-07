"""Validación controlada del coordinador; documentos y personas exclusivamente ficticios."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from threading import Thread
from pathlib import Path
from dataclasses import replace
import json,secrets
from autojob.control import Coordinator
from autojob.forms.runner import process
from autojob.profile.store import empty
from autojob.search.availability import Availability

DESCRIPTION='''Requirements:
Python required.
Minimum 2 years of software development experience required.
Completed bachelor degree required.
English B2 required.
Communication skills required.
Responsibilities: develop Python applications and collaborate with the team.
Worldwide remote. Full-time.'''

@contextmanager
def fixture_flow(settings,root):
    from docx import Document
    settings=replace(settings,root=Path(root),data_dir='data');engine=Coordinator(settings);token=secrets.token_hex(20);requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            requests.append(dict(method='GET',path=self.path));name='First' if self.path.endswith('first') else 'Second';title='Junior Python Developer '+name
            posting=json.dumps({'@context':'https://schema.org','@type':'JobPosting','title':title,'validThrough':'2035-12-31T00:00:00Z'})
            if self.path.startswith('/jobs/'):
                body=f'<h1>{title}</h1><p>Job Hunting Fictional Labs</p><script type="application/ld+json">{posting}</script><a href="/forms/{name.lower()}">Apply now</a>'
            else:
                body=f'<h1>{title}</h1><form><label>Full name<input id="name" required></label><label>Email<input id="email" type="email" required></label>'
                if name=='First':body+='<label>Unknown mandatory project code<input id="code" required></label>'
                body+='<button type="submit">Submit application</button></form>'
            data=(f'<html><head><meta name="autojob-fixture" content="{token}"><title>Job Hunting Fictional Labs — {title}</title></head><body>'+body+'</body></html>').encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(data)
        def do_POST(self):requests.append(dict(method='POST',path=self.path));self.send_error(403)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port);fixture=dict(origin=origin,token=token)
    try:
        source=Path(root)/'fictional.docx';doc=Document()
        for line in ['Full name: Alex Rivera','Email: alex@example.invalid','Education:','Bachelor of Electronics, Example University, 2020 - 2024','Work Experience:','Software Developer | Example Labs | 2022 - 2024','Technical Skills:','Python, SQL, Git, Linux','Languages:','English B2','Spanish native','Academic Projects:','Python application project']:
            doc.add_paragraph(line)
        doc.save(source);cv=engine.compatibility.library.import_document(source);engine.compatibility.library.update(cv['id'],title='Fictitious technical CV',language='en',specialty='technical',fields=cv['fields'],reviewed=True,expected_revision=cv['revision']);engine.compatibility.library.set_default(cv['id'])
        profile=engine.compatibility.profile;state=profile.load();values=state['values'];values.update(full_name='Alex Rivera',email='alex@example.invalid',country='Costa Rica',remote=True,full_time=True,positions=['Software Developer'],experience_records=['Example Labs | Software Developer | 2022-01-01 | 2024-12-31 | Python development'],qualifications=['Bachelor of Electronics'],languages=['English B2'],skills=['Python'],soft_skills=['Communication'])
        profile.save(values,state['revision'],confirmed=['full_name','email','country','remote','full_time','positions','experience_records','qualifications','languages','skills','soft_skills'])
        def search(queries,sources,limit,cancel,progress):
            found=0
            for name in ['first','second']:
                if cancel():break
                found+=engine.jobs.add(dict(source='CONTROLLED FIXTURE',source_id=name,title='Junior Python Developer '+name.title(),company='Job Hunting Fictional Labs',url=origin+'/jobs/'+name,application_url=origin+'/forms/'+name,description=DESCRIPTION,location='Worldwide',modality='remote',geography='CONFIRMADO',schedule='Full-time',availability='NO VERIFICADA'))
            engine.queue.add([j['id'] for j in engine.jobs.list()])
            first=next(j['id'] for j in engine.jobs.list() if j['title'].endswith('First'));engine.queue.priority(first,90000)
            return dict(found=found,duplicates=2-found,errors=[])
        def prepare(settings,ids,pause,stop,progress):return engine.queue.run(settings,ids,pause,stop,progress,processor=lambda q,r,s,p,c,id:process(q,r,s,p,c,id,fixture))
        services=dict(search=search,prepare=prepare);options=dict(queries=['Python'],sources=['CONTROLLED FIXTURE'],limit=2)
        yield dict(engine=engine,settings=settings,services=services,options=options,requests=requests,fixture=fixture)
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
