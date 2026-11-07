"""Pruebas locales: ninguna solicitud alcanza un portal externo."""
import os
from types import SimpleNamespace
from hashlib import sha256
import pytest
from autojob.config import Settings
from autojob.browser import BraveSession
from autojob.forms.greenhouse import CloudbedsProtocol,TARGET,UPLOAD,SUBMIT,PROCESSORS

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Requiere Brave local')
def test_native_multipart_cv_buffer_and_one_submission(tmp_path):
    fake=tmp_path/'fictional.pdf';fake.write_bytes(b'%PDF FAKE CV FOR LOCAL TEST ONLY')
    protocol=CloudbedsProtocol(dict(url=TARGET,processor_origins=PROCESSORS,cv_hash=sha256(fake.read_bytes()).hexdigest()),lambda:None)
    protocol.bind_cv(fake);writes=[];payloads=[]
    with BraveSession(Settings(tmp_path)) as browser:
        def route(r):
            request=r.request
            if request.method=='OPTIONS':r.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'POST','Access-Control-Allow-Headers':'content-type'});return
            payloads.append(dict(url=request.url,headers=request.headers,body=repr(request.post_data_buffer)));allowed=protocol.write(request,request.url==SUBMIT);writes.append((request.url,allowed))
            if request.url.rstrip('/')==UPLOAD and allowed:protocol.response(SimpleNamespace(url=UPLOAD,status=201,request=request))
            r.fulfill(status=201 if allowed else 403,body='LOCAL FIXTURE ONLY',headers={'Access-Control-Allow-Origin':'*'})
        browser.context.route('**/*',route);page=browser.new_page()
        page.set_content('<input type="file" id="resume"><output id="status"></output>')
        page.evaluate("""([upload,submit])=>{
          document.querySelector('#resume').onchange=async e=>{
            let fd=new FormData();fd.append('key','resume/fictional.pdf');fd.append('file',e.target.files[0]);
            let response=await fetch(upload,{method:'POST',body:fd});
            if(!response.ok){document.querySelector('#status').textContent='upload denied';return;}
            document.querySelector('#resume').remove();let sent=await fetch(submit,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_application:{resume_url:upload+'/resume/fictional.pdf'}})});
            document.querySelector('#status').textContent=sent.ok?'LOCAL VERIFIED':'denied';
          }
        }""",[UPLOAD,SUBMIT])
        assert protocol.attach_cv(page,page.locator('#resume'),fake,lambda:None);page.wait_for_function("document.querySelector('#status').textContent",timeout=8000)
        assert page.locator('#status').inner_text()=='LOCAL VERIFIED',payloads
        assert writes==[(UPLOAD+'/',True),(SUBMIT,True)]
        assert fake.read_bytes() in protocol.replacement_body

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_BRAVE', os.environ.get('AUTOJOB_TEST_BRAVE'))!='1',reason='Requiere Brave local')
def test_greenhouse_combobox_uses_exact_option_and_visible_value(tmp_path):
    p=CloudbedsProtocol(dict(url=TARGET,processor_origins=PROCESSORS,cv_hash='fixture'),lambda:None)
    with BraveSession(Settings(tmp_path)) as browser:
        browser.context.route('**/*',lambda r:r.abort())
        page=browser.new_page();page.set_content('''<div class="select__control"><input id="country" role="combobox"><button type="button" aria-label="Toggle flyout" onclick="document.querySelector('#list').hidden=false">Toggle</button><div class="select__single-value" hidden></div></div><div id="list" role="listbox" hidden><div role="option" onclick="document.querySelector('.select__single-value').hidden=false;document.querySelector('.select__single-value').textContent=this.textContent;document.querySelector('#list').hidden=true">Costa Rica +506</div><div role="option">United States +1</div></div>''')
        # La plantilla local aún no tiene selección: el div existe pero está vacío.
        page.locator('.select__single-value').evaluate('(e)=>e.remove()')
        page.locator('[role=option]').first.evaluate("e=>e.onclick=()=>{let v=document.createElement('div');v.className='select__single-value';v.textContent=e.textContent;document.querySelector('.select__control').append(v);document.querySelector('#list').hidden=true}")
        entry=dict(kind='combobox',selector='#country',semantic='phone_country_code',answer='+506',status='DERIVADA')
        assert p.fill_combobox(page,entry)['status']=='VERIFICADO'
        assert p.fill_combobox(page,dict(entry,answer='+1'))['status']=='PENDIENTE'
