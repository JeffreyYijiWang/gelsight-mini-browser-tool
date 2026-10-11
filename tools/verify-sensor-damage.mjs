// Isolated synthetic camera: never marks or calibrates the physical sensor.
import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
const origin=process.argv[2]||'http://127.0.0.1:8091';
await mkdir('test-artifacts',{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
await context.addInitScript(()=>{
  const devices=navigator.mediaDevices,enumerate=devices.enumerateDevices.bind(devices);
  devices.enumerateDevices=async()=>(await enumerate()).map(d=>({kind:d.kind,deviceId:d.deviceId,label:d.kind==='videoinput'?'GelSight synthetic damage fixture':d.label}));
});
try{
  await page.goto(origin+'/#typology');
  await page.locator('#mini-connect').click();await page.waitForFunction(()=>!document.querySelector('#mini-baseline').disabled);
  await page.getByRole('button',{name:'Load untouched reference',exact:true}).click();
  await page.getByText('Lift clear of contact and click Save no-contact baseline in this connection first.',{exact:true}).first().waitFor();
  await page.locator('#mini-baseline').click();await page.getByText(/Saved No-contact baseline/).waitFor();
  await page.getByRole('button',{name:'Load untouched reference',exact:true}).click();await page.locator('[data-damage]').waitFor({state:'visible'});
  await page.locator('[data-damage]').click({position:{x:200,y:150}});
  await page.getByRole('button',{name:'Use marked exclusions',exact:true}).click();
  await page.getByText(/1 exclusions enabled/).waitFor();
  await page.locator('#mini-name').fill('SYNTHETIC damage exclusion');await page.locator('#mini-capture').click();await page.getByText(/Saved SYNTHETIC damage exclusion/).waitFor();
  const state=await(await context.request.get(origin+'/api/state')).json();
  const frame=state.frames.find(f=>f.source_name==='SYNTHETIC damage exclusion.png');
  if(!frame?.settings.sensor_damage?.baseline_id)throw new Error('Frozen damage profile missing');
  await page.screenshot({path:'test-artifacts/sensor-damage-ui.png'});
  await page.locator('#mini-disconnect').click();await page.getByText('No damage exclusions set. Load a fresh untouched reference.',{exact:true}).waitFor();
  if(errors.length)throw new Error(errors.join('\n'));
  const report={passed:true,hardware:false,profile:frame.settings.sensor_damage,errors};
  await writeFile('test-artifacts/sensor-damage-ui-report.json',JSON.stringify(report,null,2));console.log(report);
}catch(error){console.error('Damage UI status:',await page.locator('[data-status]').textContent(),errors);throw error;}finally{await browser.close();}
