import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
const origin=process.argv[2]||'http://127.0.0.1:8090',report={},errors=[];
await mkdir('test-artifacts',{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1450,height:1000},acceptDownloads:true});
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
try{
  await page.goto(origin+'/#typology',{waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false');
  const token=await page.locator('meta[name="studio-token"]').getAttribute('content');
  const api=async(route,data,method='POST')=>{const response=await context.request.fetch(origin+'/api'+route,{method,headers:{'X-Studio-Token':token},data});const result=await response.json();if(!response.ok())throw new Error(JSON.stringify(result));return result;};
  const session=await api('/sessions',{name:'Synthetic typology browser fixture',synthetic:true});
  for(let i=0;i<7;i++){
    const data=await page.evaluate(i=>{const c=document.createElement('canvas');c.width=96;c.height=96;const ctx=c.getContext('2d');ctx.fillStyle='#ecddba';ctx.fillRect(0,0,96,96);ctx.strokeStyle=i<3?'#253950':'#75422e';ctx.lineWidth=i+1;for(let x=0;x<100;x+=8+i){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(96-x,96);ctx.stroke();}return c.toDataURL('image/png').split(',')[1];},i);
    const result=await context.request.post(origin+'/api/import',{headers:{'X-Studio-Token':token},multipart:{kind:'rgb',session_id:session.id,files:{name:`Synthetic stripe ${i}.png`,mimeType:'image/png',buffer:Buffer.from(data,'base64')}}});
    if(!result.ok())throw new Error(await result.text());
  }
  await page.reload({waitUntil:'networkidle'});
  await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false');
  await page.locator('#typology-session').selectOption(session.id);
  if(await page.locator('.typology-candidate').count()!==0)throw new Error('Synthetic fixtures visible by default');
  await page.locator('#typology-synthetic').check();
  if(await page.locator('.typology-candidate').count()!==7)throw new Error('Session filter did not return seven fixtures');
  await page.locator('#typology-select').click();
  const boardName='Synthetic stripes — '+session.id.slice(0,8);
  await page.locator('#typology-form [name="name"]').fill(boardName);
  await page.locator('#typology-form [name="columns"]').fill('3');
  const completed=page.waitForFunction(name=>document.querySelector('#typology-board h3')?.textContent===name,boardName,{timeout:90000});
  await page.locator('#typology-build').click();await completed;
  await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false'&&document.querySelector('#job-panel')?.hidden);
  if(await page.locator('[data-inspect]').count()!==7)throw new Error('Saved grid omitted images');
  report.shuffle_grid=true;
  await page.locator('#typology-board').screenshot({path:'test-artifacts/typology-board.png'});
  await page.locator('[data-inspect]').first().click();await page.locator('#typology-inspector').waitFor({state:'visible'});
  if(!await page.locator('#typology-image').evaluate(img=>img.complete&&img.naturalWidth>0))await page.locator('#typology-image').evaluate(img=>img.decode());
  report.inspect_original=true;await page.locator('#typology-close').click();
  const png=page.waitForEvent('download');await page.getByRole('link',{name:'Contact sheet PNG',exact:true}).click();report.sheet_download=(await png).suggestedFilename();
  const zip=page.waitForEvent('download');await page.locator('#typology-export').click();report.zip_download=(await zip).suggestedFilename();
  await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false'&&document.querySelector('#job-panel')?.hidden);
  const standalone=page.waitForEvent('popup');await page.getByRole('link',{name:'Open comparison board',exact:true}).click();const board=await standalone;await board.waitForLoadState('networkidle');
  if(await board.locator('section img').count()!==7)throw new Error('Standalone board missing images');
  await board.reload({waitUntil:'networkidle'});await board.close();report.standalone_reload=true;
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw new Error('Mobile page overflow');
  await page.locator('#typology-board').screenshot({path:'test-artifacts/typology-mobile.png'});report.mobile_no_overflow=true;
  const state=await api('/state',undefined,'GET');report.public_entries=state.specimens.filter(s=>s.state==='published').length;
  if(report.public_entries||errors.length)throw new Error(JSON.stringify({errors,report}));report.passed=true;
}catch(error){report.error=error.stack;report.notice=await page.locator('#notice').textContent().catch(()=>null);process.exitCode=1;report.passed=false;await page.screenshot({path:'test-artifacts/typology-failure.png',fullPage:true}).catch(()=>{});}
finally{report.errors=errors;console.log(report);await writeFile('test-artifacts/typology-report.json',JSON.stringify(report,null,2));await browser.close();}
