"""Configuración local del video del aviso; nunca incluye datos de candidaturas."""
import json,re
from urllib.parse import urlsplit,parse_qs
from pathlib import Path


def video_id(url):
    p=urlsplit(url.strip())
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):raise ValueError('Utiliza un enlace HTTPS de YouTube.')
    host=(p.hostname or '').lower()
    if host in {'youtube.com','www.youtube.com','m.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com'}:
        value=parse_qs(p.query).get('v',[''])[0] if p.path=='/watch' else p.path.split('/')[-1] if p.path.startswith(('/embed/','/shorts/')) else ''
    elif host=='youtu.be':value=p.path.strip('/')
    else:value=''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',value):raise ValueError('Introduce el enlace de un video concreto de YouTube.')
    return value


class NoticeMedia:
    def __init__(self,path):self.path=Path(path)/'notice-video.json'
    def load(self):
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            return dict(enabled=data.get('enabled') is True,sound=data.get('sound') is True,url='https://www.youtube.com/watch?v='+video_id(data.get('url','')))
        except (ValueError,TypeError,AttributeError,OSError):return dict(enabled=False,sound=False,url='')
    def save(self,url,enabled,sound=None):
        value=video_id(url) if url.strip() else None
        if enabled and not value:raise ValueError('Introduce un enlace o desactiva el video.')
        data=dict(enabled=bool(enabled),sound=self.load()['sound'] if sound is None else bool(sound),url='https://www.youtube.com/watch?v='+value if value else '')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(data),encoding='utf-8');temporary.replace(self.path)
        return data


def video_html(value,sound=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',value):raise ValueError('Video inválido')
    return f"""<!doctype html><html><head><meta name='referrer' content='origin'><style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#212121}}iframe{{position:absolute;width:100%;height:100%;border:0;pointer-events:none}}#hint{{position:absolute;bottom:0;color:white;background:#212121;font:13px sans-serif}}</style></head><body><iframe allow='autoplay; encrypted-media' referrerpolicy='origin' src='https://www.youtube-nocookie.com/embed/{value}?autoplay=1&mute={0 if sound else 1}&controls=0&loop=1&playlist={value}&playsinline=1&enablejsapi=1'></iframe></body></html>"""
