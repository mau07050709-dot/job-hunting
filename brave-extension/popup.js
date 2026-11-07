const status=document.querySelector('#status');
chrome.storage.local.get(['last','token']).then(async r=>{
 if(!r.token){status.textContent='Vincula la extensión una vez con el código de Job Hunting.';return;}
 try{
  await chrome.runtime.sendMessage({type:'check'});
  status.textContent=r.last||'Vinculada. Selecciona una oferta y pulsa RELLENAR en Job Hunting.';
 }catch{status.textContent='Abre Job Hunting y comprueba la vinculación de la extensión.';}
});
document.querySelector('#connect').onclick=async()=>{
 const token=document.querySelector('#token').value.trim();if(!token)return;
 const r=await chrome.runtime.sendMessage({type:'connect',token});status.textContent=r.ok?'Vinculada. Ya puedes pulsar RELLENAR en Job Hunting.':r.error;
 document.querySelector('#token').value='';
};
document.querySelector('#check').onclick=()=>chrome.runtime.sendMessage({type:'check'}).then(()=>status.textContent='Comprobando la tarea seleccionada…');
