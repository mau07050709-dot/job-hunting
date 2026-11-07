"""Contrastar el POST nativo con el FormData revisado, solo en memoria."""
from email.parser import BytesParser
from email.policy import default
from urllib.parse import parse_qsl
from hashlib import sha256

TOKENS={'h-captcha-response','g-recaptcha-response','cf-turnstile-response'}

def capture(button):
    return button.evaluate(r"""async e=>{
      const form=e.form||e.closest('form'),tokens=new Set(['h-captcha-response','g-recaptcha-response','cf-turnstile-response']);
      const read=()=>Array.from(new FormData(form).entries()).filter(([n])=>!tokens.has(n)).map(([n,v])=>[n,typeof v==='string'?v:[v.name,v.size]]);
      const files=Array.from(form.querySelectorAll('input[type=file]')).map(node=>({node,files:Array.from(node.files)}));
      const baseline=JSON.stringify(read());
      const valid=()=>form.checkValidity()&&JSON.stringify(read())===baseline&&files.every(r=>r.files.length===r.node.files.length&&r.files.every((f,i)=>f===r.node.files[i]));
      const check=event=>{if(!valid()){event?.preventDefault();event?.stopImmediatePropagation();window.__autojobFormChanged=true;return false;}return true;};
      form.addEventListener('submit',check,true);form.addEventListener('submit',check,false);
      const nativeSubmit=form.submit.bind(form);form.submit=()=>{if(check())nativeSubmit();};
      const result=[];
      for(const [name,v] of new FormData(form).entries()){
        if(typeof v==='string')result.push({name,value:v,file:null});
        else{
          const digest=await crypto.subtle.digest('SHA-256',await v.arrayBuffer());
          result.push({name,value:null,file:{name:v.name,size:v.size,sha256:Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('')}});
        }
      }
      return result;
    }""")

def verify(request,expected,cv_hash,require_hcaptcha=False):
    content=request.headers.get('content-type','');raw=request.post_data_buffer
    if raw is None:return False,'CUERPO NO DISPONIBLE'
    actual=[]
    try:
        if content.lower().startswith('multipart/form-data'):
            message=BytesParser(policy=default).parsebytes(('Content-Type: '+content+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
            if not message.is_multipart():return False,'MULTIPART NO VÁLIDO'
            for part in message.iter_parts():
                name=part.get_param('name',header='content-disposition');body=part.get_payload(decode=True) or b'';filename=part.get_filename()
                actual.append(dict(name=name,value=body.decode('utf-8').replace('\r\n','\n') if filename is None else None,file=dict(name=filename,size=len(body),sha256=sha256(body).hexdigest()) if filename is not None else None))
        elif content.lower().startswith('application/x-www-form-urlencoded'):actual=[dict(name=k,value=v.replace('\r\n','\n'),file=None) for k,v in parse_qsl(raw.decode('utf-8'),keep_blank_values=True)]
        else:return False,'TIPO DE CUERPO NO REVISADO'
    except Exception:return False,'CUERPO NO INTERPRETABLE'
    if require_hcaptcha and not any(p['name']=='h-captcha-response' and str(p.get('value') or '').strip() for p in actual):return False,'CAPTCHA HUMANO PENDIENTE'
    def grouped(parts):
        result={}
        for p in parts:
            if p['name'] in TOKENS:continue
            f=p.get('file');v=p.get('value')
            value=('file',f['name'],f['size']) if f else ('value',str(v or '').replace('\r\n','\n'))
            result.setdefault(p['name'],[]).append(value)
        return {k:sorted(v) for k,v in result.items()}
    omitted=False
    # CDP omite los bytes de archivos de formularios nativos. El File real ya se
    # verificó en el navegador y el guard DOM impide sustituirlo antes de submit.
    for part in actual:
        file=part.get('file')
        if file and file['size']==0 and file['name'] and getattr(request,'resource_type',None)=='document':
            matches=[p['file'] for p in expected if p['name']==part['name'] and p.get('file') and p['file']['name']==file['name'] and p['file']['size']>0]
            if len(matches)==1 and matches[0].get('sha256')==cv_hash:
                file.update(size=matches[0]['size'],omitted_by_cdp=True);omitted=True
    if grouped(actual)!=grouped(expected):return False,'EL POST CAMBIÓ DESPUÉS DE LA VALIDACIÓN'
    files=[p['file'] for p in actual if p.get('file') and p['file']['size']]
    if not any(f.get('sha256')==cv_hash or f.get('omitted_by_cdp') for f in files):return False,'CV DISTINTO DEL AUTORIZADO O AUSENTE'
    return True,'CAMPOS POST CONTRASTADOS; CV VERIFICADO EN EL NAVEGADOR' if omitted else 'POST Y CV CONTRASTADOS'
