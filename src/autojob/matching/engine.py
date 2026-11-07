"""Evaluación local conservadora: puntuación heurística, evidencia y bloqueos separados."""
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from functools import lru_cache
import json,re
from autojob.search.geography import normalize,classify
from autojob.profile.experience import calculate_experience

VERSION='JM-EVIDENCE.4'
WEIGHTS={'skills':30,'experience':25,'education':15,'languages':10,'role':10,'preferences':10}
ALIASES={
 'customer_service':['Customer Service','Customer Support','Consumer Support','Customer Care','Call Center','Bilingual Support','Soporte al Cliente','Atención al cliente','Servicio al cliente'],
 'it_support':['Help Desk','IT Support','Soporte técnico','Technical Support','Service Desk'],
 'python':['Python','Python Programming','Python Development'],
 'qa':['Quality Assurance','QA Testing','QA Tester'],
 'communication':['Communication Skills','Habilidades de comunicación','Communication','Comunicación'],
 'teamwork':['Teamwork','Trabajo en equipo'], 'problem_solving':['Problem-Solving','Problem Solving','Resolución de problemas'],
 'attention_detail':['Attention to Detail','Atención al detalle'], 'active_listening':['Active Listening','Escucha activa'],
 'time_management':['Time Management','Gestión del tiempo'],
 'excel':['Microsoft Excel','Excel'],'office':['Microsoft Office','Office 365','Microsoft 365'],
 'crm':['CRM','Customer Relationship Management'],'salesforce':['Salesforce'],'zendesk':['Zendesk'],
 'ticketing':['Ticketing Systems','Ticketing'],'chat_support':['Chat Support','Live Chat'],'email_support':['Email Support','Soporte por correo'],
 'back_office':['Back Office'],'data_entry':['Data Entry','Digitación'],'troubleshooting':['Troubleshooting','Resolución de fallas','Diagnóstico de Fallas'],
 'electronics':['Electronics','Electronic Engineering','Electronics Technician','Ingeniería electrónica','Circuit Analysis','Análisis de Circuitos','Ingeniería Electrónica','Diseño y Prototipado de Circuitos Electrónicos'],
 'software':['Software Developer','Software Engineer','Software Development','Programador','Desarrollador de software'],
 'javascript':['JavaScript'],'typescript':['TypeScript'],'java':['Java'],'sql':['SQL'],'html':['HTML'],'css':['CSS'],
 'django':['Django'],'flask':['Flask'],'fastapi':['FastAPI'],'react':['React'],'git':['Git'],'linux':['Linux'],
 'aws':['AWS','Amazon Web Services'],'azure':['Azure'],'docker':['Docker'],'kubernetes':['Kubernetes'],
 'cpp':['C++'],'csharp':['C#'],'dotnet':['.NET'],'sap':['SAP'],'powerbi':['Power BI'],'autocad':['AutoCAD'],
}
SOFT={'communication','teamwork','problem_solving','attention_detail','active_listening','time_management'}
CERTIFICATES=['CompTIA A+','CompTIA Security+','CCNA','CCNP','PMP','CISSP','CPA','AWS Certified','licencia profesional','professional license']
DISCIPLINES={'computer_science':['computer science','ciencias de la computación','software engineering'],'electronics':['electronic engineering','electrical engineering','ingeniería electrónica'],'industrial':['industrial engineering','ingeniería industrial'],'accounting':['accounting','contabilidad'],'medicine':['medicine','nursing','medicina','enfermería'],'business':['business administration','business management','administración de empresas'],'finance':['finance','economics','finanzas']}
LANGUAGES={'English':['English','Inglés'],'Spanish':['Spanish','Español'],'Portuguese':['Portuguese','Portugués'],'French':['French','Francés'],'German':['German','Alemán']}
LANGUAGES.update({'Czech':['Czech','Checo'],'Arabic':['Arabic','Árabe'],'Italian':['Italian','Italiano'],'Dutch':['Dutch','Neerlandés'],'Japanese':['Japanese','Japonés'],'Chinese':['Chinese','Mandarin','Chino']})
DEFAULT={'weights':WEIGHTS,'aliases':ALIASES,'certificates':CERTIFICATES,'eligible_score':60}

def digest(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
@lru_cache(maxsize=4096)
def normalized(text):return normalize(text)
@lru_cache(maxsize=2048)
def expression(term):return re.compile(r'(?<![\w])'+re.escape(normalize(term))+r'(?![\w])')
def contains(text,term):return expression(term).search(normalized(text)) is not None
@lru_cache(maxsize=16)
def alias_patterns(aliases):return [(key,re.compile(r'(?<![\w])(?:'+'|'.join(re.escape(normalize(t)) for t in terms)+r')(?![\w])')) for key,terms in aliases]
@lru_cache(maxsize=8192)
def cached_concepts(text,aliases):
 plain=normalized(text);return tuple(key for key,pattern in alias_patterns(aliases) if pattern.search(plain))
def concepts(text,config):return list(cached_concepts(text,tuple((key,tuple(terms)) for key,terms in config['aliases'].items())))
def denied(text,terms):
 terms='|'.join(re.escape(normalize(term)) for term in terms)
 return bool(re.search(r'(?:(?:no tengo|no poseo|no cuento con|no domino|no hablo|sin experiencia en|do not have|don.t have|not certified in|never used)[^.;\n]{0,55}|(?:no|not)\s+)(?:'+terms+r')(?!\w)',normalize(text)))
def family(text):
 if any(contains(text,t) for t in ('software','developer','programador','python','programming')):return 'programming'
 if any(contains(text,t) for t in ('customer','customers','consumer support','cliente','call center','bilingual support','gaming support','player support','soporte al cliente','chat support','email support','back office','virtual assistant')):return 'customer_service'
 if any(contains(text,t) for t in ('IT support','help desk','service desk','technical support','soporte técnico')):return 'it_support'
 if any(contains(text,t) for t in ('electronics','electronic','electrónica','technician','engineering','ingeniería')):return 'electronics'
 if any(contains(text,t) for t in ('QA','quality assurance','tester')):return 'qa'
 if re.search(r"\b(?:cajer[oa]s?|dependiente|operador(?:a)? de tienda|operador tienda|auxiliar tienda|gasolinera|despachador(?:a)? de (?:combustible|gas)|pistero|operador de pista|recepcionista|front desk)\b",normalize(text)):return 'customer_service'
 return None

def level(text):
 match=re.search(r'\b([abc][12])\+?\b',normalize(text))
 if match:return {'a1':1,'a2':2,'b1':3,'b2':4,'c1':5,'c2':6}[match[1]]
 if re.search(r'\bnative|nativo|nativa\b',normalize(text)):return 6
 if re.search(r'\bfluent|fluency|fluidez|avanzado|advanced\b',normalize(text)):return 5
 if re.search(r'\bintermediate|intermedio\b',normalize(text)):return 3
 if re.search(r'\bbasic|basico\b',normalize(text)):return 1
 return None

def source_text(job):
 from html import unescape
 raw=(job.get('raw') or {}).get('description')
 if isinstance(raw,str):raw=unescape(raw)
 if not isinstance(raw,str) or not re.search(r'<(?:p|div|li|h[1-6]|br)\b',raw,re.I):return job.get('description') or ''
 from lxml import etree
 tree=etree.HTML(unescape(raw.replace('\\n','\n').replace('\\"','"')))
 if tree is None:return job.get('description') or ''
 parts=[];blocks={'p','div','li','h1','h2','h3','h4','h5','h6','br','ul','ol','section'}
 for element in tree.xpath('//script|//style'):element.getparent().remove(element)
 for event,node in etree.iterwalk(tree,events=('start','end')):
  if event=='start':
   if node.tag in blocks:parts.append('\n')
   if node.text:parts.append(node.text)
  else:
   if node.tag in blocks:parts.append('\n')
   if node.tail:parts.append(node.tail)
 return ''.join(parts)

def extract(job,config):
 text=source_text(job)
 text=text.replace('\\n','\n')
 text=re.sub(r'\bU\.S\.(?=\s)', 'US',text,flags=re.I)
 text=re.sub(r',\s*(?=(?:preferred|ideally|deseable|however)\b)','\n',text,flags=re.I)
 # Los marcadores conservan el alcance de secciones que los feeds convierten en texto plano.
 text=re.sub(r'(?i)\b(nice to have|preferred qualifications|minimum qualifications|requirements|qualifications|responsibilities|what you will do|requisitos|deseables?|responsabilidades|beneficios)\s*:',r'\n\1:\n',text)
 text=re.sub(r'(A smartphone[^\n]*at least:)\s*\n+(Android[^\n]*)\s*\n+(Apple iOS[^\n]*)',r'\1 \2 / \3',text,flags=re.I)
 clauses=re.split(r'\n+|(?<=[.!?])\s+|[;•●]',text)
 result=[];seen=set();section='AMBIGUO'
 def add(kind,name,evidence,importance,**extra):
  key=(kind,name,normalize(evidence))
  if key not in seen:
   seen.add(key);result.append(dict(kind=kind,name=name,evidence=evidence.strip(),importance=importance,source=job.get('url'),**extra))
 for clause in clauses:
  clause=clause.strip(' \t-*');plain=normalize(clause).casefold()
  if not clause or not re.search(r'\w',clause):continue
  if re.fullmatch(r'#li[-_][a-z0-9_-]+',plain):continue
  if len(clause)<90 and re.fullmatch(r'(?:nice[- ]to[- ]have|preferred qualifications|bonus qualifications|preferred|desirable|deseables?|what we would love to see|bonus points)\s*:?',plain):section='DESEABLE';continue
  if len(clause)<140 and re.match(r'^(?:requirements for|qualifications for|requisitos para)\b',plain):section='OBLIGATORIO';continue
  if len(clause)<90 and re.fullmatch(r'(?:requirements|must[- ]have|essential qualifications|required qualifications|minimum requirements|requisitos obligatorios|minimum qualifications|technical requirements|about you|skills and qualifications|required experience (?:&|and) skills|qualifications|required|what we need from you|what we are looking for|what you bring|what sets you up for success|your qualifications|requisitos|your skills and experience)\s*:?',plain):section='OBLIGATORIO';continue
  if re.fullmatch(r'(?:responsibilities|key responsibilities|your responsibilities|what you will do|what you.ll do|your role|about the role|responsabilidades|your responsibilities will include|about this role)\s*:?',plain):section='RESPONSABILIDAD';continue
  if re.fullmatch(r'(?:benefits|beneficios|what we offer|about us|about the company|compensation|discover our benefits|work authorization|what to expect.*|everyone is welcome.*|equal opportunity|why join us|about boston scientific|our commitment|who we are)\s*:?',plain):section='AMBIGUO';continue
  if re.search(r'numero\s*de (?:la )?requisicion|requisition (?:number|id)',plain):section='AMBIGUO';continue
  importance='DESEABLE' if re.search(r'prefer(?:red|ably)|advantage(?:ous)?|nice.to.have|bonus|deseable|idealmente|plus\b',plain) else 'OBLIGATORIO' if re.search(r'\b(?:must|require[ds]?|requerid[oa]|mandatory|indispensable|obligatori[oa]|minimum|minimo|at least|al menos|exige|requiere)\b',plain) else section if section!='RESPONSABILIDAD' else 'AMBIGUO'
  if re.search(r'not required|no (?:es )?obligatorio|no se requiere',plain):importance='DESEABLE'
  found=False
  def item(kind,name,**extra):
   nonlocal found
   found=True;add(kind,name,clause,importance,**extra)
  from autojob.matching.semantics import recognize
  for capability in recognize(clause):item('capability',capability)
  if re.fullmatch(r'skill with computers and systems',plain):item('skill','office')
  for concept in concepts(clause,config):item('soft_skill' if concept in SOFT else 'skill',concept)
  language_alternative=bool(re.search(r'spanish\s+and/or\s+portuguese',plain))
  for language,aliases in LANGUAGES.items():
   if language_alternative and language=='Portuguese':continue
   if any(contains(clause,a) for a in aliases):
    if re.search(r'(?:submit|send|provide|enviar|presentar)[^.!?]{0,35}\b(?:cv|resume|curriculum)',plain):
     item('document','cv_language_'+language);continue
    # Nivel asociado a su idioma, evitando trasladar C1 de otro idioma.
    matches=[re.search(re.escape(normalize(a)),plain) for a in aliases];m=next(m for m in matches if m)
    segment=re.split(r'\b(?:'+'|'.join(re.escape(normalize(alias)) for aliases_ in LANGUAGES.values() for alias in aliases_)+r')\b',plain[m.end():],maxsplit=1)[0]
    before=plain[max(0,m.start()-25):m.start()]
    item('language',language,alternative_languages=['Spanish','Portuguese'] if language_alternative and language=='Spanish' else [],level=level(segment[:90]) or level(before),qualitative=bool(re.search(r'fluent|fluency|native|nativo|fluidez',segment[:90]+' '+before)),explicit_cefr=bool(re.search(r'\b[abc][12]\b',segment[:90]+' '+before)))
  years=re.search(r'\b(\d+(?:\.\d+)?)\s*(?:[-–]\s*\d+)?\+?\s*(?:years?|anos)\b[^.!?]{0,90}(?:experience|experiencia)',plain)
  if not years:years=re.search(r'(?:experience|experiencia)[^.!?]{0,35}\b(\d+)\+?\s*(?:years?|anos)',plain)
  if years:item('experience','professional_years',years=float(years[1]),domain=family(clause) or family(job.get('title','')),professional=True,technologies=[c for c in concepts(clause,config) if c not in SOFT|{'customer_service','it_support','software','electronics','qa','communication'}],sector=next((sector for sector in ['healthcare','medical billing','regulatory affairs','forex','clinical','fintech','cold calling','b2b sales','sales development','SDR','sales','accounting','payroll','bookkeeping','finance','marketing','recruitment','legal','logistics','maintenance','mantenimiento','call center','call centre','centro de llamadas','technical customer support','technical support','SaaS'] if contains(clause,sector)),None),alternative=bool(re.search(r'\bor\b|\bo\b',plain)))
  if not years and re.search(r'\b(?:experience (?:providing|handling|assisting|in|with)|background in|previous experience assisting|experiencia(?: previa)? (?:en|atendiendo))\b',plain):
   area='it_support' if re.search(r'technical (?:customer )?support|soporte tecnico',plain) else family(clause) or ('customer_service' if re.search(r'clients|clientes|customer inquiries',plain) else family(job.get('title','')))
   item('experience','relevant_experience',years=None,domain=area,professional=True,technologies=[c for c in concepts(clause,config) if c not in SOFT|{'customer_service','it_support','software','electronics','qa'}],sector=next((s for s in ['healthcare','clinical','SaaS','fintech','sales'] if contains(clause,s)),None),alternative=False)
  if years and re.search(r'front.of.house.*(?:hotel|resort)|(?:hotel|resort).*front.of.house',plain):
   for requirement in result:
    if requirement['kind']=='experience' and requirement['evidence']==clause:requirement['sector']='front_of_house_hospitality'
  if re.search(r'\bbachelor|\bdegree\b|licenciatura|titulo universitario|high school|secundaria|educacion media|tecnico medio|nivel tecnico',plain) or re.search(r'\b(?:university|universidad)\b',plain) and (section in {'OBLIGATORIO','DESEABLE'} or re.search(r'enrolled|student|estudiante|cursando',plain)):
   academic='student' if re.search(r'enrolled|in progress|estudiante|cursando|pursuing',plain) else 'secondary' if re.search(r'high school|secundaria|educacion media|tecnico medio',plain) else 'technical' if 'nivel tecnico' in plain else 'degree'
   item('education',academic,disciplines=[key for key,aliases in DISCIPLINES.items() if any(contains(clause,a) for a in aliases)],alternative=bool(re.search(r'or equivalent|o experiencia equivalente|or.*experience|equivalent.*experience',plain)))
  for certificate in config['certificates']:
   if contains(clause,certificate):item('certification',certificate)
  if re.search(r'work (?:authorization|authorisation|permit)|permiso de trabajo|visa sponsorship|authorized to work|provide sponsorship for work visas',plain):item('authorization','country_specific_authorization')
  if re.search(r'must (?:reside|be located)|residency required|residir en|residencia obligatoria|us.only',plain):item('residence','residency')
  if re.search(r'\b(?:night shift|weekends|weekend|turno nocturno|fines de semana)\b',plain):item('schedule','availability')
  if section=='RESPONSABILIDAD':add('responsibility','duties',clause,'AMBIGUO')
  # Texto obligatorio no interpretado bloquea la autorización, sin inventar un juicio.
  if importance=='OBLIGATORIO' and not found:add('other','uninterpreted',clause,importance)
 return result

def candidate(profile,cvs):
 buckets={key:[] for key in ('skills','soft_skills','languages','certifications','education','experience','positions','projects')}
 values=profile.get('values',{});manual=set(profile.get('manual',[]));conflicts=profile.get('conflicts',{})
 def confirmed(key):return key in manual or bool(profile.get('sources',{}).get(key)) and all(s.get('rank',0)>=2 or s.get('status')=='CV revisado' for s in profile.get('sources',{}).get(key,[]))
 def add(bucket,text,origin,verified=False,record=None):
  verified=verified or (origin,digest(str(text))) in {tuple(v) for v in profile.get('_review_confirmed',[])}
  if text and normalize(str(text)).strip() not in {'si','yes','no','unknown','desconocido'}:buckets[bucket].append(dict(text=str(text),origin=origin,confirmed=verified,record=record))
 mapping={'skills':'skills','programming_languages':'skills','soft_skills':'soft_skills','languages':'languages','certifications':'certifications','positions':'positions','responsibilities':'positions','education_records':'education','qualifications':'education','academic_status':'education','degree':'education'}
 for key,bucket in mapping.items():
  if key in conflicts:continue
  data=values.get(key);entries=data if isinstance(data,list) else [data]
  for entry in entries:add(bucket,entry,'Mi perfil / '+key,confirmed(key))
 # Las correcciones manuales del perfil sustituyen el grupo de datos importado.
 for cv in cvs:
  for key,target in [('technical_skills','skills'),('programming_languages','skills'),('languages','languages'),('certifications','certifications')]:
   pk='skills' if key=='technical_skills' else key
   if pk in manual or pk in conflicts:continue
   for entry in cv.get('fields',{}).get(key,[]):add(target,entry,'CV '+cv['id']+' / '+key,bool(cv.get('reviewed') or key in cv.get('manual_fields',[])))
  from autojob.profile.soft_skills import extract_soft_skills
  if 'soft_skills' not in manual:
   for entry in cv.get('fields',{}).get('soft_skills',extract_soft_skills(cv.get('source_units',[]))):add('soft_skills',entry,'CV '+cv['id']+' / soft_skills',bool(cv.get('reviewed')))
  for group,target,pk in [('experience','experience','experience_records'),('education','education','education_records'),('academic_projects','projects','academic_projects')]:
   if pk in manual:continue
   for row in cv.get('structure',{}).get(group,[]):
    text=' | '.join(str(row.get(k) or '') for k in ('company','position','institution','degree','academic_status','name','description','technologies','responsibilities'))
    origin='CV '+cv['id']+' / '+group+' / '+str(row.get('id'))
    from autojob.profile.review import fact_text
    reviewed_record=(origin,digest(fact_text(row))) in {tuple(x) for x in profile.get('_review_confirmed',[])}
    add(target,text,origin,bool(cv.get('reviewed') or row.get('origin')=='manual' or reviewed_record),row)
 for entry in values.get('experience_records',[]):
  parts=entry.split('|',4)
  row=dict(zip(('company','position','start_date','end_date','description'),[p.strip() for p in parts])) if len(parts)>=4 else None
  add('experience',entry,'Mi perfil / experience_records',confirmed('experience_records'),row)
 # No sumar dos veces los mismos períodos de CV y perfil.
 unique={}
 for fact in buckets['experience']:
  row=fact.get('record')
  marker=tuple(normalize(str(row.get(k) or '')) for k in ('company','position','start_date','end_date')) if row else (normalize(fact['text']),)
  if marker not in unique or fact['confirmed']:unique[marker]=fact
 buckets['experience']=list(unique.values())
 return dict(buckets=buckets,profile=profile)

def assess(req,person,config,job):
 b=person['buckets'];values=person['profile'].get('values',{});manual=person['profile'].get('manual',[])
 def out(state,reason,facts=(),support=None):
  if not facts and state=='CUMPLE':facts=(job.get('_requirement_answer_facts') or {}).get(digest(req['evidence']),())
  return dict(req,state=state,reason=reason,support=(1 if state=='CUMPLE' else 0) if support is None else support,profile_evidence=[{'text':f['text'],'origin':f['origin'],'confirmed':f['confirmed']} for f in facts])
 kind=req['kind'];name=req['name']
 if kind=='capability':
  from autojob.matching.semantics import capability
  return capability(req,person,job)
 def lodging_operations(fact):
  record=fact.get('record') or {};company=normalize(record.get('company') or '');position=normalize(record.get('position') or '')
  return bool(re.search(r'hotel|resort|cabanas|cabins|lodge',company) and re.search(r'front.desk|guest|night.audit|reserv|reception|recepcion|customer.*operations',position))
 if kind=='other' and re.search(r'food.*beverage.only experience does not meet',normalize(req['evidence'])):
  evidence=[f for f in b['experience'] if f['confirmed'] and lodging_operations(f)]
  if evidence:return out('CUMPLE','Existe experiencia confirmada de operaciones y atención a huéspedes en alojamiento, adicional a alimentos y bebidas.',evidence)

 # Correspondencias acotadas con evidencia ya revisada; no se añaden hechos al perfil.
 if kind=='other':
  text=normalize(req['evidence']);sources=[]
  if text=='ability to stay organized and meet deadlines in a dynamic, often ambiguous environment':sources=[f for key in ['skills','soft_skills'] for f in b[key] if f['confirmed'] and contains(f['text'],'Time Management')]
  elif text=='comfortable handling multiple conversations or tasks simultaneously':sources=[f for key in ['skills','soft_skills'] for f in b[key] if f['confirmed'] and contains(f['text'],'Multitasking')]
  elif text=='self-starter with a strong sense of ownership and follow-through':sources=[f for f in b['experience'] if f['confirmed'] and re.search(r'proactive follow.up',normalize((f.get('record') or {}).get('description') or ''))]
  if sources:return out('CUMPLE','Capacidad respaldada por habilidades o responsabilidades expresas y revisadas; se conserva su fuente original.',sources[:3])
 attested=(job.get('_requirement_answers') or {}).get(digest(req['evidence']))
 if kind=='other' and attested in {'Yes','No'}:
  return out('CUMPLE' if attested=='Yes' else 'NO CUMPLE','Declaración confirmada por el usuario para este requisito y vacante; no modifica el CV.')
 if kind in {'skill','soft_skill'}:
  facts=[f for key in ('skills','soft_skills','projects','experience') for f in b[key] if name in concepts(f['text'],config)]
  negatives=[f for f in facts if denied(f['text'],config['aliases'][name])]
  if negatives:return out('NO CUMPLE' if any(f['confirmed'] for f in negatives) and not any(f['confirmed'] and f not in negatives for f in facts) else 'POR VERIFICAR','Declaración negativa o evidencia contradictoria: no acredita esta competencia.',facts[:4],0)
  return out('CUMPLE' if any(f['confirmed'] for f in facts) else 'POR VERIFICAR','Competencia documentada'+(' y confirmada' if any(f['confirmed'] for f in facts) else ' sin confirmar') if facts else 'NO VERIFICADA: no consta esta competencia; no significa que no la posea.',facts[:4],1 if any(f['confirmed'] for f in facts) else 1 if facts else 0)
 if kind=='language':
  if req.get('alternative_languages'):
   alternatives=[assess(dict(req,name=language,alternative_languages=[]),person,config,job) for language in req['alternative_languages']]
   best=next((a for a in alternatives if a['state']=='CUMPLE'),None)
   return out('CUMPLE' if best else 'POR VERIFICAR','La oferta admite Spanish and/or Portuguese; se contrasta una alternativa sin atribuir el otro idioma.',[f for language in req['alternative_languages'] for f in b['languages'] if any(contains(f['text'],alias) for alias in LANGUAGES[language])],1 if best else 0)
  facts=[f for f in b['languages'] if any(contains(f['text'],a) for a in LANGUAGES[name])]
  negatives=[f for f in facts if denied(f['text'],LANGUAGES[name])]
  if negatives:return out('NO CUMPLE' if any(f['confirmed'] for f in negatives) and not any(f['confirmed'] and f not in negatives for f in facts) else 'POR VERIFICAR','Declaración negativa o contradictoria sobre el idioma.',facts,0)
  verified=[f for f in facts if f['confirmed']];levels=[level(f['text']) for f in verified if level(f['text'])]
  if req.get('qualitative') and not req.get('explicit_cefr'):
   if any((level(f['text']) or 0)>=5 for f in verified):return out('CUMPLE','Dominio confirmado compatible con la fluidez solicitada; no se exige ser nativo.',verified)
   if attested in {'Yes','No'}:return out('CUMPLE' if attested=='Yes' else 'NO CUMPLE','Fluidez declarada expresamente para esta vacante; no cambia el nivel CEFR guardado.',verified)
   return out('POR VERIFICAR','La fluidez publicada no equivale a un certificado C1: confirma la capacidad, sin cambiar el nivel B2+ documentado.',facts,0)
  if req.get('level') and levels and max(levels)<req['level']:return out('NO CUMPLE','Nivel confirmado inferior al requerido.',verified)
  enough=bool(verified) and (not req.get('level') or bool(levels) and min(levels)>=req['level'])
  provisional=any(not req.get('level') or (level(f['text']) or 0)>=req['level'] for f in facts)
  return out('CUMPLE' if enough else 'POR VERIFICAR','Idioma y nivel contrastados.' if enough else 'Falta confirmar idioma/nivel solicitado.',facts,1 if enough else 1 if provisional else 0)
 if kind=='certification':
  facts=[f for f in b['certifications'] if contains(f['text'],name)]
  negatives=[f for f in facts if denied(f['text'],[name])]
  if negatives:return out('NO CUMPLE' if any(f['confirmed'] for f in negatives) and not any(f['confirmed'] and f not in negatives for f in facts) else 'POR VERIFICAR','Declaración negativa o contradictoria sobre la certificación; no se acredita.',facts,0)
  return out('CUMPLE' if any(f['confirmed'] for f in facts) else 'POR VERIFICAR','La certificación requiere acreditación específica; conocimientos relacionados no la sustituyen.',facts,1 if any(f['confirmed'] for f in facts) else 1 if facts else 0)
 if kind=='education':
  facts=b['education'];verified=[f for f in facts if f['confirmed']];text=' '.join(f['text'] for f in verified);plain=normalize(text)
  progress_pattern=r'in progress|pursuing|cursando|estudiante|en curso|not completed|sin completar|sin finalizar|incomplet'
  completion_pattern=r'completed|graduated|concluido|finalizad|obtenido|graduado'
  degree_pattern=r'bachelor|licenciatura|titulo universitario|degree|ingenier'
  negatives=[f for f in verified if denied(f['text'],['bachelor','degree','licenciatura','título universitario'])]
  if name=='degree' and negatives:return out('NO CUMPLE' if not any(f not in negatives and re.search(degree_pattern,normalize(f['text'])) for f in verified) else 'POR VERIFICAR','Declaración negativa o contradictoria sobre título universitario.',verified[:5],0)
  progress=bool(re.search(progress_pattern,plain))
  # La secundaria terminada no completa una carrera universitaria en curso.
  degree_facts=[f for f in verified if re.search(degree_pattern,normalize(f['text']))]
  completed_facts=[f for f in degree_facts if not re.search(progress_pattern,normalize(f['text'])) and (re.search(completion_pattern,normalize(f['text'])) or f['origin']=='Mi perfil / qualifications')]
  completed=bool(completed_facts)
  if req.get('alternative'):return out('POR VERIFICAR','Se admite formación o experiencia equivalente; requiere revisar la alternativa publicada.',facts[:5])
  if req.get('disciplines') and not any(any(contains(f['text'],alias) for key in req['disciplines'] for alias in DISCIPLINES[key]) for f in verified):
   documented_matching=[f for f in facts if any(contains(f['text'],alias) for key in req['disciplines'] for alias in DISCIPLINES[key])]
   supported=(name=='student' and bool(documented_matching) and any(re.search(progress_pattern,normalize(f['text'])) for f in facts)) or (name=='degree' and any(not re.search(progress_pattern,normalize(f['text'])) and (re.search(completion_pattern,normalize(f['text'])) or f['origin']=='Mi perfil / qualifications') for f in documented_matching))
   return out('POR VERIFICAR','Disciplina documentada pendiente de confirmar o equivalencia académica sin acreditar.',facts[:5],1 if supported else 0)
  if name=='degree' and progress and not completed:return out('NO CUMPLE','La formación universitaria confirmada está en curso; no acredita título finalizado.',verified[:5])
  has_degree=bool(degree_facts)
  has_secondary=bool(re.search(r'high school|secundaria|bachillerato',plain))
  ok=(name=='student' and progress) or (name=='degree' and completed and has_degree) or (name=='secondary' and (has_secondary or completed and has_degree))
  documented=' '.join(f['text'] for f in facts)
  documented_progress=bool(re.search(progress_pattern,normalize(documented)))
  documented_secondary=bool(re.search(r'high school|secundaria|bachillerato',normalize(documented)))
  documented_degree=any(re.search(degree_pattern,normalize(f['text'])) and not re.search(progress_pattern,normalize(f['text'])) and (re.search(completion_pattern,normalize(f['text'])) or f['origin']=='Mi perfil / qualifications') for f in facts)
  supported=(name=='student' and documented_progress) or (name=='degree' and documented_degree) or (name=='secondary' and documented_secondary)
  return out('CUMPLE' if ok else 'POR VERIFICAR','Formación confirmada compatible.' if ok else 'Formación documentada pendiente de confirmar o completar; revisar disciplina y equivalencia.',facts[:5],1 if ok or supported else 0)
 if kind=='experience':
  domain=req.get('domain')
  def relevant(f):
   row=f.get('record') or {};area=family(row.get('position') or '') or family(row.get('description') or '')
   if not domain and not req.get('sector') and not req.get('technologies'):return False
   if domain and area!=domain:return False
   if req.get('sector')=='front_of_house_hospitality':
    if not lodging_operations(f):return False
   elif req.get('sector') and not contains(f['text'],req['sector']):return False
   technologies=req.get('technologies') or []
   if technologies:
    matches=[t in concepts(f['text'],config) for t in technologies]
    if not (any(matches) if req.get('alternative') else all(matches)):return False
   return True
  facts=[f for f in b['experience'] if relevant(f)]
  records=[dict(f['record'],kind='employment') for f in facts if f.get('record') and f['record'].get('kind','employment')=='employment']
  calc=calculate_experience(records);verified=bool(facts) and all(f['confirmed'] for f in facts)
  if req.get('years') is None:return out('CUMPLE' if verified and records else 'POR VERIFICAR','Experiencia profesional pertinente documentada; la oferta no publica un mínimo de años.',facts[:4],1 if verified and records else 0)
  if calc['status']=='unknown':return out('POR VERIFICAR','Períodos profesionales insuficientes o incompletos para el área solicitada. No se cuentan proyectos académicos.',facts[:4])
  low=calc['minimum']['days']/365.2425;high=calc['maximum']['days']/365.2425
  state='CUMPLE' if verified and low>=req['years'] else 'NO CUMPLE' if verified and high<req['years'] else 'POR VERIFICAR'
  if state=='POR VERIFICAR' and req.get('alternative') and attested=='Yes':return out('CUMPLE','Alternativa publicada de formación o experiencia confirmada por el usuario para esta vacante; no se añade un grado ni se inventan fechas.',facts[:4])
  return out(state,f"Experiencia profesional documentada del área: {low:.2f}–{high:.2f} años; exige {req['years']:g}. Fechas parciales producen intervalos; no se añaden proyectos.",facts[:4],1 if state=='CUMPLE' else 1 if low>=req['years'] else 0)
 if kind=='schedule':
  from autojob.matching.semantics import capability
  flexible=capability(dict(req,kind='capability',name='flexible_schedule'),person,job)
  if flexible['state']=='CUMPLE':return dict(flexible,kind=kind,name=name)
  if flexible['state']=='POR VERIFICAR' and 'contradictoria' in flexible['reason']:return dict(flexible,kind=kind,name=name)
  value=normalize(values.get('schedule') or '')
  incompatible=bool(re.search(r'no (?:noches|fines de semana)|no weekends|no nights|only weekdays|solo diurno',value))
  if attested=='Yes' and not ('schedule' in manual and incompatible):return out('CUMPLE','Horario confirmado para esta vacante.')
  return out('NO CUMPLE' if 'schedule' in manual and incompatible else 'POR VERIFICAR','Contrastar horario publicado con disponibilidad confirmada; no se deduce disponibilidad de tiempo completo.')
 if kind=='authorization':
  if job.get('_confirmed_cr_authorization') is True:return out('CUMPLE','País Costa Rica y autorización laboral confirmados conjuntamente en Mi perfil; no se extrapola a otros países.',[dict(text='Costa Rica / permiso confirmado',origin='Mi perfil / country + work_authorization',confirmed=True)])
  # El campo booleano existente no identifica un permiso para cada país.
  return out('POR VERIFICAR','La autorización laboral debe confirmarse específicamente para el país exigido; nacionalidad o sede empresarial no bastan.')
 if kind=='document':
  selection=job.get('_resume_selection') or {};expected={'cv_language_English':'en','cv_language_Spanish':'es'}.get(name)
  ok=bool(expected and selection.get('resume_id') and selection.get('language')==expected)
  return out('CUMPLE' if ok else 'POR VERIFICAR','Idioma del documento solicitado; no se confunde con dominio personal del idioma.',[dict(text=str(selection.get('language')),origin='CV seleccionado / '+str(selection.get('resume_id')),confirmed=True)] if ok else [])
 if kind=='residence':return out('NO CUMPLE' if job.get('geography')=='INCOMPATIBLE' else 'POR VERIFICAR','Se requiere contrastar la residencia obligatoria con la geografía publicada.')
 return out('POR VERIFICAR','Texto conservado para revisión; el motor local no puede verificar este requisito.')

def evaluate(job,profile,cvs,config,selection=None):
 from autojob.matching.semantics import assess_with_answers
 person=candidate(profile,cvs);requirements=extract(job,config);evaluated=[assess_with_answers(r,person,config,dict(job,_resume_selection=selection),assess) for r in requirements if r['kind']!='responsibility']
 groups={'skills':{'skill','soft_skill','certification'},'experience':{'experience'},'education':{'education'},'languages':{'language'}}
 criteria={};coverage={}
 for key,kinds in groups.items():
  items=[r for r in evaluated if r['kind'] in kinds and r['importance']!='DESEABLE'];den=sum(1 if r['importance']!='DESEABLE' else .5 for r in items)
  evidence=lambda r:r.get('support',0)
  criteria[key]=round(100*sum(evidence(r)*(1 if r['importance']!='DESEABLE' else .5) for r in items)/den,2) if den else 0
  coverage[key]=round(100*sum(r['state']!='POR VERIFICAR' for r in items)/len(items),2) if items else 0
 role=family(job.get('title',''));b=person['buckets'];role_facts=[f for group in ('experience','positions','education','projects') for f in b[group] if role and family(f['text'])==role]
 criteria['role']=100 if role_facts else 0;coverage['role']=100 if any(f['confirmed'] for f in role_facts) else 0
 geo=job.get('geography') or 'DESCONOCIDO'
 # Volver a contrastar restricciones explícitas, sin convertir datos de empresa en elegibilidad.
 recomputed=classify(job.get('location') or '',job.get('title','')+'\n'+(job.get('description') or ''),job.get('modality') or 'unknown',enabled=profile.get('_onsite_localities'))
 if recomputed['status']=='INCOMPATIBLE':geo='INCOMPATIBLE'
 values=profile.get('values',{});mode=job.get('modality');preference_block=mode in profile.get('manual',[]) and values.get(mode) is False
 pref=[geo=='CONFIRMADO',bool(mode in {'remote','onsite','hybrid'} and not preference_block),False,False]
 pref_known=[geo in {'CONFIRMADO','INCOMPATIBLE'},mode in {'remote','onsite','hybrid'},False,False]
 schedule=normalize(str(job.get('schedule') or ''));schedule_block=False;salary_block=False
 if re.search(r'full.time|tiempo completo|part.time|medio tiempo|flexible',schedule):
  field='part_time' if re.search(r'part.time|medio tiempo',schedule) else 'full_time'
  schedule_block=field in profile.get('manual',[]) and values.get(field) is False
  pref[2]=not schedule_block;pref_known[2]=True
 published_salary=str(job.get('salary') or '')
 if values.get('salary_min') and values.get('currency')==job.get('currency') and re.search(r'month|mensual',published_salary,re.I):
  amounts=re.findall(r'\d+(?:\.\d+)?',published_salary.replace(',',''))
  if amounts:
   salary_block=max(map(float,amounts))<float(values['salary_min']);pref[3]=not salary_block;pref_known[3]=True
 criteria['preferences']=sum(pref)*25;coverage['preferences']=sum(pref_known)*25
 overall_score=round(sum(criteria[k]*config['weights'][k]/100 for k in WEIGHTS),1)
 relevant_groups={k for k,kinds in groups.items() if any(r['kind'] in kinds and r['importance']!='DESEABLE' for r in evaluated)}|{'role'}
 professional_weight=sum(config['weights'][k] for k in relevant_groups)
 score=round(sum(criteria[k]*config['weights'][k] for k in relevant_groups)/professional_weight,1) if professional_weight else 0
 required_evidence=[r for r in evaluated if r['importance']!='DESEABLE']
 confidence=round(100*sum(r['state']!='POR VERIFICAR' for r in required_evidence)/len(required_evidence),1) if required_evidence else 0
 mandatory=[r for r in evaluated if r['importance']=='OBLIGATORIO'];fail=[r for r in mandatory if r['state']=='NO CUMPLE'];pending=[r for r in mandatory if r['state']=='POR VERIFICAR']
 blocks=[]
 if geo=='INCOMPATIBLE':blocks.append('Geografía incompatible con Costa Rica/Cartago.')
 if preference_block:blocks.append('Modalidad rechazada en preferencias confirmadas.')
 if schedule_block:blocks.append('Jornada rechazada en preferencias confirmadas.')
 if salary_block and 'salary_min' in profile.get('manual',[]):blocks.append('Salario mensual publicado inferior al mínimo confirmado, en la misma moneda.')
 if job.get('availability')=='CERRADA':blocks.append('Oferta cerrada.')
 blocks.extend(r['reason'] for r in fail)
 selected=(selection or {}).get('resume_id')
 essential=bool(job.get('title') and job.get('company') and len((job.get('description') or '').strip())>=40)
 unknown_kinds=[name for name,kinds in groups.items() if not any(r['kind'] in kinds for r in evaluated)]
 # Incluso sin requisitos detectados, nunca se autoriza automáticamente una oferta no interpretada.
 eligible=bool(role and any(f['confirmed'] for f in role_facts)) and not blocks and not pending and bool(mandatory) and essential and geo=='CONFIRMADO' and job.get('availability')=='ABIERTA' and selected and (selection or {}).get('confirmed',True) and score>=config['eligible_score'] and confidence>=60
 state='INCOMPATIBLE' if blocks else 'COMPATIBLE' if eligible else 'REQUIERE REVISIÓN'
 warnings=[]
 if not essential:warnings.append('Información esencial insuficiente: evaluación parcial, sin autorización.')
 if unknown_kinds:warnings.append('Requisitos DESCONOCIDOS: '+', '.join(unknown_kinds))
 if not selected:warnings.append('Sin CV revisado seleccionado; revisar candidatos, sin exigir un CV adicional.')
 if (selection or {}).get('provisional_resume_id'):warnings.append('CV recomendado provisionalmente; el documento requiere revisión.')
 if geo in {'POSIBLE','DESCONOCIDO'}:warnings.append('Geografía pendiente de verificación.')
 if job.get('availability')!='ABIERTA':warnings.append('Vigencia pendiente de verificación.')
 band='Alta' if score>=80 else 'Moderada' if score>=60 else 'Limitada' if score>=40 else 'Baja'
 return dict(engine_version=VERSION,job_id=job['id'],company=job.get('company'),title=job.get('title'),url=job.get('url'),score=score,professional_score=score,overall_score=overall_score,provisional=any(r['profile_evidence'] and r['state']=='POR VERIFICAR' for r in evaluated),confidence=confidence,band=band,eligibility=state,automatic_authorized=False,geography=geo,modality=mode,location=job.get('location'),published_facts={key:dict(value=job.get(key),source=job.get('url')) for key in ('schedule','salary','currency','contract_type','seniority','location','modality','mandatory_requirements','desirable_requirements')},requirements=requirements,assessments=evaluated,criteria=criteria,criteria_confidence=coverage,mandatory_status='NO CUMPLE' if fail else 'POR VERIFICAR' if pending or not mandatory else 'CUMPLE',blocks=blocks,warnings=warnings,unknown_criteria=unknown_kinds,resume_selection=selection or {},evaluated_at=datetime.now(timezone.utc).isoformat(),strengths=[r for r in evaluated if r['state']=='CUMPLE'],desirable_unverified=[r for r in evaluated if r['importance']=='DESEABLE' and r['state']!='CUMPLE'],heuristic_notice='Puntuación heurística de adecuación, no probabilidad de contratación. Fase 6B no autoriza envíos.')
