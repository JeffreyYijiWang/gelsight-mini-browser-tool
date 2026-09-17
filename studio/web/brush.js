export class DrawingLab {
  constructor(canvas,tipURL,grainURL){
    this.canvas=canvas;this.ctx=canvas.getContext('2d');this.strokes=[];this.options={size:50,spacing:.18,opacity:.8,pressure:.5,grainScale:1,pickup:false};this.ready=this.load(tipURL,grainURL);
    this.clear();this.drawing=false;
    canvas.addEventListener('pointerdown',this.down=e=>{e.preventDefault();canvas.setPointerCapture(e.pointerId);this.drawing=true;this.strokes.push({options:{...this.options},points:[]});this.last=null;this.move(e);});
    canvas.addEventListener('pointermove',this.motion=e=>{if(this.drawing)this.move(e);});
    canvas.addEventListener('pointerup',this.up=()=>{this.drawing=false;this.last=null;});canvas.addEventListener('pointercancel',this.up);
  }
  async load(tipURL,grainURL){
    const load=url=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=url;});
    const [tip,grain]=await Promise.all([load(tipURL),load(grainURL)]);this.tip=tip;this.grain=grain;
    const c=document.createElement('canvas');c.width=c.height=128;const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(tip,0,0,128,128);this.tipData=ctx.getImageData(0,0,128,128).data;ctx.drawImage(grain,0,0,128,128);this.grainData=ctx.getImageData(0,0,128,128).data;
  }
  clear(){this.ctx.fillStyle='#f7f2e7';this.ctx.fillRect(0,0,this.canvas.width,this.canvas.height);}
  move(event){
    const rect=this.canvas.getBoundingClientRect();const point={x:(event.clientX-rect.left)/rect.width*this.canvas.width,y:(event.clientY-rect.top)/rect.height*this.canvas.height,p:event.pointerType==='pen'?event.pressure:this.options.pressure};
    const stroke=this.strokes.at(-1);stroke.points.push(point);this.segment(this.last||point,point,stroke.options);this.last=point;
  }
  segment(a,b,options){const distance=Math.hypot(b.x-a.x,b.y-a.y),n=Math.max(1,Math.ceil(distance/Math.max(1,options.size*options.spacing)));for(let i=0;i<=n;i++){const t=i/n;this.stamp(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,a.p+(b.p-a.p)*t,options);}}
  stamp(x,y,p,o){
    if(!this.tipData)return;
    const c=document.createElement('canvas');c.width=c.height=128;const ctx=c.getContext('2d');const image=ctx.createImageData(128,128);
    for(let yy=0;yy<128;yy++)for(let xx=0;xx<128;xx++){
      const i=(yy*128+xx)*4,gx=Math.floor((xx+x)/o.grainScale)%128,gy=Math.floor((yy+y)/o.grainScale)%128,gi=((gy+128)%128*128+(gx+128)%128)*4;
      const relief=1-this.tipData[i]/255;const pickup=o.pickup?(relief>=1-p?1:0):p;const alpha=relief*(.35+.65*this.grainData[gi]/255)*o.opacity*pickup;
      image.data[i]=33;image.data[i+1]=48;image.data[i+2]=39;image.data[i+3]=Math.round(alpha*255);
    }
    ctx.putImageData(image,0,0);const size=o.size*(.45+.55*p);this.ctx.drawImage(c,x-size/2,y-size/2,size,size);
  }
  async replay(){await this.ready;this.clear();for(const stroke of this.strokes){let previous=null;for(const point of stroke.points){this.segment(previous||point,point,stroke.options);previous=point;}}}
  undo(){this.strokes.pop();this.replay();}
  dispose(){this.canvas.removeEventListener('pointerdown',this.down);this.canvas.removeEventListener('pointermove',this.motion);this.canvas.removeEventListener('pointerup',this.up);this.canvas.removeEventListener('pointercancel',this.up);}
}
