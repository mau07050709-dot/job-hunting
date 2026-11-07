"""Número de WhatsApp y preguntas de uso/consentimiento son datos distintos."""
import re
import phonenumbers
from autojob.profile.answers import norm

def canonical_phone(value):
    try:
        number=phonenumbers.parse(str(value),None)
        return phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.E164) if phonenumbers.is_valid_number(number) else None
    except phonenumbers.NumberParseException:return None

def same_phone(a,b):return bool(canonical_phone(a) and canonical_phone(a)==canonical_phone(b))

def whatsapp_intent(question):
    q=norm(question)
    if not re.search(r'whats\s*app',q):return None
    if re.search(r'consent|permission|authorize|agree|may we|can we|autoriz|consient|acept|allow us',q):return 'consent'
    if re.search(r'prefer|preferred|preference|preferencia',q):return 'preference'
    if re.search(r'number|numero|prefijo|country code',q):return 'number'
    if re.search(r'do you (?:have|use)|have (?:an? )?(?:active )?whatsapp|tienes|dispone|utiliza|cuentas con',q):return 'account'
    return 'unknown'
