"""Prueba cerrada en loopback con datos ficticios y bloqueo de destinos externos."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from threading import Thread
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
import json
from urllib.parse import urlsplit
from autojob.forms.preparation import inspect

@contextmanager
def controlled_site():
 token=token_hex(20);requests=[]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   requests.append(dict(method='GET',path=self.path))
   if not self.path.startswith('/autojob-test/'):
    self.send_error(404);return
   body=(f'<html><head><meta name="autojob-fixture" content="{token}"><title>Job Hunting controlled fixture</title></head><body>'+('''<form><label for="name">Full name</label><input id="name" name="full_name" required><label for="mail">Email</label><input id="mail" type="email" required><label for="dob">Fecha de nacimiento</label><input id="dob" type="date"><label for="pc">Do you have your own computer?</label><select id="pc" required><option value="">Choose</option><option value="yes">Yes</option><option value="no">No</option></select><button type="button" id="next" onclick="location.href='/autojob-test/step2'">Next</button></form>''' if self.path.endswith('step1') else '''<form><label for="salary">Expected monthly salary USD</label><input id="salary" type="number" required><label for="exp">Describe your customer service experience.</label><textarea id="exp"></textarea><fieldset><legend>Accepted shifts</legend><label><input type="checkbox" name="shift" value="day">Day</label><label><input type="checkbox" name="shift" value="night">Night</label></fieldset><fieldset><legend>Preferred mode</legend><label><input type="radio" name="mode" value="remote">Remote</label><label><input type="radio" name="mode" value="onsite">Onsite</label></fieldset><label for="cv">Resume / CV</label><input id="cv" type="file"><label for="letter">Cover letter</label><input id="letter" type="file"><label for="unknown">Unknown mandatory project code</label><input id="unknown" required><button type="submit">Submit application</button></form>''')+'</body></html>').encode()
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
  def do_POST(self):requests.append(dict(method='POST',path=self.path));self.send_error(405)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
 try:yield dict(origin=origin,token=token,requests=requests)
 finally:server.shutdown();server.server_close();thread.join(timeout=2)

def fill_controlled(page,fixture,values,files=None):
 if page.url.split('/autojob-test/')[0]!=fixture['origin'] or urlsplit(page.url).hostname!='127.0.0.1' or '/autojob-test/' not in page.url:raise ValueError('El relleno solo está permitido en el entorno local controlado.')
 if page.locator('meta[name="autojob-fixture"]').get_attribute('content')!=fixture['token']:raise ValueError('El servidor no corresponde a la prueba controlada.')
 report=[]
 for field in inspect(page)['fields']:
  if field['kind']=='button':continue
  target=page.locator(field['selector']);value=values.get(field['label']);key=field['label']
  if field['kind']=='file':
   path=(files or {}).get(field.get('document'))
   if path:target.set_input_files(str(path));report.append(key)
  elif value is not None:
   if field['kind'] in {'select','multiple'}:
    entries=value if isinstance(value,list) else [value];options=field['options'];selected=[o['value'] for o in options if o['label'] in entries or o['value'] in entries]
    if len(selected)!=len(entries):raise ValueError('La respuesta no coincide con las opciones locales.')
    target.select_option(selected)
   elif field['kind'] in {'checkbox','radio'}:target.set_checked(value is True)
   else:target.fill(str(value))
   report.append(key)
 return report

def run_controlled(settings):
 from autojob.browser import BraveSession
 from autojob.profile.application_data import ApplicationData
 from autojob.forms.preparation import Preparation
 from docx import Document
 with TemporaryDirectory(prefix='autojob-7a-fixture-') as folder,controlled_site() as fixture:
  data_path=Path(folder);data=ApplicationData(data_path)
  fake={'first_name':'Test','last_name':'Candidate','birth_date':'2000-02-03','own_computer':True,'main_expected':'1200','main_min':'1000','main_max':'1500','main_currency':'USD','main_period':'month','main_hours':'40'};data.save(fake,confirmed=fake)
  profile=data.profile.load();profile['values']['full_name']='Test Candidate';profile['values']['email']='candidate@example.invalid';data.profile.save(profile['values'],profile['revision'])
  resolver=Preparation(data_path);cv=data_path/'fictional-cv.docx';letter=data_path/'fictional-letter.docx'
  for path,text in [(cv,'FICTIONAL CV — Test Candidate — no real applicant data.'),(letter,'FICTIONAL COVER LETTER — controlled local test.')]:
   doc=Document();doc.add_paragraph(text);doc.save(path)
  with BraveSession(settings) as browser:
   browser.context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(fixture['origin']+'/') else route.abort())
   page=browser.new_page(fixture['origin']+'/autojob-test/step1');first=inspect(page);answers={f['label']:resolver.resolve(f['label'])['answer'] for f in first['fields'] if f['kind']!='button'};fill_controlled(page,fixture,answers)
   assert page.locator('#name').input_value()=='Test Candidate' and page.locator('#mail').input_value()=='candidate@example.invalid'
   page.locator('#next').click();page.wait_for_url('**/autojob-test/step2');second=inspect(page);answers={f['label']:resolver.resolve(f['label'])['answer'] for f in second['fields'] if f['kind'] not in {'button','file'}};fill_controlled(page,fixture,answers,{'cv':cv,'letter':letter})
   fill_controlled(page,fixture,{'Day':True,'Night':False,'Remote':True,'Onsite':False})
   assert page.locator('input[name=shift][value=day]').is_checked() and page.locator('input[name=mode][value=remote]').is_checked()
   assert page.locator('#salary').input_value()=='1200.00';assert page.locator('#unknown').input_value()==''
   assert page.locator('#cv').evaluate('(e)=>e.files[0].name')=='fictional-cv.docx';assert page.locator('#letter').evaluate('(e)=>e.files[0].name')=='fictional-letter.docx'
   assert any(f.get('action')=='ENVÍO FINAL' for f in second['fields'])
   return dict(stages=2,first_fields=len(first['fields']),second_fields=len(second['fields']),fictional_cv_attached=True,fictional_letter_attached=True,checkbox_and_radio_verified=True,unknown_left_empty=True,monthly_salary='1200.00',requests=fixture['requests'],submitted=False,external_requests_allowed=False)
