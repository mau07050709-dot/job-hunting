const BASE='http://127.0.0.1:18746';
let busy=false,runRequested=false;
async function api(path,body={}){
  const {token}=await chrome.storage.local.get('token');if(!token)throw Error('Vincula la extensión con Job Hunting.');
  const r=await fetch(BASE+path,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(body),signal:AbortSignal.timeout(25000)});
  const data=await r.json();if(!r.ok)throw Error(data.error||'Puente local no disponible');return data;
}
function applyEntries(entries,expectedUrl){
  if(location.href!==expectedUrl)return {pending:['La página cambió durante el análisis'],filled:[]};
  const pending=[],filled=[];
  const legal=/\b(i accept|i agree|i certify|i attest|acepto|certifico|declaro|signature|firma|terms|terminos|privacy|privacidad|consent)\b/i;
  for(const e of entries){
    try{
      const nodes=document.querySelectorAll(e.selector);if(nodes.length!==1){pending.push(e.label);continue;}
      const el=nodes[0];if(el.disabled||(!el.getClientRects().length&&!(el.type==='file'&&e.document==='cv'&&el.closest('[data-fabric-component=FileUpload]')?.getClientRects().length))||legal.test(e.label+' '+(e.group||''))){pending.push(e.label);continue;}
      // Nunca botones, contraseñas, identidad ni clic de envío.
      if(!['INPUT','TEXTAREA','SELECT'].includes(el.tagName)||['submit','button','reset','password','hidden'].includes(el.type)){pending.push(e.label);continue;}
      const value=String(e.answer),valid=!el.willValidate||el.validity.valid;
      if(el.type==='file'){
        if(el.files?.length)continue;
        if(e.document!=='cv'||!e.file||e.file.data.length>7*1024*1024){pending.push(e.label);continue;}
        const accepts=el.accept.split(',').map(x=>x.trim().toLowerCase()).filter(Boolean);
        if(accepts.length&&!accepts.some(a=>a===e.file.type||a==='*/*'||a.startsWith('.')&&e.file.name.toLowerCase().endsWith(a))){pending.push(e.label);continue;}
        const bytes=Uint8Array.from(atob(e.file.data),c=>c.charCodeAt(0));
        const transfer=new DataTransfer();transfer.items.add(new File([bytes],e.file.name,{type:e.file.type}));el.files=transfer.files;
        if(el.files.length!==1||el.files[0].size!==bytes.length){pending.push(e.label);continue;}
      }else if(el.type==='radio'||el.type==='checkbox'){
        const bool=v=>/^(yes|si|sí|true)$/i.test(v)?true:/^(no|false)$/i.test(v)?false:null;
        if(el.type==='radio'){
          const group=Array.from(document.querySelectorAll('input[type=radio]')).filter(x=>x.name===el.name);
          if(group.some(x=>x.checked))continue;
          if(e.label!==value&&!(bool(value)!==null&&bool(e.label)===bool(value)))continue;
          el.checked=true;
        }else{
          if(el.checked)continue;
          if(bool(value)!==true){if(bool(value)===null)pending.push(e.label);continue;}el.checked=true;
        }
      }else if(el.tagName==='SELECT'){
        if(el.value&&valid)continue;
        const requested=el.multiple?value.split('|').map(x=>x.trim()):[value];
        const options=Array.from(el.options).filter(o=>requested.includes(o.text.trim())||requested.includes(o.value));
        if(options.length!==requested.length||options.some(o=>o.disabled)){pending.push(e.label);continue;}
        for(const o of el.options)o.selected=options.includes(o);
      }else{
        if(el.value&&!(el.type==='tel'&&/^\+\d{1,3}$/.test(el.value)&&value.startsWith(el.value)&&document.activeElement!==el)){
          if(!valid)pending.push(e.label);
          continue;
        }
        const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);
        if(el.value!==value){pending.push(e.label);continue;}
      }
      el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
      if(el.willValidate&&!el.validity.valid)pending.push(e.label);else filled.push(e.selector);
    }catch{pending.push(e.label);}
  }
  return {pending,filled};
}

async function watches(){return (await chrome.storage.session.get('watches')).watches||{};}
async function watch(tabId,task){
  const all=await watches();all[tabId]={id:task.id,url:task.url,owner:task.owner,until:Date.now()+1800000};
  await chrome.storage.session.set({watches:all});
}
async function scan(tabId){
  return (await scanDocument(tabId)).result;
}
async function scanDocument(tabId){
  let documents;
  try{
    await chrome.scripting.executeScript({target:{tabId,allFrames:true},files:['scanner.js']});
    documents=await chrome.scripting.executeScript({target:{tabId,allFrames:true},func:()=>globalThis.scanJobMaxxing()});
  }catch{
    await chrome.scripting.executeScript({target:{tabId},files:['scanner.js']});
    documents=await chrome.scripting.executeScript({target:{tabId},func:()=>globalThis.scanJobMaxxing()});
  }
  documents=documents.filter(d=>d.result?.fields);
  const top=documents.find(d=>d.frameId===0)?.result;
  const score=d=>(candidateReady(d.result)?1000:0)+d.result.fields.length;
  const selected=documents.slice(0,12).sort((a,b)=>score(b)-score(a))[0];
  if(!selected)throw Error('No pude leer el documento activo');
  selected.top=top;return selected;
}
function candidateReady(data){
  const clean=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]/g,'');
  const fields=data.fields.filter(f=>!f.disabled&&f.visible!==false);
  const identity=fields.some(f=>/fullname|firstname|givenname|nombre|apellido/.test(clean(f.label+' '+f.name+' '+f.autocomplete)));
  return !data.password&&identity&&fields.some(f=>f.kind==='email'||/email|correo/.test(clean(f.label+' '+f.name)));
}
function likelyTask(task,tab){
  const clean=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]/g,'');
  const company=clean(task.company),where=clean(tab.url+' '+tab.title);
  return company.length>=4&&where.includes(company);
}
async function authorizeDocument(task,tab,document,landing=false){
  if(document.frameId===0&&await permitted(task,tab.url))return true;
  return (await api('/adopt',{id:task.id,url:document.result.page_url,scan:document.result,
    parent_url:document.frameId?tab.url:null,parent_scan:document.top,landing})).allowed;
}
function fingerprint(url,data){
  return url+'|'+JSON.stringify(data.captcha||{})+'|'+data.fields.map(
    f=>[f.selector,f.label,f.kind,f.required,f.disabled,f.options?.length,f.has_value,f.valid].join(':')
  ).join('|');
}
function applicationEntry(action='scan',selector){
  const visible=e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
  const identity=Array.from(document.querySelectorAll('input,textarea')).some(e=>
    visible(e)&&(['password','file'].includes(e.type)||/first.?name|full.?name|nombre|apellido/i.test(e.name+' '+e.id+' '+e.getAttribute('autocomplete'))));
  if(identity)return action==='scan'?[]:false;
  const exact=/^(?:apply(?: now| for (?:this )?(?:job|position))?|aplicar(?: ahora)?|postular(?:me| ahora)?|solicitar(?: puesto| empleo| este trabajo)?)\s*(?:→|↗)?$/i;
  const path=e=>{
    if(e.id&&document.querySelectorAll('#'+CSS.escape(e.id)).length===1)return '#'+CSS.escape(e.id);
    const parts=[];
    while(e&&e.tagName!=='HTML'){
      const siblings=Array.from(e.parentElement?.children||[]).filter(s=>s.tagName===e.tagName);
      parts.unshift(e.tagName.toLowerCase()+':nth-of-type('+(siblings.indexOf(e)+1)+')');
      e=e.parentElement;
    }
    return parts.join(' > ');
  };
  const hiddenForm=Array.from(document.querySelectorAll('form')).some(form=>
    !visible(form)&&form.querySelector('input[type="email"],input[type="file"]'));
  const candidates=Array.from(document.querySelectorAll('a[href],button')).filter(e=>
    visible(e)&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&
    !e.closest('iframe,[data-sitekey],#jm-fill-notice')&&exact.test((e.innerText||e.value||'').trim())&&
    !(e.tagName==='BUTTON'&&(e.type!=='button'||!hiddenForm))&&!e.getAttribute('form')&&
    (!e.closest('form')||e.type==='button'));
  const entries=candidates.map(e=>({selector:path(e),label:(e.innerText||e.value).trim(),url:e.tagName==='A'?e.href:null}));
  if(action==='scan')return entries;
  if(entries.length!==1||entries[0].selector!==selector||entries[0].url)return false;
  candidates[0].click();
  return true;
}
function sameOffer(a,b){
  try{
    const first=new URL(a),second=new URL(b);
    return first.origin===second.origin&&first.pathname.replace(/\/$/,'')===second.pathname.replace(/\/$/,'')&&first.search===second.search;
  }catch{return false;}
}
async function permitted(task,url){
  if((await api('/scope',{id:task.id,url})).allowed)return true;
  return (await api('/entry',{id:task.id,url})).allowed;
}
async function observe(tabId,task,frameId=0){
  await chrome.scripting.executeScript({target:{tabId,frameIds:[frameId]},func:id=>{
    if(window.__jmWatch?.id===id)return;
    window.__jmWatch?.observer.disconnect();
    clearInterval(window.__jmWatch?.interval);
    window.__jmWatch?.controller?.abort();
    const controller=new AbortController();
    let last='',timer;
    const until=Date.now()+1800000;
    const signature=()=>{
      const data=globalThis.scanJobMaxxing();
      return location.href+'|'+JSON.stringify(data.captcha)+'|'+data.fields.map(
        e=>[e.selector,e.label,e.kind,e.required,e.disabled,e.options?.length,e.has_value,e.valid].join(':')
      ).join('|');
    };
    const send=()=>{
      const now=signature();
      if(now===last)return;
      last=now;
      chrome.runtime.sendMessage({type:'formChanged',id}).catch(()=>{});
    };
    const observer=new MutationObserver(()=>{
      clearTimeout(timer);
      timer=setTimeout(send,600);
    });
    last=signature();
    observer.observe(document,{subtree:true,childList:true,attributes:true,
      attributeFilter:['required','aria-label','hidden','style','disabled','aria-expanded']});
    // Solo se lee el estado público de ESTA candidatura. Nunca se resuelve el desafío.
    const responseState=()=>Array.from(document.querySelectorAll(
      '[name="g-recaptcha-response"],[name="h-captcha-response"],[name="cf-turnstile-response"]'
    )).some(e=>!!e.value?.trim());
    let lastResponse=responseState();
    const interval=setInterval(()=>{
      if(Date.now()>until){clearInterval(interval);observer.disconnect();controller.abort();return;}
      chrome.runtime.sendMessage({type:'visualTick',id,title:document.title,height:innerHeight,captcha:globalThis.scanJobMaxxing().captcha.pending}).catch(()=>{});
      const response=responseState();
      if(response!==lastResponse){lastResponse=response;send();}
    },1500);
    const changed=()=>{clearTimeout(timer);timer=setTimeout(send,600);};
    document.addEventListener('input',changed,{signal:controller.signal});
    document.addEventListener('change',changed,{signal:controller.signal});
    window.__jmWatch={id,observer,interval,controller};
  },args:[task.id]});
}
async function fillTask(task,tab){
  let filled=new Set(),pending=[];
  try{
    let hops=0,data,current;
    const deadline=Date.now()+15000;
    while(Date.now()<deadline){
      current=await chrome.tabs.get(tab.id);
      if(!current.url || (current.pendingUrl && current.pendingUrl!==current.url)){
        await new Promise(r=>setTimeout(r,150));continue;
      }
      try{const document=await scanDocument(tab.id);data=document.result;
        if(!await authorizeDocument(task,current,document,true)){
          if(current.status!=='complete'||!data.fields.length){await new Promise(r=>setTimeout(r,300));continue;}
          throw Error('Detecté una página distinta; no pude vincularla con la empresa y puesto seleccionados.');
        }}catch(error){
        if(current.status==='complete')throw error;
        await new Promise(r=>setTimeout(r,150));continue;
      }
      if(candidateReady(data))break;
      if(data.captcha?.pending)break;
      if(hops<3){
        const [{result:entries}]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:applicationEntry});
        if(entries.length===1){
          const entry=entries[0];
          if(entry.url&&entry.url!==current.url&&(await permitted(task,entry.url)||(await api('/follow',{id:task.id,from_url:current.url,url:entry.url,label:entry.label})).allowed)){
            await chrome.tabs.update(tab.id,{url:entry.url});
            hops++;
            await new Promise(r=>setTimeout(r,200));
            continue;
          }
          if(!entry.url){
            const [{result:clicked}]=await chrome.scripting.executeScript({
              target:{tabId:tab.id},func:applicationEntry,args:['click',entry.selector]
            });
            if(clicked){
              hops++;
              await new Promise(r=>setTimeout(r,400));
              continue;
            }
          }
        }
      }
      await new Promise(r=>setTimeout(r,400));
    }
    for(let round=0;round<4;round++){
      current=await chrome.tabs.get(tab.id);
      const scanned=await scanDocument(tab.id);
      data=scanned.result;
      if(!await authorizeDocument(task,current,scanned))throw Error('No pude vincular este formulario con la candidatura seleccionada.');
      const plan=await api('/plan',{id:task.id,url:data.page_url,scan:data});
      const [{result:out}]=await chrome.scripting.executeScript({
        target:{tabId:tab.id,documentIds:[scanned.documentId]},func:applyEntries,args:[plan.entries,data.page_url]
      });
      out.filled.forEach(x=>filled.add(x));pending=[...plan.pending,...out.pending];
      if(plan.waiting)pending.push(data.captcha?.pending?'Resuelve el CAPTCHA en esta pestaña de Brave; continuaré al cambiar el formulario':'No encontré una entrada Apply segura; abre el formulario en esta pestaña y continuaré al detectarlo');
      if(!out.filled.length)break;
      await new Promise(r=>setTimeout(r,220));
    }
    // Queda reservada SOLO esta pestaña. No observa otras pestañas personales.
    const observedDocument=await scanDocument(tab.id);const observed=observedDocument.result;const all=await watches();if(all[tab.id]){all[tab.id].fingerprint=fingerprint(current.url,observed);await chrome.storage.session.set({watches:all});}
    await observe(tab.id,task,observedDocument.frameId);
    const verified=observed.fields.filter(f=>filled.has(f.selector)&&f.has_value&&f.valid).length;
    const result=await api('/done',{id:task.id,url:current.url,filled:verified,pending:[...new Set(pending)]});
    await chrome.storage.local.set({last:result.message});
    await chrome.scripting.executeScript({target:{tabId:tab.id},func:(message,expectedUrl)=>{
      if(location.href!==expectedUrl)return;
      document.getElementById('jm-fill-notice')?.remove();const box=document.createElement('div');box.id='jm-fill-notice';box.textContent='Job Hunting: '+message;
      Object.assign(box.style,{position:'fixed',bottom:'12px',right:'12px',maxWidth:'440px',padding:'16px',background:'#14283d',color:'white',zIndex:'2147483647',font:'15px sans-serif',border:'2px solid #64b5f6'});
      const close=document.createElement('button');close.textContent='Cerrar aviso';close.onclick=()=>box.remove();box.append(document.createElement('br'),close);document.documentElement.append(box);
    },args:[result.message,current.url]});
  }catch(error){
    try{await api('/done',{id:task.id,filled:filled.size,pending:[error.message]});}catch{}
    await chrome.storage.local.set({last:error.message});
  }
}
const wakeTabs=new Set();
async function run(){
  if(busy){runRequested=true;return;}busy=true;
  try{
    const task=await api('/next');
    if(!task.id){
      for(const id of wakeTabs){
        wakeTabs.delete(id);
        const marker=await chrome.tabs.get(id).catch(()=>null);
        if(marker?.url===BASE+'/jobmaxxing-wake')await chrome.tabs.remove(id).catch(()=>{});
      }
      return;
    }
    const allWatches=await watches();
    const tabs=await chrome.tabs.query({});
    let prepared;
    for(const possible of tabs.filter(t=>!t.incognito&&likelyTask(task,t))){
      const ownership=allWatches[possible.id];if(ownership&&ownership.owner!==task.owner)continue;
      try{const document=await scanDocument(possible.id);if(candidateReady(document.result)&&await authorizeDocument(task,possible,document)){prepared=possible;break;}}catch{}
    }
    const existing=prepared||tabs.find(t=>!t.incognito&&
      (allWatches[t.id]?.id===task.id||
       ((!allWatches[t.id]||allWatches[t.id].owner===task.owner)&&
        (sameOffer(t.url,task.url)||sameOffer(t.pendingUrl,task.url)))));
    const tab=existing?await chrome.tabs.update(existing.id,{active:true}):await chrome.tabs.create({url:task.url,active:true});
    await chrome.windows.update(tab.windowId,{focused:true});
    const wakeTab=wakeTabs.values().next().value;
    if(wakeTab!==undefined){
      wakeTabs.delete(wakeTab);
      const marker=await chrome.tabs.get(wakeTab).catch(()=>null);
      if(marker?.url===BASE+'/jobmaxxing-wake')await chrome.tabs.remove(wakeTab).catch(()=>{});
    }
    await watch(tab.id,task);await fillTask(task,tab);
  }catch(error){wakeTabs.clear();await chrome.storage.local.set({last:error.message});}
  finally{busy=false;if(runRequested||wakeTabs.size){runRequested=false;setTimeout(run,50);}}
}
const pendingTabs=new Set();
async function resumeTab(tabId){
  if(busy){pendingTabs.add(tabId);setTimeout(drain,1000);return;}
  busy=true;
  try{
    let w=(await watches())[tabId];
    const tab=await chrome.tabs.get(tabId);
    if(tab.status!=='complete')return;
    if(!w){
      if(!tab.active||!(await chrome.windows.get(tab.windowId)).focused||!tab.url?.startsWith('https://'))return;
      for(const task of await api('/active')){
        if(!likelyTask(task,tab))continue;
        const document=await scanDocument(tabId);
        if(candidateReady(document.result)&&await authorizeDocument(task,tab,document)){await watch(tabId,task);w=(await watches())[tabId];break;}
      }
    }
    if(!w||w.until<Date.now())return;
    const document=await scanDocument(tabId);
    if(!await authorizeDocument(w,tab,document,true))return;
    const data=document.result;if(fingerprint(tab.url,data)===w.fingerprint)return;
    const task=await api('/resume',{id:w.id,url:tab.url});await fillTask(task,tab);
  }catch(error){await chrome.storage.local.set({last:error.message});}
  finally{busy=false;if(runRequested||wakeTabs.size){runRequested=false;setTimeout(run,50);}}
}
async function drain(){if(busy){setTimeout(drain,1000);return;}const id=pendingTabs.values().next().value;if(id!==undefined){pendingTabs.delete(id);await resumeTab(id);}if(pendingTabs.size)setTimeout(drain,500);}
chrome.windows.onFocusChanged.addListener(async id=>{if(id<0)return;for(const tab of await chrome.tabs.query({windowId:id,active:true})){if(!tab.incognito){pendingTabs.add(tab.id);setTimeout(drain,200);}}});
chrome.tabs.onActivated.addListener(info=>{pendingTabs.add(info.tabId);setTimeout(drain,200);});
chrome.tabs.onUpdated.addListener((id,change)=>{if(change.status==='complete'){pendingTabs.add(id);setTimeout(drain,500);}});
chrome.tabs.onCreated.addListener(async tab=>{if(tab.openerTabId){const w=(await watches())[tab.openerTabId];if(w&&w.until>Date.now())await watch(tab.id,w);}});
chrome.tabs.onRemoved.addListener(async id=>{const all=await watches();delete all[id];await chrome.storage.session.set({watches:all});pendingTabs.delete(id);});
chrome.alarms.create('jobmaxxing',{periodInMinutes:0.5});
async function announce(){
  try{await api('/ping',{fast_wake:true});}catch{}
}
announce();
chrome.runtime.onInstalled.addListener(()=>{announce();run();});
chrome.runtime.onStartup.addListener(()=>{announce();run();});
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='jobmaxxing'){announce();run();}});

chrome.runtime.onMessage.addListener((m,sender,reply)=>{
  if(m.type==='connect'){
    chrome.storage.local.set({token:m.token}).then(()=>api('/ping',{fast_wake:true})).then(()=>{reply({ok:true});run();}).catch(e=>reply({error:e.message}));return true;
  }
  if(m.type==='wake' && sender.tab && sender.frameId===0 && sender.url===BASE+'/jobmaxxing-wake'){
    wakeTabs.add(sender.tab.id);run();
  }
  if(m.type==='check'){run();reply({ok:true});}
  if(m.type==='visualTick'&&sender.tab){
    (async()=>{
      const tab=await chrome.tabs.get(sender.tab.id),w=(await watches())[tab.id];
      if(!w||w.id!==m.id||w.until<Date.now()||!tab.active||!(await chrome.windows.get(tab.windowId)).focused)return;
      if(!await permitted(w,tab.url))return;
      await api('/visual',{id:w.id,url:tab.url,title:tab.title.replace(/ - Brave$/,''),height:m.height,captcha:m.captcha});
      for(const task of await api('/visual-next'))if(task.id===w.id){pendingTabs.add(tab.id);setTimeout(drain,100);}
    })().catch(()=>{});
  }
  if(m.type==='formChanged'&&sender.tab){pendingTabs.add(sender.tab.id);setTimeout(drain,200);}
});
