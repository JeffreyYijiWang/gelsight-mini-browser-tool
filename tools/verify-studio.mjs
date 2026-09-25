import { chromium } from 'playwright';
import { mkdir,writeFile } from 'node:fs/promises';
const origin=process.argv[2]||'http://127.0.0.1:8090';
await mkdir('test-artifacts',{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1512,height:1000},deviceScaleFactor:1,acceptDownloads:true});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
const report={};
async function waitJob(timeout=180000){await page.waitForFunction(()=>document.querySelector('#job-panel')?.hidden===false,null,{timeout:10000});await page.waitForFunction(()=>document.querySelector('#job-panel')?.hidden===true,null,{timeout});const error=await page.locator('#notice').evaluate(e=>e.classList.contains('error')?e.textContent:null);if(error)throw new Error(error);}
try{
  await page.goto(origin,{waitUntil:'networkidle'});await page.getByRole('heading',{name:'From touch to a surface.'}).waitFor();
  const token=await page.locator('meta[name="studio-token"]').getAttribute('content');
  const getState=async()=>await(await context.request.get(origin+'/api/state',{headers:{'X-Studio-Token':token}})).json();
  let state=await getState();
  // p5 demo captures are also marked synthetic; use the analytic mm fixture for
  // this manufacturing regression, not whichever demo happened to be saved first.
  if(!state.patches.some(p=>p.provenance?.some(e=>e.operation==='analytic fixture'))){await page.getByRole('button',{name:'Load synthetic sample project'}).click();await waitJob();state=await getState();}
  const source=state.patches.find(p=>p.synthetic&&p.version==='original'&&p.provenance?.some(e=>e.operation==='analytic fixture'));
  await page.locator(`[data-action="select-patch"][data-id="${source.id}"]`).click();
  await page.screenshot({path:'test-artifacts/studio-capture.png'});
  await page.locator('[data-mode="material"]').click();await page.getByRole('heading',{name:'A surface, many interpretations.'}).waitFor();
  await page.locator('#material-form [name="name"]').fill('Synthetic browser-verified material');
  await page.getByRole('button',{name:'Generate material and brushes',exact:true}).click();await waitJob();
  await page.locator('#drawing').waitFor();
  const draw=await page.locator('#drawing').boundingBox();await page.mouse.move(draw.x+60,draw.y+60);await page.mouse.down();await page.mouse.move(draw.x+300,draw.y+100,{steps:8});await page.mouse.up();
  await page.getByRole('button',{name:'Replay strokes',exact:true}).click();
  const downloadEvent=page.waitForEvent('download');await page.getByRole('button',{name:'Save drawing PNG',exact:true}).click();const drawing=await downloadEvent;report.drawing_download=drawing.suggestedFilename();
  await page.screenshot({path:'test-artifacts/studio-material.png'});
  report.geometry=await page.evaluate(async()=>{
    const {SurfaceViewer}=await import('/web/viewer.js');const div=document.createElement('div');div.style.cssText='width:400px;height:400px;position:fixed;top:0;left:0';document.body.append(div);
    const viewer=new SurfaceViewer(div);if(viewer.failed)throw new Error('Software WebGL unavailable in test.');
    const h=Array.from({length:40},(_,y)=>Array.from({length:48},(_,x)=>Math.sin(x/47*Math.PI)**2*(.5+.5*Math.sin(y/39*Math.PI))));
    viewer.setSurface({height:h,width:48,height_px:40},{mode:'normal',quality:96});viewer.render();const normalRadius=viewer.object.geometry.boundingSphere.radius;
    viewer.setOptions({mode:'displacement',strength:.3});viewer.render();const displacedRadius=viewer.object.geometry.boundingSphere.radius;
    const counts={normalRadius,displacedRadius,triangles:viewer.object.geometry.index.count/3};viewer.dispose();div.remove();return counts;
  });
  if(report.geometry.displacedRadius<=report.geometry.normalRadius+.1)throw new Error('Displacement did not change actual geometry.');
  await page.locator('[data-mode="print"]').click();await page.getByRole('heading',{name:'Give the surface a physical scale.'}).waitFor();
  await page.waitForFunction(()=>document.querySelector('#workspace').getAttribute('aria-busy')==='false');
  await page.locator('#print-form [name="name"]').fill('Browser-verified synthetic relief');
  await page.getByRole('button',{name:'Build and validate geometry',exact:true}).click();await waitJob();
  state=await getState();const prints=state.prints.filter(p=>p.name==='Browser-verified synthetic relief');const print=prints.at(-1);report.print={geometry_valid:print.report.geometry_valid,errors:print.report.errors,roundtrip:print.exports.roundtrip};
  if(!report.print.geometry_valid)throw new Error(JSON.stringify(report.print));
  await page.screenshot({path:'test-artifacts/studio-print.png'});
  await page.locator('[data-mode="atlas"]').click();await page.getByRole('heading',{name:'Build a planar tactile atlas.'}).waitFor();
  const syntheticSession=state.sessions.find(s=>s.synthetic&&s.frame_ids.length>=3);
  await page.locator('#atlas-form [name="session"]').selectOption(syntheticSession.id);
  await page.getByRole('button',{name:'Build atlas',exact:true}).click();await waitJob();
  await page.locator('#atlas-canvas').waitFor();await page.screenshot({path:'test-artifacts/studio-atlas.png'});
  await page.locator('[data-mode="dictionary"]').click();
  const [created]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/specimens')&&r.request().method()==='POST'),page.getByRole('button',{name:'Collect selected surface',exact:true}).click()]);
  const newSpecimen=await created.json();report.specimen_id=newSpecimen.id;
  await page.waitForFunction(id=>document.querySelector('#specimen-form')?.dataset.specimenId===id,newSpecimen.id);
  await page.locator('#specimen-form [name="title"]').fill('Browser-verified synthetic specimen');
  await page.locator('#specimen-form [name="category"]').fill('synthetic study');
  const [saved]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/specimens/'+newSpecimen.id)&&r.request().method()==='PATCH'),page.getByRole('button',{name:'Save specimen details',exact:true}).click()]);
  report.saved_specimen=await saved.json();if(report.saved_specimen.title!=='Browser-verified synthetic specimen')throw new Error(JSON.stringify(report.saved_specimen));
  await page.waitForTimeout(700);
  await page.getByText('Page size, scale and reproducibility',{exact:true}).click();
  await page.locator('#ink-form [name="output_px"]').fill('800');await page.getByRole('button',{name:'Save new impression variant',exact:true}).click();await waitJob();
  await page.locator('#public-form [name="view_interactive_ink"]').check();await page.locator('#public-form [name="view_surface"]').check();
  await page.getByRole('button',{name:'Save public asset choices',exact:true}).click();await page.waitForTimeout(700);
  await page.getByRole('button',{name:'Preview exact entry',exact:true}).click();await waitJob();
  const previewURL=await page.getByRole('link',{name:'Open dictionary preview'}).getAttribute('href');
  const dictionary=await context.newPage();dictionary.on('pageerror',e=>errors.push(e.message));await dictionary.goto(new URL(previewURL,origin).href,{waitUntil:'networkidle'});
  await dictionary.getByRole('heading',{name:'Texture Dictionary',exact:true}).waitFor();await dictionary.screenshot({path:'test-artifacts/dictionary-desktop.png'});
  const requests=[];dictionary.on('request',r=>requests.push(r.url()));
  await dictionary.getByRole('link',{name:'Browser-verified synthetic specimen',exact:true}).click();await dictionary.getByRole('heading',{name:'Browser-verified synthetic specimen',exact:true}).waitFor();
  await dictionary.reload({waitUntil:'networkidle'});report.direct_entry_refresh=await dictionary.title();
  report.lazy_three_before_view=!requests.some(u=>u.includes('three.module.js'));
  await dictionary.locator('#pressure').fill('0.8');await dictionary.locator('#pressure').dispatchEvent('input');await dictionary.locator('#entry-view canvas').waitFor();
  await dictionary.getByRole('button',{name:'Reset print',exact:true}).click();await dictionary.locator('#entry-view img').waitFor();
  await dictionary.getByRole('button',{name:'Surface',exact:true}).click();await dictionary.locator('#entry-view canvas.webgl').waitFor();
  report.lazy_three_after_view=requests.some(u=>u.includes('three.module.js'));
  await dictionary.screenshot({path:'test-artifacts/dictionary-entry.png'});
  await dictionary.setViewportSize({width:390,height:844});await dictionary.goto(new URL(previewURL,origin).href,{waitUntil:'networkidle'});
  await dictionary.locator('#search').fill('nonexistent-texture');await dictionary.getByText('No specimens here yet.').waitFor();await dictionary.locator('#search').fill('synthetic');
  const mobileOverflow=await dictionary.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);if(mobileOverflow)throw new Error('Dictionary overflows the mobile viewport.');
  await dictionary.screenshot({path:'test-artifacts/dictionary-mobile.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'test-artifacts/studio-mobile.png'});
  report.mobile_overflow=mobileOverflow;report.public_entries=(await getState()).specimens.filter(s=>s.state==='published').length;
  if(report.public_entries!==0)throw new Error('Browser test unexpectedly published a specimen.');
  if(errors.length)throw new Error(errors.join('\n'));
  report.page_errors=errors;report.passed=true;
}catch(error){report.passed=false;report.error=error.stack;await page.screenshot({path:'test-artifacts/browser-failure.png',fullPage:true}).catch(()=>{});process.exitCode=1;}
finally{await writeFile('test-artifacts/browser-report.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();}
