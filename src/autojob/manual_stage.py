"""Etapa humana directa: OTP solo con permiso LOGIN previo; nunca crea cuentas."""
import re
from autojob.forms.guard import PreparationGuard,origin
from autojob.intervention_context import focus

def otp_form(forms):
    candidates=[]
    for form in forms:
        if any(re.search(r'apply|application|postula|contrato|contract|accept|agree|acepto|firma',f.get('label',''),re.I) for f in form['fields'] if f['type'] in {'submit','button'}):continue
        fields=[f for f in form['fields'] if f['type'] not in {'submit','button','hidden'}]
        if form['method'].upper()!='POST' or not fields:continue
        if all(f.get('autocomplete')=='one-time-code' or re.search(r'\b(?:otp|verification code|security code|c[oó]digo)\b',f.get('label',''),re.I) for f in fields):candidates.append(form)
    return candidates[0] if len(candidates)==1 else None

def open_stage(browser,settings,row,context,seconds=None,stop=lambda:False):
    from autojob.auth.service import Accounts
    from autojob.auth.permissions import Permissions,scope
    from autojob.auth.external import AuthGuard,FORM_SCAN,authentication_observation
    accounts=Accounts(settings.data_path);account=next((a for a in accounts.list() if a['origin']==origin(context['url']) and a['domain_verified'] and a['exists_remotely']),None)
    auth_kind=any(k in row['kind'] for k in ['MFA','SMS','CORREO','AUTENTICACIÓN','LOGIN'])
    def allowed():return bool(account and Permissions(settings.data_path).allowed(context['url'],'LOGIN',scope(accounts,accounts.get(account['id']),'LOGIN')))
    guard=AuthGuard(browser,origin(context['url']),allowed) if auth_kind and allowed() else PreparationGuard(browser)
    page=guard.page(context['url']);page.bring_to_front();focused=focus(page,context);armed=False
    if isinstance(guard,AuthGuard):
        form=otp_form(page.evaluate(FORM_SCAN))
        if form:
            try:
                guard.arm(page,form['index'],form['action']);armed=True
                target=page.locator('[autocomplete=one-time-code]')
                if target.count()==1 and target.is_visible():target.focus();focused=True
            except ValueError:pass
    from autojob.live import _lock,_sessions
    from threading import Event
    item=dict(end=Event(),focus=Event(),check=Event(),active=True,proposed={})
    with _lock:
        if row['job_id'] in _sessions:raise ValueError('Sesión ya reservada.')
        _sessions[row['job_id']]=item
    try:
        while not stop() and not item['end'].is_set():
            if page.is_closed():break
            if item['focus'].is_set():page.bring_to_front();focus(page,context);item['focus'].clear()
            if account and armed:
                observation=authentication_observation(page)
                if observation['authenticated']:accounts.observe(account['id'],observation);return dict(focused=focused,authenticated=True)
            page.wait_for_timeout(250)
    finally:
        with _lock:_sessions.pop(row['job_id'],None)
    return dict(focused=focused,authenticated=False,otp_permitted=armed)
