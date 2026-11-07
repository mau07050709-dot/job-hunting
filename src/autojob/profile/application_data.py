"""Datos adicionales locales, confirmación explícita y respuestas con procedencia."""
from contextlib import closing, contextmanager
from datetime import date,datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
import json,re,platform
from threading import local
from zoneinfo import ZoneInfo
from autojob.storage.database import Database
from autojob.profile.calculations import age,salary
from autojob.profile.store import ProfileStore,today

GROUPS={
 'Datos personales':{'first_name':'Nombre(s) confirmado(s)','last_name':'Apellidos confirmados','birth_date':'Fecha de nacimiento (AAAA-MM-DD)','nationality':'Nacionalidad','country':'País de residencia','province':'Provincia','canton':'Cantón','address':'Dirección opcional','postal_code':'Código postal','whatsapp':'WhatsApp internacional','linkedin':'LinkedIn','professional_links':'Enlaces profesionales adicionales','work_authorization_cr':'Autorización laboral en Costa Rica','other_work_permits':'Otros permisos (país y permiso confirmado)'},
 'Equipo remoto':{'own_computer':'Computadora propia','computer_type':'Escritorio / portátil','operating_system':'Sistema operativo','ram_gb':'RAM (GB)','processor':'Procesador','webcam':'Cámara web','microphone':'Micrófono','headset':'Audífonos con micrófono','stable_internet':'Internet estable','download_mbps':'Descarga Mbps','upload_mbps':'Subida Mbps','connection_type':'Tipo de conexión','private_workspace':'Espacio privado','backup_power':'Respaldo eléctrico','alternative_connection':'Conexión alternativa'},
 'Disponibilidad':{'start_next_day':'Calcular incorporación para el día siguiente (Costa Rica)','start_date':'Fecha de incorporación (AAAA-MM-DD)','immediate_start':'Disponibilidad inmediata','weekly_hours':'Horas semanales disponibles','full_time':'Tiempo completo','part_time':'Medio tiempo','weekends':'Fines de semana','nights':'Noches','preferred_schedule':'Horario preferido','accepted_shifts':'Turnos aceptados','timezone':'Zona horaria IANA','accepted_contracts':'Modalidades de contratación','remote_conditions':'Condiciones para remoto','onsite_conditions':'Condiciones para presencial'},
 'Salario principal':{},'Salario tiempo completo':{},'Salario medio tiempo':{},'Salario contractor':{},
 'Conversión manual':{'fx_from':'Moneda de origen','fx_to':'Moneda de destino','fx_rate':'Tipo de cambio manual (destino por 1 origen)','international_expectations':'Expectativas para contratos internacionales'},
}
for group,prefix in [('Salario principal','main'),('Salario tiempo completo','full'),('Salario medio tiempo','part'),('Salario contractor','contractor')]:
 GROUPS[group]={prefix+'_'+k:v for k,v in {'min':'Salario mínimo','max':'Salario máximo','expected':'Expectativa exacta opcional','currency':'Moneda ISO','period':'Período: month, year o hour','hours':'Horas semanales de referencia','basis':'Bruto o neto','negotiable':'Negociable'}.items()}
FIELDS={k:v for group in GROUPS.values() for k,v in group.items()}
BOOLS={'start_next_day','work_authorization_cr','own_computer','webcam','microphone','headset','stable_internet','private_workspace','backup_power','alternative_connection','immediate_start','full_time','part_time','weekends','nights'}|{p+'_negotiable' for p in ('main','full','part','contractor')}
NUMBERS={'ram_gb','download_mbps','upload_mbps','weekly_hours','fx_rate'}|{p+'_'+f for p in ('main','full','part','contractor') for f in ('min','max','expected','hours')}
BRIDGE={'birth_date':'birth_date','nationality':'nationality','country':'country','province':'province','whatsapp':'whatsapp','linkedin':'linkedin','full_time':'full_time','part_time':'part_time','main_min':'salary_min','main_max':'salary_max','main_currency':'currency'}

def number(value):
 try:
  result=Decimal(str(value))
  if not result.is_finite() or result<0:raise ValueError()
  return result
 except (ValueError,InvalidOperation):raise ValueError('Cantidad inválida; utiliza un número sin separadores de miles.') from None

class ApplicationData:
 def __init__(self,data_path):
  self._reads=local()
  self.data_path=data_path;self.db=Database(data_path/'autojob.sqlite3');self.profile=ProfileStore(data_path)
  with closing(self.db.connect()) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS application_data(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,confirmed INTEGER NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS application_data_history(id INTEGER PRIMARY KEY,key TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS application_faq(id INTEGER PRIMARY KEY,company TEXT NOT NULL,question TEXT NOT NULL,answer TEXT,confirmed INTEGER NOT NULL,UNIQUE(company,question))')
 @contextmanager
 def read_snapshot(self):
  if getattr(self._reads,'cache',None) is not None:
   yield
   return
  self._reads.cache={}
  try:yield
  finally:self._reads.cache=None
 def _read(self,key,loader):
  cache=getattr(self._reads,'cache',None)
  if cache is None:return loader()
  if key not in cache:cache[key]=loader()
  return cache[key]
 def load(self):
  return self._read('additional',self._load)
 def _load(self):
  with closing(self.db.connect()) as db:return {r['key']:dict(value=json.loads(r['value_json']),confirmed=bool(r['confirmed']),revision=r['revision'],updated_at=r['updated_at']) for r in db.execute('SELECT * FROM application_data')}
 def validate(self,values):
  if not set(values)<=set(FIELDS):raise ValueError('Campo adicional desconocido.')
  for key,value in values.items():
   if value in (None,''):continue
   if key in BOOLS:
    if type(value) is not bool:raise ValueError('Selección booleana inválida.')
   elif not isinstance(value,str) or len(value)>10000:raise ValueError('Texto inválido.')
   if key in NUMBERS:
    n=number(value)
    if key.endswith('_hours') or key in {'weekly_hours','fx_rate'}:
     if n<=0:raise ValueError('Las horas y el tipo de cambio deben ser mayores que cero.')
   if key in {'birth_date','start_date'}:
    try:parsed=date.fromisoformat(value)
    except ValueError:raise ValueError('Fecha inválida: utiliza AAAA-MM-DD.') from None
    if key=='birth_date':age(parsed,today())
   if key=='timezone':
    try:ZoneInfo(value)
    except Exception:raise ValueError('Zona horaria IANA inválida.') from None
   if key.endswith('_currency') or key in {'fx_from','fx_to'}:
    if not re.fullmatch('[A-Z]{3}',value):raise ValueError('Moneda inválida: utiliza tres letras mayúsculas.')
   if key.endswith('_period') and value not in {'month','year','hour'}:raise ValueError('Período: month, year o hour.')
   if key.endswith('_basis') and value not in {'gross','net','bruto','neto'}:raise ValueError('Indica gross/bruto o net/neto.')
   if key=='whatsapp':
    import phonenumbers
    try:
     if not phonenumbers.is_valid_number(phonenumbers.parse(value,None)):raise ValueError()
    except Exception:raise ValueError('WhatsApp inválido; incluye el prefijo internacional.') from None
   if key=='linkedin' and not re.fullmatch(r'https://(?:www\.)?linkedin\.com/[^\s]+',value):raise ValueError('LinkedIn debe usar https://linkedin.com/...')
   if key=='professional_links' and any(not re.fullmatch(r'https://[^\s]+',v.strip()) for v in value.splitlines() if v.strip()):raise ValueError('Los enlaces deben usar HTTPS, uno por línea.')
  for p in ('main','full','part','contractor'):
   if values.get(p+'_min') and values.get(p+'_max') and number(values[p+'_min'])>number(values[p+'_max']):raise ValueError('El mínimo salarial supera al máximo.')
   if values.get(p+'_expected'):
    if values.get(p+'_min') and number(values[p+'_expected'])<number(values[p+'_min']):raise ValueError('La expectativa exacta está por debajo del mínimo.')
    if values.get(p+'_max') and number(values[p+'_expected'])>number(values[p+'_max']):raise ValueError('La expectativa exacta supera el máximo del rango.')
 def save(self,values,confirmed=(),expected=None):
  self.validate(values);current=self.load();merged={k:r['value'] for k,r in current.items()};merged.update(values);self.validate(merged);now=datetime.now(timezone.utc).isoformat()
  if not set(confirmed)<=set(values):raise ValueError('Confirmación de un campo inexistente.')
  with closing(self.db.connect()) as db,db:
   db.execute('BEGIN IMMEDIATE')
   for key,value in values.items():
    old=current.get(key);rev=old['revision'] if old else 0
    live=db.execute('SELECT revision FROM application_data WHERE key=?',(key,)).fetchone()
    if (live['revision'] if live else 0)!=rev:raise ValueError('Los datos cambiaron mientras guardabas; actualiza antes de continuar.')
    if expected is not None and expected.get(key,0)!=rev:raise ValueError('Los datos cambiaron en otra ventana; actualiza antes de guardar.')
    # El formulario solo escribe cambios o confirmaciones explícitas, preservando los demás valores confirmados.
    is_confirmed=key in confirmed and value not in (None,'')
    if old and value==old['value'] and is_confirmed==old['confirmed']:continue
    db.execute('INSERT OR REPLACE INTO application_data VALUES (?,?,?,?,?)',(key,json.dumps(value),int(is_confirmed),rev+1,now));db.execute('INSERT INTO application_data_history(key,payload,updated_at) VALUES (?,?,?)',(key,json.dumps(dict(value=value,confirmed=is_confirmed)),now))
 def delete(self,keys):
  with closing(self.db.connect()) as db,db:
   for key in keys:
    db.execute('DELETE FROM application_data WHERE key=?',(key,));db.execute('DELETE FROM application_data_history WHERE key=?',(key,))
 def value(self,key):
  if key=='start_date':
   rule=self.load().get('start_next_day',{})
   if rule.get('confirmed') and rule.get('value') is True:return (datetime.now(ZoneInfo('America/Costa_Rica')).date()+timedelta(days=1)).isoformat(),'DERIVADA'
  item=self.load().get(key)
  if key=='whatsapp' and item and not item['confirmed']:
   from autojob.profile.contact import same_phone
   profile=self.profile_state()
   if 'whatsapp' in profile['manual'] and same_phone(item['value'],profile['values'].get('whatsapp')):return profile['values']['whatsapp'],'CONFIRMADA'
  if item and item['value'] not in (None,''):return item['value'],'CONFIRMADA' if item['confirmed'] else 'SUGERIDA'
  profile=self.profile_state();field=BRIDGE.get(key)
  if key=='main_period' and any(profile['values'].get(k) and k in profile['manual'] for k in ('salary_min','salary_max')):return 'month','CONFIRMADA'
  if field and profile['values'].get(field) not in (None,'',[]):return profile['values'][field],'CONFIRMADA' if field in profile['manual'] else 'SUGERIDA'
  return None,'DESCONOCIDA'
 def profile_state(self):
  return self._read('profile',self._profile_state)
 def _profile_state(self):
  from autojob.profile.review import ReviewStore
  review=ReviewStore(self.data_path);p=self.profile.load()
  if not review.decisions():return p
  return review.effective(p,[review.library.get(c['id']) for c in review.library.list()])[0]
 def conflicts(self):
  profile=self.profile_state();additional=self.load();result={}
  for key,field in BRIDGE.items():
   from autojob.profile.contact import same_phone
   if key=='whatsapp' and key in additional and same_phone(additional[key]['value'],profile['values'].get(field)):continue
   if key in additional and additional[key]['value'] not in (None,'') and profile['values'].get(field) not in (None,'',[]) and str(additional[key]['value'])!=str(profile['values'][field]):result[key]=dict(additional=additional[key]['value'],profile=profile['values'][field],profile_confirmed=field in profile['manual'])
  return result
 def salary(self,prefix='main',target='month',currency=None,bound='min'):
  with self.read_snapshot():
   return self._salary(prefix,target,currency,bound)
 def _salary(self,prefix,target,currency,bound):
  entries={key:self.value(prefix+'_'+key) for key in ('min','max','expected','currency','period','hours','basis')}
  if bound not in {'min','max','expected'}:raise ValueError('Importe salarial desconocido.')
  if any(entries[k][0] is None or entries[k][1]!='CONFIRMADA' for k in (bound,'currency','period')):return None,'DESCONOCIDA','Faltan importe, moneda o período confirmados.'
  if any(prefix+'_'+k in self.conflicts() for k in ('min','max','currency')):return None,'CONFLICTO','Rango salarial en conflicto con Mi perfil.'
  amount=entries[bound][0];source=entries['period'][0];hours=entries['hours'][0]
  if 'hour' in {target,source} and (not hours or entries['hours'][1]!='CONFIRMADA'):return None,'DESCONOCIDA','Faltan horas semanales de referencia confirmadas.'
  # Reutiliza la función previa; month/year no dependen de horas, valor técnico neutro sin afirmar jornada.
  result=salary(amount,source,target,hours if hours else 1)
  if currency and currency!=entries['currency'][0]:
   fx=[self.value(k) for k in ('fx_from','fx_to','fx_rate')]
   if not all(s=='CONFIRMADA' for _,s in fx) or [fx[0][0],fx[1][0]]!=[entries['currency'][0],currency]:return None,'DESCONOCIDA','No hay tipo de cambio manual confirmado para ese par y dirección.'
   result*=number(fx[2][0])
  return format(result.quantize(Decimal('.01')),'f'),'DERIVADA' if target!=source or currency and currency!=entries['currency'][0] else 'CONFIRMADA',(currency or entries['currency'][0])+' / '+target
 def faq_save(self,company,question,answer,confirmed=False):
  if not question.strip():raise ValueError('Escribe la pregunta.')
  q=question.casefold()
  if any(term in q for term in ('worked','employed','trabajado','anteriormente','esta empresa','this company','herramienta','tool')) and not company.strip():raise ValueError('Indica empresa o contexto específico; no se permite una respuesta genérica.')
  with closing(self.db.connect()) as db,db:db.execute('INSERT INTO application_faq(company,question,answer,confirmed) VALUES (?,?,?,?) ON CONFLICT(company,question) DO UPDATE SET answer=excluded.answer,confirmed=excluded.confirmed',(company.strip().casefold(),question.strip(),answer,int(confirmed and answer is not None)))
 def faqs(self):
  with closing(self.db.connect()) as db:return [dict(r) for r in db.execute('SELECT * FROM application_faq ORDER BY company,question')]
 def faq_delete(self,id):
  with closing(self.db.connect()) as db,db:db.execute('DELETE FROM application_faq WHERE id=?',(id,))

def detect_windows():
 """Solo se llama desde el botón solicitado; no hace pruebas de red ni confirma los valores."""
 import subprocess
 command='[Console]::OutputEncoding=[Text.Encoding]::UTF8; $c=Get-CimInstance Win32_ComputerSystem; $p=Get-CimInstance Win32_Processor | Select-Object -First 1; @{ram_gb=[math]::Round($c.TotalPhysicalMemory/1GB,1).ToString();processor=$p.Name;operating_system=(Get-CimInstance Win32_OperatingSystem).Caption}|ConvertTo-Json -Compress'
 raw=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=20,creationflags=0x08000000)
 if raw.returncode:raise ValueError('No se pudo detectar el equipo. Puedes completar los campos manualmente.')
 result=json.loads(raw.stdout.decode('utf-8-sig'))
 if 'ram_gb' in result:result['ram_gb']=str(result['ram_gb']).replace(',','.').strip()
 return {key:str(value).strip() for key,value in result.items()}
