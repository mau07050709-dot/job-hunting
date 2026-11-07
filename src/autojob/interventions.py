from contextlib import closing
from autojob.control import ControlStore
from autojob.forms.queue import ACTIVE
from autojob.auth.verifications import VerificationStore

class InterventionService:
    def __init__(self,coordinator):self.engine=coordinator;self.store=coordinator.store;self.queue=coordinator.queue
    def validate(self,row):
        from autojob.live import active
        if active(row['job_id']):return False
        if row['kind']=='REVISAR CURRÍCULUMS':return any(c.get('reviewed') for c in self.engine.compatibility.library.list())
        if row['kind']=='CARTA DE PRESENTACIÓN':
            from autojob.forms.submission_letters import SubmissionLetters
            job=next((j for j in self.engine.jobs.list() if j['id']==row['job_id']),None);evaluation=self.engine.compatibility.latest().get(row['job_id']) or {};cv=(evaluation.get('resume_selection') or {}).get('resume_id')
            return bool(job and cv and SubmissionLetters(self.store.data_path).artifact(job,cv))
        if row['verification_id']:
            verification=next((v for v in VerificationStore(self.store.data_path).list() if v['id']==row['verification_id']),None)
            if verification and verification['state']=='LISTA PARA CONTINUAR':return True
        if row['kind'] in {'INFORMACIÓN FALTANTE','DATO OBLIGATORIO PENDIENTE'}:
            # Un CV existente en SQLite no demuestra que esté adjunto en el portal.
            # El propietario de la sesión o un comprobante final resuelven este aviso.
            if row.get('message','').strip()=='Revisar campos requeridos: Resume/CV':return False
            qrow=next((r for r in self.queue.list() if r['job_id']==row['job_id']),None)
            if not qrow:return False
            payload=qrow['payload'];doc=(payload.get('stages') or [{}])[-1].get('document')
            job=next((j for j in self.engine.jobs.list() if j['id']==row['job_id']),None)
            if not doc:return False
            preview=self.queue.preparation.prepare(doc,job)
            required=[e for e in preview['entries'] if not e.get('requires_specific_consent') and (e.get('required') or e['label'] in payload.get('review_optional',[]))]
            def ready(entry):
                from autojob.forms.runner import enrich
                entry=enrich(self.queue.preparation,entry)
                import re
                if re.search(r'accept|agree|acepto|certifico|firma|signature|terms|privacy|privacidad',entry.get('label',''),re.I):return False
                if entry.get('kind')=='file':return entry.get('document')=='cv' and preview.get('cv_confirmed') and entry.get('status')=='DOCUMENTO LOCAL'
                if entry.get('sensitive_identity'):
                    from autojob.auth.permissions import Permissions
                    return entry['status']=='REQUIERE AUTORIZACIÓN' and Permissions(self.store.data_path).allowed(row['url'],'IDENTIDAD',str(entry['identity_revision'])+':'+entry['identity_field'])
                return entry['status'] in {'CONFIRMADA','DERIVADA'}
            return bool(required) and all(ready(e) for e in required) and (self.queue.preparation.inputs_hash()!=row['profile_hash'] or any(e.get('sensitive_identity') for e in required))
        if any(k in row['kind'] for k in ['LOGIN','REGISTRO','AUTENTICACIÓN','CORREO','MFA','VERIFICACIÓN']):
            from autojob.auth.service import Accounts
            from autojob.auth.permissions import Permissions,scope
            for account in Accounts(self.store.data_path).list():
                if not row['url'].startswith(account['origin']+'/') and row['url']!=account['origin']:continue
                if account['state']=='ACTIVA' and account['last_auth_at'] and account['last_auth_at']>row['created_at']:return True
                if row['kind'] in {'REQUIERE LOGIN','REQUIERE REGISTRO','AUTENTICACIÓN'} and account['domain_verified'] and account['email_confirmed'] and account['credential_ref']:
                    action='LOGIN' if account['exists_remotely'] else 'REGISTRO'
                    if Permissions(self.store.data_path).allowed(account['origin'],action,scope(Accounts(self.store.data_path),account,action)):return True
        return False
    def resume(self,id):
        row=next((r for r in self.store.interventions() if r['id']==id),None)
        if not row or row['state']=='OMITIDA' or not self.validate(row):return False,'La solución todavía no tiene evidencia suficiente. Guarda y confirma el dato o comprueba la verificación en el portal.'
        self.store.intervention_state(id,'RESUELTA');job=row['job_id']
        if job and job not in self.store.excluded():
            qrow=next((r for r in self.queue.list() if r['job_id']==job),None)
            if qrow and qrow['state'] not in ACTIVE:
                self.queue.requeue([job]);self.queue.priority(job,100000)
                with closing(self.store.db.connect()) as db,db:db.execute('UPDATE control_interventions SET resumed=1 WHERE id=?',(id,))
                return True,job
        return True,None
    def ready(self):
        jobs=[]
        for row in self.store.interventions():
            if row['state'] not in {'PENDIENTE','POSPUESTA'} or row['resumed']:continue
            if self.validate(row):
                ok,job=self.resume(row['id'])
                if ok:jobs.append(job)
        return jobs
