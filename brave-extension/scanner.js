globalThis.scanJobMaxxing = () => {
 if(/(?:recaptcha|hcaptcha|challenges\.cloudflare)/i.test(location.hostname+location.pathname))return {title:document.title,page_url:location.href,context:'',fields:[],frames:[],text:'',password:false,captcha:{present:true,pending:true}};
 const visible=e=>e.getClientRects().length>0 && getComputedStyle(e).visibility!=='hidden';
 const selector=e=>{if(e.id&&document.querySelectorAll('#'+CSS.escape(e.id)).length===1)return '#'+CSS.escape(e.id);let p=[];while(e&&e.nodeType===1&&e.tagName!=='HTML'){let s=e.tagName.toLowerCase();let same=Array.from(e.parentElement?.children||[]).filter(x=>x.tagName===e.tagName);if(same.length>1)s+=':nth-of-type('+(same.indexOf(e)+1)+')';p.unshift(s);e=e.parentElement;}return p.join(' > ');};
 const nearbyLabel=e=>{
   let node=e.parentElement;
   for(let depth=0;node&&depth<4;depth++,node=node.parentElement){
     const controls=node.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]),textarea,select');
     if(controls.length>1)break;
     const candidates=Array.from(node.querySelectorAll('label,legend,.control-label,.form-label,[data-label]'));
     const found=candidates.map(l=>(l.innerText||l.textContent||'').trim()).find(t=>t&&t.length<400&&!/^(choose file|browse|elegir archivo|seleccionar archivo)/i.test(t));
     if(found)return found;
     const previous=node.previousElementSibling;
     if(previous?.matches('label,legend,.control-label,.form-label'))return previous.innerText.trim();
   }
   if(['checkbox','radio'].includes(e.type)){
     const text=(e.parentElement?.innerText||'').trim();if(text.length<500)return text;
   }
   return '';
 };
 const label=e=>{
   if(e.type==='file'&&e.closest('[data-fabric-component=FileUpload]')?.querySelector('input[name=resumeFileId]'))return 'Resume / CV';
   const labels=e.labels?Array.from(e.labels).map(l=>l.innerText||l.textContent||'').join(' '):'';
   const aria=(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ').trim();
   return (aria||e.getAttribute('aria-label')||labels||nearbyLabel(e)||e.getAttribute('placeholder')||e.getAttribute('name')||e.id||'Sin etiqueta').trim().replace(/^e-mail\b/i,'Email');
 };
 const responsePresent=Array.from(document.querySelectorAll('[name="g-recaptcha-response"],[name="h-captcha-response"],[name="cf-turnstile-response"]')).some(e=>!!e.value?.trim());
 const challengePresent=Array.from(document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"],[data-sitekey]')).some(visible)||/verify you are human|verifica que eres humano/i.test(document.body?.innerText||'');
 const captcha={present:challengePresent,solved:responsePresent,pending:challengePresent&&!responsePresent};
 let controls=Array.from(document.querySelectorAll('input,select,textarea,button,[role="combobox"],[role="checkbox"],[role="radio"],[contenteditable="true"]')).filter(e=>!e.closest('#jm-fill-notice')&&(visible(e)||e.type==='file')&&!['hidden','password'].includes(e.type));
 return {title:document.title,page_url:location.href,context:Array.from(document.querySelectorAll('h1,h2,h3,nav[aria-label*=breadcrumb],[class*=breadcrumb]')).filter(visible).map(e=>e.innerText).join(' ').slice(0,3000),captcha,fields:controls.slice(0,200).map((e,i)=>({id:String(i),visible:visible(e),selector:selector(e),label:label(e),tag:e.tagName.toLowerCase(),kind:e.tagName==='SELECT'?(e.multiple?'multiple':'select'):e.tagName==='TEXTAREA'?'textarea':e.getAttribute('role')||e.type||'text',has_value:e.type==='checkbox'||e.type==='radio'?e.checked:!!e.value?.trim(),valid:!e.willValidate||e.validity.valid,required:e.required||e.getAttribute('aria-required')==='true'||/[*✱]/.test(label(e)),disabled:e.disabled||e.getAttribute('aria-disabled')==='true',options:e.tagName==='SELECT'?Array.from(e.options).map(o=>({label:o.text,value:o.value})):[],group:e.closest('fieldset')?.querySelector('legend')?.textContent||'',name:e.name||'',placeholder:e.getAttribute('placeholder')||'',aria_label:e.getAttribute('aria-label')||'',aria_labelledby_text:(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' '),data_ui:e.getAttribute('data-ui')||'',accept:e.accept||'',autocomplete:e.autocomplete||'',button_text:['BUTTON'].includes(e.tagName)||['submit','button'].includes(e.type)?(e.innerText||e.value||''):''})),text:document.body?.innerText?.slice(0,150000)||'',frames:Array.from(document.querySelectorAll('iframe')).map(e=>({title:e.title,src:e.src,visible:visible(e)})).concat(Array.from(document.querySelectorAll('script[src*="captcha"],[data-sitekey]')).map(e=>({title:'CAPTCHA marker',src:e.src||''}))),password:!!document.querySelector('input[type=password]')};
};