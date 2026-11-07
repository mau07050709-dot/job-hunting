"""Validación del estado real del formulario. Los valores se comparan en memoria."""
import re
from hashlib import sha256

STATE_JS=r'''e=>({tag:e.tagName,type:e.type||e.getAttribute('role')||'',name:e.name||'',required:!!e.required||e.getAttribute('aria-required')==='true',disabled:!!e.disabled,visible:!!(e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'),valid:!e.willValidate||e.validity.valid,invalid:e.getAttribute('aria-invalid')==='true',value:'value' in e?e.value:e.innerText,checked:!!e.checked||e.getAttribute('aria-checked')==='true',selected:e.selectedOptions?Array.from(e.selectedOptions).map(o=>({value:o.value,label:o.label})):[],files:e.files?Array.from(e.files).map(f=>({name:f.name,size:f.size})):[],successful:!!(e.name&&e.form&&!e.disabled&&new FormData(e.form).has(e.name)),submitted:e.name&&e.form?new FormData(e.form).getAll(e.name).map(v=>typeof v==='string'?v:{file:!!v.name,size:v.size}):[],value_missing:!!e.validity?.valueMissing})'''

def visible_errors(page):
    result=[]
    for frame in page.frames:
        from urllib.parse import urlsplit
        host=(urlsplit(frame.url).hostname or '').lower()
        if host=='hcaptcha.com' or host.endswith('.hcaptcha.com'):continue
        try:
            controls=frame.locator('form [role=alert],form .field-error,form .error-message,form .validation-error,form .invalid-feedback,form [aria-invalid=true],.application-error,.application-success,[role=alert]')
            for target in controls.all()[:40]:
                if not target.is_visible():continue
                text=target.inner_text(timeout=1000).strip()
                if not text:continue
                # Los mensajes privados se conservan solo como categorías y huellas, no como texto libre.
                error=bool(re.search(r'required|invalid|must (?:be|provide|select|enter)|please (?:enter|select|provide|upload)|could not|unable|failed|error|obligatorio|inv[aá]lid|debe (?:ingresar|seleccionar)',text,re.I))
                result.append(dict(kind='VALIDACIÓN VISIBLE' if error else 'AVISO VISIBLE',fingerprint=sha256(text.encode()).hexdigest(),length=len(text)))
        except Exception:continue
    return result

def form_state(page,entries=None):
    fields=[]
    for frame_index,frame in enumerate(page.frames):
        try:
            root=frame
            if entries is not None:
                candidates=[e for e in entries if e.get('frame_index',0)==frame_index and e['kind']!='button'];candidates.sort(key=lambda e:e['kind']!='file')
                index=-1
                for entry in candidates:
                    anchor=frame.locator(entry['selector'])
                    if anchor.count()==1:
                        index=anchor.evaluate('(e)=>Array.from(document.forms).indexOf(e.form||e.closest("form"))')
                        if index>=0:break
                if index<0:continue
                root=frame.locator('form').nth(index)
            states=root.locator('input:not([type=hidden]):not([type=submit]):not([type=button]),select,textarea,[aria-required=true]').evaluate_all('(es)=>es.map(e=>({name:e.name||e.id||"",kind:e.type||e.getAttribute("role")||e.tagName,required:!!e.required||e.getAttribute("aria-required")==="true",disabled:!!e.disabled,nonempty:e.type==="file"?!!e.files?.length:(e.type==="radio"||e.type==="checkbox")?e.checked:!!(e.value||e.getAttribute("aria-activedescendant")),valid:(!e.willValidate||e.validity.valid)&&e.getAttribute("aria-invalid")!=="true",selected_count:e.selectedOptions?.length||0}))')
            for state in states:
                state['field_id']=sha256((str(frame_index)+':'+state.pop('name')).encode()).hexdigest()[:20];fields.append(state)
        except Exception:continue
    return dict(field_count=len(fields),required_count=sum(f['required'] and not f['disabled'] for f in fields),invalid_count=sum(not f['valid'] and not f['disabled'] for f in fields),nonempty_count=sum(f['nonempty'] for f in fields),fields=fields)

def audit(page,entries,cv_path=None,uploaded=False):
    from autojob.forms.runner import truth
    errors=[];verified=[]
    for entry in entries:
        if entry['kind']=='button':continue
        field_id=sha256((str(entry.get('frame_index',0))+':'+entry['selector']).encode()).hexdigest()[:20]
        def fail(code):errors.append(dict(code=code,field=entry['label'],field_id=field_id))
        try:
            frame=page.frames[entry.get('frame_index',0)];target=frame.locator(entry['selector'])
            if target.count()!=1:
                if entry.get('required'):fail('CONTROL AUSENTE O AMBIGUO')
                continue
            if entry.get('checkbox_group'):
                expected={a.strip() for a in str(entry.get('answer') or '').split('|')};actual=set();published={o['label'] for o in entry.get('options',[])};success=True
                for option in entry.get('options',[]):
                    box=frame.locator(option['selector'])
                    if box.count()!=1:success=False;continue
                    state=box.evaluate(STATE_JS)
                    if state['checked']:
                        actual.add(option['label']);success=success and state['successful'] and state['value'] in state['submitted']
                if entry.get('status') not in {'CONFIRMADA','DERIVADA'} or not expected<=published or actual!=expected or entry.get('required') and not actual or not success:fail('GRUPO DE CASILLAS SIN VALORES DE ENVÍO VÁLIDOS')
                verified.append(dict(field_id=field_id,kind='multiple',required=bool(entry.get('required')),valid=bool(success and actual==expected),successful=success,nonempty=bool(actual)));continue
            state=target.evaluate(STATE_JS);required=entry.get('required') or state['required']
            if state['disabled']:
                if required:fail('CONTROL OBLIGATORIO DESHABILITADO')
                continue
            if required and (not state['valid'] or state['invalid']):fail('CAMPO OBLIGATORIO INVÁLIDO')
            answer=entry.get('answer');kind=entry['kind'];ready=entry.get('status') in {'CONFIRMADA','DERIVADA'}
            if kind=='file':
                if entry.get('document')=='cv' and cv_path:
                    ok=uploaded or len(state['files'])==1 and state['files'][0]['name']==cv_path.name and state['files'][0]['size']==cv_path.stat().st_size
                    if not ok:fail('CV NO RECONOCIDO')
                elif required and not state['files']:fail('ARCHIVO OBLIGATORIO AUSENTE')
            elif entry.get('requires_specific_consent'):
                expected=entry.get('authorized_answer')
                if expected is None:fail('CONSENTIMIENTO SIN PERMISO ESPECÍFICO')
                elif kind=='checkbox' and not state['checked']:fail('CONSENTIMIENTO NO SELECCIONADO')
                elif kind=='select' and [o['label'] for o in state['selected']]!=[expected]:fail('CONSENTIMIENTO NO CONSERVADO')
            elif entry.get('sensitive_identity'):pass
            elif ready and answer is not None:
                if entry.get('semantic')=='phone_5ca':
                    import phonenumbers
                    hidden=frame.locator('input[name=full_phone]')
                    try:ok=hidden.count()==1 and phonenumbers.format_number(phonenumbers.parse(hidden.input_value(),None),phonenumbers.PhoneNumberFormat.E164)==phonenumbers.format_number(phonenumbers.parse(str(answer),None),phonenumbers.PhoneNumberFormat.E164)
                    except phonenumbers.NumberParseException:ok=False
                elif kind in {'select','multiple'}:
                    expected=[a.strip().casefold() for a in str(answer).split('|')] if kind=='multiple' else [str(answer).strip().casefold()]
                    selected=state['selected'];ok=len(selected)==len(expected) and all(any(a in {o['label'].strip().casefold(),o['value'].casefold()} for o in selected) for a in expected)
                    if state['name'] and {str(v) for v in state['submitted']}!={o['value'] for o in selected}:ok=False
                elif kind=='checkbox':ok=state['checked']==truth(answer)
                elif kind=='radio':
                    same=truth(entry['label'])==truth(answer) if truth(entry['label']) is not None and truth(answer) is not None else entry['label'].strip().casefold()==str(answer).strip().casefold()
                    ok=state['checked']==same
                else:ok=str(state['value']).strip()==str(answer).strip()
                if not ok:fail('VALOR REAL DISTINTO DE LA RESPUESTA CONFIRMADA')
            elif required:fail('RESPUESTA OBLIGATORIA SIN CONFIRMAR')
            if required and state['name'] and state['tag'] in {'INPUT','SELECT','TEXTAREA'} and kind!='radio' and not state['successful'] and not (kind=='file' and uploaded):fail('CAMPO OBLIGATORIO AUSENTE DE LOS DATOS DE ENVÍO')
            verified.append(dict(field_id=field_id,kind=kind,required=bool(required),valid=state['valid'],successful=state['successful'],nonempty=bool(state['value'] or state['files'] or state['checked'])))
        except Exception:fail('NO SE PUDO VERIFICAR EL CONTROL')
    state=form_state(page,entries);notices=visible_errors(page)
    if state['invalid_count']:errors.append(dict(code='FORMULARIO CON CONTROLES INVÁLIDOS',count=state['invalid_count']))
    if any(n['kind']=='VALIDACIÓN VISIBLE' for n in notices):errors.append(dict(code='ERRORES DE VALIDACIÓN VISIBLES'))
    return dict(valid=not errors,errors=errors,fields=verified,form_state=state,notices=notices)
