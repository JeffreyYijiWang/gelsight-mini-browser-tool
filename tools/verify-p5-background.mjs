// A synthetic canvas stream verifies the RGB calibration hook; no camera opens.
import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:1280,height:760}});
try{
  await page.goto('http://127.0.0.1:8091/p5-studio');
  await page.waitForFunction(()=>window.studioP5?.ready(),null,{timeout:60000});
  await page.getByRole('button',{name:'Demo',exact:true}).click();
  await page.waitForFunction(()=>window.__gelsightState.lastDepth&&!window.__gelsightState.busy,null,{timeout:60000});
  const result=await page.evaluate(async()=>{
    noLoop();await waitForProcessingIdle(3000);
    state.baseline=null;state.baselineCount=0;state.calibrating=true;state.baselineAccum=new Float32Array(Core.PIXELS);
    for(let i=0;i<50;i++)await processSourceFrame(state.sampleImage);
    const status=window.studioP5.backgroundStatus();
    if(status.frames!==50||!status.available)throw new Error('RGB calibration did not follow the 50 depth frames.');
    const canvas=document.createElement('canvas');canvas.width=state.captureCanvas.width;canvas.height=state.captureCanvas.height;
    canvas.getContext('2d').drawImage(state.captureCanvas,0,0);
    const video=document.createElement('video');video.muted=true;video.srcObject=canvas.captureStream(15);await video.play();
    state.sampleImage=null;state.stream=video.srcObject;state.video=video;state.calibrationDirty=false;
    const bundle=await window.studioP5.snapshot();
    state.stream.getTracks().forEach(t=>t.stop());
    if(!bundle.color_baseline?.size||!bundle.model_rgb?.size)throw new Error('RGB reference missing from synchronized snapshot.');
    return {synthetic_stream:true,hardware_opened:false,calibration_frames:status.frames,color_baseline_bytes:bundle.color_baseline.size,model_rgb_bytes:bundle.model_rgb.size,passed:true};
  });
  await writeFile('test-artifacts/p5-background-report.json',JSON.stringify(result,null,2));console.log(result);
}finally{await browser.close();}
