"""Portal oficial público; navegación con el perfil independiente de Brave."""
from html import unescape
from datetime import datetime, timezone
import re
from urllib.parse import urljoin

BASE='https://jobs.bostonscientific.com'

def source_date(value):
 try:return datetime.strptime(value,'%a %b %d %H:%M:%S UTC %Y').replace(tzinfo=timezone.utc).isoformat()
 except (ValueError,TypeError):return None

def parse_detail(html,url,location):
 from autojob.search.jobs import clean
 from lxml import etree
 tree=etree.HTML(html)
 def text(xpath):
  found=tree.xpath(xpath)
  return ' '.join(' '.join(element.itertext()).split()) if (element:=next(iter(found),None)) is not None else None
 def meta(key):
  m=re.search(r'<meta\b[^>]*itemprop="'+key+r'"[^>]*content="([^"]*)"',html,re.I)
  return unescape(m[1]) if m else None
 title=text('//*[@itemprop="title"]')
 description=text('//*[contains(concat(" ",normalize-space(@class)," ")," jobdescription ")]')
 if not title or not description:raise ValueError('No se encontró una oferta completa en el portal oficial')
 description=clean(description);mode=None;evidence=None
 published_mode=text('//*[@data-careersite-propertyid="customfield1"]') or ''
 # Estas reglas sólo usan lenguaje de modalidad explícito; una sede no implica presencialidad.
 for pattern,value in [(r'\b(?:híbrido|hybrid)\b','hybrid'),(r'\b(?:presencial|on[ -]?site)\b','onsite'),(r'\b(?:remoto|remote|teletrabajo)\b','remote')]:
  m=re.search(pattern,published_mode+'\n'+description,re.I)
  if m:mode=value;evidence=m[0];break
 return dict(id=url.rstrip('/').split('/')[-1],title=clean(title),company_name='Boston Scientific',url=url,
  location=re.sub(r',\s*CR\s*$',', Costa Rica',location),description=description,modality=mode,
  modality_evidence=evidence,publication_date=source_date(meta('datePosted')),valid_through=source_date(meta('validThrough')),
  country='Costa Rica' if ('costa rica' in location.casefold() or re.search(r',\s*CR\s*$',location)) else None,province='Cartago' if ('cartago' in location.casefold() and ('costa rica' in location.casefold() or re.search(r',\s*CR\s*$',location))) else None)

def fetch_jobs(cancel=lambda:False):
 from pathlib import Path
 from autojob.browser import BraveSession
 from autojob.config import Settings
 jobs=[];seen=set()
 from dataclasses import replace
 with BraveSession(replace(Settings.load(Path(__file__).resolve().parents[3]),timeout_ms=30000)) as browser:
  # Cartago primero; otra página nacional amplía cobertura sin consultas por cada palabra clave.
  for place in ['Cartago','Costa Rica']:
   if cancel():break
   page=browser.new_page(BASE+'/search/?q=&locationsearch='+place.replace(' ','%20'))
   if page.locator('table#searchresults').count()==0:
    raise ValueError('Fuente no disponible: no hay tabla pública de resultados')
   links=[]
   for row in page.locator('tr.data-row').all():
    link=row.locator('a.jobTitle-link').first
    if not link.count():continue
    url=urljoin(BASE,link.get_attribute('href'));loc=row.locator('td.colLocation').inner_text().strip()
    if url not in seen:links.append((url,loc));seen.add(url)
   page.close()
   for url,loc in links[:12-len(jobs)]:
    if cancel():break
    page=browser.new_page(url)
    try:jobs.append(parse_detail(page.content(),url,loc))
    except ValueError:
     import logging
     logging.getLogger(__name__).warning('Detalle público no legible: %s',url)
    finally:page.close()
   if len(jobs)>=12:break
 if not jobs:raise ValueError('No se pudieron leer detalles públicos; la fuente no está disponible')
 return jobs
