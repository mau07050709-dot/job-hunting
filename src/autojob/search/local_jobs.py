"""Ofertas públicas de Saplic. Límites, caché y lectura de JobPosting sin autenticación."""
from contextlib import closing
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import urljoin, urlsplit, urlencode
from urllib.request import Request, urlopen

from lxml import html
from autojob.search.geography import normalize
from autojob.search.onsite import fast_food, service_opportunity, night_status


def fetch_html(url):
    request=Request(url,headers={"User-Agent":"JobHunting/0.3 (public job discovery)","Accept":"text/html"})
    with urlopen(request,timeout=15) as response:
        if urlsplit(response.url).hostname!="saplic.com":
            raise ValueError("La fuente cambió de dominio.")
        content=response.read(2_500_001)
    if len(content)>2_500_000:
        raise ValueError("La página supera el tamaño permitido.")
    return content.decode("utf-8","replace")


def parse_posting(content,url):
    tree=html.fromstring(content)
    postings=[]
    for node in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            data=json.loads(node.text or "")
        except ValueError:
            continue
        items=data if isinstance(data,list) else data.get("@graph",[data])
        postings.extend(item for item in items if isinstance(item,dict) and item.get("@type")=="JobPosting")
    for item in postings:
        location=item.get("jobLocation") or {}
        if isinstance(location,list):
            if len(location)!=1:continue
            location=location[0]
        address=location.get("address") or {}
        company=item.get("hiringOrganization") or {}
        country=address.get("addressCountry")
        if isinstance(country,dict):country=country.get("name")
        if str(country).casefold() not in {"cr","costa rica"}:continue
        city=address.get("addressLocality")
        if not city or not item.get("title") or not company.get("name"):continue
        expires=item.get("validThrough")
        if expires:
            try:
                if datetime.fromisoformat(expires.replace("Z","+00:00"))<datetime.now(timezone.utc):continue
            except (ValueError,TypeError):pass
        # Leer solo la modalidad del encabezado, no la de ofertas similares.
        heading=" ".join(tree.xpath('//h1/following-sibling::*//text()'))
        mode_text=re.search(r"Modalidad:\s*([^·\n]+)",tree.text_content(),re.I)
        mode=normalize(mode_text.group(1)) if mode_text else normalize(heading)
        if "presencial" not in mode or "remoto" in mode:continue
        description=item.get("description") or ""
        salary=item.get("baseSalary") or {}
        amount=salary.get("value") or {}
        if not isinstance(amount,dict):amount={}
        value=amount.get("value")
        if value is None and amount.get("minValue") is not None:
            value=str(amount["minValue"])+"–"+str(amount.get("maxValue") or "")
        yield dict(id=str((item.get("identifier") or {}).get("value") or url),
                   title=item["title"],company=company["name"],url=url,
                   description=description,location=city+", Costa Rica",locality=city,
                   country="Costa Rica",province=address.get("addressRegion"),
                   modality="onsite",modality_evidence=mode_text.group(0) if mode_text else "Presencial publicado",
                   employmentType=item.get("employmentType"),date=item.get("datePosted"),
                   salary=str(value)+" "+str(amount.get("unitText") or "") if value is not None else None,
                   currency=salary.get("currency"),work_hours=item.get("workHours"),
                   local_source=True)


class LocalJobs:
    def __init__(self,jobs,localities,cancel=lambda:False,progress=lambda text:None,fetch=None,max_details=24):
        self.jobs=jobs
        self.localities=localities
        self.cancel=cancel
        self.progress=progress
        self.fetch=fetch or fetch_html
        self.max_details=max_details
        self.errors=[]
        with closing(jobs.db.connect()) as db,db:
            db.execute("CREATE TABLE IF NOT EXISTS local_job_cache(url TEXT PRIMARY KEY,checked REAL,payload TEXT NOT NULL)")

    def page(self,url):
        if self.cancel():return ""
        with closing(self.jobs.db.connect()) as db:
            row=db.execute("SELECT checked,payload FROM local_job_cache WHERE url=?",(url,)).fetchone()
        if row and time.time()-row["checked"]<21600:return row["payload"]
        content=self.fetch(url)
        with closing(self.jobs.db.connect()) as db,db:
            db.execute("INSERT OR REPLACE INTO local_job_cache VALUES(?,?,?)",(url,time.time(),content))
        for _ in range(3):
            if self.cancel():break
            time.sleep(.1)
        return content

    def search(self):
        links={}
        try:
            for city in self.localities:
                if self.cancel():break
                slug=re.sub(r"[^a-z0-9]+","-",normalize(city)).strip("-")
                pages=["https://saplic.com/cr/empleos-en/"+slug,
                       "https://saplic.com/busqueda-ofertas-empleo.php?"+urlencode(dict(pais=51,ciudad=city))]
                for url in pages:
                    page=pages.index(url)+1
                    if self.cancel():break
                    self.progress("Buscando presencial en "+city+" · página "+str(page))
                    try:
                        tree=html.fromstring(self.page(url) or "<html/>")
                    except Exception as exc:
                        self.errors.append("Saplic CR / "+city+": "+type(exc).__name__)
                        if getattr(exc,"code",None) in {401,403,429}:break
                        continue
                    if page==1:
                        # Seguir solo el enlace público de resultados publicado por la fuente.
                        for anchor in tree.xpath('//a[@href]'):
                            target=urljoin("https://saplic.com",anchor.get("href"))
                            if (urlsplit(target).hostname=="saplic.com"
                                and urlsplit(target).path=="/busqueda-ofertas-empleo.php"
                                and "Ver las " in anchor.text_content() and target not in pages):
                                pages.append(target)
                                break
                    for anchor in tree.xpath('//a[starts-with(@href,"/empleo/")]'):
                        link=urljoin("https://saplic.com",anchor.get("href"))
                        title=anchor.text_content().strip()
                        if link in links or not service_opportunity(dict(title=title,company="")):continue
                        if fast_food(dict(title=title,company="")):continue
                        links[link]=title
            ordered=sorted(links,key=lambda link:0 if night_status(dict(title=links[link]))=="NOCTURNO PUBLICADO" else 1)
            for link in ordered[:self.max_details]:
                if self.cancel():break
                self.progress("Leyendo puesto local: "+links[link])
                try:
                    yield from parse_posting(self.page(link),link)
                except Exception as exc:
                    self.errors.append("Saplic CR: "+type(exc).__name__)
                    if getattr(exc,"code",None) in {401,403,429}:break
        except Exception as exc:
            self.errors.append("Saplic CR: "+type(exc).__name__)
