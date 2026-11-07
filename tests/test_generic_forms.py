import time
import pytest
from autojob.config import Settings
from autojob.extension_fill import ExtensionFill
from autojob.forms.detection import candidate_form


def form(company='Example Employer',title='Customer Care Specialist'):
 return dict(title=title+' â€” '+company,context=title,page_url='https://forms.any-employer.test/candidate/123',password=False,fields=[dict(label='Full Name: *',name='123',kind='text'),dict(label='E-mail: *',name='124',kind='text'),dict(label='Resume: *',name='125',kind='file')],frames=[])


def bridge(tmp_path):
 s=Settings(tmp_path);s.data_path.mkdir();b=ExtensionFill(s)
 b.tasks['t']=dict(id='t',state='DONE',url='https://board.example.test/job/1',job=dict(company='Example Employer',title='Customer Care Specialist'),created=time.monotonic(),rounds=0)
 return b


def test_generic_form_on_unlisted_domain_and_exact_scope(tmp_path):
 b=bridge(tmp_path);scan=form();assert candidate_form(scan)
 assert b.handle('/adopt',dict(id='t',url=scan['page_url'],scan=scan))['allowed']
 assert b.handle('/scope',dict(id='t',url=scan['page_url']))['allowed']
 assert not b.handle('/scope',dict(id='t',url='https://forms.any-employer.test/candidate/999'))['allowed']
 assert b.handle('/resume',dict(id='t',url=scan['page_url']))['id']=='t'

@pytest.mark.parametrize('url,scan',[
 ('https://unrelated.test/apply',form('Different Company','Different Position')),
 ('https://accounts.google.com/apply',form()),
 ('https://127.0.0.1/apply',form()),
 ('https://forms.any-employer.test/signup',dict(form(),password=True)),
 ('https://forms.any-employer.test/signup',dict(form(),fields=[dict(label='Email',kind='email')])),
])
def test_not_every_input_is_an_employment_form(tmp_path,url,scan):
 assert not bridge(tmp_path).handle('/adopt',dict(id='t',url=url,scan=scan))['allowed']


def test_visible_embedded_form_in_verified_job_page(tmp_path):
 b=bridge(tmp_path);scan=form();scan['title']='Application';scan['context']=''
 parent=dict(title='Customer Care Specialist â€” Example Employer',context='',frames=[dict(src=scan['page_url'],visible=True)])
 assert b.handle('/adopt',dict(id='t',url=scan['page_url'],scan=scan,parent_url='https://example-employer.test/jobs/123',parent_scan=parent))['allowed']


def test_follow_apply_general_without_portal_whitelist(tmp_path):
 b=bridge(tmp_path)
 assert b.handle('/follow',dict(id='t',from_url=b.tasks['t']['url'],url='https://hiring.unlisted.test/application/1',label='Apply now'))['allowed']
 assert not b.handle('/follow',dict(id='t',from_url='https://unrelated.test/',url='https://another.test/application',label='Apply now'))['allowed']
 assert not b.handle('/follow',dict(id='t',from_url=b.tasks['t']['url'],url='https://another.test/application',label='Submit application'))['allowed']


def test_finished_tasks_are_not_rearmed(tmp_path):
 b=bridge(tmp_path);b.finish_manual(b.tasks['t']['job'].get('id'))
 assert b.handle('/active',{})==[]
 assert not b.handle('/adopt',dict(id='t',url=form()['page_url'],scan=form()))['allowed']


@pytest.mark.skipif(__import__('os').environ.get('JOB_HUNTING_TEST_EXTENSION', __import__('os').environ.get('AUTOJOB_TEST_EXTENSION'))!='1',reason='Extensión Brave real optativa')
def test_actual_extension_adopts_existing_unowned_form_and_embedded_form(tmp_path,monkeypatch):
 import json,shutil
 from pathlib import Path
 from test_batch_https import seed
 from autojob.forms.controlled import controlled_site
 from autojob.browser.discovery import find_brave
 from playwright.sync_api import sync_playwright
 import autojob.extension_fill as module
 store,_=seed(tmp_path);monkeypatch.setattr(module,'PORT',0)
 b=ExtensionFill(Settings(tmp_path));b.start()
 extension=tmp_path/'extension';shutil.copytree(Path(__file__).parents[1]/'brave-extension',extension)
 for name in ('background.js','wake.js'):
  path=extension/name;path.write_text(path.read_text(encoding='utf-8').replace('127.0.0.1:18746','127.0.0.1:'+str(b.server.server_port)),encoding='utf-8')
 manifest=json.loads((extension/'manifest.json').read_text(encoding='utf-8'));manifest['host_permissions'].append('http://127.0.0.1/*');(extension/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
 html="""<html><head><title>Junior Python Developer — Fictional Labs</title></head><body><h1>Junior Python Developer</h1><form><div><label>Full Name: *</label><div><input id='name' type='text' placeholder='Full Name'></div></div><div><label>E-mail: *</label><div><input id='mail' type='text' placeholder='Email'></div></div><div><label>Resume: *</label><input id='cv' type='file' placeholder='Resume'></div><div><label>Unknown required project code *</label><input id='unknown'></div><button type='submit'>Submit application</button></form></body></html>"""
 try:
  with controlled_site() as fixture,sync_playwright() as pw:
   ctx=pw.chromium.launch_persistent_context(str(tmp_path/'browser'),executable_path=str(find_brave()),headless=True,ignore_default_args=['--disable-extensions'],args=['--disable-extensions-except='+str(extension),'--load-extension='+str(extension)])
   try:
    url='https://unlisted-employer.example/applications/123'
    parent='https://different-board.example/jobs/123'
    child='https://embedded-forms.example/application/123'
    ctx.route(url,lambda r:r.fulfill(content_type='text/html',body=html))
    ctx.route(child,lambda r:r.fulfill(content_type='text/html',body=html.replace('Junior Python Developer — Fictional Labs','Application')))
    ctx.route(parent,lambda r:r.fulfill(content_type='text/html',body="<html><title>Junior Python Developer — Fictional Labs</title><h1>Junior Python Developer</h1><iframe style='width:900px;height:700px' src='"+child+"'></iframe></html>"))
    page=ctx.new_page();page.goto(url)
    worker=ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event('serviceworker')
    worker.evaluate("async token=>{await chrome.storage.local.set({token});return await api('/ping');}",b.token)
    job=store.prep.compatibility.jobs.list()[0]
    b.tasks['generic']=dict(id='generic',state='WAITING',url=fixture['origin']+'/autojob-test/step1',job=job,created=time.monotonic(),rounds=0)
    worker.evaluate('run()')
    page.wait_for_function("document.querySelector('#mail').value==='alex@example.invalid'",timeout=25000)
    assert page.locator('#name').input_value()=='Alex Rivera'
    assert page.locator('#cv').evaluate('(e)=>e.files.length')==1
    assert page.locator('#unknown').input_value()==''
    deadline=time.monotonic()+15
    while b.tasks['generic']['state']!='DONE' and time.monotonic()<deadline:page.wait_for_timeout(50)
    assert b.tasks['generic']['state']=='DONE'
    page.goto(parent)
    frame=page.frame_locator('iframe')
    deadline=time.monotonic()+25
    while frame.locator('#mail').input_value()!='alex@example.invalid' and time.monotonic()<deadline:page.wait_for_timeout(100)
    assert frame.locator('#mail').input_value()=='alex@example.invalid'
    assert frame.locator('#cv').evaluate('(e)=>e.files.length')==1
    assert frame.locator('#unknown').input_value()==''
    assert not any(r['method']=='POST' for r in fixture['requests'])
   finally:ctx.close()
 finally:b.close()
