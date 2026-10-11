// Explicit no-contact reference and authored exclusions; never auto-detect damage.
export function damageEditor(host,{reference,apply,notice}){
  const panel=document.createElement('section');panel.className='panel';
  panel.innerHTML=`<h3>Startup: permanent gel damage</h3><p>Lift the Mini clear of all contact. Save/calibrate an untouched reference first, then mark the puncture and its disturbed rim. Baseline subtraction offsets fixed background; excluded pixels remain unknown, not repaired.</p><div class="actions"><button type="button" data-ref>Load untouched reference</button><label>Mark radius <input data-radius type="range" min="3" max="60" value="12" aria-label="Damage mark radius"></label><button type="button" data-undo>Undo mark</button><button type="button" data-apply>Use marked exclusions</button><button type="button" data-clear>Disable damage exclusions</button></div><canvas data-damage width="320" height="240" aria-label="Mark damaged gel on untouched reference" style="display:none;width:100%;max-width:480px;touch-action:none;cursor:crosshair"></canvas><p data-status role="status">No damage exclusions set. Original images are preserved.</p>`;
  host.append(panel);const canvas=panel.querySelector('canvas'),ctx=canvas.getContext('2d'),status=panel.querySelector('[data-status]');
  let current=null,image=null,regions=[];
  function draw(){if(!image)return;ctx.drawImage(image,0,0,320,240);ctx.fillStyle='rgba(240,45,70,.45)';ctx.strokeStyle='#ff244b';for(const [x,y,rx,ry] of regions){ctx.beginPath();ctx.ellipse(x*320,y*240,rx*320,ry*240,0,0,Math.PI*2);ctx.fill();ctx.stroke();}}
  panel.querySelector('[data-ref]').onclick=async()=>{try{
    const ref=await reference();const img=new Image();img.src=ref.url;await img.decode();
    current=ref;image=img;regions=[];apply(null);canvas.style.display='block';draw();status.textContent='Click each damaged area; include its rim. Then use marked exclusions.';
  }catch(e){status.textContent=e.message;notice?.(e.message,true);}};
  canvas.onpointerdown=e=>{if(!image)return;if(regions.length>=64){status.textContent='Maximum 64 marks.';return;}const b=canvas.getBoundingClientRect(),r=Number(panel.querySelector('[data-radius]').value);regions.push([(e.clientX-b.left)/b.width,(e.clientY-b.top)/b.height,r/320,r/240]);draw();status.textContent=`${regions.length} draft marks — click Use marked exclusions to apply.`;};
  panel.querySelector('[data-undo]').onclick=()=>{regions.pop();draw();status.textContent='Draft changed. Apply again to update exclusions.';};
  panel.querySelector('[data-apply]').onclick=()=>{try{
    if(!current||!regions.length)throw new Error('Load a reference and click the damaged spot first.');
    const [x,y,w,h]=current.crop||[0,0,1,1];const mapped=regions.map(([cx,cy,rx,ry])=>[x+cx*w,y+cy*h,rx*w,ry*h]);
    apply({...current,regions:mapped});status.textContent=`${regions.length} exclusions enabled for new captures. Depth/normals/meshes exclude this area; original RGB is retained.`;
  }catch(e){status.textContent=e.message;notice?.(e.message,true);}};
  function reset(){current=null;image=null;regions=[];apply(null);ctx.clearRect(0,0,320,240);canvas.style.display='none';status.textContent='No damage exclusions set. Load a fresh untouched reference.';}
  panel.querySelector('[data-clear]').onclick=reset;
  return {reset};
}
