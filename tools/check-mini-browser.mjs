import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const browser=await chromium.launch({channel:'chrome',headless:true});
try {
  const context=await browser.newContext({permissions:['camera']});
  const page=await context.newPage();await page.goto('http://127.0.0.1:8090/');
  const result=await page.evaluate(async()=>{
    const devices=await navigator.mediaDevices.enumerateDevices(),mini=devices.find(d=>d.kind==='videoinput'&&/gelsight/i.test(d.label));
    const names=devices.filter(d=>d.kind==='videoinput').map(d=>d.label);
    if(!mini)return {names,error:'No named Mini in the browser.'};
    try{
      const stream=await navigator.mediaDevices.getUserMedia({video:{deviceId:{exact:mini.deviceId},width:{ideal:640},height:{ideal:480}},audio:false});
      const video=document.createElement('video');video.muted=true;video.srcObject=stream;await video.play();
      await new Promise(resolve=>video.requestVideoFrameCallback(resolve));
      const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext('2d').drawImage(video,0,0);
      const settings=stream.getVideoTracks()[0].getSettings();stream.getTracks().forEach(t=>t.stop());
      return {names,connected:true,width:settings.width,height:settings.height,image:canvas.toDataURL('image/png')};
    }catch(error){return {names,error:error.name+': '+error.message};}
  });
  if(result.image){await writeFile('test-artifacts/mini-browser-check.png',Buffer.from(result.image.split(',')[1],'base64'));delete result.image;}
  await writeFile('test-artifacts/mini-browser-check.json',JSON.stringify(result,null,2));console.log(result);
}finally{await browser.close();}
