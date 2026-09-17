// Owner-only preview. Saving a variant is a separate, explicit action.
export function mountInkPreview(form,{specimen,variant,token,fileURL,onError}) {
  const box=document.createElement('div');box.className='live-ink';
  box.innerHTML='<div class="actions"><button type="button" data-live="show">Live pressure preview</button><button type="button" data-live="saved">Saved impression</button><button type="button" data-live="source">Source relief / image</button></div><p class="hint" aria-live="polite">Move pressure or change a printing effect to preview it. Save to create a reproducible full-resolution variant.</p><img class="ink-preview" alt="Live artistic ink preview" hidden>';
  form.prepend(box);const image=box.querySelector('img'),caption=box.querySelector('p');
  let timer,controller,objectURL;
  function settings(){const result={};for(const el of form.querySelectorAll('[name]'))result[el.name]=el.type==='checkbox'?el.checked:['number','range'].includes(el.type)?Number(el.value):el.value;result.crop=String(result.crop).split(',').map(Number);return result;}
  async function update(){
    if(!form.isConnected)return;controller?.abort();controller=new AbortController();
    try{
      const response=await fetch(`/api/specimens/${specimen.id}/ink-preview`,{method:'POST',headers:{'X-Studio-Token':token,'Content-Type':'application/json'},body:JSON.stringify(settings()),signal:controller.signal});
      if(!response.ok)throw new Error((await response.json()).detail||'Preview failed.');
      const blob=await response.blob();if(!form.isConnected)return;
      if(objectURL)URL.revokeObjectURL(objectURL);objectURL=URL.createObjectURL(blob);image.src=objectURL;image.hidden=false;
      caption.textContent=`Live artistic preview · pressure ${settings().pressure.toFixed(2)} · reduced resolution; save for the master print. No source data is changed.`;
    }catch(error){if(error.name!=='AbortError')onError(error.message);}
  }
  form.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(update,180);});
  box.querySelector('[data-live="show"]').onclick=update;
  box.querySelector('[data-live="saved"]').onclick=()=>{if(!variant)return;controller?.abort();image.hidden=false;image.src=fileURL('impressions',variant.id,'display.webp');caption.textContent='Saved cover impression. Current unsaved controls do not change this image.';};
  box.querySelector('[data-live="source"]').onclick=()=>{controller?.abort();image.hidden=false;image.src=specimen.source_kind==='frame'?`/api/frames/${specimen.source_id}/image`:`/api/patches/${specimen.source_id}/image/height`;caption.textContent=specimen.source_kind==='frame'?'Original tactile RGB — image-based artistic input.':'Source height preview — unchanged by ink and paper effects.';};
  return ()=>{clearTimeout(timer);controller?.abort();if(objectURL)URL.revokeObjectURL(objectURL);};
}
