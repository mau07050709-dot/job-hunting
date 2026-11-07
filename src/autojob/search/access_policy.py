"""Fuentes excluidas y evidencia explícita de pago; sin evadir barreras."""
import re
from urllib.parse import urlsplit,parse_qs
from html import unescape

def remote_ok(value):
    return 'remoteok' in re.sub(r'\s+','',str(value or '').casefold())

def blocked_source(value):
    compact=re.sub(r'[^a-z0-9]','',str(value or '').casefold())
    return remote_ok(value) or 'weworkremotely' in compact

def paywall_url(url):
    try:p=urlsplit(unescape(url or ''))
    except (ValueError,TypeError):return False
    if (p.hostname or '').lower() not in {'weworkremotely.com','www.weworkremotely.com'}:return False
    query=parse_qs(p.query)
    return (query.get('context')==['paywall'] or bool(query.get('payment_plan')) or
            bool(re.search(r'^/job-seekers/(?:onboarding/step_3|(?:checkout|payment|subscribe|pricing|plans))(?:/|$)',p.path)))

def paywall_page(url,body):
    if paywall_url(url):return True
    if (urlsplit(url).hostname or '').lower() not in {'weworkremotely.com','www.weworkremotely.com'}:return False
    # No basta un anuncio genérico de Premium en el lateral: exigir una ruta
    # de acceso de pago vinculada a una oferta o una declaración de pago para aplicar.
    links=re.findall(r'(?:href|action)=[\"\']([^\"\']+)',body,re.I)
    from urllib.parse import urljoin
    if any(paywall_url(urljoin(url,link)) for link in links):return True
    text=unescape(re.sub('<[^>]+>',' ',body))
    return bool(re.search(r'(?:subscribe|pay|purchase (?:a )?membership|upgrade)[^.!?\n]{0,70}(?:to apply|to view (?:the |full )?job)|(?:paid|premium) membership (?:is )?required to apply|(?:suscr[ií]bete|paga)[^.!?\n]{0,60}para (?:postular|aplicar)',text,re.I))

def excluded_job(job):
    urls=[job.get(k) for k in ('url','application_url','discovery_url')]
    return (blocked_source(job.get('source')) or any(blocked_source(u) or paywall_url(u) for u in urls) or
            job.get('application_access')=='PAGO' or job.get('availability')=='REQUIERE PAGO')
