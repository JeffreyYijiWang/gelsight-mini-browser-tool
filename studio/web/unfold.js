import * as THREE from 'three';
import {SurfaceViewer} from './viewer.js';
const $=s=>document.querySelector(s),token=$('meta[name="studio-token"]').content;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let catalog=[],records=[],selected=new Set(),current=null,viewer=null,job=null,view='image',generation=0;
async function api(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'X-Studio-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;}
function status(text,error=false){$('#unfold-status').textContent=text;$('#unfold-status').classList.toggle('error',error);}
const attempt=fn=>async()=>{try{await fn();}catch(error){status(error.message,true);}};
function candidates(){
  const search=$('#source-search').value.toLowerCase(),items=catalog.filter(i=>['frames','patches'].includes(i.kind)&&!i.baseline&&(!i.synthetic||$('#show-fixtures').checked)&&i.name.toLowerCase().includes(search));
  $('#unfold-sources').innerHTML=items.map(i=>`<label><input type="checkbox" data-key="${i.kind}:${i.id}" ${selected.has(i.kind+':'+i.id)?'checked':''}><img loading="lazy" src="/api/typology/thumbnail/${i.kind}/${i.id}" alt="${esc(i.name)}">${esc(i.name)}<small> · ${i.kind}</small></label>`).join('')||'<p>No matching sources. Save a p5 sample or import images in Studio.</p>';
  $('#selection-count').textContent=`${selected.size} selected · maximum 32`;
  $('#unfold-build').disabled=Boolean(job)||selected.size<1||selected.size>32;
  $('#unfold-sources').querySelectorAll('input').forEach(input=>input.onchange=()=>{input.checked?selected.add(input.dataset.key):selected.delete(input.dataset.key);candidates();});
}
async function refresh(){const state=await api('/state');records=state.unfoldings||[];catalog=await api('/typology/items');$('#unfold-saved').innerHTML='<option value="">Choose an assembly</option>'+records.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('');if(current)$('#unfold-saved').value=current.id;candidates();}
async function run(kind,params){
  if(job)throw new Error('Wait for the current job or cancel it.');job=await api('/jobs','POST',{kind,params});$('#unfold-cancel').hidden=false;$('#unfold-progress').hidden=false;candidates();
  try{while(true){const info=await api('/jobs/'+job.id);status(info.message);$('#unfold-progress').value=info.progress;if(info.status==='completed')return info.result;if(['failed','cancelled','interrupted'].includes(info.status))throw new Error(info.message);await new Promise(r=>setTimeout(r,650));}}
  finally{job=null;$('#unfold-cancel').hidden=true;$('#unfold-progress').hidden=true;candidates();}
}
async function show(record){
  current=record;const serial=++generation;viewer?.dispose();viewer=null;if(!record)return;
  const base='/api/files/unfoldings/'+record.id+'/';
  $('#unfold-saved').value=record.id;$('#unfold-interpretation').textContent=record.interpretation;
  $('#unfold-image img').src=base+'flat.png';
  $('#unfold-downloads').innerHTML=`<a class="web-link" href="${base}flat.png" download>Flat image PNG</a><a class="web-link" href="${base}unfolding.json" download>Region / join manifest</a><button type="button" id="unfold-export">Export private bundle</button>`;
  $('#unfold-export').onclick=attempt(async()=>{const result=await run('unfold_export',{id:record.id});const a=document.createElement('a');a.href='/api/downloads/'+result.id;a.download='private-unfolding.zip';a.click();status('Private assembly bundle exported.');});
  $('#unfold-segments').innerHTML=record.sources.map((s,i)=>`<figure><img src="${base}source-${String(i).padStart(2,'0')}.png" alt="${esc(s.name)} source"><img src="${base}segments-${String(i).padStart(2,'0')}.png" alt="Texture groups in ${esc(s.name)}"><figcaption>${esc(s.name)}</figcaption></figure>`).join('');
  $('#unfold-report').hidden=false;$('#unfold-report').innerHTML=`<h3>${record.regions.length} connected regions · ${record.settings.groups} texture groups</h3><p>Colors in the separated view indicate appearance clusters. Small fragments are excluded; original inputs remain unchanged. No proposed join is treated as verified overlap.</p><ul>${record.coverage.map(c=>`<li>${esc(record.sources[c.source].name)}: ${(c.fraction*100).toFixed(1)}% of valid analysis pixels retained; ${record.sources[c.source].depth_present?'relative relief available':'RGB only; zero relief'}</li>`).join('')}</ul><details><summary>Proposed neighboring joins and relative edge costs</summary><ul>${record.seams.filter(s=>s.left!==null||s.above!==null).map(s=>`<li>Cell ${s.cell+1}: ${[s.left===null?'':`left ${s.left+1}`,s.above===null?'':`above ${s.above+1}`].filter(Boolean).join(', ')} · cost ${s.cost.toFixed(3)} · inferred</li>`).join('')}</ul></details>`;
  const surface=await(await fetch(base+'surface.json')).json();if(serial!==generation)return;
  viewer=new SurfaceViewer($('#unfold-viewer'),{onStatus:t=>$('#unfold-geometry').textContent=t});viewer.setSurface(surface,{shape:'flat',mode:'displacement',strength:Number($('#unfold-relief').value),color:'#ffffff',quality:192});
  if(!viewer.failed){const thisViewer=viewer,texture=await new THREE.TextureLoader().loadAsync(base+'flat.png');if(serial!==generation){texture.dispose();return;}texture.colorSpace=THREE.SRGBColorSpace;thisViewer.textures.push(texture);thisViewer.material.map=texture;thisViewer.material.needsUpdate=true;}
  setView(view);
}
function setView(mode){view=mode;$('#unfold-image').hidden=mode!=='image';$('#unfold-viewer').hidden=!['flat','sphere'].includes(mode);$('#unfold-controls').hidden=!['flat','sphere'].includes(mode);$('#unfold-segments').hidden=mode!=='segments';$('#unfold-tabs').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.view===mode));if(viewer&&['flat','sphere'].includes(mode)){viewer.setOptions({shape:mode});viewer.resize();}}
$('#unfold-tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>setView(b.dataset.view));
$('#unfold-relief').oninput=e=>viewer?.setOptions({strength:Number(e.target.value)});$('#unfold-wire').onchange=e=>viewer?.setOptions({wireframe:e.target.checked});
$('#show-fixtures').onchange=candidates;$('#source-search').oninput=candidates;
$('#unfold-saved').onchange=attempt(()=>show(records.find(r=>r.id===$('#unfold-saved').value)));
$('#unfold-cancel').onclick=attempt(()=>job&&api('/jobs/'+job.id+'/cancel','POST',{}));
$('#unfold-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const form=new FormData(e.currentTarget);const record=await run('unfold',{items:[...selected].map(k=>{const [kind,id]=k.split(':');return {kind,id};}),name:form.get('name'),settings:{groups:Number(form.get('groups')),columns:Number(form.get('columns')),seed:Number(form.get('seed'))}});await refresh();await show(record);status('Texture regions separated and an inferred assembly saved locally.');})();};
await attempt(async()=>{await refresh();if(records.length)await show(records.at(-1));else status('Choose captures to begin.');})();
window.addEventListener('pagehide',()=>viewer?.dispose());
