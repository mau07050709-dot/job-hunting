"""Revisión geográfica conservadora con evidencia literal y auditoría local."""
from contextlib import closing
from datetime import datetime,timezone
import json,re,unicodedata

LOCALITIES=['Cartago','Paraíso','Oreamuno','El Guarco','La Unión','Turrialba','Jiménez','Alvarado']
def normalize(value):return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))

def classify(location,description,modality='remote',enabled=None):
 text=location+'\n'+description;plain=normalize(text);loc=normalize(location);enabled=LOCALITIES if enabled is None else enabled
 def result(status,evidence,reason):return dict(status=status,evidence=evidence,reason=reason)
 if modality!='remote':
  if 'colombia' in plain or 'valle del cauca' in plain:return result('INCOMPATIBLE',location,'Localidad fuera de Costa Rica')
  if 'costa rica' not in loc:return result('DESCONOCIDO',location,'No está confirmado el país del lugar presencial')
  matching=next((place for place in enabled if re.search(r'(?<!\w)'+re.escape(normalize(place))+r'(?!\w)',loc)),None)
  if matching:return result('CONFIRMADO',location,'Localidad habilitada de Cartago, Costa Rica')
  return result('INCOMPATIBLE',location,'Lugar presencial fuera de las localidades habilitadas')
 patterns=[
  r'(?:excluding|except|not available in|no contratamos en|excluye)\s+(?:candidates in\s+)?costa rica',
  r'(?:us|usa|united states|uk|eu|europe|canada)[ -]only',
  r'(?:must reside|must be located|residency required|residir en|residencia obligatoria)[^.!?\n]{0,80}(?:united states|canada|europe|united kingdom|estados unidos)',
  r'(?:us|united states|estados unidos)[^.!?\n]{0,30}(?:work authorization|work authorisation|work permit)[^.!?\n]{0,30}(?:required|mandatory)',
 ]
 for pattern in patterns:
  match=re.search(pattern,plain)
  if match:return result('INCOMPATIBLE',text[match.start():match.end()],'Restricción explícita de residencia o contratación')
 # Exigir lenguaje de alcance/candidatos para no confundir una sede con elegibilidad.
 patterns=[r'(?:remote (?:throughout|across|in)|anywhere in|candidates (?:throughout|across|from)|eligible countries)[^.!?\n]{0,60}(?:latin america|latam|central america|costa rica)\b',r'(?:open to|hiring in|candidates (?:in|from)|applicants (?:in|from)|residents of|remote (?:in|from))[^.!?\n]{0,160}\bcosta rica\b']
 favorable=None
 for pattern in patterns:
  match=re.search(pattern,plain)
  if match:favorable=text[match.start():match.end()];break
 timezone=re.search(r'(?:must|require|required|mandatory|only)[^.!?\n]{0,65}(?:time ?zone|utc|gmt|pacific time|eastern time)',plain)
 if timezone:return result('POSIBLE',text[timezone.start():timezone.end()],'Restricción horaria: requiere verificar UTC-6 y el horario publicado')
 if favorable and re.search(r'(?:only (?:in|from)|eligible countries (?:are|:)|except|excluding)',plain) and 'costa rica' not in plain:return result('POSIBLE',favorable,'Alcance regional con excepciones; requiere revisar países concretos')
 if favorable:return result('CONFIRMADO',favorable,'Alcance geográfico explícito')
 if any(x in loc for x in ('worldwide','work from anywhere')):return result('POSIBLE',location,'Alcance global publicado; falta confirmar contratación desde Costa Rica')
 if any(x in loc for x in ('costa rica','central america','latin america','latam')):
  return result('CONFIRMADO',location,'Ubicación permitida publicada incluye Costa Rica')
 if re.search(r'\b(?:latam|latin america|central america|americas)\b',plain):
  return result('POSIBLE',next((line for line in text.splitlines() if re.search(r'latam|latin america|central america|americas',line,re.I)),location),'Indicio regional; no confirma por sí solo países admitidos')
 if re.search(r'\b(?:north america|europe|united states|usa|uk|eu)\b',loc):return result('INCOMPATIBLE',location,'Alcance publicado excluye Costa Rica')
 return result('POSIBLE' if modality=='remote' and loc in {'','remote','remoto','unknown','unspecified'} else 'DESCONOCIDO',location or 'Sin evidencia geográfica explícita','Información insuficiente para confirmar elegibilidad')

def review_store(store,cancel=lambda:False,progress=lambda value:None):
 with closing(store.db.connect()) as db,db:
  db.execute('CREATE TABLE IF NOT EXISTS job_geography_reviews (id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,reviewed_at TEXT NOT NULL,source TEXT NOT NULL,previous TEXT NOT NULL,result_json TEXT NOT NULL)')
 counts={};reviewed=0
 for job in store.list():
  if cancel():break
  if job.get('manual_fields') and 'geography' in job['manual_fields']:continue
  if job['geography']=='INCOMPATIBLE':continue
  result=classify(job.get('location') or '',job.get('title','')+'\n'+(job.get('description') or ''),job.get('modality') or 'remote')
  if result['status']==job.get('geography') and result['evidence']==job.get('geography_evidence') and job.get('geography_reviewed_at'):continue
  now=datetime.now(timezone.utc).isoformat();previous=job['geography'];job['geography']=result['status'];job['geography_evidence']=result['evidence'];job['geography_reviewed_at']=now;job['geography_review_source']=job['url'];job['geography_reason']=result['reason']
  # El formato previo del payload se conserva; se actualiza solamente geografía.
  with closing(store.db.connect()) as db,db:
   row=db.execute('SELECT payload FROM discovered_jobs WHERE id=?',(job['id'],)).fetchone()
   if not row:continue
   payload=json.loads(row[0])
   for key in ('geography','geography_evidence','geography_reviewed_at','geography_review_source','geography_reason'):payload[key]=job[key]
   payload['status']='GEOGRAFÍA CONFIRMADA' if result['status']=='CONFIRMADO' else 'GEOGRAFÍA INCOMPATIBLE' if result['status']=='INCOMPATIBLE' else 'REQUIERE REVISIÓN'
   db.execute('UPDATE discovered_jobs SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),job['id']))
   db.execute('INSERT INTO job_geography_reviews(job_id,reviewed_at,source,previous,result_json) VALUES (?,?,?,?,?)',(job['id'],now,job['url'],previous,json.dumps(result,ensure_ascii=False)))
  reviewed+=1;counts[result['status']]=counts.get(result['status'],0)+1;progress('Geografía revisada: '+str(reviewed))
 return dict(reviewed=reviewed,results=counts,cancelled=cancel())
