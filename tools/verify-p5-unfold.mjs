import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
const origin=process.argv[2]||'http://127.0.0.1:8091';
await mkdir('test-artifacts',{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1512,height:1050},acceptDownloads:true});
const page=await context.newPage(),errors=[],report={};page.on('pageerror',e=>errors.push(e.message));
try{
  await page.goto(origin+'/#p5');await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false');
  await page.waitForFunction(()=>document.querySelector('#p5-viewer')?.contentWindow?.studioP5?.ready(),null,{timeout:60000});
  const frame=page.frames().find(f=>f.url().includes('/p5-studio'));
  const sizes=await frame.locator('.camera-resolution-select option').allTextContents();
  if(sizes.join('|')!=='640×480|958×720|1640×1232|3280×2464')throw new Error('Missing p5 resolutions');report.resolutions=sizes;
  const crop=await frame.evaluate(()=>window.__gelsightState.cropRect);if(crop.x!==.1||crop.w!==.8)throw new Error('Wrong default crop');
  await frame.getByRole('button',{name:'Demo',exact:true}).click();
  await frame.waitForFunction(()=>window.__gelsightState?.lastDepth&&window.__gelsightState.sampleImage&&!window.__gelsightState.busy,null,{timeout:60000});
  await page.locator('#p5-center').click();
  await frame.waitForFunction(()=>!window.__gelsightState.busy);
  const ids=[];
  for(let i=0;i<2;i++){
    if(i)await frame.evaluate(()=>{ui.zScale.value(16);});
    await page.locator('#p5-name').fill(`p5 browser coin ${Date.now()} ${i}`);
    const captureResponse=page.waitForResponse(r=>r.url()===origin+'/api/samples/p5'&&r.request().method()==='POST',{timeout:120000});
    await page.locator('#p5-save').click();await page.waitForFunction(()=>document.querySelector('#p5-save-status').textContent.startsWith('Saved ')||document.querySelector('#notice').classList.contains('error'),null,{timeout:120000});
    if(await page.locator('#notice').evaluate(e=>e.classList.contains('error')))throw new Error(await page.locator('#p5-save-status').textContent());
    const saved=await(await captureResponse).json();ids.push(saved.frame.id);
  }
  report.synchronized_bundles=true;
  await page.screenshot({path:'test-artifacts/p5-studio.png'});
  await page.locator('[data-mode="typology"]').click();await page.locator('#typology-synthetic').check();
  for(const id of ids)await page.locator(`[data-image-key="frames:${id}"]`).check();
  const title='Synchronized views '+Date.now();await page.locator('#typology-form [name="name"]').fill(title);
  await page.locator('#typology-build').click();await page.getByRole('heading',{name:title,exact:true}).waitFor({timeout:120000});
  await page.waitForFunction(()=>document.querySelector('#workspace').getAttribute('aria-busy')==='false'&&document.querySelector('#job-panel').hidden);
  for(const view of ['raw','depth','mesh'])for(const suffix of ['images only','with names']){
    const download=page.waitForEvent('download');await page.getByRole('link',{name:view+' '+suffix,exact:true}).click();await download;
  }
  report.all_six_sheets=true;await page.screenshot({path:'test-artifacts/p5-typology.png'});
  await page.locator('#typology-surface-view canvas').waitFor();
  await page.locator('#typology-show-depth').click();await page.locator('#typology-stitched-depth').waitFor();
  await page.locator('#typology-show-mesh').click();await page.locator('#typology-wire').check();
  await page.locator('#typology-connect-seams').check();
  await page.waitForFunction(()=>document.querySelector('#typology-geometry-info').textContent.includes('artistic connecting seams'));
  await page.waitForTimeout(600);await page.locator('#typology-surface-view').screenshot({path:'test-artifacts/typology-stitched-mesh.png'});
  report.actual_mesh_and_combined_depth=true;
  await page.locator('#typology-show-normal').click();
  const normalPreview=page.locator('#typology-stitched-depth');
  for(const connected of [true,false]){
    await page.locator('#typology-connect-seams').setChecked(connected);
    for(const convention of ['opengl','directx']){
      await page.locator('#typology-normal-convention').selectOption(convention);
      const file=`${connected?'connected':'stitched'}-normal-${convention}.png`;
      await page.waitForFunction(file=>{const img=document.querySelector('#typology-stitched-depth');return !img.hidden&&img.src.endsWith(file)&&img.complete&&img.naturalWidth>0;},file);
      const download=page.waitForEvent('download');await page.locator(`a[href$="/${file}"]`).click();
      const saved=await download;if(await saved.failure())throw new Error('Normal PNG download failed');
    }
  }
  await normalPreview.screenshot({path:'test-artifacts/typology-normal-map.png'});
  await page.locator('#typology-show-depth').click();
  if(!(await normalPreview.getAttribute('src')).endsWith('stitched-depth.png'))throw new Error('Depth mode did not restore depth image');
  report.normal_maps_both_conventions_and_seams=true;
  const unfolding=await context.newPage();unfolding.on('pageerror',e=>errors.push(e.message));await unfolding.goto(origin+'/unfold');
  await unfolding.locator('#show-fixtures').check();
  for(const id of ids)await unfolding.locator(`[data-key="frames:${id}"]`).check();
  await unfolding.locator('[name="groups"]').fill('3');await unfolding.locator('#unfold-build').click();
  await unfolding.waitForFunction(()=>document.querySelector('#unfold-status').textContent.includes('assembly saved'),null,{timeout:120000});
  await unfolding.getByRole('button',{name:'Flat 3D mesh',exact:true}).click();
  await unfolding.locator('#unfold-viewer canvas').waitFor();await unfolding.waitForTimeout(800);
  await unfolding.screenshot({path:'test-artifacts/unfold-flat.png'});
  await unfolding.getByRole('button',{name:'Wrapped ball',exact:true}).click();await unfolding.waitForTimeout(800);await unfolding.screenshot({path:'test-artifacts/unfold-ball.png'});
  await unfolding.getByRole('button',{name:'Separated regions',exact:true}).click();await unfolding.screenshot({path:'test-artifacts/unfold-regions.png'});
  report.unfolding_views=true;
  const zip=unfolding.waitForEvent('download');await unfolding.locator('#unfold-export').click();await zip;report.private_bundle=true;
  await unfolding.reload();await unfolding.locator('#unfold-viewer canvas').waitFor({state:'attached'});report.reload=true;
  await unfolding.setViewportSize({width:390,height:844});await unfolding.waitForTimeout(400);
  if(!await unfolding.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))throw new Error('Unfolding mobile overflow');
  report.mobile=true;report.errors=errors;if(errors.length)throw new Error(errors.join('\n'));report.passed=true;
}catch(error){report.failure=error.message;report.status=await page.locator('#p5-save-status').textContent().catch(()=>null);report.captureStage=await page.evaluate(()=>document.querySelector('#p5-viewer')?.contentWindow?.studioP5?.captureStage).catch(()=>null);report.errors=errors;await page.screenshot({path:'test-artifacts/p5-unfold-failure.png'}).catch(()=>{});throw error;}
finally{await writeFile('test-artifacts/p5-unfold-report.json',JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify(report,null,2));
