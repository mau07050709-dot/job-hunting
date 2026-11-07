"""Equivalencias acotadas: cada predicado exige evidencia y conserva su alcance."""
import re,json
from autojob.search.geography import normalize


def recognize(text):
    t=normalize(text).strip(' .:')
    if re.fullmatch(r'(?:ability to |capacidad para )?(?:follow established procedures|seguir procedimientos establecidos)(?: while recognizing when an issue needs escalation)?',t):return ['procedures','escalation'] if 'escalation' in t else ['procedures']
    if re.fullmatch(r'comfort(?:able)? learning product details and explaining instructions to customers',t):return ['learnability','customer_explanation']
    if re.fullmatch(r'(?:familiarity with|comfortable using|manejo de) (?:customer management systems|crm),? (?:email|correo)(?:,? and| y) (?:spreadsheets|hojas de calculo)',t):return ['crm_general','email_tools','spreadsheets']
    if re.fullmatch(r'(?:comfortable using|familiarity with|manejo de|comodidad con) (?:online tools|digital tools|herramientas (?:digitales|en linea))',t):return ['digital_tools']
    if re.fullmatch(r'(?:reliable |own |a )?computer and (?:a )?(?:reliable |stable )?internet(?: connection)?|computadora(?: propia)? e internet estable',t):return ['computer','internet']
    if re.fullmatch(r'reliable internet connection and a quiet workspace suitable for customer calls',t):return ['internet','workspace']
    if re.fullmatch(r'(?:reliable|stable) internet(?: connection)?|(?:conexion de )?internet estable',t):return ['internet']
    if re.fullmatch(r'(?:availability for|available for|disponibilidad para) (?:flexible schedules|horarios flexibles)',t):return ['flexible_schedule']
    if re.fullmatch(r'ability to work consistently from \d{1,2}(?::\d{2})?\s*[ap]m to \d{1,2}(?::\d{2})?\s*[ap]m (?:us |u\.s\. )?(?:eastern|central|pacific) time',t):return ['flexible_schedule']
    return []


def applicable_answers(profile,job):
    out=[]
    for row in profile.get('_eligibility_answers',[]):
        scope=row.get('scope');key=row.get('scope_key','')
        if scope=='job' and key!=job.get('id'):continue
        if scope=='company' and normalize(key)!=normalize(job.get('company','')):continue
        if row.get('company') and normalize(row['company'])!=normalize(job.get('company','')):continue
        conditions=row.get('conditions') or {}
        if isinstance(conditions,str):
            try:conditions=json.loads(conditions)
            except ValueError:continue
        if any(str(job.get('title' if k=='position' else k,''))!=str(v) for k,v in conditions.items() if v not in (None,'')):continue
        if row.get('confirmed') and row.get('value') not in (None,''):out.append(row)
    return out


def evidence(person,job):
    b=person['buckets'];p=person['profile'];facts=[]
    for group in b:
        for f in b[group]:facts.append(dict(f,group=group))
    for k,r in p.get('_application_data',{}).items():
        if r.get('confirmed') and r.get('value') is not None:facts.append(dict(text=str(r['value']),origin='Información adicional / '+k,confirmed=True,group='additional',key=k,value=r['value']))
    v=p.get('values',{})
    for k in ('schedule','accepted_shifts','preferred_schedule','weekends'):
        if k in p.get('manual',[]) and v.get(k) is not None and k not in p.get('conflicts',{}):facts.append(dict(text=str(v[k]),origin='Mi perfil / '+k,confirmed=True,group='additional',key=k,value=v[k]))
    for a in applicable_answers(p,job):
        facts.append(dict(text=str(a['value']),origin=a.get('origin','Respuesta aprobada')+' / '+str(a.get('id','')),confirmed=True,group='answer',question=a['question']))
    return facts


def capability(req,person,job):
    name=req['name'];facts=evidence(person,job)
    def matches(f):
        t=normalize(f['text']);q=normalize(f.get('question',''));k=f.get('key')
        patterns={
          'procedures':r'checklist|follow.{0,20}procedur|seguir.{0,20}procedimient',
          'escalation':r'escalation handling|escalat.{0,30}manager|escalamiento',
          'learnability':r'fast learner|quick learner|aprendizaje rapido',
          'customer_explanation':r'communication skills|clear bilingual support|habilidades de comunicacion|comunicacion',
          'crm_general':r'\bcrm\b|customer relationship management|customer management system',
          'email_tools':r'email support|outlook|soporte por correo',
          'spreadsheets':r'\bexcel\b|spreadsheet|hojas de calculo',
          'digital_tools':r'microsoft office|google workspace|\bcrm\b|\bexcel\b',
        }
        if name in patterns and f['group']=='answer':
            positive=normalize(f['text']).strip() in {'yes','si','true','no','false'}
            if name=='crm_general' and normalize(f['text']).strip()=='other':positive=True
            return positive and bool(re.search(patterns[name],q))
        if name in patterns:return f['group'] in {'skills','soft_skills','experience'} and bool(re.search(patterns[name],t))
        if name in {'computer','internet','workspace'}:
            expected={'computer':'own_computer','internet':'stable_internet','workspace':'private_workspace'}[name]
            return k==expected or f['group']=='answer' and bool(re.fullmatch({'computer':r'(?:do you have )?(?:your own|a) computer\??','internet':r'(?:do you have )?(?:a )?(?:stable|reliable) internet(?: connection)?\??','workspace':r'(?:do you have )?(?:a )?(?:quiet|private) workspace\??'}[name],q))
        if name=='flexible_schedule':
            return k in {'accepted_shifts','schedule'} and bool(re.search(r'cualquier horario|any (?:work )?(?:shift|schedule)|all shifts|flexible schedules?|no (?:noches|fines)|no nights|only weekdays|solo diurno',t))
        return False
    matching=[f for f in facts if matches(f) and f['confirmed']]
    def negative(f):return f.get('value') is False or bool(re.search(r'^(?:no|false)$|^(?:no|not|sin)\b|no tengo|do not have|never used|no nights|no noches|only weekdays|solo diurno',normalize(f['text'])))
    no=[f for f in matching if negative(f)];yes=[f for f in matching if not negative(f)]
    if name=='flexible_schedule':
        restrictions=[f for f in facts if f.get('key') in {'schedule','accepted_shifts'} and re.search(r'only|solo|except|excluding|unavailable|cannot|no puedo|no nights|no noches|no fines|no weekends',normalize(f['text']))]
        restrictions.extend(f for f in facts if f.get('key') in {'weekends','nights'} and f.get('value') is False and re.search('weekend|fines de semana' if f['key']=='weekends' else 'night|noches',normalize(req['evidence'])))
        no.extend(restrictions)
    state='POR VERIFICAR' if no and yes else 'NO CUMPLE' if no else 'CUMPLE' if yes else 'POR VERIFICAR'
    return dict(req,state=state,reason='Evidencia confirmada de la misma capacidad; equivalencia acotada.' if state=='CUMPLE' else 'Evidencia contradictoria; requiere revisión.' if no and yes else 'Declaración negativa confirmada.' if no else 'No hay evidencia confirmada suficiente para esta capacidad.',support=1 if state=='CUMPLE' else 0,profile_evidence=[{k:f[k] for k in ('text','origin','confirmed')} for f in (yes+no)[:8]])


def assess_with_answers(req,person,config,job,base):
    result=base(req,person,config,job)
    from autojob.profile.semantic import equivalent
    from autojob.forms.answers9b import restricted
    if restricted(req['evidence']):return result
    markers=lambda t:set(re.findall(r'\b[abc][12]\b|\b\d+(?:\.\d+)?(?=\s*(?:years?|anos))',normalize(t)))
    matches=[a for a in applicable_answers(person['profile'],job) if markers(a['question'])==markers(req['evidence']) and equivalent(a['question'],req['evidence']) and normalize(str(a['value'])).strip() in {'yes','si','true','no','false'}]
    if not matches:return result
    values={normalize(str(a['value'])).strip() not in {'no','false'} for a in matches}
    facts=result['profile_evidence']+[dict(text=str(a['value']),origin='Respuesta aprobada / '+str(a['id']),confirmed=True) for a in matches]
    conflict=len(values)>1 or (True in values and result['state']=='NO CUMPLE') or (False in values and result['state']=='CUMPLE')
    state='POR VERIFICAR' if conflict else 'CUMPLE' if True in values else 'NO CUMPLE'
    return dict(result,state=state,support=1 if state=='CUMPLE' else 0,profile_evidence=facts,reason='Fuentes confirmadas contradictorias; revisar.' if conflict else 'Respuesta aprobada equivalente con alcance y condiciones coincidentes.')
