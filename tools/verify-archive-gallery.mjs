import {chromium} from 'playwright';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFile,mkdir} from 'node:fs/promises';
const target=resolve(process.argv[2]);
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const report={};
try{
  await page.goto(pathToFileURL(target).href);
  await page.locator('#layer').selectOption('normal-supplied');
  await page.waitForFunction(()=>document.querySelector('#sheet').complete&&document.querySelector('#sheet').naturalWidth>0);
  report.layers=await page.locator('#layer option').count();
  if(report.layers!==13)throw new Error('Missing aligned image layers.');
  report.cells=await page.locator('.grid article').count();
  if(report.cells!==12)throw new Error('Layout must preserve twelve positions.');
  await mkdir('test-artifacts',{recursive:true});
  await page.screenshot({path:'test-artifacts/archive-gallery-desktop.png'});
  report.video=await page.locator('video').first().evaluate(async video=>{
    video.load();await new Promise((ok,no)=>{video.addEventListener('loadedmetadata',ok,{once:true});video.addEventListener('error',()=>no(new Error('Video failed')),{once:true});setTimeout(()=>no(new Error('Video timeout')),20000);});
    await video.play();await new Promise(ok=>video.requestVideoFrameCallback(ok));video.pause();
    return {width:video.videoWidth,height:video.videoHeight,duration:video.duration,decoded:true};
  });
  if(report.video.width!==864||report.video.height!==1036)throw new Error('Wrong video size.');
  await page.setViewportSize({width:390,height:844});
  report.mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);
  if(report.mobileOverflow)throw new Error('Mobile overflow.');
  await page.screenshot({path:'test-artifacts/archive-gallery-mobile.png'});
  report.errors=errors;if(errors.length)throw new Error(errors.join('\n'));report.passed=true;
  await writeFile('test-artifacts/archive-gallery-report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}finally{await browser.close();}
