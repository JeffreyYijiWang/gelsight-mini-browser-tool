// Stopped recordings survive navigation in this tab until uploaded or replaced.
let draft=null,selectedRecording='',selectedRun='',lastStride=10,lastLimit=60;

export async function mountVideo(root,{api,runJob,refresh,getState,esc,notice}){
  let stream=null,recorder=null,timer=null,reference=null,disposed=false,uploading=false,device='';
  const state=getState();
  root.innerHTML=`<section class="mode-intro"><div><h2>Record a touch sequence.</h2><p>Record the Mini, review the video, then extract photos with matching cropped depth, normals and geometry.</p></div></section>
  <section class="panel"><div class="field-row"><label class="field">GelSight camera<select id="video-device"></select></label><label class="field">Requested resolution<select id="video-resolution"><option value="640,480">640 × 480</option><option value="958,720">958 × 720</option><option value="1640,1232">1640 × 1232</option></select></label><label class="field">Recording name<input id="video-name" maxlength="100" value="Mini sequence"></label></div>
  <div class="actions"><button type="button" id="video-connect">Connect Mini</button><button type="button" id="video-reference" disabled>Save untouched reference</button><button type="button" id="video-start" disabled>Start recording</button><button type="button" id="video-stop" disabled>Stop recording</button></div>
  <p id="video-status" role="status">Connect the named GelSight Mini. No recording starts automatically.</p><p id="video-reference-status" class="hint">Optional: lift clear of contact and save a reference before recording. This is background subtraction, not metric calibration.</p>
  <video id="video-live" autoplay playsinline muted style="width:100%;max-height:440px;background:#182722;object-fit:contain"></video>
  <p class="hint">Records RGB video without audio, up to 10 minutes or approximately 120 MiB. All derived assets use the central 80% in X and Y: 10% removed from every edge, once before reconstruction. Video depth is computed offline, not recorded as live p5 depth.</p></section>
  <section class="panel"><h3>Review and extract photos</h3><video id="video-review" controls playsinline style="width:100%;max-height:360px" hidden></video><a id="video-download" class="web-link" download="mini-recording.webm" hidden>Download recorded video</a>
  <div class="field-row"><label class="field">Extract every Nth frame<input id="video-stride" type="number" min="1" max="300" value="10"></label><label class="field">Maximum photos<input id="video-limit" type="number" min="1" max="120" value="60"></label><label class="field">Saved recording<select id="video-saved"><option value="">Current stopped recording</option>${(state.recordings||[]).map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('')}</select></label></div>
  <div class="actions"><button type="button" id="video-process">Extract frames + depth + normals + mesh</button><a class="web-link" href="#typology">Compare photos in Live Typology</a></div><p class="hint">FFmpeg extracts at most 120 photos from the first 10 minutes, resizing only when larger than 1280 × 960. Low-quality frames stay saved as RGB with a rejection reason; missing depth is never invented. Work can be cancelled in the job panel.</p></section>
  <section class="panel"><h3>Extracted collections</h3><select id="video-runs">${(state.video_runs||[]).map(r=>`<option value="${r.id}">${esc(r.name)} · ${r.items.length} photos · ${esc(r.status)}</option>`).join('')}</select><div id="video-results"></div></section>`;
  const $=selector=>root.querySelector(selector),status=text=>{if(!disposed)$('#video-status').textContent=text;};
  $('#video-stride').value=lastStride;$('#video-limit').value=lastLimit;
  const attempt=fn=>async()=>{try{await fn();}catch(e){status(e.message);notice(e.message,true);}};
  let previewURL=null;
  const showDraft=()=>{if(previewURL){URL.revokeObjectURL(previewURL);previewURL=null;}const saved=getState().recordings?.find(r=>r.id===selectedRecording);let source,filename;
    if(saved){source='/api/recordings/'+saved.id+'/video';filename=saved.name;}
    else if(draft){previewURL=URL.createObjectURL(draft.blob);source=previewURL;filename=draft.filename;}
    else{$('#video-review').hidden=true;$('#video-download').hidden=true;return;}
    $('#video-review').src=source;$('#video-review').hidden=false;$('#video-download').href=source;$('#video-download').download=filename;$('#video-download').hidden=false;};showDraft();
  const stop=()=>{if(recorder?.state==='recording'){recorder.stop();clearInterval(timer);status('Finishing video…');}};
  $('#video-stop').onclick=stop;
  $('#video-connect').onclick=attempt(async()=>{
    if(recorder?.state==='recording')throw new Error('Stop recording before changing the camera.');
    stream?.getTracks().forEach(t=>t.stop());stream=null;$('#video-start').disabled=true;$('#video-reference').disabled=true;
    const devices=await navigator.mediaDevices.enumerateDevices(),chosen=devices.find(d=>d.deviceId===$('#video-device').value&&/gel\s*sight/i.test(d.label));
    if(!chosen)throw new Error('No named GelSight found. Plug it in and open Studio with Start-Material-Studio.cmd.');
    const [width,height]=$('#video-resolution').value.split(',').map(Number);
    stream=await navigator.mediaDevices.getUserMedia({video:{deviceId:{exact:chosen.deviceId},width:{ideal:width},height:{ideal:height}},audio:false});
    if(disposed){stream.getTracks().forEach(t=>t.stop());return;}
    device=chosen.label;reference=null;$('#video-reference-status').textContent='No reference saved for this camera setup.';
    $('#video-live').srcObject=stream;await $('#video-live').play();$('#video-start').disabled=false;$('#video-reference').disabled=false;
    const settings=stream.getVideoTracks()[0].getSettings();status(`${device} · ${settings.width} × ${settings.height} · ready`);
    stream.getVideoTracks()[0].onended=()=>{stop();if(!disposed){$('#video-start').disabled=true;$('#video-reference').disabled=true;status('Mini disconnected. Stop/review any recorded video, then reconnect.');}};
  });
  $('#video-reference').onclick=attempt(async()=>{
    if(!stream?.active)throw new Error('Connect the Mini first.');
    const video=$('#video-live'),canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;canvas.getContext('2d').drawImage(video,0,0);
    reference=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));$('#video-reference-status').textContent='Untouched reference saved for this recording setup. Reconnect to reset it.';
  });
  $('#video-start').onclick=attempt(async()=>{
    if(!stream?.active)throw new Error('Connect the Mini first.');
    if(uploading)throw new Error('Wait for the current upload.');
    const mime=['video/webm;codecs=vp8','video/webm;codecs=vp9','video/webm','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    if(!mime)throw new Error('This browser cannot record video. Use the dedicated Chrome window.');
    const chunks=[];let bytes=0;const started=performance.now(),recordedReference=reference,recordedDevice=device,name=$('#video-name').value.trim()||'Mini sequence';
    recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:6000000});
    recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>=120*1024*1024)stop();}};
    recorder.onerror=e=>{status(e.error?.message||'Recording failed.');stop();};
    recorder.onstop=()=>{clearInterval(timer);const blob=new Blob(chunks,{type:mime});
      if(!blob.size){if(!disposed){$('#video-start').disabled=!stream?.active;$('#video-stop').disabled=true;$('#video-reference').disabled=!stream?.active;$('#video-connect').disabled=false;$('#video-process').disabled=false;status('No video frames were recorded. Wait for the live preview, then record a longer take.');}return;}
      draft={blob,baseline:recordedReference,device:recordedDevice,filename:name+(mime.includes('mp4')?'.mp4':'.webm')};selectedRecording='';
      if(!disposed){$('#video-start').disabled=!stream?.active;$('#video-stop').disabled=true;$('#video-reference').disabled=!stream?.active;$('#video-connect').disabled=false;$('#video-process').disabled=false;$('#video-saved').value='';showDraft();status(`Stopped · ${(blob.size/1024/1024).toFixed(1)} MiB. Review, then extract photos.`);}};
    recorder.start(1000);$('#video-start').disabled=true;$('#video-stop').disabled=false;$('#video-reference').disabled=true;$('#video-connect').disabled=true;$('#video-process').disabled=true;
    timer=setInterval(()=>{const seconds=Math.floor((performance.now()-started)/1000);status(`Recording · ${seconds}s · ${(bytes/1024/1024).toFixed(1)} MiB`);if(seconds>=600)stop();},500);
  });
  $('#video-saved').value=selectedRecording;$('#video-saved').onchange=()=>{selectedRecording=$('#video-saved').value;showDraft();};
  $('#video-process').onclick=attempt(async()=>{
    if(recorder?.state==='recording')throw new Error('Stop recording before extraction.');
    const stride=Number($('#video-stride').value),limit=Number($('#video-limit').value);
    if(!Number.isInteger(stride)||stride<1||stride>300||!Number.isInteger(limit)||limit<1||limit>120)throw new Error('Use an interval of 1–300 and a photo limit of 1–120.');
    lastStride=stride;lastLimit=limit;
    const button=$('#video-process');button.disabled=true;uploading=true;
    try{
      if(!selectedRecording){if(!draft)throw new Error('Record and stop a video first, or select a saved recording.');if(draft.blob.size>128*1024*1024)throw new Error('Video exceeds 128 MiB. Download it and record a shorter take.');
        const form=new FormData();form.append('file',draft.blob,draft.filename);form.append('device',draft.device);if(draft.baseline)form.append('baseline',draft.baseline,'baseline.png');status('Saving the original video locally…');
        const saved=await api('/video-recordings','POST',form);selectedRecording=saved.id;await refresh(false);$('#video-saved').add(new Option(saved.name,saved.id));$('#video-saved').value=saved.id;
      }
      stream?.getTracks().forEach(t=>t.stop());stream=null;
      await runJob('video_frames',{id:selectedRecording,stride,max_frames:limit},result=>{selectedRun=result.id;});
    }finally{uploading=false;if(!disposed)button.disabled=false;}
  });
  function renderRun(){const run=getState().video_runs?.find(r=>r.id===selectedRun);if(!run){$('#video-results').innerHTML='<p>No extracted collection selected yet.</p>';return;}
    $('#video-results').dataset.recordingId=run.recording_id;
    const samples=getState().samples||[];
    $('#video-results').innerHTML=`<p>${run.items.filter(i=>i.status==='ready').length} ready · ${run.items.filter(i=>i.status==='rejected').length} rejected${run.frame_limit_reached?' · photo limit reached':''}. ${esc(run.interpretation)}</p><a class="web-link" href="/api/files/video_runs/${run.id}/manifest.json" download>Frame and crop manifest</a><div class="typology-candidates">${run.items.map(item=>{const sample=samples.find(s=>s.id===item.sample_id),base=sample?`/api/files/samples/${sample.id}/`:'';return `<article><img loading="lazy" style="max-width:100%" src="${base?base+'raw.png':'/api/frames/'+item.frame_id+'/image'}" alt="Extracted frame ${item.original_frame}"><p>Frame ${item.original_frame} · ${item.timestamp_seconds?.toFixed(3)??'?'}s</p>${sample?Object.entries({rgb:'RGB',depth_preview:'Depth',normal_opengl:'Normal',mesh:'3D OBJ'}).map(([key,label])=>`<a class="web-link" href="${base}${sample.assets[key]}" download>${label}</a>`).join(' '):`<p>${esc(item.error||'No surface')}</p>`}</article>`;}).join('')}</div>`;
  }
  selectedRun=selectedRun||state.video_runs?.at(-1)?.id||'';$('#video-runs').value=selectedRun;$('#video-runs').onchange=()=>{selectedRun=$('#video-runs').value;renderRun();};renderRun();
  const capabilities=await api('/video-capabilities');if(!capabilities.ffmpeg){$('#video-process').disabled=true;status('Install FFmpeg and add its bin folder to PATH, then restart Studio before extraction.');}
  const devices=(await navigator.mediaDevices.enumerateDevices().catch(()=>[])).filter(d=>d.kind==='videoinput'&&/gel\s*sight/i.test(d.label));
  $('#video-device').innerHTML=devices.map(d=>`<option value="${esc(d.deviceId)}">${esc(d.label)}</option>`).join('')||'<option>No named GelSight detected</option>';
  const unload=e=>{if(recorder?.state==='recording'||draft&&!selectedRecording){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',unload);
  return ()=>{disposed=true;clearInterval(timer);stop();stream?.getTracks().forEach(t=>t.stop());if(previewURL)URL.revokeObjectURL(previewURL);window.removeEventListener('beforeunload',unload);};
}
