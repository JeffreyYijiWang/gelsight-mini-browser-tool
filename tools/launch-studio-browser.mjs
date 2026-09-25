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
    channel:'chrome',headless:false,viewport:null,args:[`--app=${origin}/#p5`]
  });
  // Explicit user-requested camera connection. This permission is scoped to the
  // loopback Studio origin, and capture code selects only a named GelSight device.
  await context.grantPermissions(['camera'],{origin});
  const page=context.pages()[0]||await context.newPage();
  await page.goto(origin+'/#p5');
  await page.waitForFunction(()=>document.querySelector('#workspace')?.getAttribute('aria-busy')==='false');
  await page.waitForFunction(()=>document.querySelector('#p5-viewer')?.contentWindow?.studioP5?.ready(),{},{timeout:60000});
  await page.evaluate(()=>document.querySelector('#p5-viewer').contentWindow.studioP5.connect());
  await mkdir(path.join(root,'studio-data','logs'),{recursive:true});
  const status=await page.evaluate(()=>{const s=document.querySelector('#p5-viewer').contentWindow.__gelsightState;return {page:location.href,status:s.status,live:Boolean(s.video?.videoWidth),width:s.video?.videoWidth,height:s.video?.videoHeight};});
  await writeFile(path.join(root,'studio-data','logs','browser-status.json'),JSON.stringify(status,null,2));
  console.log('Studio is open. Close the Chrome app window when finished.');
  await new Promise(resolve=>context.on('close',resolve));
}catch(error){
  await mkdir(path.join(root,'studio-data','logs'),{recursive:true});
  await writeFile(path.join(root,'studio-data','logs','browser-error.txt'),String(error.stack||error));
  console.error('Could not open Studio. If its dedicated Chrome window is already open, use that window. '+error.message);
  await context?.close();process.exitCode=1;
}
