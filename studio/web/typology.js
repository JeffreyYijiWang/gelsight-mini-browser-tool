const css=document.createElement('link');css.rel='stylesheet';css.href='/web/typology.css';document.head.append(css);
let activeSession=localStorage.getItem('mini-session')||'',boardId=null,sourceKind='frames';
let miniStream=null,miniDevice=null;
const chosen=new Set();
const key=item=>item.kind+':'+item.id;

export async function mountTypology(root,{api,getState,refresh,runJob,notice,esc,openFrame}) {
  let catalog=[],disposed=false,connected=false,capturing=false;
  const state=getState();
  if(activeSession&&!state.sessions.some(s=>s.id===activeSession))activeSession='';
  root.innerHTML=`<section class="mode-intro"><div><h2>A typology of things touched.</h2><p>Collect tactile images with your Mini. Compare texture, arrange the collection with ShuffleSnap, then inspect each surface.</p></div><span class="badge">Private · stored on this computer</span></section>
  <div class="typology-workspace"><section class="panel mini-panel"><h3>GelSight Mini</h3><p id="mini-status" role="status">Checking connected devices…</p>
  <label class="field"><span>Connected Mini</span><select id="mini-device" aria-label="Connected Mini"></select></label>
  <div class="actions"><button type="button" id="mini-connect" class="primary">Connect Mini</button><button type="button" id="mini-disconnect">Disconnect</button></div>
  <div class="mini-live"><video id="mini-live" aria-label="Live GelSight tactile image" autoplay playsinline muted hidden></video><span id="mini-placeholder">Connect to see the sensor. No images are saved automatically.</span></div>
  <label class="field"><span>Collection session</span><select id="mini-session"><option value="">Start a new collection</option>${state.sessions.filter(s=>s.sensor_id&&!s.synthetic).map(s=>`<option value="${s.id}" ${s.id===activeSession?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>
  <label class="field"><span>Sample name</span><input id="mini-name" placeholder="Bark / specimen 01" maxlength="120"></label>
  <div class="actions"><button type="button" id="mini-capture" class="primary" disabled>Capture sample</button><button type="button" id="mini-baseline" disabled>Save no-contact baseline</button></div>
  <p class="hint">For the baseline, lift the Mini clear of the surface. For a sample, make gentle contact, wait for a steady image, then capture. Baselines stay outside the typology by default. This does not calibrate physical depth.</p><div id="last-capture"></div>
  </section><div><form id="typology-form" class="panel"><h3>Arrange your collection</h3><div class="field-row">
  <label class="field"><span>Images to compare</span><select id="typology-kind"><option value="frames">Tactile RGB captures</option><option value="patches">Reconstructed height previews</option><option value="impressions">Gyotaku ink impressions</option><option value="all">All image types</option></select></label>
  <label class="field"><span>Session filter</span><select id="typology-session"><option value="">All sessions</option>${state.sessions.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></label>
  <label class="field"><span>Find a sample</span><input id="typology-search" type="search" placeholder="Filter by name"></label>
  <label class="field"><span>Similarity</span><select name="comparison"><option value="texture">Texture and directional structure</option><option value="appearance">Overall appearance and color</option></select></label>
  <label class="field"><span>Board title</span><input name="name" value="My tactile typology" maxlength="160" required></label>
  <label class="field"><span>Columns (0 = automatic)</span><input name="columns" type="number" min="0" max="100" value="0" step="1"></label></div>
  <label class="check"><input id="typology-synthetic" type="checkbox">Include synthetic demonstration images</label>
  <label class="check"><input id="typology-baselines" type="checkbox">Include no-contact baselines</label>
  <div class="actions"><button type="button" id="typology-select">Select visible images</button><button type="button" id="typology-clear">Clear selection</button><button class="primary" id="typology-build" disabled>Build with ShuffleSnap</button></div><p id="typology-count" role="status" class="hint"></p>
  <div id="typology-candidates" class="typology-candidates"></div>
  <p class="hint">Texture features or color descriptors → PCA → ShuffleSnap grid. Neighborhoods show visual resemblance, not material identity or measured roughness. Lighting, orientation, crop and contact pressure affect comparisons.</p></form>
  <section class="panel"><label class="field"><span>Saved comparison board</span><select id="typology-boards"><option value="">Choose a saved board</option>${(state.typologies||[]).map(b=>`<option value="${b.id}">${esc(b.name)} · ${b.items.length} images</option>`).join('')}</select></label><div id="typology-board"></div></section></div></div>
  <dialog id="typology-inspector"><button type="button" id="typology-close">Close</button><h2 id="typology-image-title"></h2><img id="typology-image" alt=""><p id="typology-image-info"></p><button type="button" id="typology-open-frame" hidden>Reconstruct this capture</button></dialog>`;
  const $=selector=>root.querySelector(selector);
  function attempt(fn){return async()=>{try{await fn();}catch(error){notice(error.message,true);}};}
  function status(text){$('#mini-status').textContent=text;}
  function setConnected(value){connected=value;$('#mini-capture').disabled=!value;$('#mini-baseline').disabled=!value;$('#mini-disconnect').disabled=!value;$('#mini-connect').disabled=value;}
  async function showStream(){
    const video=$('#mini-live');video.srcObject=miniStream;video.hidden=false;$('#mini-placeholder').hidden=true;await video.play();
    const track=miniStream.getVideoTracks()[0],settings=track.getSettings();
    setConnected(true);status(`${miniDevice.label} · ${settings.width} × ${settings.height} · live`);
    track.onended=()=>{if(!disposed){setConnected(false);status('Mini disconnected. Check the USB cable and reconnect.');}};
  }
  $('#mini-connect').onclick=attempt(async()=>{
    status('Opening the GelSight Mini…');
    const found=await navigator.mediaDevices.enumerateDevices(),device=found.find(d=>d.deviceId===$('#mini-device').value&&/gelsight/i.test(d.label));
    if(!device)throw new Error('Camera permission is needed to identify the Mini safely. Open Studio with Start-Material-Studio.cmd, then click Connect Mini.');
    try{miniStream=await navigator.mediaDevices.getUserMedia({video:{deviceId:{exact:device.deviceId},width:{ideal:640},height:{ideal:480}},audio:false});}
    catch(error){status('Camera did not open. Use Start-Material-Studio.cmd in Chrome; close other camera feeds and check Windows camera access.');throw error;}
    miniDevice=device;await showStream();
  });
  $('#mini-disconnect').onclick=()=>{miniStream?.getTracks().forEach(t=>t.stop());miniStream=null;miniDevice=null;setConnected(false);$('#mini-live').srcObject=null;$('#mini-live').hidden=true;$('#mini-placeholder').hidden=false;status('Mini disconnected. Saved captures remain available.');};
  $('#mini-session').onchange=()=>{activeSession=$('#mini-session').value;localStorage.setItem('mini-session',activeSession);};
  async function capture(baseline){
    if(capturing)return;capturing=true;$('#mini-capture').disabled=true;$('#mini-baseline').disabled=true;
    try{
      const video=$('#mini-live');
      if(!miniStream?.active||!video.videoWidth)throw new Error('Wait for a live Mini image before capturing.');
      const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext('2d').drawImage(video,0,0);
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png')),upload=new FormData();
      upload.append('file',blob,'tactile.png');upload.append('device_name',miniDevice.label);upload.append('device_id',miniDevice.deviceId);upload.append('session_id',activeSession);upload.append('baseline',String(baseline));upload.append('name',baseline?'No-contact baseline':$('#mini-name').value);
      const result=await api('/camera/browser-capture','POST',upload);
      activeSession=result.session.id;localStorage.setItem('mini-session',activeSession);
      for(const selector of ['#mini-session','#typology-session'])if(![...$(selector).options].some(o=>o.value===activeSession))$(selector).add(new Option(result.session.name,activeSession));
      $('#mini-session').value=activeSession;
      if(!baseline)chosen.add('frames:'+result.frame.id);
      await refresh(false);catalog=await api('/typology/items');renderCandidates();
      $('#last-capture').innerHTML=`<p class="hint">Saved ${esc(result.frame.source_name)} · ${baseline?'baseline':'sample'}</p><img class="last-tactile" src="/api/frames/${result.frame.id}/image" alt="Most recently saved tactile capture">${baseline?'':'<button type="button" id="reconstruct-last">Reconstruct last capture</button>'}`;
      if($('#reconstruct-last'))$('#reconstruct-last').onclick=()=>openFrame(result.frame.id);
      notice(baseline?'No-contact baseline saved for this session.':'Sample saved and selected for your typology.');
    }finally{capturing=false;$('#mini-capture').disabled=!connected;$('#mini-baseline').disabled=!connected;}
  }
  $('#mini-capture').onclick=attempt(()=>capture(false));$('#mini-baseline').onclick=attempt(()=>capture(true));
  function visible(){const search=$('#typology-search').value.toLowerCase(),session=$('#typology-session').value;return catalog.filter(item=>(sourceKind==='all'||item.kind===sourceKind)&&(!session||item.session_id===session)&&(!item.synthetic||$('#typology-synthetic').checked)&&(!item.baseline||$('#typology-baselines').checked)&&item.name.toLowerCase().includes(search));}
  function counts(){const count=chosen.size;$('#typology-count').textContent=`${count} selected · ${visible().length} visible · selection is retained across filters`;$('#typology-build').disabled=count<2||count>2000;}
  function renderCandidates(){
    const shown=visible();$('#typology-candidates').innerHTML=shown.map(item=>`<label class="typology-candidate"><input type="checkbox" data-image-key="${key(item)}" ${chosen.has(key(item))?'checked':''}><img loading="lazy" src="/api/typology/thumbnail/${item.kind}/${item.id}" alt="${esc(item.name)}"><span>${esc(item.name)}<small>${item.kind}${item.synthetic?' · synthetic':''}${item.baseline?' · baseline':''}</small></span></label>`).join('')||'<p class="empty">No images match these filters. Capture a sample, import images in Surface Capture, or choose another image type.</p>';
    $('#typology-candidates').querySelectorAll('[data-image-key]').forEach(input=>input.onchange=()=>{input.checked?chosen.add(input.dataset.imageKey):chosen.delete(input.dataset.imageKey);counts();});counts();
  }
  $('#typology-kind').value=sourceKind;
  $('#typology-kind').onchange=()=>{sourceKind=$('#typology-kind').value;renderCandidates();};
  for(const id of ['#typology-session','#typology-search','#typology-synthetic','#typology-baselines'])$(id).oninput=renderCandidates;
  $('#typology-select').onclick=()=>{visible().forEach(item=>chosen.add(key(item)));renderCandidates();};
  $('#typology-clear').onclick=()=>{chosen.clear();renderCandidates();};
  $('#typology-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{const form=new FormData(e.currentTarget);await runJob('typology',{name:form.get('name'),items:catalog.filter(item=>chosen.has(key(item))).map(({kind,id})=>({kind,id})),settings:{comparison:form.get('comparison'),columns:Number(form.get('columns'))}},result=>{boardId=result.id;});})();};
  function renderBoard(){
    const board=getState().typologies?.find(b=>b.id===boardId),box=$('#typology-board');
    if(!board){box.innerHTML='<p class="hint">Your saved layouts will appear here. Original images are never reordered or overwritten.</p>';return;}
    const base=`/api/files/typologies/${board.id}/`;
    box.innerHTML=`<h3>${esc(board.name)}</h3><p class="hint">${board.items.length} images · ${board.width} × ${board.height} grid · ${esc(board.settings.comparison)} · PCA retains ${(board.explained_variance_fraction*100).toFixed(1)}% of descriptor variation</p><div class="actions"><a class="web-link" href="${base}contact-sheet.png" download>Contact sheet PNG</a><a class="web-link" href="${base}index.html" target="_blank" rel="noopener">Open comparison board</a><button type="button" id="typology-export">Export private board ZIP</button></div><div class="typology-scroll"><div class="typology-grid" style="grid-template-columns:repeat(${board.width},minmax(110px,1fr));min-width:${board.width*120}px">${board.items.map((item,i)=>`<button type="button" data-inspect="${i}" style="grid-column:${item.column+1};grid-row:${item.row+1}"><img loading="lazy" src="${base}${item.image}" alt="${esc(item.name)}"><span>${String(i+1).padStart(3,'0')} ${esc(item.name)}</span></button>`).join('')}</div></div>`;
    box.querySelectorAll('[data-inspect]').forEach(button=>button.onclick=()=>{const item=board.items[Number(button.dataset.inspect)];$('#typology-image-title').textContent=item.name;$('#typology-image').src=item.kind==='frames'?`/api/frames/${item.id}/image`:item.kind==='impressions'?`/api/files/impressions/${item.id}/display.webp`:`/api/patches/${item.id}/image/height`;$('#typology-image').alt=item.name;$('#typology-image-info').textContent=`${item.kind} · ${item.synthetic?'synthetic fixture':'recorded source'} · ${board.interpretation}`;$('#typology-open-frame').hidden=item.kind!=='frames';$('#typology-open-frame').onclick=()=>{$('#typology-inspector').close();openFrame(item.id);};$('#typology-inspector').showModal();});
    $('#typology-export').onclick=attempt(async()=>{await runJob('typology_export',{id:board.id},result=>{const a=document.createElement('a');a.href='/api/downloads/'+result.id;a.download='private-typology.zip';a.click();});});
  }
  $('#typology-close').onclick=()=>$('#typology-inspector').close();
  $('#typology-boards').onchange=()=>{boardId=$('#typology-boards').value;renderBoard();};
  if(!boardId)boardId=state.typologies?.at(-1)?.id||null;
  $('#typology-boards').value=boardId||'';renderBoard();
  catalog=await api('/typology/items');
  const valid=new Set(catalog.map(key));for(const selected of chosen)if(!valid.has(selected))chosen.delete(selected);
  renderCandidates();
  try{
    const all=await navigator.mediaDevices.enumerateDevices(),found=all.filter(d=>d.kind==='videoinput'&&/gelsight/i.test(d.label));
    $('#mini-device').innerHTML=found.map(device=>`<option value="${device.deviceId}">${esc(device.label)}</option>`).join('')||'<option value="">Mini access not available</option>';
    setConnected(Boolean(miniStream?.active));
    if(miniStream?.active)await showStream();
    else status(found.length?'Mini detected. Connect when ready.':'Use Start-Material-Studio.cmd to enable camera access in the dedicated Chrome window, or plug in your Mini and refresh. Saved images can still be compared.');
  }catch(error){setConnected(false);status(error.message);}
  return ()=>{disposed=true;miniStream?.getVideoTracks().forEach(track=>track.onended=null);};
}
window.addEventListener('beforeunload',()=>miniStream?.getTracks().forEach(track=>track.stop()));
