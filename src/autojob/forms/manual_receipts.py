"""Conciliación expresa con un comprobante aportado por el usuario, sin consultar su correo."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from uuid import uuid4
from contextlib import closing
import json,re,shutil
from autojob.forms.confirmations import ACK
from autojob.profile.answers import norm
from autojob.storage.database import utc_now

def incorporate(store,attempt_id,path,received_at,channel,reference='',reviewed=False):
    if reviewed is not True or channel not in {'Correo','Portal'}:raise ValueError('Revisa y confirma que el comprobante es legítimo y corresponde exactamente a esta candidatura.')
    attempt=next((r for r in store.rows() if r['id']==attempt_id),None)
    if not attempt or attempt['state']!='ENVÍO NO VERIFICADO':raise ValueError('Solo se concilia un intento incierto existente; nunca se crea otro envío.')
    job=next(j for j in store.prep.compatibility.jobs.list() if j['id']==attempt['job_id'])
    try:
        when=datetime.fromisoformat(received_at);start=datetime.fromisoformat(attempt['started_at'])
        if when.tzinfo is None or when<start-timedelta(minutes=5) or when>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError()
    except (ValueError,TypeError):raise ValueError('Fecha de recepción inválida: incluye zona horaria y una fecha posterior al intento, sin fechas futuras.') from None
    source=Path(path);extension=source.suffix.lower()
    if extension not in {'.txt','.eml','.pdf','.png','.jpg','.jpeg'} or not source.is_file() or not 0<source.stat().st_size<=15000000:raise ValueError('Selecciona un comprobante de correo o portal válido, de hasta 15 MB.')
    data=source.read_bytes();text=''
    if extension=='.txt':text=data.decode('utf-8-sig')
    elif extension=='.eml':
        from email.parser import BytesParser
        from email.policy import default
        message=BytesParser(policy=default).parsebytes(data)
        if not message.get('From') or not message.get('Date') or not message.get('Subject'):raise ValueError('El correo no conserva sus encabezados de origen.')
        text=str(message['Subject'])+'\n'+'\n'.join(str(part.get_content()) for part in message.walk() if part.get_content_type() in {'text/plain','text/html'} and not part.get_content_disposition()=='attachment')
    elif extension=='.pdf':
        from pypdf import PdfReader
        try:text='\n'.join(page.extract_text() or '' for page in PdfReader(source).pages)
        except Exception:raise ValueError('El PDF no es legible.') from None
    else:
        from PySide6.QtGui import QImage
        if QImage(str(source)).isNull():raise ValueError('La imagen no es legible.')
    if text:
        from html import unescape
        text=unescape(re.sub('<[^>]+>',' ',text))
        if not ACK.search(text) or norm(job['company']) not in norm(text) or norm(job['title']) not in norm(text):raise ValueError('El texto no acredita recepción de esta empresa y este puesto. Revisa el comprobante correcto.')
    elif extension in {'.txt','.eml'}:raise ValueError('El comprobante no contiene una confirmación de recepción.')
    if reference and not re.fullmatch(r'[A-Za-z0-9_-]{3,128}',reference):raise ValueError('El identificador debe ser el del portal; déjalo vacío si no existe.')
    private=store.data_path/'receipts';private.mkdir(exist_ok=True);target=private/(uuid4().hex+extension);shutil.copy2(source,target)
    digest=sha256(data).hexdigest();evidence=dict(mode=attempt['mode'],verified=True,receipt_id=reference or None,evidence_id=uuid4().hex,source='MANUAL_USUARIO',manual_checked=True,receipt_file=str(target.relative_to(store.data_path)),receipt_file_sha256=digest,receipt_channel=channel,received_at=when.isoformat(),confirmed_at=utc_now(),cv_id=attempt['evidence'].get('cv_id'),previous_evidence=attempt['evidence'])
    store.finish(attempt_id,'ENVIADA CONFIRMADA',evidence);store.event(attempt_id,job['id'],'ENVIADA CONFIRMADA','COMPROBANTE_APORTADO_REVISADO_POR_USUARIO')
    from autojob.control import ControlStore
    controls=ControlStore(store.data_path)
    for intervention in controls.interventions():
        if intervention['job_id']==job['id'] and intervention['kind']=='COMPROBANTE NO VERIFICADO' and intervention['state'] in {'PENDIENTE','POSPUESTA'}:controls.intervention_state(intervention['id'],'RESUELTA')
    return evidence
