from tempfile import TemporaryDirectory
from pathlib import Path
from dataclasses import replace
from contextlib import closing
import json
from autojob.auth.local import local_portal
from autojob.auth.external import ExternalAuth
from autojob.auth.permissions import scope
from autojob.auth.identity import IdentityStore,TYPES
from autojob.auth.verifications import VerificationStore
from autojob.auth.detection import inspect_auth
from autojob.profile.application_data import ApplicationData
from autojob.browser import BraveSession
from autojob.forms.guard import PreparationGuard

def run_lab(settings,simulate_human=True,root=None):
    if root is None:
        with TemporaryDirectory(prefix='autojob8b-lab-') as directory:return run_lab(settings,simulate_human,Path(directory))
    settings=replace(settings,root=Path(root),data_dir='data');data_path=settings.data_path
    data=ApplicationData(data_path);data.save({'first_name':'Test','last_name':'Candidate'},confirmed=['first_name','last_name'])
    with local_portal() as fixture:
        engine=ExternalAuth(data_path);id=engine.accounts.add('Portal ficticio 8B',fixture['origin'],'candidate@example.invalid',domain_verified=True,email_confirmed=True,allow_local=True)
        report=dict(external_accounts_created=0,applications_sent=0,identities_transmitted=0,human_intervention_simulated=simulate_human)
        try:
            engine.accounts.prepare(id);row=engine.accounts.get(id);engine.permissions.set(fixture['origin'],'REGISTRO',scope(engine.accounts,row,'REGISTRO'),True,True)
            registered=engine.run(settings,id,'REGISTRO',fixture['origin']+'/signup',local=True,fixture=fixture)
            assert registered['state']=='VERIFICACIÓN PENDIENTE',registered
            assert len(fixture['accounts'])==1;report['authorized_registration']=True
            duplicate=engine.run(settings,id,'REGISTRO',fixture['origin']+'/signup',local=True,fixture=fixture);assert 'ya existe' in duplicate['reason'];report['duplicate_prevented']=True
            fixture['accounts']['candidate@example.invalid']['verified']=True
            fixture['human_captcha']=True
            if not simulate_human:fixture['wait_seconds']=120
            if simulate_human:
                def simulated(page,task,store):
                    store.update(task,command='RESOLVER');page.locator('#human-check').click()
                fixture['on_wait']=simulated
            row=engine.accounts.get(id);engine.permissions.set(fixture['origin'],'LOGIN',scope(engine.accounts,row,'LOGIN'),True,True)
            logged=engine.run(settings,id,'LOGIN',fixture['origin']+'/login',job_id='local-auth8b',title='Empresa ficticia · Customer Support',local=True,fixture=fixture)
            if logged['state']!='ACTIVA':
                report.update(captcha_pending=True,result=logged);return report
            report['authorized_login']=True;report['captcha_resumed']=any(t['state']=='LISTA PARA CONTINUAR' for t in VerificationStore(data_path).list())
            reused=engine.run(settings,id,'LOGIN',fixture['origin']+'/protected',local=True,fixture=fixture);assert reused['state']=='ACTIVA';report['session_reused']=True
            fixture['human_captcha']=False;fixture['sessions'].clear()
            with BraveSession(settings) as browser:
                page=PreparationGuard(browser).page(fixture['origin']+'/protected');expired=inspect_auth(page,True);assert 'SESIÓN EXPIRADA' in expired['blocks'];engine.accounts.observe(id,expired);report['expiry_detected']=True
            identity=IdentityStore(data_path,Path(root)/'private-document');identity.save(TYPES[0],'1-9999-9999','Costa Rica','2035-01-01','Test Candidate',True)
            secret=identity.reveal(True)
            try:
                with closing(engine.db.connect()) as db:dump='\n'.join(db.iterdump())
                assert secret.reveal() not in dump
                path=Path(root)/'export.json';engine.accounts.export(path);assert secret.reveal() not in path.read_text(encoding='utf-8')
            finally:secret.clear()
            assert identity.resolve('Passport number')['status']=='DESCONOCIDA';report['identity_encrypted']=True;report['identity_not_in_general_export']=True;identity.delete();assert identity.summary() is None;report['identity_deleted']=True
            engine.permissions.revoke(fixture['origin'],True)
            try:engine.run(settings,id,'LOGIN',fixture['origin']+'/login',local=True,fixture=fixture)
            except ValueError:report['revocation_verified']=True
            else:raise AssertionError('Permiso revocado ignorado')
            report['no_application_post']=fixture['application_posts']==0
            return report
        finally:
            ref=engine.accounts.get(id)['credential_ref'];engine.accounts.remove(id)
            assert engine.accounts.vault.get(ref) is None;report['test_credential_deleted']=True
