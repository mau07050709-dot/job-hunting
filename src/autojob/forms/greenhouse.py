"""Lectura estructurada del portal elegido. No autoriza relleno, adjuntos ni envíos."""
from functools import lru_cache
import json,re,time
from urllib.request import urlopen
from autojob.profile.answers import norm

TARGET='https://job-boards.greenhouse.io/cloudbedsthirdpartyboard/jobs/4466028005'
API='https://boards-api.greenhouse.io/v1/boards/cloudbedsthirdpartyboard/jobs/4466028005?questions=true'

@lru_cache(maxsize=2)
def public_job(hour):
    with urlopen(API,timeout=15) as response:
        data=json.loads(response.read(2000000))
    if data.get('id')!=4466028005 or data.get('absolute_url','').split('?')[0]!=TARGET:raise ValueError('La oferta pública no coincide con el formulario.')
    return data

def enrich_document(document,data):
    original=document['fields'];fields=[];used=set();missing=[]
    questions=list(data['questions'])
    for q in data.get('demographic_questions',{}).get('questions',[]):
        questions.append(dict(label=q['label'],required=q['required'],fields=[dict(name='demographic_'+str(q['id']),type=q['type'],values=[dict(label=o['label'],value=o['id'],decline=o.get('decline_to_answer') is True) for o in q['answer_options']])]))
    key=lambda value:norm(value).strip(' *')
    for q in questions:
        shape=q['fields'][0];kind=shape['type'];name=shape['name'];label=q['label'].strip()
        doc_kind='cv' if name=='resume' else 'letter' if name=='cover_letter' else None
        candidates=[(i,f) for i,f in enumerate(original) if i not in used and ((doc_kind and f.get('document')==doc_kind and f['kind']=='file') or (not doc_kind and key(f['label'])==key(label) and f['kind']!='button'))]
        if len(candidates)!=1:
            if q['required']:missing.append(label)
            continue
        i,native=candidates[0];used.add(i);field=dict(native,label=label,required=q['required'],options=[dict(label=o['label'],value=str(o['value'])) for o in shape.get('values',[])],public_field_name=name)
        if name=='question_6844845005':field['semantic']='residence_country'
        if name=='question_6844844005':field['semantic']='authorization_cr'
        if name=='question_6844848005':field['semantic']='fluency_en_es'
        if name=='question_6844849005':field['semantic']='hospitality_experience'
        declines=[o['label'] for o in shape.get('values',[]) if o.get('decline') is True]
        if name.startswith('demographic_') and len(declines)==1:field.update(semantic='demographic_decline',decline_option=declines[0])
        fields.append(field)
    if missing:
        document['obstacles'].append(dict(type='FORMULARIO CAMBIADO',evidence='Preguntas públicas sin control inequívoco: '+', '.join(missing)));return document
    # Conservar acciones y campos extra etiquetados; retirar únicamente controles internos sin etiqueta del combobox.
    for i,f in enumerate(original):
        if i in used:continue
        if f['label']=='Sin etiqueta' and f['kind'] not in {'button','file'}:continue
        if key(f['label'])=='country' and f['kind']=='combobox':f=dict(f,semantic='phone_country_code')
        fields.append(f)
    document['fields']=fields;document['schema_source']=API;return document

def enrich_page(document):
    if document['url'].split('?')[0].rstrip('/')==TARGET:
        try:return enrich_document(document,public_job(int(time.time()//3600)))
        except Exception:document['obstacles'].append(dict(type='ESQUEMA NO VERIFICADO',evidence='No se pudo contrastar el formulario con las preguntas públicas del portal.'))
    return document


# Procesadores publicados por el formulario nativo, limitados a esta candidatura.
SUBMIT='https://boards.greenhouse.io/cloudbedsthirdpartyboard/jobs/4466028005'
UPLOAD='https://grnhse-prod-jben-us-east-1.s3.amazonaws.com'
PROCESSORS=['https://job-boards.greenhouse.io','https://boards.greenhouse.io',UPLOAD]

class CloudbedsProtocol:
    def __init__(self,rule,check):
        if rule.get('url')!=TARGET or rule.get('processor_origins')!=PROCESSORS:raise ValueError('Procesadores no autorizados para esta candidatura.')
        self.rule=rule;self.check=check;self.upload_phase=False;self.upload_started=False;self.upload_complete=False;self.resume_url=None;self.final_used=False;self.cv_bytes=None;self.cv_name=None;self.replacement_body=None
    def bind_cv(self,path):
        from hashlib import sha256
        data=path.read_bytes()
        if not data or len(data)>20000000 or sha256(data).hexdigest()!=self.rule['cv_hash']:raise ValueError('El documento no coincide con el CV autorizado.')
        self.cv_bytes=data;self.cv_name=path.name
    def write(self,request,final):
        from urllib.parse import urlsplit,unquote
        from hashlib import sha256
        from email.parser import BytesParser
        from email.policy import default
        self.check()
        url=request.url.rstrip('/')
        if request.method!='POST':return False
        if url==UPLOAD and self.upload_phase and not final and not self.upload_started:
            content=request.headers.get('content-type','')
            if not content.startswith('multipart/form-data;'):return False
            body=request.post_data_buffer
            if not body or len(body)>20000000:return False
            message=BytesParser(policy=default).parsebytes(('Content-Type: '+content+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
            parts=list(message.iter_parts());files=[part for part in parts if part.get_filename()]
            keys=[part.get_payload(decode=True).decode() for part in parts if part.get_param('name',header='content-disposition')=='key']
            if len(files)!=1 or len(keys)!=1:return False
            content=files[0].get_payload(decode=True)
            if not content and self.cv_bytes is not None and files[0].get_filename()==self.cv_name:
                # CDP omite los bytes de archivos multipart. Reponer únicamente el CV local autorizado,
                # conservando los campos firmados del formulario nativo; nunca permitir un archivo opaco.
                boundary=message.get_boundary().encode('ascii');chunks=[]
                for part in parts:
                    headers=part.as_bytes(policy=default.clone(linesep='\r\n')).split(b'\r\n\r\n',1)[0]
                    payload=self.cv_bytes if part is files[0] else part.get_payload(decode=True)
                    chunks.append(b'--'+boundary+b'\r\n'+headers+b'\r\n\r\n'+payload+b'\r\n')
                self.replacement_body=b''.join(chunks)+b'--'+boundary+b'--\r\n';content=self.cv_bytes
            if sha256(content).hexdigest()!=self.rule['cv_hash']:return False

            key=keys[0]
            if not key or '..' in key.split('/') or key.startswith('/') or '${' in key:return False
            self.resume_url=UPLOAD+'/'+key;self.upload_started=True;return True
        if request.url==SUBMIT and final and self.upload_complete and not self.final_used:
            try:
                data=json.loads(request.post_data or '{}');application=data['job_application']
                if unquote(application.get('resume_url') or '')!=unquote(self.resume_url or ''):return False
                # No autorizar documentos o acuerdos adicionales por el permiso ordinario del CV.
                def forbidden(value):
                    if isinstance(value,dict):
                        return any((bool(v) and re.search(r'cover_letter|attachment|consent|signature|identity|national_id',k,re.I)) or forbidden(v) for k,v in value.items())
                    if isinstance(value,list):return any(forbidden(v) for v in value)
                    return False
                if forbidden(application):return False
            except (ValueError,KeyError,TypeError):return False
            self.final_used=True;return True
        host=urlsplit(request.url).hostname
        # El SDK nativo puede evaluar el riesgo. Los desafíos interactivos siguen siendo humanos.
        return bool(final and host in {'www.google.com','www.recaptcha.net'} and urlsplit(request.url).path.startswith('/recaptcha/'))
    def response(self,response):
        if response.url.rstrip('/')==UPLOAD and response.request.method=='POST' and self.upload_started:self.upload_complete=200<=response.status<300
    def final_button(self,page):
        target=page.get_by_role('button',name='Submit application',exact=True)
        return target if target.count()==1 and target.is_visible() and target.is_enabled() else None
    def native_action(self,page):
        return page.evaluate("() => Object.values(window.__remixContext?.state?.loaderData||{}).some(v=>v?.submitPath===\""+SUBMIT+"\")")

    def fill_combobox(self,page,entry):
        if entry.get('status') not in {'CONFIRMADA','DERIVADA'} or entry.get('answer') is None:return dict(status='PENDIENTE')
        target=page.locator(entry['selector'])
        if target.count()!=1:return dict(status='PENDIENTE')
        control=target.locator('xpath=ancestor::div[contains(concat(" ",normalize-space(@class)," ")," select__control ")]')
        if control.count()!=1:return dict(status='PENDIENTE')
        value=control.locator('.select__single-value');answer=str(entry['answer']);phone=entry.get('semantic')=='phone_country_code'
        matches=lambda text:bool(re.search(r'(?<![0-9])'+re.escape(answer)+r'$',text.strip())) if phone else text.strip()==answer
        if value.count():return dict(status='VERIFICADO' if matches(value.inner_text()) else 'PENDIENTE')
        toggle=control.get_by_role('button',name='Toggle flyout',exact=True)
        if toggle.count()==1:toggle.click()
        else:target.click()
        try:page.get_by_role('option').first.wait_for(state='visible',timeout=5000)
        except Exception:return dict(status='PENDIENTE')
        options=page.get_by_role('option');labels=options.all_text_contents();indexes=[i for i,text in enumerate(labels) if matches(text)]
        if len(indexes)!=1:return dict(status='PENDIENTE')
        options.nth(indexes[0]).click()
        ok=value.count()==1 and matches(value.inner_text())
        return dict(status='VERIFICADO' if ok else 'PENDIENTE',reason='Opción nativa exacta contrastada; no se confunde el país telefónico con residencia.')

    def attach_cv(self,page,target,path,check):
        import time
        self.bind_cv(path);self.upload_phase=True
        try:
            target.set_input_files(str(path))
            deadline=time.monotonic()+15
            while not self.upload_complete and time.monotonic()<deadline:check();page.wait_for_timeout(150)
            # Greenhouse retira el input al completar la carga. Se verifica la respuesta real del
            # almacén, y el envío posterior exige que el payload nativo referencie ese mismo CV.
            return self.upload_complete
        finally:self.upload_phase=False
