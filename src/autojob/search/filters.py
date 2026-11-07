"""Filtros combinables sobre valores publicados; desconocidos visibles por elección."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
import json,re
from autojob.search.geography import normalize,LOCALITIES

def value(job,key):
 if key=='published_days':return job.get('published_at')
 if key=='keywords':return ' '.join(str(job.get(k) or '') for k in ('title','company','description'))
 if key=='availability':return job.get(key) if job.get(key) in {'ABIERTA','CERRADA','NO VERIFICADA','ERROR DE VERIFICACIÓN'} else 'NO VERIFICADA'
 if key=='category':
  title=normalize(job.get('title',''))
  categories=[]
  if any(t in title for t in ('developer','software','python','engineer','qa','technician','technical','it support','help desk')):categories.append('Tecnología')
  if any(t in title for t in ('customer','support','call center','assistant','back office','service desk','help desk')):categories.append('Customer Service')
  return ', '.join(categories) or None
 if key in {'country','province','canton'}:
  if job.get(key):return job[key]
  loc=job.get('location') or '';plain=normalize(loc)
  if key=='country':
   return next((country for country in ['Costa Rica','United States','Canada','United Kingdom','Colombia','Mexico','Germany','France','Spain','Brazil'] if normalize(country) in plain),None)
  if 'costa rica' in plain:
   if key=='province':
    for province in ['Cartago','Heredia','San José','Alajuela','Guanacaste','Puntarenas','Limón']:
     if normalize(province) in plain:return province
    if any(normalize(place) in plain for place in LOCALITIES):return 'Cartago'
   if key=='canton':return next((p for p in LOCALITIES if re.search(r'\b'+re.escape(normalize(p))+r'\b',plain)),None)
  return None
 return job.get(key)

def matches(job,filters,include_unknown=True):
 for key,expected in filters.items():
  if not expected:continue
  actual=value(job,key)
  if actual in (None,'',[],{}):
   if include_unknown:continue
   return False
  if key=='published_days':
   try:
    date=datetime.fromisoformat(str(job.get('published_at')).replace('Z','+00:00'))
    if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
    if date<datetime.now(timezone.utc)-timedelta(days=int(expected)):return False
   except (ValueError,TypeError):
    if not include_unknown:return False
  elif key=='salary':
   if expected=='Publicado' and not job.get('salary'):return False
  elif key=='keywords':
   if not all(normalize(term) in normalize(str(actual)) for term in expected.split()):return False
  elif key in {'source','geography','modality','availability'}:
   if actual!=expected:return False
  elif normalize(str(expected)) not in normalize(str(actual)):return False
 return True

class Favorites:
 def __init__(self,store):
  self.db=store.db
  with closing(self.db.connect()) as db,db:db.execute('CREATE TABLE IF NOT EXISTS job_filter_favorites(name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
 def save(self,name,filters,unknown):
  if not name.strip():raise ValueError('Escribe un nombre para el filtro')
  with closing(self.db.connect()) as db,db:db.execute('INSERT OR REPLACE INTO job_filter_favorites VALUES (?,?)',(name.strip(),json.dumps(dict(filters=filters,unknown=unknown))))
 def list(self):
  with closing(self.db.connect()) as db:return {r['name']:json.loads(r['payload']) for r in db.execute('SELECT * FROM job_filter_favorites ORDER BY name')}

def export_rows(rows,filename):
 from openpyxl import Workbook
 keys=['company','title','source','location','modality','schedule','seniority','geography','availability','salary','currency','published_at','url']
 book=Workbook();sheet=book.active;sheet.append(keys)
 for row in rows:
  sheet.append([str(value(row,key) or '') for key in keys])
  for cell in sheet[sheet.max_row]:cell.data_type='s'
 book.save(filename)
