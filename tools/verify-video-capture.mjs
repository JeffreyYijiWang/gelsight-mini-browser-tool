import {chromium} from 'playwright';
import {mkdir,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const origin=process.argv[2]||'http://127.0.0.1:8091';
await mkdir('test-artifacts',{recursive:true});
execFileSync('ffmpeg',['-v','error','-nostdin','-y','-f','lavfi','-i',"nullsrc=s=96x72:r=10,geq=lum='120+35*sin(X*0.4)+20*cos(Y*0.5)':cb='128+12*sin(X*0.2)':cr='128+12*cos(Y*0.3)'",'-t','2','-pix_fmt','yuv420p','-threads','2','test-artifacts/video-camera.y4m'],{timeout:30000});
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',`--use-file-for-fake-video-capture=${resolve('test-artifacts/video-camera.y4m')}`]});
const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage(),errors=[],report={};
page.on('pageerror',e=>errors.push(e.message));
await context.addInitScript(()=>{
  const NativeRecorder=window.MediaRecorder;window.recordEvents=[];
  window.MediaRecorder=class extends NativeRecorder {constructor(...args){super(...args);this.addEventListener('dataavailable',e=>window.recordEvents.push({size:e.data.size,time:performance.now()}));this.addEventListener('error',e=>window.recordEvents.push({error:e.error?.message}));}};
  const originalFetch=window.fetch.bind(window);
  window.fetch=(input,options)=>{if(input==='/api/video-recordings'&&options?.body instanceof FormData)options.body.set('synthetic','true');return originalFetch(input,options);};
  const devices=navigator.mediaDevices;
  const enumerate=devices.enumerateDevices.bind(devices),getMedia=devices.getUserMedia.bind(devices);
  devices.enumerateDevices=async()=>(await enumerate()).map(d=>({kind:d.kind,deviceId:d.deviceId,label:d.kind==='videoinput'?'GelSight synthetic browser fixture':d.label}));
  devices.getUserMedia=async constraints=>{
    if(!constraints.video.deviceId.exact||constraints.audio!==false)throw new Error('Camera selection was not explicit');
    const stream=await getMedia(constraints);window.fixtureStream=stream;return stream;
  };
});
try{
  await page.goto(origin+'/#video');await page.waitForFunction(()=>document.querySelector('#workspace').getAttribute('aria-busy')==='false');
  await page.locator('#video-connect').click();await page.locator('#video-start').waitFor();
  await page.locator('#video-start').click();await page.waitForFunction(()=>window.recordEvents.filter(e=>e.size>0).length>=3,null,{timeout:30000});await page.locator('#video-stop').click();
  await page.waitForFunction(()=>document.querySelector('#video-status').textContent.startsWith('Stopped'));
  report.recorded_video=await page.locator('#video-review').evaluate(e=>e.src.startsWith('blob:'));
  report.recording_size=await page.locator('#video-review').evaluate(async e=>(await(await fetch(e.src)).blob()).size);
  // Leaving the mode releases hardware, but the stopped video survives navigation.
  await page.locator('[data-mode="typology"]').click();
  report.stream_released=await page.evaluate(()=>window.fixtureStream.getTracks().every(t=>t.readyState==='ended'));
  await page.locator('[data-mode="video"]').click();await page.locator('#video-review').waitFor();
  await page.waitForFunction(()=>document.querySelector('#workspace').getAttribute('aria-busy')==='false');
  await page.locator('#video-stride').fill('5');await page.locator('#video-limit').fill('2');
  report.selected_stride=await page.locator('#video-stride').inputValue();report.selected_limit=await page.locator('#video-limit').inputValue();
  const jobRequest=page.waitForRequest(r=>r.url()===origin+'/api/jobs'&&r.method()==='POST');
  await page.locator('#video-process').click();
  const requested=(await jobRequest).postDataJSON();report.job_params=requested.params;
  if(requested.params.stride!==5||requested.params.max_frames!==2)throw new Error('Extraction controls were not used');
  await page.waitForFunction(recordingId=>document.querySelector('#video-results')?.dataset.recordingId===recordingId&&document.querySelector('#job-panel').hidden&&document.querySelector('#workspace').getAttribute('aria-busy')==='false',requested.params.id,{timeout:120000,polling:500});
  if(await page.locator('#notice').evaluate(e=>e.classList.contains('error')))throw new Error(await page.locator('#notice').textContent());
  for(const label of ['RGB','Depth','Normal','3D OBJ']){
    const link=page.locator('#video-results').getByRole('link',{name:label,exact:true}).first();
    const result=await context.request.get(new URL(await link.getAttribute('href'),origin).href);
    if(!result.ok()||!(await result.body()).length)throw new Error('Missing asset '+label);
  }
  const manifestURL=await page.getByRole('link',{name:'Frame and crop manifest'}).getAttribute('href');
  const manifest=await(await context.request.get(origin+manifestURL)).json();
  report.manifest={url:manifestURL,id:manifest.id,recording_id:manifest.recording_id,stride:manifest.stride,max_frames:manifest.max_frames};
  if(manifest.recording_id!==requested.params.id||manifest.stride!==5||manifest.max_frames!==2)throw new Error('Wrong run displayed');
  if(manifest.crop.join(',')!=='.1,.1,.8,.8'&&manifest.crop.join(',')!=='0.1,0.1,0.8,0.8')throw new Error('Crop mismatch');
  report.ready=manifest.ready;report.frames=manifest.items.map(i=>i.original_frame);
  const videoResponse=await context.request.get(origin+'/api/recordings/'+requested.params.id+'/video');
  if(!videoResponse.ok()||!(await videoResponse.body()).length)throw new Error('Saved recording is not accessible for playback');
  await page.screenshot({path:'test-artifacts/video-capture.png',fullPage:true});
  await page.reload();await page.getByRole('link',{name:'Frame and crop manifest'}).waitFor();report.reload=true;
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2))throw new Error('Video mode has mobile overflow');
  await page.locator('#video-saved').selectOption(requested.params.id);await page.locator('#video-stride').fill('1');await page.locator('#video-limit').fill('120');
  const cancelJobResponse=page.waitForResponse(r=>r.url()===origin+'/api/jobs'&&r.request().method()==='POST');
  await page.locator('#video-process').click();const cancelJob=await(await cancelJobResponse).json();
  await page.locator('#cancel-job').click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Cancelled'),null,{timeout:30000});
  const cancelled=await(await context.request.get(origin+'/api/jobs/'+cancelJob.id)).json();
  if(cancelled.status!=='cancelled')throw new Error('Extraction cancellation failed');report.cancelled=true;
  if(errors.length)throw new Error(errors.join('\n'));
  report.errors=errors;report.passed=true;
}catch(error){report.error=error.message;report.errors=errors;report.record_events=await page.evaluate(()=>window.recordEvents).catch(()=>[]);report.notice=await page.locator('#notice').textContent().catch(()=>null);await page.screenshot({path:'test-artifacts/video-capture-failure.png'}).catch(()=>{});process.exitCode=1;}
finally{await writeFile('test-artifacts/video-capture-report.json',JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify(report,null,2));
