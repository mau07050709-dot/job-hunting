import pytest
from autojob.forms.navigation import category_url,classify,public_asset
from autojob.search.jobs import Connector
@pytest.mark.parametrize('url',["https://workingnomads.com/remote-writing-jobs","https://www.workingnomads.com/jobs"])
def test_categories(url):assert category_url(url) and classify(url,200,'Jobs','',False)=='ENLACE INVÁLIDO'
def test_specific():assert not category_url('https://www.workingnomads.com/jobs/support-example')
def test_invalid_connector_not_application():
 row=dict(title='Writer',company='Example',url='https://workingnomads.com/remote-writing-jobs')
 c=Connector('Working Nomads');assert list(c.search_jobs([],payload=[row]))==[] and c.errors
 row['apply_url']='https://jobs.example.invalid/job/1'
 assert next(Connector('Working Nomads').search_jobs([],payload=[row]))['url']==row['apply_url']
@pytest.mark.parametrize('status,text,fields,expected',[(404,'',False,'VACANTE CERRADA'),(200,'Loading',False,'FORMULARIO NO COMPATIBLE'),(200,'',True,'FORMULARIO DISPONIBLE'),(200,'Verify you are human',False,'REQUIERE INTERVENCIÓN'),(503,'Try again',False,'CARGA TEMPORAL FALLIDA')])
def test_states(status,text,fields,expected):assert classify('https://example.invalid/job/1',status,'Support',text,fields)==expected
def test_assets_only_read_not_upload_or_submission():
 url='https://dcvxs6ggqztsa.cloudfront.net/candidate/releases/careers.abc.js'
 assert public_asset('https://apply.workable.com',url,'GET','script')
 assert not public_asset('https://apply.workable.com',url,'POST','script')
 assert not public_asset('https://apply.workable.com','https://evil.invalid/file.js','GET','script')
 assert not public_asset('https://other.invalid',url,'GET','script')


def test_bad_row_does_not_hide_valid_offer():
 c=Connector('Working Nomads');rows=[dict(title='Writer',company='Example',url='https://workingnomads.com/remote-writing-jobs'),dict(title='Support',company='Example',url='https://www.workingnomads.com/jobs/support-example')]
 assert len(list(c.search_jobs([],payload=rows)))==1 and c.errors

def test_challenge_identifiers_redacted():
 from autojob.forms.navigation import safe
 assert safe('https://example.invalid/cdn-cgi/challenge-platform/secret/token?cookie=abc')=='https://example.invalid/cdn-cgi/challenge-platform/[redacted]'


@pytest.mark.skipif(__import__('os').environ.get('AUTOJOB_TEST_BRAVE')!='1',reason='Brave local')
def test_javascript_delayed_form_with_public_guard(tmp_path):
 from test_submissions9b import portal
 from autojob.browser import BraveSession
 from autojob.forms.guard import PreparationGuard
 from autojob.forms.navigation import open_page
 with portal(tmp_path) as lab:
  with BraveSession(lab['settings']) as b:
   guard=PreparationGuard(b,controlled_origin=lab['job']['application_url'].split('/form')[0]);page=b.new_page();native=guard.navigate
   def delayed(p,url):
    native(p,url);p.evaluate("document.body.innerHTML='<div>Loading</div>';setTimeout(()=>document.body.innerHTML='<form><input type=email><input type=file></form>',400)")
   guard.navigate=delayed
   r=open_page(guard,page,lab['job']['application_url'])
   assert r['state']=='FORMULARIO DISPONIBLE' and r['controls_detected']
  assert not any(m=='POST' for m,p in lab['requests'])
