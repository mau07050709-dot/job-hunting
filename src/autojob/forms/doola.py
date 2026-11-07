"""Lectura semántica de la candidatura doola revisada; no envía ni acepta avisos."""
import re
from urllib.parse import urlsplit
TARGET='https://jobs.lever.co/doola/999a0f10-0738-42f7-a9f6-5c7192e74873/apply'

def accepts(url):return urlsplit(url)._replace(query='',fragment='').geturl().rstrip('/')==TARGET

def enrich_page(document,page):
    if not accepts(document['url']):return document
    fields=[];groups={}
    for raw in document['fields']:
        host=(urlsplit(raw.get('frame_url','')).hostname or '').lower()
        if host=='hcaptcha.com' or host.endswith('.hcaptcha.com'):continue
        field=dict(raw);field['label']=re.sub(r'[✱*]','',field['label']).strip()
        if field['kind'] in {'radio','checkbox'}:
            try:
                question=page.frames[field.get('frame_index',0)].locator(field['selector']).evaluate('(e)=>e.closest(".application-question")?.querySelector(".application-label")?.innerText||""');question=re.sub(r'[✱*]','',question).strip()
            except Exception:question=''
            if not question:document['obstacles'].append(dict(type='PREGUNTA SIN CONTEXTO',evidence=field.get('name','')))
            field['group']=question
            if field['kind']=='checkbox':
                groups.setdefault(field.get('name'),[]).append(field);continue
        name=field.get('name','')
        if name=='opportunityLocationId':field['semantic']='doola_job_location'
        elif name=='location':field['semantic']='doola_location'
        elif name=='org':field['semantic']='doola_current_company'
        elif name=='resume':field.update(document='cv',required=True,label='Resume/CV')
        elif name=='cards[6c5ec2fe-1448-478a-afe3-26ad6581c041][field0]':field['semantic']='doola_years'
        elif name=='cards[6c5ec2fe-1448-478a-afe3-26ad6581c041][field2]':field['semantic']='doola_generic_crm'
        elif name=='cards[6c5ec2fe-1448-478a-afe3-26ad6581c041][field6]':field['semantic']='doola_international'
        elif name=='cards[6c5ec2fe-1448-478a-afe3-26ad6581c041][field7]':field['semantic']='doola_schedule'
        elif name=='cards[a7fdd47f-efc4-4bb8-8556-b5401eb030b1][field0]':field.update(semantic='doola_salary',label='What are your annual/yearly salary expectations in US Dollars? (Note that not providing a range will result in disqualification)')
        elif name=='cards[bd04103e-8ccb-4e40-80fa-5f4b073e07af][field0]':field['semantic']='doola_english'
        elif name=='cards[fedd5170-7cc1-4b83-908d-f0b7042d8ac1][field0]':field['semantic']='doola_region'
        fields.append(field)
    for name,options in groups.items():
        field=dict(options[0],kind='multiple',checkbox_group=True,label=options[0]['group'],group='',options=[dict(label=o['label'],value=o.get('value') or o['label'],selector=o['selector']) for o in options])
        # El valor publicado se obtiene del control nativo, no se construye con su etiqueta.
        for option in field['options']:option['value']=page.frames[field.get('frame_index',0)].locator(option['selector']).get_attribute('value') or 'on'
        if name=='cards[6c5ec2fe-1448-478a-afe3-26ad6581c041][field1]':field['semantic']='doola_channels'
        fields.append(field)
    document['fields']=fields;return document

def resolve(prep,field,context):
    from autojob.matching.engine import candidate,contains,level,LANGUAGES
    from autojob.profile.experience import calculate_experience
    semantic=field.get('semantic');profile=prep.data.profile_state();v=profile['values'];manual=profile.get('manual',[])
    def out(answer=None):return dict(answer=answer,status='DERIVADA' if answer is not None else 'DESCONOCIDA',source='Perfil y CV revisados / pregunta publicada',reason='Inferencia acotada de datos confirmados; no se completa información ausente.',automatic=False)
    if semantic=='doola_job_location':return out('Remote in Latin America') if 'country' in manual and v.get('country')=='Costa Rica' else out()
    if semantic=='doola_location':return out(', '.join(v[k] for k in ['city','country'])) if all(k in manual and v.get(k) for k in ['city','country']) else out()
    if semantic=='doola_current_company':return prep.resolve('Current company',context)
    if semantic=='doola_salary':
        answer=prep.resolve('Expected salary USD annual',context)
        # El portal pide texto con un rango anual; conservar las cantidades
        # derivadas y hacer explícitas las unidades, sin inventar otra expectativa.
        if answer.get('status') in {'CONFIRMADA','DERIVADA'} and re.fullmatch(r'\d+(?:\.\d+)?\s*[–-]\s*\d+(?:\.\d+)?',str(answer.get('answer',''))):
            low,high=re.split(r'\s*[–-]\s*',answer['answer'])
            answer=dict(answer,answer='USD '+format(float(low),',.2f')+' - USD '+format(float(high),',.2f')+' per year')
        return answer
    if semantic=='doola_region':return out('Latin America') if 'country' in manual and v.get('country')=='Costa Rica' else out()
    if semantic=='doola_schedule':
        value,status=prep.data.value('accepted_shifts');return out('Yes') if status=='CONFIRMADA' and value and ('cualquier horario' in value.lower() or 'any' in value.lower()) else out()
    if semantic=='doola_english':return out('Advanced (C1)') if 'languages' in manual and any(any(contains(text,a) for a in LANGUAGES['English']) and level(text)==5 for text in v.get('languages',[])) else out()
    if semantic=='doola_international':
        from autojob.forms.answers9b import ScopedAnswers
        return ScopedAnswers(prep.data.data_path).resolve(field['group'],context) or out()
    snap=prep.compatibility.snapshot();person=candidate(snap['profile'],snap['cvs']);facts=person['buckets']['experience']
    confirmed_skills=[f for f in person['buckets']['skills'] if f['confirmed']]
    def skill(term):return any(contains(f['text'],term) for f in confirmed_skills)
    if semantic=='doola_generic_crm':return out('Yes') if skill('CRM') or skill('Ticketing Systems') else out()
    if semantic=='doola_channels':
        answers=[]
        if skill('Inbound Calls'):answers.append('Voice/Phone')
        if skill('Email Support'):answers.append('Email')
        if skill('Live Chat'):answers.append('Chat')
        if any(f['confirmed'] and 'bartender' in str((f.get('record') or {}).get('position','')).lower() for f in facts):answers.append('In-Person')
        return out('|'.join(answers)) if answers else out()
    if semantic=='doola_years':
        from autojob.forms.answers9b import ScopedAnswers
        saved=ScopedAnswers(prep.data.data_path).resolve(field['group'],context)
        if saved and saved.get('answer') in {'0-1 year','1-3 years','3-5 years','5+ years'}:return saved
        if not facts or not all(f['confirmed'] and f.get('record') for f in facts):return out()
        calc=calculate_experience([f['record'] for f in facts]);low=calc['minimum']['days']/365.2425;high=calc['maximum']['days']/365.2425
        for lower,upper,label in [(0,1,'0-1 year'),(1,3,'1-3 years'),(3,5,'3-5 years'),(5,float('inf'),'5+ years')]:
            if low>=lower and high<upper:return out(label)
        return out()
    return out()
