/* Loaded only by /p5-studio, after the untouched upstream classic scripts. */
state.cropFraction=.1;state.cropRect={x:.1,y:.1,w:.8,h:.8};
// Follow the same distinct-frame calibration count as upstream's depth average.
let colorAccum=null,colorReference=null,colorReferenceDepth=null;
const upstreamProcess=processSourceFrame;
processSourceFrame=async function(source){
  const calibrating=state.calibrating,count=state.baselineCount;
  await upstreamProcess(source);
  if(calibrating&&state.baselineCount===count+1&&state.lastImageData){
    const pixels=state.lastImageData.data;
    if(count===0||!colorAccum){colorAccum=new Float64Array(pixels.length);colorReference=null;colorReferenceDepth=null;}
    for(let i=0;i<pixels.length;i++)colorAccum[i]+=pixels[i];
    if(!state.calibrating&&state.baseline){
      const average=new Uint8ClampedArray(pixels.length);for(let i=0;i<average.length;i++)average[i]=colorAccum[i]/state.baselineCount;
      colorReference=new ImageData(average,Core.WIDTH,Core.HEIGHT);colorReferenceDepth=state.baseline;
    }
  }
};
const bridgeStyle=document.createElement('style');bridgeStyle.textContent='.toolbar{overflow-x:auto;overflow-y:hidden}.toolbar>*{flex-shrink:0}';document.head.append(bridgeStyle);
// Studio must never silently open the laptop webcam, including permission probes.
chooseGelSightDevice=devices=>devices.find(d=>/gel\s*sight/i.test(d.label));
const upstreamStartDevice=startSelectedDevice;
startSelectedDevice=async function(){
  const device=state.devices.find(d=>d.deviceId===ui.deviceSelect.value());
  if(!device||!/gel\s*sight/i.test(device.label))throw new Error('Select the named GelSight Mini. Use Start-Material-Studio.cmd if camera labels are unavailable.');
  return upstreamStartDevice();
};
enableCamera=async function(){
  try{await refreshDevices();const device=chooseGelSightDevice(state.devices);
    if(!device)throw new Error('Mini not identified. Connect it and use Start-Material-Studio.cmd for local camera permission.');
    ui.deviceSelect.selected(device.deviceId);state.cameraEnabled=true;await startSelectedDevice();updateToolbarAvailability();
  }catch(error){setStatus(error.message);}
};
function copyCanvas(source){const copy=document.createElement('canvas');copy.width=source.width;copy.height=source.height;copy.getContext('2d').drawImage(source,0,0);return copy;}
// A paused/offscreen embedded p5 canvas can starve Chrome's deferred toBlob
// encoder. Encode the already-frozen bounded canvas synchronously instead.
function pngBlob(canvas){
  const url=canvas.toDataURL('image/png');if(!url.startsWith('data:image/png;base64,'))throw new Error('Image encoding failed.');
  const bytes=Uint8Array.from(atob(url.split(',')[1]),c=>c.charCodeAt(0));
  return new Blob([bytes],{type:'image/png'});
}
let studioSaving=false;
window.studioP5={
  ready:()=>Boolean(state.session&&ui.deviceSelect),
  backgroundStatus:()=>({frames:state.baselineCount,available:Boolean(colorReference&&colorReferenceDepth===state.baseline&&!state.calibrationDirty)}),
  connect:()=>enableCamera(),
  disconnect:()=>{state.stream?.getTracks().forEach(t=>t.stop());state.stream=null;state.cameraEnabled=false;updateToolbarAvailability();},
  centerCrop:async()=>{state.cropFraction=.1;state.cropRect={x:.1,y:.1,w:.8,h:.8};markLiveCalibrationDirty();resetInputSmoothing();if(state.sampleImage)await processSourceFrame(state.sampleImage);},
  async snapshot(backgroundThreshold=12){
    if(studioSaving)throw new Error('A sample is already being saved.');
    if(!state.lastDepth)throw new Error('Connect and calibrate the Mini, or load Demo, before saving.');
    if(state.calibrating||state.calibrationDirty)throw new Error('Complete a fresh no-contact calibration before saving.');
    studioSaving=true;window.studioP5.captureStage='waiting for frame';noLoop();
    try{
      await waitForProcessingIdle(3000);
      if(state.busy)throw new Error('Processing is busy. Try again after the frame finishes.');
      if(!await prepareSynchronousCaptureForExport())throw new Error('No synchronized frame is available.');
      window.studioP5.captureStage='copying mesh';
      // Freeze all arrays and images before any asynchronous PNG encoding.
      renderMeshLayer();
      const raw=copyCanvas(state.captureCanvas),mesh=copyCanvas(state.meshLayer.elt),depth=copyCanvas(state.depthCanvas);
      const rows=data=>data?Array.from({length:Core.HEIGHT},(_,y)=>Array.from(data.slice(y*Core.WIDTH,(y+1)*Core.WIDTH))):null;
      const r=state.cropRect,device=state.devices.find(d=>d.deviceId===ui.deviceSelect.value());
      const payload={depth:rows(state.lastDepth),baseline:rows(state.baseline),crop:[r.x,r.y,r.w,r.h],demo:Boolean(state.sampleImage),device:state.sampleImage?'Bundled p5 demo':device?.label,metadata:createExportMetadata(new Date()),calibrating:false,background_threshold:backgroundThreshold};
      window.studioP5.captureStage='encoding frozen images';
      let background=null,model=null;
      if(colorReference&&colorReferenceDepth===state.baseline&&!state.sampleImage){
        background=document.createElement('canvas');background.width=Core.WIDTH;background.height=Core.HEIGHT;background.getContext('2d').putImageData(colorReference,0,0);
        model=document.createElement('canvas');model.width=Core.WIDTH;model.height=Core.HEIGHT;model.getContext('2d').putImageData(state.lastImageData,0,0);
      }
      const blobs=await Promise.all([pngBlob(raw),pngBlob(mesh),pngBlob(depth)]);
      const output={raw:blobs[0],mesh:blobs[1],depth_preview:blobs[2],payload:new Blob([JSON.stringify(payload)],{type:'application/json'})};
      if(background){output.color_baseline=await pngBlob(background);output.model_rgb=await pngBlob(model);}
      window.studioP5.captureStage='ready to save';
      return output;
    }finally{studioSaving=false;loop();}
  }
};
window.addEventListener('pagehide',()=>state.stream?.getTracks().forEach(t=>t.stop()));
