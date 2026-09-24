// A separate local Chrome profile; no changes to the user's everyday profile.
import {chromium} from 'playwright';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {writeFile,mkdir} from 'node:fs/promises';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const origin='http://127.0.0.1:8090';
let context;
try{
  context=await chromium.launchPersistentContext(path.join(root,'studio-data','mini-browser-profile'),{
    channel:'chrome',headless:false,viewport:null,args:[`--app=${origin}/#typology`]
  });
  // Explicit user-requested camera connection. This permission is scoped to the
  // loopback Studio origin, and capture code selects only a named GelSight device.
  await context.grantPermissions(['camera'],{origin});
  const page=context.pages()[0]||await context.newPage();
  await page.goto(origin+'/#typology');
  await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false');
  const mini=await page.locator('#mini-device option').allTextContents();
  if(mini.some(name=>/gelsight/i.test(name))){
    await page.locator('#mini-connect').click();
    await page.waitForFunction(()=>document.querySelector('#mini-live')?.videoWidth>0,{},{timeout:20000}).catch(()=>{});
  }
  await mkdir(path.join(root,'studio-data','logs'),{recursive:true});
  const status=await page.evaluate(()=>({page:location.href,status:document.querySelector('#mini-status')?.textContent,live:Boolean(document.querySelector('#mini-live')?.videoWidth),width:document.querySelector('#mini-live')?.videoWidth,height:document.querySelector('#mini-live')?.videoHeight}));
  await writeFile(path.join(root,'studio-data','logs','browser-status.json'),JSON.stringify(status,null,2));
  console.log('Studio is open. Close the Chrome app window when finished.');
  await new Promise(resolve=>context.on('close',resolve));
}catch(error){
  await mkdir(path.join(root,'studio-data','logs'),{recursive:true});
  await writeFile(path.join(root,'studio-data','logs','browser-error.txt'),String(error.stack||error));
  console.error('Could not open Studio. If its dedicated Chrome window is already open, use that window. '+error.message);
  await context?.close();process.exitCode=1;
}
