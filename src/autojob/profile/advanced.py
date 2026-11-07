import re
from autojob.profile.answers import Resolution,norm
from autojob.profile.templates import INTENTS
from autojob.profile.experience import calculate_experience

EXTRA={
 'first_name':['first name','given name','nombre de pila'],'last_name':['last name','surname','family name','apellidos'],
 'province':['province','state of residence','provincia'],'nationality':['nationality','nacionalidad'],
 'location':['address','direccion','ubicacion'],'degree':['university degree','carrera universitaria','what are you studying','que estudias'],
 'academic_status':['academic status','estado academico','currently a student','actualmente estudiante'],
 'qualifications':['highest completed education','nivel educativo completado','titulos obtenidos'],
 'english_level':['english level','nivel de ingles','english proficiency'],
 'academic_projects':['academic projects','technical projects','proyectos academicos','proyectos tecnicos'],
 'start_availability':['start date','when can you start','incorporacion','cuando puedes empezar'],
 'remote':['remote work','trabajo remoto','work remotely'],'experience_duration':['years of experience','anos de experiencia','months of experience','meses de experiencia'],
}

def resolve_advanced(question,context,profile,bank,base_resolver,templates):
 context=context or {};q=norm(question);lang=context.get('language','en' if re.search(r'\b(what|your|why|tell|describe|how|are|years|first|last|english)\b',q) else 'es')
 def out(field,answer,category,source,reason,auto=False):return Resolution(question,field,answer,lang,category,source,'alta' if auto else 'media' if answer else 'baja',auto,auto,not auto,reason)
 # Las declaraciones legales nunca se trasladan entre países ni desde el banco.
 if any(term in q for term in ('authorized','autorizacion','permiso de trabajo','legally','visa','criminal','discapacidad','disability','contrato')):
  country='US' if any(t in q for t in ('united states','estados unidos','usa')) else 'CR' if 'costa rica' in q else 'unspecified'
  return out('work_authorization_'+country,None,'SENSIBLE','Declaración personal','Requiere autorización específica para el país solicitado.')
 if bank:
  match=bank.match(question,lang,profile)
  if match:
   contextual=bool(context.get('company') or context.get('position')) and any(t in q for t in ('why','motiva','por que','candidate','candidat'))
   return out('approved',match['answer'],'SUGERIDA' if contextual else 'CONFIRMADA','Banco aprobado','Comprueba que la respuesta aprobada siga siendo pertinente para la empresa y puesto actuales.' if contextual else 'Respuesta vigente aprobada por el usuario.',not contextual)
 intents=[intent for intent,patterns in INTENTS.items() if any(p in q for p in patterns)]
 if intents and templates:
  intent=intents[0]
  if intent=='challenge':return out(intent,None,'DESCONOCIDA','Sin ejemplo aprobado','Un ejemplo personal concreto debe documentarse o aprobarse en el banco.')
  values=profile.get('values',{});category=context.get('job_category')
  skills=values.get('skills',[]) if category!='customer_service' else values.get('soft_skills',[])
  records=values.get('experience_records',[])
  if intent=='customer_service' or category=='customer_service':records=[r for r in records if any(t in norm(r) for t in ('customer','cliente','servicio','support'))]
  if category=='technical':records=[r for r in records if any(t in norm(r) for t in ('developer','program','technical','tecnic','engineering','ingenier'))]
  concise=[]
  for entry in records[:3]:
   parts=entry.split('|',4)
   summary=' | '.join(part.strip() for part in parts[:4])
   if len(parts)==5:
    first_sentence=re.split(r'(?<=[.!?])\s+',parts[4].strip())[0]
    if len(first_sentence)<=350:summary+=' — '+first_sentence
   concise.append(summary)
  records=concise;skills=skills[:6]
  variables={'name':values.get('full_name'),'company':context.get('company'),'position':context.get('position'),'skills':'; '.join(skills),'soft_skills':'; '.join(values.get('soft_skills',[])),'languages':'; '.join(values.get('languages',[])),'experience':'; '.join(records)}
  answer,source=templates.render(intent,lang,variables,context.get('template_id'))
  return out(intent,answer,'SUGERIDA' if answer else 'DESCONOCIDA','Plantilla: '+source,'Borrador para revisión; solo utiliza variables documentadas y el contexto proporcionado.')
 matches=[field for field,patterns in EXTRA.items() if any(re.search(r'(?<!\w)'+re.escape(p)+r'(?!\w)',q) for p in patterns)]
 if len(matches)>1:return out(None,None,'DESCONOCIDA','Interpretación ambigua','Divide la pregunta en campos separados.')
 values=profile.get('values',{});manual=profile.get('manual',[])
 if matches:
  field=matches[0]
  if field=='academic_projects':
   records=context.get('academic_projects',[])
   summaries=[' | '.join(str(row.get(key)) for key in ('name','description','technologies') if row.get(key)) for row in records]
   answer='; '.join(summaries)
   return out(field,answer or None,'SUGERIDA' if answer else 'DESCONOCIDA','Proyectos del CV seleccionado','Revisar la relevancia y los datos del proyecto antes de usar.')
  if field=='experience_duration':
   category='customer_service' if 'customer' in q or 'cliente' in q else 'programming' if 'program' in q else None
   result=calculate_experience(context.get('employment_records',[]),category,context.get('today'))
   if result['status']=='unknown':return out(field,None,'DESCONOCIDA','Fechas laborales',str(result))
   def duration(value):
    return f"{value['calendar_years']} años, {value['calendar_months']} meses completos y {value['remaining_days']} días residuales ({value['days']} días en total)" if lang=='es' else f"{value['calendar_years']} years, {value['calendar_months']} full months and {value['remaining_days']} remaining days ({value['days']} total days)"
   text=duration(result['minimum']) if result['minimum']==result['maximum'] else duration(result['minimum'])+' — '+duration(result['maximum'])
   confirmed=context.get('employment_verified',False) is True
   return out(field,text,'DERIVADA' if confirmed else 'SUGERIDA','Períodos laborales unidos',str(result),confirmed)
  if field in {'first_name','last_name'}:return out(field,None,'DESCONOCIDA','Nombre completo','No se separa automáticamente un nombre compuesto; usa una respuesta aprobada específica.')
  if field=='location':return out(field,None,'DESCONOCIDA','Perfil','La dirección postal completa no se deduce de ciudad y provincia.')
  if field=='english_level':
   items=[v for v in values.get('languages',[]) if 'english' in norm(v) or 'ingles' in norm(v)];value='; '.join(items)
   return out(field,value or None,'SUGERIDA' if value else 'DESCONOCIDA','Idiomas documentados','Revisa el nivel solicitado.')
  value=values.get(field)
  if value is None or value=='' or value==[]:return out(field,None,'DESCONOCIDA','Perfil','Dato desconocido.')
  answer=(('Yes' if value else 'No') if lang=='en' else ('Sí' if value else 'No')) if isinstance(value,bool) else ('; '.join(value) if isinstance(value,list) else str(value))
  verified=field in manual
  return out(field,answer,'CONFIRMADA' if verified else 'SUGERIDA','Perfil','Dato confirmado.' if verified else 'Confirma el dato importado.',verified)
 if any(t in q for t in ('salary','salario','sueldo','compensation')):
  from autojob.profile.calculations import salary
  periods=[any(t in q for t in terms) for terms in [('annual','annually','anual','year'),('hour','hora'),('month','mensual','mes')]]
  if sum(periods)>1:return out('salary_ambiguous',None,'DESCONOCIDA','Pregunta ambigua','La pregunta contiene varios períodos salariales; sepáralos.')
  period='year' if any(t in q for t in ('annual','annually','anual','year')) else 'hour' if any(t in q for t in ('hour','hora')) else 'month' if any(t in q for t in ('month','mensual','mes')) else None
  if period is None or period=='hour':return out('salary_'+str(period),None,'DESCONOCIDA','Salario','Indica período, moneda, bruto/neto y horas confirmadas; no se supone jornada.')
  if not values.get('salary_min') or not values.get('currency'):return out('salary_'+period,None,'DESCONOCIDA','Perfil','Falta salario o moneda.')
  amount=salary(values['salary_min'],'month',period,1)
  answer=f"{amount} {values['currency']} / {period}"
  return out('salary_'+period,answer,'SUGERIDA','Salario mensual del perfil','Conversión de 12 meses por año. Bruto/neto y aceptación requieren revisión; sin conversión de moneda.')
 return base_resolver(question,context,profile,None)
