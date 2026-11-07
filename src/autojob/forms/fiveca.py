"""Adaptación limitada al formulario público de 5CA y a la vacante revisada."""
from functools import lru_cache
from urllib.parse import urlsplit,parse_qs
from urllib.request import urlopen
from hashlib import sha256
import json,time
from autojob.profile.answers import norm

TARGET='https://jobs.5ca.com/jobs?gh_jid=4726900101'
API='https://boards-api.greenhouse.io/v1/boards/5ca/jobs/4726900101?questions=true'
ASSESSMENT='I consent to 5CA processing information about how I performed during the selection assessments (e.g., typing accuracy-speed, computer literacy). Without consent, I understand that 5CA cannot proceed with my application.'
PROCESSING='By sending your application, you understand that your personal data will be processed by 5CA B.V on behalf of its entities, primarily for considering your application and your suitability for the employment as per 5CA’s Privacy Policy. In case you share contact details of the reference, you confirm the reference consents to such use.'
NEWSLETTER='I agree that 5CA will collect, store, and process my personal data for sending me company-related communications (newsletter), surveys and online forms to let you know about 5CA’s recruitment-related and general activities.'
MULTIPLE={'question_7859687101[]','question_7859688101[]'}
def accepts(url):
    p=urlsplit(url);return p.scheme=='https' and p.netloc=='jobs.5ca.com' and p.path.rstrip('/')=='/jobs' and parse_qs(p.query).get('gh_jid')==['4726900101']
def key(label):return sha256(norm(label).encode()).hexdigest()
def consents():return {key(ASSESSMENT):'I consent to this',key(PROCESSING):'Yes',key(NEWSLETTER):'No'}
@lru_cache(maxsize=2)
def public_job(hour):
    with urlopen(API,timeout=15) as response:data=json.load(response)
    if data.get('id')!=4726900101 or not accepts(data.get('absolute_url','')):raise ValueError('El esquema no corresponde a la vacante revisada.')
    return data
def enrich_document(document,data):
    if not accepts(document['url']) or data.get('id')!=4726900101:raise ValueError('Formulario fuera de alcance.')
    used=set();fields=[];missing=[]
    for question in data['questions']:
        shape=question['fields'][0];name=shape['name'];label=question['label']
        candidates=[(i,f) for i,f in enumerate(document['fields']) if i not in used and f['kind']!='button' and (f.get('name')==name or norm(f['label']).strip(' *')==norm(label).strip(' *'))]
        if len(candidates)!=1:
            if question['required']:missing.append(label)
            continue
        i,f=candidates[0];used.add(i);f=dict(f,label=label,required=question['required'],public_field_name=name,options=[dict(label=o['label'],value=str(o['value'])) for o in shape.get('values',[])])
        if name=='phone':f['semantic']='phone_5ca'
        if name=='question_7859684101':f['semantic']='residence_country'
        if name=='question_7859685101':f['semantic']='residence_city_5ca'
        if name=='question_7859686101':f['semantic']='english_level_5ca'
        if name=='question_7859687101[]':f['semantic']='shifts_5ca'
        if name=='question_7859688101[]':f['semantic']='days_5ca'
        if name=='question_7859689101':f['semantic']='obligations_5ca'
        if name in {'question_7859690101','question_7859691101'}:
            if key(label) not in consents():missing.append('Texto de consentimiento cambiado')
            f.update(semantic='consent_5ca',requires_specific_consent=True)
        fields.append(f)
    for i,f in enumerate(document['fields']):
        if i in used:continue
        if f.get('name')=='data_compliance[gdpr_processing_consent_given]':
            if key(f['label'])!=key(PROCESSING):missing.append('Aviso de privacidad cambiado')
            f=dict(f,semantic='consent_5ca',requires_specific_consent=True)
        elif f['label']=='Sin etiqueta' and f['kind']=='combobox' and not f.get('name'):continue
        fields.append(f)
    if missing:document['obstacles'].append(dict(type='FORMULARIO CAMBIADO',evidence='; '.join(missing)))
    document.update(fields=fields,schema_source=API);return document
def enrich_page(document):
    if accepts(document['url']):
        try:return enrich_document(document,public_job(int(time.time()//3600)))
        except Exception:document['obstacles'].append(dict(type='ESQUEMA NO VERIFICADO',evidence='No se pudo contrastar el esquema público de 5CA.'))
    return document
def fill_consent(page,entry,rule):
    expected=consents().get(key(entry['label']))
    if expected is None or rule.get('specific_consents',{}).get(key(entry['label']))!=expected:return dict(status='PENDIENTE',reason='Falta autorización específica de este aviso.')
    target=page.locator(entry['selector'])
    if not accepts(page.url) or target.count()!=1:return dict(status='PENDIENTE')
    if entry['kind']=='checkbox':
        if not target.is_checked():
            identifier=target.get_attribute('id');label=page.locator('label[for="disabledFieldsetCheck"]')
            if identifier=='disabledFieldsetCheck' and target.get_attribute('name')=='data_compliance[gdpr_processing_consent_given]' and label.count()==1:label.click(position=dict(x=5,y=5),timeout=5000)
            else:target.set_checked(True,timeout=5000)
        valid=target.is_checked()
    elif entry['kind']=='select':
        options=[o for o in entry['options'] if o['label']==expected]
        if len(options)!=1:return dict(status='PENDIENTE')
        target.select_option(options[0]['value']);valid=target.input_value()==options[0]['value']
    else:return dict(status='PENDIENTE')
    return dict(status='VERIFICADO' if valid else 'PENDIENTE',reason='Permiso expreso vinculado al texto exacto; comunicaciones generales rechazadas.')
def fill_multiple(page,entry):
    if entry.get('status') not in {'CONFIRMADA','DERIVADA'} or entry.get('public_field_name') not in MULTIPLE:return dict(status='PENDIENTE')
    labels=[s.strip() for s in str(entry['answer']).split('|')];options=[o for o in entry['options'] if o['label'] in labels]
    if len(options)!=len(set(labels)) or len(labels)>1 and any(s.startswith('Any shift') or s.startswith('I can work on any day') for s in labels):return dict(status='PENDIENTE',reason='Selección ambigua o no publicada.')
    target=page.locator(entry['selector']);parent=target.locator('..');menu=parent.locator('.ms-options-wrap');button=menu.locator(':scope > button')
    if target.count()!=1 or target.get_attribute('name')!=entry['public_field_name'] or button.count()!=1:return dict(status='PENDIENTE')
    # El HTML publica botones de desplegable sin type. Solo estos dos controles conocidos
    # se normalizan como botones de presentación; el envío sigue protegido en DOM y red.
    button.evaluate('(e)=>e.type="button"');button.click();wanted={o['value'] for o in options};boxes=menu.locator('input[type=checkbox]')
    for checkbox in boxes.all():checkbox.set_checked(checkbox.get_attribute('value') in wanted)
    selected=set(target.evaluate('(e)=>Array.from(e.selectedOptions).map(o=>o.value)'))
    if menu.locator('.ms-options').is_visible():button.click()
    return dict(status='VERIFICADO' if selected==wanted else 'PENDIENTE',reason='Opciones visibles seleccionadas y contrastadas con el valor nativo.')


def fill_phone(page,entry):
    """Usar el selector de país y el evento real que calcula full_phone, sin escribir ocultos."""
    import phonenumbers
    if not accepts(page.url) or entry.get('status') not in {'CONFIRMADA','DERIVADA'}:return dict(status='PENDIENTE')
    try:
        number=phonenumbers.parse(str(entry['answer']),None)
        if not phonenumbers.is_valid_number(number):return dict(status='PENDIENTE')
        country=phonenumbers.region_code_for_number(number)
        if not country:return dict(status='PENDIENTE')
        target=page.locator(entry['selector']);container=target.locator('..');flag=container.locator('.iti__selected-flag')
        if target.count()!=1 or flag.count()!=1:return dict(status='PENDIENTE',reason='Selector telefónico no reconocido.')
        flag.click();option=container.locator('.iti__country[data-country-code="'+country.lower()+'"]')
        if option.count()!=1:return dict(status='PENDIENTE')
        option.click();target.fill(phonenumbers.national_significant_number(number));target.press('End')
        hidden=page.locator('input[name=full_phone]')
        actual=phonenumbers.parse(hidden.input_value(),None) if hidden.count()==1 else None
        valid=actual is not None and phonenumbers.format_number(actual,phonenumbers.PhoneNumberFormat.E164)==phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.E164)
        return dict(status='VERIFICADO' if valid else 'PENDIENTE',reason='Teléfono visible, país telefónico y valor real de envío contrastados sin modificar campos ocultos.')
    except Exception:return dict(status='PENDIENTE',reason='No se pudo verificar el teléfono que enviaría el portal.')
