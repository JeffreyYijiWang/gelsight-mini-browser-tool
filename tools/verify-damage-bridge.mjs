// Test the actual Studio bridge's baseline binding without loading camera/WASM.
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const state={baselineCount:0,calibrating:true,calibrationDirty:false,video:{videoWidth:640,videoHeight:480},lastDepth:new Float32Array(320*240),session:{}};
const context=vm.createContext({state,Core:{WIDTH:320,HEIGHT:240},ui:{deviceSelect:{value:()=> 'fixture'}},
  ImageData:class{constructor(data,width,height){Object.assign(this,{data,width,height});}},
  processSourceFrame:async()=>{state.baselineCount++;state.lastImageData={data:new Uint8ClampedArray(320*240*4).fill(128)};if(state.baselineCount===50){state.calibrating=false;state.baseline=new Float32Array(320*240);}},
  startSelectedDevice:()=>{},document:{head:{append:()=>{}},createElement:()=>({getContext:()=>({putImageData:()=>{}}),toDataURL:()=> 'data:image/png;base64,fixture'})},
  window:{addEventListener:()=>{}}});
vm.runInContext(readFileSync('studio/web/p5-bridge.js','utf8'),context);
const bridge=context.window.studioP5;
assert.throws(()=>bridge.damageReference(),/untouched/);
for(let i=0;i<50;i++)await context.processSourceFrame({});
const reference=bridge.damageReference();bridge.setDamage({...reference,regions:[[.5,.5,.05,.05]]});
state.baseline=new Float32Array(320*240);
await assert.rejects(bridge.snapshot(),/stale/);
assert.throws(()=>bridge.setDamage(reference),/Reference changed/);
bridge.setDamage(null);
state.calibrationDirty=true;
assert.throws(()=>bridge.damageReference(),/untouched/);
console.log('Damage reference binding, 50-frame reference readiness, and stale-baseline save rejection passed.');
