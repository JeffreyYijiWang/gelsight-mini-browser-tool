export function mountP5(root,{api,refresh,notice,esc,getState}){
  const sessions=getState().sessions.filter(s=>s.sensor_id);
  root.innerHTML=`<section class="mode-intro"><div><h2>Touch, depth, and the view you chose.</h2><p>Golan Levin’s original p5 viewer, connected to your private collection.</p></div><a class="web-link" href="/unfold" target="_blank" rel="noopener">Open Texture Unfolding</a></section>
  <section class="panel"><div class="field-row"><label class="field"><span>Sample name</span><input id="p5-name" maxlength="120" placeholder="Bark / specimen 01"></label><label class="field"><span>Collection</span><select id="p5-session"><option value="">Start a new collection</option>${sessions.map(s=>`<option value="${s.id}">${esc(s.name)}${s.synthetic?' · demo':''}</option>`).join('')}</select></label></div>
  <div class="actions"><button type="button" id="p5-save" class="primary">Save RGB + depth + current mesh view</button><button type="button" id="p5-center">Restore 10% edge crop</button><button type="button" id="p5-disconnect">Disconnect Mini</button><a class="web-link" href="#typology">Compare saved samples</a></div>
  <p id="p5-save-status" role="status">Default crop removes 10% from each edge. Full originals are retained. If you move the crop handles, the saved sample records that exact crop.</p>
  <p class="hint">Lift clear of contact, click Calibrate, and wait for 50 frames. Changing crop, camera resolution, inference quality or Lambda requires recalibration. This removes a background; depth remains relative, not millimeters. Rotate or zoom the mesh before saving to record that view.</p></section>
  <div style="overflow:auto;background:#111418;border-radius:12px"><iframe id="p5-viewer" title="Original p5 live RGB, depth and mesh viewer" src="/p5-studio" allow="camera 'self'" style="display:block;width:100%;min-width:760px;height:650px;border:0"></iframe></div>`;
  const frame=root.querySelector('#p5-viewer'),status=root.querySelector('#p5-save-status');
  const backgroundControl=document.createElement('label');backgroundControl.className='field';backgroundControl.innerHTML='<span>Clear-background threshold (RGB difference)</span><input id="p5-background-threshold" type="number" min="1" max="100" value="12"><small>Calibration also records averaged no-contact RGB. New live samples include a transparent contact image and a background-difference view; lower values keep fainter changes.</small>';status.before(backgroundControl);
  const bridge=()=>{const b=frame.contentWindow?.studioP5;if(!b?.ready())throw new Error('The p5 model is still loading. Try again shortly.');return b;};
  const attempt=fn=>async()=>{try{await fn();}catch(error){status.textContent=error.message;notice(error.message,true);}};
  root.querySelector('#p5-center').onclick=attempt(async()=>{await bridge().centerCrop();status.textContent='Central 80% restored. Recalibrate before saving a live sample.';});
  root.querySelector('#p5-disconnect').onclick=attempt(()=>bridge().disconnect());
  root.querySelector('#p5-save').onclick=attempt(async()=>{
    const button=root.querySelector('#p5-save');button.disabled=true;
    try{status.textContent='Freezing the current RGB, depth, and mesh view…';const capture=await bridge().snapshot(Number(root.querySelector('#p5-background-threshold').value)),form=new FormData();
      for(const [key,blob] of Object.entries(capture))form.append(key,blob,key+(key==='payload'?'.json':'.png'));
      form.append('name',root.querySelector('#p5-name').value);form.append('session_id',root.querySelector('#p5-session').value);
      status.textContent='Images frozen. Saving the sample and depth arrays locally…';
      const result=await api('/samples/p5','POST',form);await refresh(false);
      const select=root.querySelector('#p5-session');if(![...select.options].some(o=>o.value===result.session.id))select.add(new Option(result.session.name,result.session.id));select.value=result.session.id;
      status.textContent=`Saved ${result.sample.name}: cropped RGB, relative depth and the current mesh view. Select the RGB capture in Live Typology for coordinated sheets.`;notice('Sample bundle saved locally.');
      root.querySelector('#p5-clean-result')?.remove();const clear=document.createElement('p');clear.id='p5-clean-result';
      if(result.sample.background?.available){const base='/api/files/samples/'+result.sample.id+'/';clear.innerHTML=`<a class="web-link" href="${base}clean.png" target="_blank" rel="noopener">Clear contact image</a> <a class="web-link" href="${base}difference.png" target="_blank" rel="noopener">RGB background difference</a>`;}
      else clear.textContent='No matching RGB background is available for this sample. Calibrate in the live Studio viewer to include the clear-background version.';
      status.after(clear);
    }finally{button.disabled=false;}
  });
  return ()=>frame.contentWindow?.studioP5?.disconnect();
}
