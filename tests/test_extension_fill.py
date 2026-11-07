import json,os,shutil,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from autojob.config import Settings
from autojob.extension_fill import ExtensionFill

def test_bridge_auth_and_origin_scope(tmp_path,monkeypatch):
    from test_batch_https import seed
    import autojob.extension_fill as module
    seed(tmp_path);monkeypatch.setattr(module,'PORT',0)
    bridge=ExtensionFill(Settings(tmp_path));bridge.start()
    url='http://127.0.0.1:'+str(bridge.server.server_port)
    try:
        with pytest.raises(HTTPError):urlopen(Request(url+'/ping',data=b'{}',headers={'Origin':'https://evil.example','Authorization':'Bearer '+bridge.token}))
        headers={'Origin':'chrome-extension://'+'a'*32,'Authorization':'Bearer '+bridge.token,'Content-Type':'application/json'}
        assert json.load(urlopen(Request(url+'/ping',data=b'{}',headers=headers)))['ok']
        assert bridge.paired
        assert ExtensionFill(Settings(tmp_path)).paired
        bridge.tasks['x']=dict(id='x',state='FILLING',url='https://employer.example/apply',job={})
        with pytest.raises(ValueError,match='otro dominio'):bridge.handle('/plan',{'id':'x','url':'https://other.example/apply'})
    finally:bridge.close()

def test_pending_popup_and_posts_share_fill_action(tmp_path,qt_application_lifetime,await_ui,monkeypatch):
    from test_batch_https import seed
    from autojob.ui.main_window import MainWindow
    from autojob.ui.manual_results import LinksDialog
    from PySide6.QtWidgets import QPushButton
    seed(tmp_path);w=MainWindow(Settings(tmp_path));await_ui(lambda:not w._ui_tasks,30000)
    job=w.shell.engine.jobs.list()[0];row=dict(job=job,url=job['url']);seen=[]
    monkeypatch.setattr(w.shell,'fill_selected',lambda r:seen.append(r))
    d=LinksDialog(w.shell,dict(results=[],review=[row]),review_only=True)
    d.fill();assert seen==[row]
    assert any('RELLENAR' in b.text() for b in w.shell.posts.findChildren(QPushButton))
    d.close();await_ui(lambda:not w._ui_tasks,30000);w.close()

@pytest.mark.skipif(os.environ.get('JOB_HUNTING_TEST_EXTENSION', os.environ.get('AUTOJOB_TEST_EXTENSION'))!='1',reason='Prueba real de extensiÃ³n Brave optativa')
def test_actual_extension_fill_and_no_post(tmp_path,monkeypatch):
    from test_batch_https import seed
    from autojob.forms.controlled import controlled_site
    from autojob.browser.discovery import find_brave
    from playwright.sync_api import sync_playwright
    store,cv=seed(tmp_path)
    import autojob.extension_fill as module
    monkeypatch.setattr(module,'PORT',0)
    bridge=ExtensionFill(Settings(tmp_path));bridge.start()
    extension=tmp_path/'extension';shutil.copytree(Path(__file__).parents[1]/'brave-extension',extension)
    manifest=json.loads((extension/'manifest.json').read_text(encoding='utf-8'));manifest['host_permissions'].append('http://127.0.0.1/*');(extension/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    background=extension/'background.js';background.write_text(background.read_text(encoding='utf-8').replace('127.0.0.1:18746','127.0.0.1:'+str(bridge.server.server_port)),encoding='utf-8')
    wake=extension/'wake.js'
    wake.write_text(wake.read_text(encoding='utf-8').replace('127.0.0.1:18746','127.0.0.1:'+str(bridge.server.server_port)),encoding='utf-8')
    try:
        with controlled_site() as fixture,sync_playwright() as pw:
            # Datos ficticios, perfil temporal. Nunca se conecta al Brave personal.
            context=pw.chromium.launch_persistent_context(str(tmp_path/'browser'),executable_path=str(find_brave()),headless=True,ignore_default_args=['--disable-extensions'],args=['--disable-extensions-except='+str(extension),'--load-extension='+str(extension)])
            try:
                # Reproducir la carga observada en Workable: load termina antes
                # de que React muestre nombre/correo. Solo hay botones al inicio.
                def delayed_form(route):
                    response=route.fetch()
                    html=response.text().replace('</body>', '''<script>const f=document.querySelector('form');const content=f.innerHTML;f.innerHTML='<button type="button">Loading</button>';setTimeout(()=>f.innerHTML=content,1800);</script></body>''')
                    route.fulfill(response=response,body=html)
                context.route(fixture['origin']+'/autojob-test/step1',delayed_form)
                worker=context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker',timeout=20000)
                # Misma ruta de vinculaciÃ³n y sondeo que utiliza la extensiÃ³n instalada.
                worker.evaluate("async token=>{await chrome.storage.local.set({token});return await api('/ping');}",bridge.token)
                job=store.prep.compatibility.jobs.list()[0]
                bridge.tasks['local']=dict(id='local',state='WAITING',url=fixture['origin']+'/autojob-test/step1',job=job,created=time.monotonic(),rounds=0)
                worker.evaluate('run()')
                page=next(p for p in context.pages if '/autojob-test/' in p.url)
                assert page.locator('#name').input_value()=='Alex Rivera'
                assert page.locator('#mail').input_value()=='alex@example.invalid'
                assert page.locator('#next').is_visible()
                assert bridge.tasks['local']['state']=='DONE'
                assert not any(r['method']=='POST' for r in fixture['requests'])
                assert 'campos rellenados' in bridge.events.get_nowait()
                page.locator('#name').fill('CorrecciÃ³n manual conservada')
                page.evaluate("""() => {const label=document.createElement('label');label.htmlFor='unknown';label.textContent='Unknown required project code';const input=document.createElement('input');input.id='unknown';input.required=true;document.querySelector('form').append(label,input);}""")
                bridge.tasks['local2']=dict(id='local2',state='WAITING',url=fixture['origin']+'/autojob-test/step1',job=job,created=time.monotonic(),rounds=0)
                marker=worker.evaluate("async url=>(await chrome.tabs.create({url})).id", 'http://127.0.0.1:'+str(bridge.server.server_port)+module.WAKE_PATH)
                assert marker
                deadline=time.monotonic()+8
                while bridge.tasks['local2']['state']!='DONE' and time.monotonic()<deadline:
                    page.wait_for_timeout(40)
                assert bridge.tasks['local2']['state']=='DONE'
                assert not worker.evaluate("async id=>await chrome.tabs.get(id).then(()=>true,()=>false)",marker)
                assert page.locator('#name').input_value()=='CorrecciÃ³n manual conservada'
                assert page.locator('#unknown').input_value()==''
                assert len([p for p in context.pages if '/autojob-test/' in p.url])==1
                assert 'Unknown required project code' in bridge.events.get_nowait()
                # El usuario abre Apply despuÃ©s: la pestaÃ±a ya reservada debe
                # reanalizarse sin volver a pulsar RELLENAR en la aplicaciÃ³n.
                landing=fixture['origin']+'/autojob-test/landing'
                body="""<html><body><button id='apply' type='button' onclick="document.getElementById('signup').hidden=false">Apply</button><section id='signup' hidden><h1>Join Fictional Labs</h1><form method='post'><label for='resume-name'>Full name</label><input id='resume-name' required><label for='resume-email'>Email</label><input id='resume-email' type='email' required><label><input id='terms' type='checkbox' required>I agree to the Terms of Use</label><button type='submit' id='create'>Create account</button></form></section></body></html>"""
                context.route(landing,lambda route:route.fulfill(status=200,content_type='text/html',body=body))
                page.goto(landing)
                page.locator('#apply').click()
                page.wait_for_function("document.querySelector('#resume-email').value==='alex@example.invalid'",timeout=30000)
                assert page.locator('#resume-name').input_value()=='Alex Rivera'
                assert not page.locator('#terms').is_checked()
                assert page.locator('#create').is_visible()

                # BotÃ³n Apply, campos desconocidos y reanudaciÃ³n tras intervenciÃ³n local.
                # Este desafÃ­o es ficticio; el cÃ³digo de producto solo observa seÃ±ales pÃºblicas.
                flow=fixture['origin']+'/autojob-test/handoff'
                body='''<html><head><title>Fictional Labs application</title></head><body>
                <button type="button" id="open-form" onclick="document.getElementById('application').hidden=false;this.hidden=true">Apply now</button>
                <form id="application" hidden>
                  <label for="flow-name">Full name</label><input id="flow-name" required>
                  <label for="flow-unknown">Unknown required project code</label><input id="flow-unknown" required>
                  <label for="flow-email">Email</label><input id="flow-email" type="email" required>
                  <div data-fabric-component="FileUpload"><label>Resume</label><input id="flow-cv" type="file" aria-label="file-input" style="display:none"><input name="resumeFileId" type="hidden"></div>
                  <div id="manual-check" data-sitekey="local-demo">CAPTCHA simulado para intervenciÃ³n humana local.
                    <button type="button" id="local-human" onclick="document.getElementById('extra').hidden=false;document.getElementById('manual-check').remove()">He completado la verificaciÃ³n local</button>
                  </div>
                  <section id="extra" hidden><label for="flow-country">Country of residence</label><input id="flow-country" required></section>
                  <button type="submit" id="final-send">Submit application</button>
                </form></body></html>'''
                context.route(flow,lambda route:route.fulfill(status=200,content_type='text/html',body=body))
                flow_page=context.new_page()
                flow_page.goto(flow)
                deadline=time.monotonic()+35
                while worker.evaluate('busy') and time.monotonic()<deadline:
                    page.wait_for_timeout(50)
                assert not worker.evaluate('busy')
                bridge.tasks['handoff']=dict(id='handoff',state='WAITING',url=flow,job=job,created=time.monotonic(),rounds=0)
                worker.evaluate('run()')
                deadline=time.monotonic()+25
                while bridge.tasks['handoff']['state']!='DONE' and time.monotonic()<deadline:flow_page.wait_for_timeout(50)
                assert bridge.tasks['handoff']['state']=='DONE'
                flow_page=next(p for p in context.pages if p.url==flow)
                assert flow_page.locator('#flow-name').input_value()=='Alex Rivera', worker.evaluate("async()=>await chrome.storage.local.get('last')")
                assert flow_page.locator('#flow-email').input_value()=='alex@example.invalid'
                assert flow_page.locator('#flow-cv').evaluate('(e)=>e.files.length')==1
                assert flow_page.locator('#flow-unknown').input_value()==''
                assert flow_page.locator('#flow-country').input_value()==''
                assert flow_page.locator('#manual-check').is_visible()
                notices=[]
                while not bridge.notices.empty():notices.append(bridge.notices.get_nowait())
                assert any(n['id']=='handoff' and any('CAPTCHA' in x for x in n['pending']) for n in notices)
                flow_page.locator('#flow-unknown').fill('Manual value retained')
                flow_page.locator('#local-human').click()
                flow_page.wait_for_function("document.querySelector('#flow-country').value==='Costa Rica'",timeout=20000)
                assert flow_page.locator('#flow-unknown').input_value()=='Manual value retained'
                assert flow_page.locator('#final-send').is_visible()
                assert not any(r['method']=='POST' for r in fixture['requests'])
            finally:context.close()
    finally:bridge.close()


def test_employer_scope_is_specific_not_all_domains():
    from autojob.extension_fill import allowed_page
    task=dict(url='https://www.workingnomads.com/job/go/1923073/',job=dict(company='Lemon.io'))
    assert allowed_page(task,'https://lemon.io/for-developers/')
    assert allowed_page(task,'https://me.lemon.io/escape-the-matrix')
    assert not allowed_page(task,'https://accounts.google.com/')
    assert not allowed_page(task,'https://me.lemon.io.evil.example/signup')
    assert not allowed_page(dict(task,job=dict(company='Other')),'https://me.lemon.io/')
