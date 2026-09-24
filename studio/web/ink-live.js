// Owner-only print workbench. Proofs and recipe edits do not save or publish.
const stylesheet=document.createElement('link');stylesheet.rel='stylesheet';stylesheet.href='/web/ink.css';document.head.append(stylesheet);
export async function mountInkPreview(form,{specimen,variant,variants,patch,frames,token,fileURL,onError}) {
  const response=await fetch('/api/ink-settings');
  if(!response.ok)throw new Error('Could not load the print engine settings.');
  const config=await response.json();
  form.elements.namedItem('ink_amount').step='.01';
  const box=document.createElement('div');box.className='live-ink';
  box.innerHTML=`<h3>Develop your impression</h3>
    <div class="field-row"><label class="field"><span>Ink & paper starting point</span><select data-ink-preset><option value="">Choose a palette…</option></select></label>
    <label class="field"><span>Restore a saved recipe</span><select data-ink-recipe><option value="">Current working recipe</option></select></label></div>
    <div class="actions"><button type="button" data-live="show">Live pressure preview</button><button type="button" data-live="saved">Saved impression</button><button type="button" data-live="source">Source relief / image</button><button type="button" data-live="capture" hidden>Original capture</button></div>
    <div class="actions"><button type="button" data-live="proof">Make pressure proof</button><a data-proof-download class="web-link" download="pressure-proof.png" hidden>Download proof PNG</a></div>
    <p class="hint" data-recipe-status></p><p class="hint" data-preview-status role="status" aria-live="polite">Move pressure or change a printing effect to preview it. Save to create a full-resolution variant.</p>
    <img class="ink-preview" alt="Live artistic ink preview" hidden>
    <div class="actions" data-recipe-downloads></div>`;
  form.prepend(box);
  const image=box.querySelector('img'),caption=box.querySelector('[data-preview-status]'),recipeStatus=box.querySelector('[data-recipe-status]');
  const presetSelect=box.querySelector('[data-ink-preset]'),recipeSelect=box.querySelector('[data-ink-recipe]');
  const engine=document.createElement('input');engine.type='number';engine.hidden=true;engine.name='engine_version';form.append(engine);
  let timer,controller,objectURL,proofURL,revision=0,selectedVariant=variant;
  const capturedFrame=specimen.source_kind==='frame'?specimen.source_id:patch?.source_ids.find(id=>frames.some(f=>f.id===id&&f.kind==='rgb'));
  const captureButton=box.querySelector('[data-live="capture"]');captureButton.hidden=!capturedFrame;
  for(const preset of config.presets)presetSelect.add(new Option(preset.name,preset.id));
  for(const saved of variants)recipeSelect.add(new Option(`${saved.created_at.slice(0,16)} · ${saved.settings.style||'ink'} · pressure ${saved.settings.pressure??.55}`,saved.id));
  function cancel(){clearTimeout(timer);controller?.abort();revision++;box.setAttribute('aria-busy','false');}
  function settings(){const result={};for(const el of form.querySelectorAll('[name]'))result[el.name]=el.type==='checkbox'?el.checked:['number','range'].includes(el.type)?Number(el.value):el.value;result.crop=String(result.crop).split(',').map(Number);return result;}
  function populate(recipe){
    for(const [name,value] of Object.entries(recipe)){
      const el=form.elements.namedItem(name);if(!el)continue;
      if(el.type==='checkbox')el.checked=value;else el.value=Array.isArray(value)?value.join(','):value;
    }
    updateStyle();
  }
  function updateStyle(){
    const relief=form.elements.namedItem('style').value==='relief',clean=form.elements.namedItem('style').value==='clean',modern=Number(engine.value)===2;
    box.querySelector('[data-live="proof"]').disabled=relief;
    for(const name of ['dry_brush','spread','edge_softness','paper_grain']){
      const field=form.elements.namedItem(name);field.disabled=modern&&(clean||relief);
      field.closest('label').classList.toggle('inactive-ink-effect',field.disabled);
    }
    recipeStatus.textContent=`Engine ${engine.value} · ${!modern?'Legacy recipe retained for reproduction. Choose a palette to use the updated engine.':relief?'Light-shaded surface; pressure affects the separate contact-mask export.':clean?'Clean impression; dry brush, spread, edge blur and paper grain are suppressed.':'Ink effects remain separate from the sampled surface.'}`;
  }
  function links(saved){
    const target=box.querySelector('[data-recipe-downloads]');target.replaceChildren();
    if(!saved)return;
    for(const [label,name] of [['Print PNG','print.png'],['Transparent contact ink','ink-transparent.png'],['Coverage mask','coverage.png'],['Source-space artistic layers','artistic_layers.npz'],['Recipe JSON','variant.json']]){
      const link=document.createElement('a');link.className='web-link';link.textContent=label;link.download=name;link.href=fileURL('impressions',saved.id,name);target.append(link);
    }
  }
  function restore(saved){
    cancel();selectedVariant=saved;recipeSelect.value=saved?.id||'';presetSelect.value='';
    const version=saved?.settings.engine_version??(saved?1:2);
    populate({...((version===1)?config.legacy_defaults:config.defaults),...saved?.settings,engine_version:version});
    links(saved);box.querySelector('[data-live="saved"]').disabled=!saved;
    if(saved){image.hidden=false;image.src=fileURL('impressions',saved.id,'display.webp');image.alt='Saved impression';caption.textContent='Saved recipe restored, including crop, rotation, palette, page size and seed. Save creates a new variant.';}
  }
  function invalidateProof(){if(proofURL){URL.revokeObjectURL(proofURL);proofURL=null;}box.querySelector('[data-proof-download]').hidden=true;}
  async function update(proof=false){
    cancel();if(!form.isConnected||!form.reportValidity())return;
    const requested=settings(),requestRevision=revision;
    controller=new AbortController();caption.textContent=proof?'Preparing three pressure proofs…':'Rendering impression…';
    box.setAttribute('aria-busy','true');
    try{
      const result=await fetch(`/api/specimens/${specimen.id}/${proof?'pressure-proof':'ink-preview'}`,{method:'POST',headers:{'X-Studio-Token':token,'Content-Type':'application/json'},body:JSON.stringify(requested),signal:controller.signal});
      if(!result.ok)throw new Error((await result.json()).detail||'Preview failed.');
      const blob=await result.blob();if(!form.isConnected||revision!==requestRevision)return;
      if(objectURL)URL.revokeObjectURL(objectURL);objectURL=URL.createObjectURL(blob);image.src=objectURL;image.hidden=false;
      image.alt=proof?'Pressure proof with virtual pressures 0.25, 0.55 and 0.85':'Live artistic ink preview';
      caption.textContent=proof?'Pressure 0.25 / 0.55 / 0.85. Same source, seed, palette and scale in all three. No variants have been saved.':`Live artistic preview · pressure ${requested.pressure.toFixed(2)} · ${requested.engine_version===2?'same source-space ink layers as the master':'legacy reduced-resolution preview'}; save for full resolution.`;
      if(proof){invalidateProof();proofURL=URL.createObjectURL(blob);const link=box.querySelector('[data-proof-download]');link.href=proofURL;link.hidden=false;}
    }catch(error){if(error.name!=='AbortError'&&revision===requestRevision){caption.textContent='Preview needs attention: '+error.message;onError(error.message);}}
    finally{if(revision===requestRevision)box.setAttribute('aria-busy','false');}
  }
  function schedule(){cancel();invalidateProof();updateStyle();timer=setTimeout(()=>update(),250);}
  form.addEventListener('input',event=>{if(event.target.name)schedule();});
  presetSelect.onchange=()=>{const preset=config.presets.find(p=>p.id===presetSelect.value);if(!preset)return;populate({...settings(),...preset.settings,engine_version:2});schedule();};
  recipeSelect.onchange=()=>{const saved=variants.find(v=>v.id===recipeSelect.value);if(saved){invalidateProof();restore(saved);}};
  box.querySelector('[data-live="show"]').onclick=()=>update();
  box.querySelector('[data-live="proof"]').onclick=()=>update(true);
  box.querySelector('[data-live="saved"]').onclick=()=>{cancel();if(!selectedVariant)return;image.hidden=false;image.src=fileURL('impressions',selectedVariant.id,'display.webp');image.alt='Saved impression';caption.textContent='Saved impression. Unsaved controls do not change this image.';};
  box.querySelector('[data-live="source"]').onclick=()=>{cancel();image.hidden=false;image.src=specimen.source_kind==='frame'?`/api/frames/${specimen.source_id}/image`:`/api/patches/${specimen.source_id}/image/height`;image.alt='Unchanged source';caption.textContent=specimen.source_kind==='frame'?'Original tactile RGB — image-based artistic input.':'Source height preview — unchanged by ink and paper effects.';};
  captureButton.onclick=()=>{cancel();image.hidden=false;image.src=`/api/frames/${capturedFrame}/image`;image.alt='Original tactile capture';caption.textContent='Original tactile RGB capture — private owner view.';};
  restore(variant);
  return ()=>{cancel();if(objectURL)URL.revokeObjectURL(objectURL);invalidateProof();};
}
