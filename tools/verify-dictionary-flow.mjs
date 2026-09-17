import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const origin=process.argv[2]||'http://127.0.0.1:8090',report={},errors=[];
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({acceptDownloads:true,viewport:{width:1440,height:960}}),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(origin,{waitUntil:'networkidle'});await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false');const token=await page.locator('meta[name="studio-token"]').getAttribute('content');
 const api=async(route,body,method='POST')=>{const r=await context.request.fetch(origin+'/api'+route,{method,headers:{'X-Studio-Token':token},data:body});const data=await r.json();if(!r.ok())throw new Error(JSON.stringify(data));return data;};
 const job=async(kind,params)=>{const j=await api('/jobs',{kind,params});for(let i=0;i<180;i++){const s=await api('/jobs/'+j.id,undefined,'GET');if(s.status==='completed')return s.result;if(s.status==='failed')throw new Error(s.message);await page.waitForTimeout(500);}throw new Error('Job timed out');};
 // A small float32 NPY exercises browser upload without external data or Python.
 let header="{'descr': '<f4', 'fortran_order': False, 'shape': (24, 32), }";header+=' '.repeat((16-(10+header.length+1)%16)%16)+'\n';
 const data=Buffer.alloc(10+header.length+24*32*4);data.set([147,78,85,77,80,89,1,0]);data.writeUInt16LE(header.length,8);data.write(header,10,'ascii');for(let y=0;y<24;y++)for(let x=0;x<32;x++)data.writeFloatLE(-Math.exp(-(((x-16)/2)**2)),10+header.length+(y*32+x)*4);
 await page.locator('#import-form [name="kind"]').selectOption('height');await page.locator('#import-form [name="files"]').setInputFiles({name:'Browser uploaded fixture.npy',mimeType:'application/octet-stream',buffer:data});
 const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/import')&&r.request().method()==='POST'),page.getByRole('button',{name:'Import selected files',exact:true}).click()]);const imported=(await response.json())[0];if(!imported.patch)throw new Error(JSON.stringify(imported));report.imported_relative=imported.patch.state==='uncalibrated';
 await page.waitForFunction(id=>document.querySelector(`[data-action="select-patch"][data-id="${id}"]`)?.classList.contains('selected'),imported.patch.id);
 const [created]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/specimens')&&r.request().method()==='POST'),page.getByRole('button',{name:'Collect in dictionary',exact:true}).click()]);const s=await created.json();await page.waitForFunction(id=>document.querySelector('#specimen-form')?.dataset.specimenId===id,s.id);
 const live=page.waitForResponse(r=>r.url().endsWith('/ink-preview'));await page.locator('#ink-form [name="pressure"]').fill('0.7');if(!(await live).ok())throw new Error('Live pressure preview failed');await page.locator('.live-ink img').waitFor();report.live_ink=true;
 await job('impression',{specimen_id:s.id,settings:{output_px:384,pressure:.7}});
 await api('/specimens/'+s.id,{tags:['browser-test-grain'],category:'Import fixture',public_assets:['impression','surface','interactive_ink'],downloads:['print_png']},'PATCH');
 const state=await api('/state',undefined,'GET'),material=state.materials.findLast(m=>m.synthetic);if(!material)throw new Error('Run the Studio smoke test first to create a synthetic material.');
 const second=await api('/specimens',{source_id:material.patch_id,title:'Synthetic sphere comparison fixture'});await job('impression',{specimen_id:second.id,settings:{output_px:384}});
 await api('/specimens/'+second.id,{material_id:material.id,public_assets:['impression','surface','interactive_ink','material']},'PATCH');
 const preview=await job('dictionary_preview',{specimen_ids:[s.id,second.id]});await page.goto(origin+preview.url,{waitUntil:'networkidle'});
 await page.locator('#search').fill('browser-test-grain');if(await page.locator('.specimen-card').count()!==1)throw new Error('Tag search failed');await page.locator('#search').fill('');await page.locator('#category').selectOption('Import fixture');if(await page.locator('.specimen-card').count()!==1)throw new Error('Category filter failed');await page.locator('#category').selectOption('');
 await page.getByRole('button',{name:'Sphere thumbnails',exact:true}).click();await page.locator('img[src*="material-sphere-preview.png"]').waitFor();report.filters_and_sphere_thumbnails=true;
 const checks=page.locator('[data-compare]');await checks.nth(0).check();await checks.nth(1).check();await page.locator('nav a').filter({hasText:'Compare'}).click();await page.getByRole('heading',{name:'Compare impressions.',exact:true}).waitFor();
 await page.locator('#sync-ink').check();await page.locator('#compare-pressure').fill('0.8');await page.waitForFunction(()=>document.querySelectorAll('.compare-picture canvas').length===2);await page.locator('#sync-scale').check();await page.getByRole('button',{name:'Inspect available spheres',exact:true}).click();await page.locator('canvas.webgl').waitFor();await page.locator('#sync-light').check();await page.locator('#compare-light').fill('120');
 await page.screenshot({path:'test-artifacts/dictionary-compare.png'});report.comparison=true;
 await page.getByRole('link',{name:'Browser uploaded fixture',exact:true}).click();const download=page.waitForEvent('download');await page.getByRole('link',{name:'Print PNG',exact:true}).click();report.download=(await download).suggestedFilename();
 report.public_entries=(await api('/state',undefined,'GET')).specimens.filter(s=>s.state==='published').length;report.errors=errors;if(errors.length||report.public_entries)throw new Error(JSON.stringify(report));report.passed=true;
}catch(error){report.error=error.stack;report.errors=errors;report.notice=await page.locator('#notice').textContent().catch(()=>null);report.passed=false;process.exitCode=1;await page.screenshot({path:'test-artifacts/dictionary-flow-failure.png',fullPage:true}).catch(()=>{});}
finally{await writeFile('test-artifacts/dictionary-flow-report.json',JSON.stringify(report,null,2));console.log(report);await browser.close();}
