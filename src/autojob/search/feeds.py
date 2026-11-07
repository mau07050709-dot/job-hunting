from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

def parse_wwr(content):
 root=ElementTree.fromstring(content);jobs=[]
 for item in root.findall('./channel/item'):
  title=item.findtext('title') or '';company,separator,role=title.partition(':')
  if not separator:continue
  published=item.findtext('pubDate')
  try:published=parsedate_to_datetime(published).isoformat() if published else None
  except (ValueError,TypeError):published=None
  url=item.findtext('link') or ''
  jobs.append(dict(id=item.findtext('guid') or url,title=role.strip(),company_name=company.strip(),url=url,description=item.findtext('description') or '',candidate_required_location='Remote',publication_date=published))
 return {'jobs':jobs}
