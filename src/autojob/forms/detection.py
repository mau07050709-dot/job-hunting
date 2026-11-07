"""Reconocimiento de formularios por señales semánticas, independiente del portal."""
import re,unicodedata
from urllib.parse import urlsplit
from ipaddress import ip_address


def key(text):return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',str(text or '')).encode('ascii','ignore').decode().lower())

def candidate_form(scan):
    fields=[f for f in scan.get('fields',[]) if not f.get('disabled') and f.get('visible') is not False and f.get('kind') not in {'button','submit','reset','hidden','password'}]
    names=any(any(w in key(f.get('label','')+' '+f.get('name','')+' '+f.get('autocomplete','')) for w in ('fullname','firstname','givenname','nombre','apellido')) for f in fields)
    mail=any(f.get('kind')=='email' or any(w in key(f.get('label','')+' '+f.get('name','')) for w in ('email','correo')) for f in fields)
    cv=any(f.get('kind')=='file' and re.search(r'\b(?:resume|cv|curriculum)\b',f.get('label',''),re.I) for f in scan.get('fields',[]))
    context=' '.join(str(scan.get(k) or '') for k in ('page_url','title','context'))
    employment=bool(re.search(r'job|career|application|apply|vacante|postul|empleo|candidatura',context,re.I))
    return bool(names and mail and (cv or employment) and not scan.get('password'))


def job_identity(job,url,scan):
    company=key(job.get('company'))
    context=' '.join((url,str(scan.get('title','')),str(scan.get('context',''))[:3000]))
    if len(company)<4 or company not in key(context):return False
    stop={'remote','remoto','remota','full','part','time','tiempo','the','and','for','with','from','latam','worldwide','en','de','el','la','a'}
    words=set(re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKD',job.get('title','').lower()))) - stop
    observed=set(re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKD',context.lower())))
    return len(words & observed)>=min(2,len(words)) if words else False


def safe_destination(url):
    from autojob.search.access_policy import remote_ok,paywall_url
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password or not p.hostname or p.port not in (None,443) or remote_ok(url) or paywall_url(url):return False
        host=p.hostname.lower()
        if host in {'localhost','accounts.google.com','login.microsoftonline.com','login.live.com'} or host.endswith(('.localhost','.local')):return False
        try:
            if not ip_address(host).is_global:return False
        except ValueError:pass
        return True
    except ValueError:return False
