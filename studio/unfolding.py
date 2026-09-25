"""Appearance-based texture separation and an explicitly inferred flat assembly.

This is not a metric atlas, a recovered object topology, or a UV unwrap of an
observed closed mesh. Source regions, exclusions, rotations and seam scores are
retained so every displayed pixel can be traced back to its selected input.
"""
import json
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .records import uid, now
from .typology import source_image


def _source(store, item):
    kind, key=item['kind'],item['id']
    if kind not in ('frames','patches'):raise ValueError('Unfolding accepts RGB frames or height patches.')
    picture,digest=source_image(store,kind,key)
    record=store.get(kind,key);patch_id=key if kind=='patches' else None
    if kind=='frames' and record['settings'].get('sample_id'):
        patch_id=store.get('samples',record['settings']['sample_id'])['patch_id']
    field=None;mask=None
    if patch_id:
        patch,arrays=store.patch(patch_id);field=arrays['height'];mask=arrays['mask']
        if 'rgb' in arrays:picture=Image.fromarray(arrays['rgb'].astype(np.uint8))
    picture.thumbnail((256,256),Image.Resampling.LANCZOS)
    rgb=np.asarray(picture.convert('RGB'));h,w=rgb.shape[:2]
    valid=np.ones((h,w),bool) if mask is None else cv2.resize(mask.astype(np.uint8),(w,h),interpolation=cv2.INTER_NEAREST).astype(bool)
    height=np.zeros((h,w),np.float32)
    if field is not None:
        height=cv2.resize(field,(w,h),interpolation=cv2.INTER_LINEAR)
        lo,hi=np.percentile(height[valid],[1,99]);height=np.clip((height-lo)/max(hi-lo,1e-9),0,1)
    return rgb,height,valid,dict(**item,source_sha256=digest,patch_id=patch_id,
        name=record.get('name',record.get('source_name','Texture')),analysis_size=[w,h],
        depth_present=field is not None,display_depth_normalization='per-source 1–99 percentile; no physical scale',
        source_crop=record.get('settings',{}).get('sample_crop'))


def _features(rgb):
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(np.float32)/255
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    mean=cv2.GaussianBlur(gray,(0,0),3)
    spread=np.sqrt(np.maximum(0,cv2.GaussianBlur(gray*gray,(0,0),3)-mean*mean))
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0);gy=cv2.Sobel(gray,cv2.CV_32F,0,1)
    return np.dstack((cv2.GaussianBlur(lab,(0,0),3),spread*3,cv2.GaussianBlur(np.abs(gx),(0,0),3),cv2.GaussianBlur(np.abs(gy),(0,0),3)))


def _edge(rgb,mask,axis,side):
    """Appearance, occupancy and contour-distance profiles along a facing edge."""
    if axis==0:rgb,mask=rgb.transpose(1,0,2),mask.T
    if side==0:rgb,mask=rgb[:,::-1],mask[:,::-1]
    profile=[]
    for row,m in zip(rgb,mask):
        indices=np.flatnonzero(m)
        if indices.size:
            last=indices[-1];profile.append([*row[max(0,last-3):last+1].mean(axis=0)/255,1,(len(m)-1-last)/len(m)])
        else:profile.append([0,0,0,0,1])
    return cv2.resize(np.asarray(profile,np.float32),(5,32),interpolation=cv2.INTER_AREA)


def build_unfolding(store,items,name='Texture unfolding',settings=None,progress=None):
    settings=settings or {};groups=int(settings.get('groups',4));seed=int(settings.get('seed',7))
    if not isinstance(items,list) or not 1<=len(items)<=32:raise ValueError('Select 1–32 source images.')
    if len({(i['kind'],i['id']) for i in items})!=len(items):raise ValueError('Select each source once.')
    if not 2<=groups<=8:raise ValueError('Choose 2–8 texture groups.')
    if not 0<=seed<=2**31-1:raise ValueError('Seed must be an integer between 0 and 2147483647.')
    sources=[_source(store,item) for item in items]
    features=[_features(s[0]) for s in sources]
    training=np.concatenate([f[s[2]][::max(1,int(s[2].sum())//4000)] for f,s in zip(features,sources)])
    if len(training)<groups:raise ValueError('Not enough valid pixels for the requested groups.')
    scale=np.maximum(training.std(axis=0),.04);training=np.ascontiguousarray(training/scale,np.float32)
    cv2.setRNGSeed(seed)
    _,_,centers=cv2.kmeans(training,groups,None,(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,60,.001),1,cv2.KMEANS_PP_CENTERS)
    record_id=uid();directory=store.path('unfoldings/'+record_id);directory.mkdir(parents=True)
    regions=[];coverage=[]
    palette=np.array([[75,117,96],[188,110,72],[99,134,173],[173,148,66],[140,99,159],[65,155,155],[195,112,142],[157,155,146]],np.uint8)
    for index,((rgb,height,valid,meta),f) in enumerate(zip(sources,features)):
        distances=np.sum((f[:,:,None,:]/scale-centers[None,None,:,:])**2,axis=-1)
        labels=np.argmin(distances,axis=-1).astype(np.uint8)
        labels=cv2.medianBlur(labels,5)
        segmented=palette[labels];segmented[~valid]=[241,236,223]
        Image.fromarray(segmented).save(directory/f'segments-{index:02}.png')
        Image.fromarray(rgb).save(directory/f'source-{index:02}.png')
        candidates=[]
        for group in range(groups):
            count,component,stats,_=cv2.connectedComponentsWithStats(((labels==group)&valid).astype(np.uint8),8)
            for label in range(1,count):
                x,y,w,h,area=stats[label]
                if area<max(32,int(valid.sum()*.015)):continue
                candidates.append((int(area),group,(int(x),int(y),int(w),int(h)),component[y:y+h,x:x+w]==label))
        # Bound complexity while retaining the largest connected regions from each input.
        candidates=sorted(candidates,key=lambda c:-c[0])[:max(2,64//len(items))]
        included=0
        for area,group,(x,y,w,h),mask in candidates:
            included+=area
            regions.append(dict(source=index,group=group,box=[x,y,w,h],pixels=area,
                rgb=rgb[y:y+h,x:x+w].copy(),height=height[y:y+h,x:x+w].copy(),mask=mask))
        coverage.append(dict(source=index,retained_pixels=included,valid_pixels=int(valid.sum()),fraction=included/max(1,int(valid.sum()))))
        if progress:progress(.1+.35*(index+1)/len(sources),'Separating connected texture regions')
    regions=regions[:64]
    if not regions:raise ValueError('No connected texture regions were large enough. Try fewer groups or a clearer crop.')
    columns=int(settings.get('columns') or math.ceil(math.sqrt(len(regions))))
    if not 1<=columns<=16:raise ValueError('Choose 1–16 assembly columns or 0 for automatic.')
    rows=math.ceil(len(regions)/columns);tile=128
    if max(columns,rows)>32:raise ValueError('Assembly is too elongated. Use more columns.')
    variants={}
    for i,r in enumerate(regions):
        scale_tile=min((tile-4)/r['rgb'].shape[1],(tile-4)/r['rgb'].shape[0]);size=(max(2,round(r['rgb'].shape[1]*scale_tile)),max(2,round(r['rgb'].shape[0]*scale_tile)))
        rgb=np.full((tile,tile,3),[241,236,223],np.uint8);height=np.zeros((tile,tile),np.float32);mask=np.zeros((tile,tile),bool)
        x=(tile-size[0])//2;y=(tile-size[1])//2
        rgb[y:y+size[1],x:x+size[0]]=cv2.resize(r['rgb'],size)
        height[y:y+size[1],x:x+size[0]]=cv2.resize(r['height'],size)
        mask[y:y+size[1],x:x+size[0]]=cv2.resize(r['mask'].astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
        rgb[~mask]=[241,236,223]
        for rotation in range(4):
            a,b,c=[np.rot90(v,rotation).copy() for v in (rgb,height,mask)]
            variants[i,rotation]=(a,b,c,[_edge(a,c,axis,side) for axis,side in ((1,0),(1,1),(0,0),(0,1))])
    remaining=set(range(len(regions)));placed=[];seams=[]
    for cell in range(len(regions)):
        left=placed[-1] if cell%columns else None;above=placed[cell-columns] if cell>=columns else None
        best=None
        for i in sorted(remaining):
            for rotation in range(4):
                score=0.;edges=variants[i,rotation][3]
                for neighbor,direction,target in ((left,0,1),(above,2,3)):
                    if neighbor is not None:
                        prev,turn,_=neighbor
                        score+=float(np.mean((edges[direction]-variants[prev,turn][3][target])**2))
                        score+=.12*(regions[prev]['group']!=regions[i]['group'])
                choice=(score,i,rotation)
                if best is None or choice<best:best=choice
        score,i,rotation=best;remaining.remove(i);placed.append((i,rotation,score))
        seams.append(dict(cell=cell,left=cell-1 if left is not None else None,above=cell-columns if above is not None else None,cost=score,verified=False))
        if progress:progress(.5+.35*(cell+1)/len(regions),'Connecting similar edge profiles and texture groups')
    image=np.full((rows*tile,columns*tile,3),[241,236,223],np.uint8)
    height=np.zeros(image.shape[:2],np.float32);mask=np.zeros(height.shape,bool);region_map=np.zeros(height.shape,np.uint16);manifest=[]
    for cell,(index,turn,cost) in enumerate(placed):
        r=regions[index];rgb,z,m,_=variants[index,turn];x=cell%columns*tile;y=cell//columns*tile
        image[y:y+tile,x:x+tile]=rgb;height[y:y+tile,x:x+tile]=z;mask[y:y+tile,x:x+tile]=m;region_map[y:y+tile,x:x+tile]=np.where(m,cell+1,0)
        manifest.append(dict(id=cell+1,source=r['source'],group=r['group'],source_box=r['box'],source_pixels=r['pixels'],rotation_ccw=turn*90,cell=[cell%columns,cell//columns],display_cell_pixels=tile,edge_cost=cost))
    Image.fromarray(image).save(directory/'flat.png');Image.fromarray(region_map).save(directory/'regions.png')
    Image.fromarray((mask*255).astype(np.uint8)).save(directory/'coverage.png')
    np.savez_compressed(directory/'assembly.npz',height=height,mask=mask,region_ids=region_map,synthetic_mask=mask)
    # Bound browser geometry while keeping the full-resolution image and provenance.
    size=(min(256,image.shape[1]),min(256,image.shape[0]))
    surface=dict(height=cv2.resize(height,size).tolist(),mask=(cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0).astype(int).tolist(),source_units='relative',width=size[0],height_px=size[1])
    (directory/'surface.json').write_text(json.dumps(surface),encoding='utf-8')
    record=dict(id=record_id,created_at=now(),name=str(name).strip()[:160] or 'Texture unfolding',directory='unfoldings/'+record_id,
        sources=[s[3] for s in sources],regions=manifest,seams=seams,coverage=coverage,
        settings=dict(groups=groups,seed=seed,columns=columns,algorithm='Lab / local contrast / directional gradients; k-means + connected components; greedy rotated edge matching',version=1),
        cluster_centers=centers.tolist(),feature_scale=scale.tolist(),
        interpretation='Inferred artistic assembly. Region grouping and joins are appearance-based, not verified overlap or recovered object topology. Sphere is a UV projection with seam and pole distortion. Missing depth is flat; available depth is normalized per source.',
        metric_validated=False,synthetic=True)
    (directory/'unfolding.json').write_text(json.dumps(record,indent=2,allow_nan=False),encoding='utf-8')
    store.save('unfoldings',record)
    return record
