import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';

export function sampleField(field,u,v) {
  const h=field.length,w=field[0].length,x=Math.max(0,Math.min(w-1,u*(w-1))),y=Math.max(0,Math.min(h-1,v*(h-1)));
  const x0=Math.floor(x),y0=Math.floor(y),x1=Math.min(x0+1,w-1),y1=Math.min(y0+1,h-1),fx=x-x0,fy=y-y0;
  return field[y0][x0]*(1-fx)*(1-fy)+field[y0][x1]*fx*(1-fy)+field[y1][x0]*(1-fx)*fy+field[y1][x1]*fx*fy;
}

export class SurfaceViewer {
  constructor(container,{fallback=null,onStatus=()=>{}}={}) {
    this.container=container;this.onStatus=onStatus;this.options={shape:'sphere',mode:'combined',strength:.13,quality:128,roughness:.62,color:'#929795',exposure:1,environment:true,wireframe:false,repeats:1,rotation:0,physical:false,physicalScale:1,lightAngle:45};
    this.textures=[];this.disposed=false;this.visible=true;
    try {
      this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true});
      this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));this.renderer.outputColorSpace=THREE.SRGBColorSpace;
      this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1;
      this.renderer.domElement.className='webgl';this.renderer.domElement.setAttribute('aria-label','Interactive relief viewer. Drag to rotate, scroll to zoom.');this.renderer.domElement.tabIndex=0;
      container.replaceChildren(this.renderer.domElement);
    } catch(error) {
      this.failed=true;container.textContent='3D unavailable on this device. Static relief preview shown.';
      if(fallback){const img=new Image();img.src=fallback;img.alt='Static relief preview';container.append(img);}
      onStatus('Static fallback — WebGL unavailable');return;
    }
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#182722');
    this.camera=new THREE.PerspectiveCamera(38,1,.01,100);this.camera.up.set(0,0,1);this.camera.position.set(2.2,-3.3,2);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=true;this.controls.dampingFactor=.12;this.controls.minDistance=1.3;this.controls.maxDistance=12;
    this.controls.addEventListener('change',()=>this.render());
    const key=new THREE.DirectionalLight('#fff3db',4.5);key.position.set(-3,-2,3);this.scene.add(key);this.key=key;
    const fill=new THREE.DirectionalLight('#bfdbdf',1.8);fill.position.set(3,3,1);this.scene.add(fill);
    this.ambient=new THREE.HemisphereLight('#d8e8dc','#17201a',1.2);this.scene.add(this.ambient);
    const pmrem=new THREE.PMREMGenerator(this.renderer),room=new RoomEnvironment();this.environment=pmrem.fromScene(room,.06);room.dispose();pmrem.dispose();this.scene.environment=this.environment.texture;
    this.material=new THREE.MeshPhysicalMaterial({color:this.options.color,roughness:.62,metalness:0,ior:1.45,side:THREE.DoubleSide,envMapIntensity:.55});
    this.object=new THREE.Mesh(new THREE.SphereGeometry(1,64,32),this.material);this.scene.add(this.object);
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(container);
    this.visibility=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;if(this.visible)this.render();});this.visibility.observe(container);
    this.renderer.domElement.addEventListener('keydown',e=>{
      if(e.key==='ArrowLeft'||e.key==='ArrowRight'){this.object.rotation.z+=(e.key==='ArrowLeft'?-.12:.12);e.preventDefault();this.render();}
      if(e.key==='+'||e.key==='='){this.camera.position.multiplyScalar(.9);this.render();}
      if(e.key==='-'){this.camera.position.multiplyScalar(1.1);this.render();}
    });
    this.animate=()=>{if(this.disposed)return;this.raf=requestAnimationFrame(this.animate);if(this.visible)this.controls.update();};this.animate();this.resize();
  }
  resize(){if(this.failed||this.disposed)return;const w=this.container.clientWidth||500,h=this.container.clientHeight||420;this.renderer.setSize(w,h,false);this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.render();}
  render(){if(!this.failed&&!this.disposed&&this.visible)this.renderer.render(this.scene,this.camera);}
  setSurface(surface,options={}){this.surface=surface;if(!this.failed)this.makePreviewMaps();this.setOptions(options);}
  makePreviewMaps(){
    // Source inspection supports normal/bump modes even before a material pack.
    this.textures.forEach(t=>t.dispose());this.textures=[];
    const s=this.surface,h=s.height,rows=h.length,cols=h[0].length;
    const stride=s.preview_stride||1,spacing=s.source_spacing||[1,1],dx=spacing[0]*stride,dy=spacing[1]*stride;
    let low=Infinity,high=-Infinity;for(let y=0;y<rows;y++)for(let x=0;x<cols;x++)if(!s.mask||s.mask[y][x]){low=Math.min(low,h[y][x]);high=Math.max(high,h[y][x]);}
    const span=Math.max(high-low,1e-12);
    const texture=(field,normal)=>{
      const pixels=new Uint8Array(rows*cols*4);
      for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){
        let vector;
        if(normal){
          const x0=Math.max(0,x-1),x1=Math.min(cols-1,x+1),y0=Math.max(0,y-1),y1=Math.min(rows-1,y+1);
          const nx=-(field[y][x1]-field[y][x0])/((x1-x0)*dx),ny=(field[y1][x]-field[y0][x])/((y1-y0)*dy),length=Math.hypot(nx,ny,1);
          vector=[nx/length*.5+.5,ny/length*.5+.5,1/length*.5+.5];
          if(s.mask&&!s.mask[y][x])vector=[.5,.5,1];
        }else{const v=(field[y][x]-low)/span;vector=[v,v,v];}
        const index=(y*cols+x)*4;for(let i=0;i<3;i++)pixels[index+i]=Math.round(Math.max(0,Math.min(1,vector[i]))*255);pixels[index+3]=255;
      }
      const t=new THREE.DataTexture(pixels,cols,rows,THREE.RGBAFormat);t.flipY=true;t.wrapS=t.wrapT=THREE.RepeatWrapping;t.magFilter=THREE.LinearFilter;t.needsUpdate=true;this.textures.push(t);return t;
    };
    const fine=s.coarse?h.map((row,y)=>row.map((v,x)=>v-s.coarse[y][x])):h;
    this.maps={normal:texture(fine,true),fullNormal:texture(h,true),bump:texture(h,false)};
  }
  async setMaterial(base,descriptor={},files={}) {
    if(this.failed)return;
    this.material.color.set(descriptor.base_color||'#929795');this.material.roughness=descriptor.roughness??.62;this.material.ior=descriptor.ior??1.45;
    const names={normal:'normal_opengl.png',fullNormal:'normal_full_opengl.png',roughness:'roughness.png',bump:'bump.png',...files};
    const loader=new THREE.TextureLoader();const maps={};
    await Promise.all(Object.entries(names).map(async([key,name])=>{try{const texture=await loader.loadAsync(base+name);texture.colorSpace=THREE.NoColorSpace;texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.anisotropy=Math.min(4,this.renderer.capabilities.getMaxAnisotropy());if(this.disposed){texture.dispose();return;}this.textures.push(texture);maps[key]=texture;}catch{}}));
    if(!this.disposed){this.maps=maps;this.applyMaps();this.render();}
  }
  applyMaps(){
    if(this.failed)return;
    const mode=this.options.mode,maps=this.maps||{};
    this.material.normalMap=mode==='normal'?maps.fullNormal||maps.normal:mode==='combined'?maps.normal:null;
    this.material.bumpMap=mode==='bump'?maps.bump:null;this.material.bumpScale=.08;
    this.material.roughnessMap=maps.roughness||null;
    for(const texture of Object.values(maps)){texture.repeat.set(this.options.repeats,this.options.repeats);texture.rotation=this.options.rotation*Math.PI/180;texture.center.set(.5,.5);}
    this.material.normalScale.set(1,this.options.directx?-1:1);
    this.material.needsUpdate=true;
  }
  setOptions(options={}) {
    Object.assign(this.options,options);if(this.failed||this.disposed)return;
    if(this.options.physical&&this.surface?.source_units!=='mm')this.options.physical=false;
    const o=this.options;this.material.wireframe=o.wireframe;this.material.color.set(o.color);this.material.roughness=o.roughness;
    this.renderer.toneMappingExposure=o.exposure;this.scene.environment=o.environment?this.environment.texture:null;this.ambient.intensity=o.environment?1.2:.25;
    const angle=o.lightAngle*Math.PI/180;this.key.position.set(4*Math.cos(angle),4*Math.sin(angle),o.grazing?.35:2.8);
    this.applyMaps();if(this.surface)this.rebuild();this.render();
  }
  rebuild(){
    const s=this.surface,o=this.options,source=o.mode==='combined'&&s.coarse?s.coarse:s.height;
    const rows=source.length,cols=source[0].length;let lo=Infinity,hi=-Infinity;
    for(let y=0;y<rows;y++)for(let x=0;x<cols;x++)if(!s.mask||s.mask[y][x]){lo=Math.min(lo,source[y][x]);hi=Math.max(hi,source[y][x]);}
    const span=Math.max(hi-lo,1e-12),displaced=['combined','displacement'].includes(o.mode);
    let geometry;
    if(o.shape==='flat'){
      const w=Math.min(cols,o.quality+1),h=Math.min(rows,o.quality+1),positions=[],uv=[],faces=[];
      for(let y=0;y<h;y++)for(let x=0;x<w;x++){
        const u=x/(w-1),v=y/(h-1);const value=sampleField(source,u,v);
        const z=displaced?(o.physical?(value-lo)/25*o.physicalScale:(value-lo)/span*o.strength):0;
        const stride=s.preview_stride||1,sx=o.physical?(cols-1)*(s.source_spacing?.[0]||1)*stride/25:2,sy=o.physical?(rows-1)*(s.source_spacing?.[1]||1)*stride/25:2*rows/cols;
        positions.push((u-.5)*sx,(.5-v)*sy,z);uv.push(u,1-v);
      }
      for(let y=0;y<h-1;y++)for(let x=0;x<w-1;x++){
        const a=y*w+x,b=a+1,c=a+w,d=c+1;
        if(s.mask&&[a,b,c,d].some(i=>!s.mask[Math.round(Math.floor(i/w)/(h-1)*(rows-1))][Math.round((i%w)/(w-1)*(cols-1))]))continue;
        faces.push(a,c,b,b,c,d);
      }
      geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geometry.setIndex(faces);
    } else {
      geometry=new THREE.SphereGeometry(1,o.quality,Math.max(16,o.quality/2));const p=geometry.attributes.position,uv=geometry.attributes.uv;
      const angle=o.rotation*Math.PI/180,cos=Math.cos(angle),sin=Math.sin(angle);
      for(let i=0;i<p.count;i++){
        let u=uv.getX(i),v=1-uv.getY(i),x=u-.5,y=v-.5;
        u=((x*cos-y*sin+.5)*o.repeats)%1;v=((x*sin+y*cos+.5)*o.repeats)%1;if(u<0)u++;if(v<0)v++;
        let value=sampleField(source,u,v);
        if(uv.getY(i)===0||uv.getY(i)===1){const row=source[uv.getY(i)===1?0:rows-1];value=row.reduce((a,b)=>a+b,0)/row.length;}
        const offset=displaced?(o.physical?(value-lo)/25*o.physicalScale:(value-lo)/span*o.strength):0;
        const radial=new THREE.Vector3(p.getX(i),p.getY(i),p.getZ(i)).normalize().multiplyScalar(Math.max(.05,1+offset));p.setXYZ(i,radial.x,radial.y,radial.z);
      }
      // SphereGeometry is Y-up. Rotate to the Z-up surface convention.
      geometry.rotateX(Math.PI/2);
    }
    geometry.computeVertexNormals();geometry.computeBoundingSphere();this.object.geometry.dispose();this.object.geometry=geometry;this.object.scale.setScalar(1);
    this.onStatus(`${displaced?'Actual displaced geometry':'Undisplaced geometry · '+o.mode+' shading'} · ${(geometry.index?.count||geometry.attributes.position.count)/3|0} triangles`);
  }
  setMesh(data){
    if(this.failed)return;this.surface=null;this.maps={};this.applyMaps();
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(data.vertices.flat(),3));geometry.setIndex(data.faces.flat());geometry.computeVertexNormals();geometry.computeBoundingBox();
    const center=geometry.boundingBox.getCenter(new THREE.Vector3()),size=geometry.boundingBox.getSize(new THREE.Vector3());geometry.translate(-center.x,-center.y,-center.z);geometry.scale(2/Math.max(size.x,size.y,size.z),2/Math.max(size.x,size.y,size.z),2/Math.max(size.x,size.y,size.z));
    this.object.geometry.dispose();this.object.geometry=geometry;this.onStatus(`Actual mesh · ${data.full_triangles||data.faces.length} export triangles · ${data.preview_triangles||data.faces.length} preview triangles`);this.render();
  }
  screenshot(){return this.renderer?.domElement.toDataURL('image/png');}
  dispose(){if(this.disposed)return;this.disposed=true;cancelAnimationFrame(this.raf);this.observer?.disconnect();this.visibility?.disconnect();this.controls?.dispose();this.object?.geometry.dispose();this.material?.dispose();this.textures.forEach(t=>t.dispose());this.environment?.dispose();this.renderer?.dispose();this.renderer?.forceContextLoss();}
}
