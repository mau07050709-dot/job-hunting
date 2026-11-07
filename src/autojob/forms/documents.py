"""Reconocer el propósito del adjunto sin inferirlo de su extensión."""
import re
from autojob.profile.answers import norm

def document_kind(field):
    parts=[str(field.get(k) or '') for k in ('label','group','aria_label','aria_labelledby_text','data_ui','name')]
    text=norm(re.sub(r'([a-z])([A-Z])',r'\1 \2',' '.join(parts))).replace('_',' ').replace('-',' ')
    cv=bool(re.search(r'\b(?:resume|cv|curriculum(?: vitae)?)\b',text))
    letter=bool(re.search(r'cover letter|carta de presentacion',text))
    other=bool(re.search(r'passport|identity|national id|identificacion|cedula|certificat|diploma|transcript|photo|fotograf|portfolio|portafolio|additional document|supporting document',text))
    if other or cv and letter:return 'unknown'
    return 'cv' if cv else 'letter' if letter else 'unknown'
