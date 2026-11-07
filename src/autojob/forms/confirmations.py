"""Evidencia de recepción mínima: no almacena el contenido del formulario."""
import re
from urllib.parse import urlsplit,urldefrag

ACK=re.compile(r'(?:we\s+have\s+received|we\s+received)\s+your\s+application|(?:your\s+)?application\s+(?:(?:has\s+been|was|is)\s+)?(?:successfully\s+)?(?:received|submitted|accepted)|(?:thank\s+you|thanks)\s+for\s+(?:applying|your\s+application)|solicitud\s+(?:(?:ha\s+sido|fue)\s+)?(?:recibida|enviada|registrada)|postulaci[oó]n\s+recibida',re.I)
REJECT=re.compile(r'application\s+(?:was\s+)?(?:not\s+(?:submitted|accepted)|rejected)|(?:unable|failed)\s+to\s+submit|no\s+(?:se\s+pudo|fue\s+posible)\s+enviar',re.I)
IDENTIFIER=re.compile(r'[A-Za-z0-9_-]{3,128}')

def response_signal(status,data=None):
    """Clasificar solo claves de aceptación/rechazo; nunca persistir cuerpos o errores libres."""
    result=dict(status=int(status),accepted=False,rejected=False,receipt_id=None)
    if not isinstance(data,dict):return result
    success=data.get('success');state=str(data.get('status') or '').casefold()
    rejected=success is False or state in {'rejected','validation_error','invalid','failed','error'} or bool(data.get('errors') or data.get('error'))
    accepted=success is True or state in {'accepted','submitted','received','success'}
    receipt=data.get('application_id') or data.get('applicationId') or data.get('confirmationId') or data.get('receipt_id')
    if isinstance(data.get('application'),dict):
        application=data['application'];state=str(application.get('status') or '').casefold();accepted=accepted or state in {'submitted','received','accepted'};receipt=receipt or application.get('id')
    if receipt is not None and IDENTIFIER.fullmatch(str(receipt)):result['receipt_id']=str(receipt)
    result.update(accepted=bool(200<=status<300 and accepted and not rejected),rejected=bool(rejected));return result

def detect(text,url,signals,request_released,receipt_id=None,expected_confirmation=None):
    ack=ACK.search(text or '');negative=REJECT.search(text or '')
    positive=[r for r in signals if 200<=r['status']<400]
    explicit_reject=any(r.get('rejected') for r in signals) or bool(negative)
    confirmed_json=any(r.get('accepted') for r in positive)
    identifier=receipt_id or next((r.get('receipt_id') for r in positive if r.get('receipt_id')),None)
    expected=bool(expected_confirmation and urldefrag(url)[0].rstrip('/')==urldefrag(expected_confirmation)[0].rstrip('/'))
    thanks=bool(re.search(r'^\s*(?:thank\s+you|thanks|gracias)\s*[!.]?\s*$',text or '',re.I))
    confirmed=bool(request_released and positive and not explicit_reject and (ack or (identifier and confirmed_json) or (expected and confirmed_json and thanks)))
    state='ENVIADA CONFIRMADA' if confirmed else 'RECHAZADA' if request_released and explicit_reject and not ack else 'ENVÍO NO VERIFICADO'
    return dict(state=state,transmission=('CON RESPUESTA HTTP' if signals else 'INICIADA SIN RESPUESTA') if request_released else 'NO OBSERVADA',verified=confirmed,receipt_id=str(identifier) if identifier else None,confirmation_kind='MENSAJE VISIBLE' if confirmed and ack else 'ACEPTACIÓN E IDENTIFICADOR' if confirmed and identifier else 'RUTA NATIVA Y ACEPTACIÓN' if confirmed else None,phrase=ack.group(0) if confirmed and ack else None,http_response_statuses=[r['status'] for r in signals],portal_rejected=bool(explicit_reject),url=url.split('?')[0].split('#')[0])

def observe_response(response,endpoint):
    if response.request.method!='POST' or urldefrag(response.url)[0]!=endpoint:return None
    data=None
    try:
        if 'json' in response.headers.get('content-type',''):
            body=response.body()
            if len(body)<=65536:
                import json
                data=json.loads(body)
    except Exception:pass
    return response_signal(response.status,data)

def collect(page,guard,entries=None):
    text=page.locator('body').inner_text(timeout=2500);receipt=None
    element=page.locator('[data-application-id],[data-confirmation-id]')
    if element.count()==1:
        receipt=element.get_attribute('data-application-id') or element.get_attribute('data-confirmation-id')
        if not receipt or not IDENTIFIER.fullmatch(receipt):receipt=None
    # Texto completo solo en memoria: la evidencia persistida contiene únicamente una frase reconocida.
    result=detect(text,page.url,guard.acceptance_signals,guard.used,receipt,getattr(guard,'confirmation_url',None))
    from autojob.forms.validation import visible_errors,form_state
    result['visible_notices']=visible_errors(page);result['form_state']=form_state(page,entries)
    if result['state']!='ENVIADA CONFIRMADA' and guard.used and any(n['kind']=='VALIDACIÓN VISIBLE' for n in result['visible_notices']):result.update(state='RECHAZADA',portal_rejected=True,rejection_kind='VALIDACIÓN VISIBLE EN LA RESPUESTA')
    result['invalid_field_count']=page.locator('[aria-invalid=true],input:invalid,select:invalid,textarea:invalid').count()
    return result
