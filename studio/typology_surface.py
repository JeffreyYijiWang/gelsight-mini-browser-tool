"""Actual comparison geometry in the frozen ShuffleSnap cell order."""
import json
import math

import cv2
import numpy as np
from PIL import Image


def display_normals(height, labels, spacing):
    """Finite differences only across valid edges within the same component.

    Average forward/backward slopes where both exist, use one-sided slopes at
    boundaries, and mask points without a slope in both axes. Rows point down.
    """
    gradients=[];supported=[]
    for axis,step in ((1,spacing[0]),(0,spacing[1])):
        before=[slice(None)]*2;after=before.copy()
        before[axis]=slice(None,-1);after[axis]=slice(1,None)
        before,after=tuple(before),tuple(after)
        edges=(labels[before]>0)&(labels[before]==labels[after])
        delta=np.where(edges,(height[after]-height[before])/step,0)
        total=np.zeros(height.shape,np.float32);count=np.zeros(height.shape,np.uint8)
        total[before]+=delta;total[after]+=delta
        count[before]+=edges;count[after]+=edges
        gradients.append(total/np.maximum(count,1));supported.append(count>0)
    valid=(labels>0)&supported[0]&supported[1]
    normals=np.stack((-gradients[0],gradients[1],np.ones(height.shape)),axis=-1)
    normals/=np.linalg.norm(normals,axis=-1,keepdims=True)
    normals[~valid]=(0,0,1)
    return normals.astype(np.float32),valid


def save_normals(directory, prefix, normals, mask, synthetic_influence):
    encoded=np.rint(np.clip(normals*.5+.5,0,1)*255).astype(np.uint8)
    for convention in ('opengl','directx'):
        pixels=encoded.copy()
        if convention=='directx':pixels[...,1]=255-pixels[...,1]
        pixels[~mask]=(128,128,255)
        Image.fromarray(pixels).save(directory/f'{prefix}-normal-{convention}.png')
    Image.fromarray((mask*255).astype(np.uint8)).save(directory/f'{prefix}-normal-mask.png')
    np.savez_compressed(directory/f'{prefix}-normals.npz',normals=normals,mask=mask,
                        synthetic_influence_mask=synthetic_influence)


def build_surface(store,directory,board):
    columns,rows=board['width'],board['height']
    tile=max(3,min(128,int(math.sqrt(220_000/(columns*rows))),1024//max(columns,rows)))
    shape=(rows*tile,columns*tile)
    height=np.zeros(shape,np.float32);mask=np.zeros(shape,bool);cell_ids=np.zeros(shape,np.uint16)
    rgb=np.full((*shape,3),[241,236,223],np.uint8);sources=[]
    # p5 samples are always relative. If a board mixes metric and relative inputs,
    # keep original source numbers in separate patches; use per-source normalized
    # display values here rather than incorrectly combining incompatible units.
    candidates=[]
    patches=store.list('patches')
    for entry in board['items']:
        patch_id=entry['id'] if entry['kind']=='patches' else None
        if entry.get('sample_id'):patch_id=store.get('samples',entry['sample_id'])['patch_id']
        elif entry['kind']=='frames':
            matching=[p for p in patches if entry['id'] in p['source_ids']]
            if matching:patch_id=matching[-1]['id']
        if patch_id:candidates.append((entry,*store.patch(patch_id)))
    if not candidates:return
    units={p.units for _,p,_ in candidates};mixed=len(units)>1
    for entry,patch,arrays in candidates:
        z=arrays['height'].astype(np.float32);valid=arrays['mask'].astype(bool)
        scale=1.;offset=0.
        if mixed:
            offset=float(z[valid].min());scale=1/max(float(np.ptp(z[valid])),1e-9);z=(z-offset)*scale
        h,w=z.shape;fit=min(tile/w,tile/h);size=(max(2,round(w*fit)),max(2,round(h*fit)))
        x=entry['column']*tile+(tile-size[0])//2;y=entry['row']*tile+(tile-size[1])//2
        local_mask=cv2.resize(valid.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
        # Normalized convolution prevents excluded source values bleeding into relief.
        weights=cv2.resize(valid.astype(np.float32),size,interpolation=cv2.INTER_AREA)
        local_z=cv2.resize(np.where(valid,z,0),size,interpolation=cv2.INTER_AREA)/np.maximum(weights,1e-9)
        slices=np.s_[y:y+size[1],x:x+size[0]];height[slices]=local_z;mask[slices]=local_mask;cell_ids[slices]=np.where(local_mask,entry['cell']+1,0)
        if 'rgb' in arrays:rgb[slices]=cv2.resize(arrays['rgb'].astype(np.uint8),size)
        elif entry.get('views',{}).get('raw'):
            with Image.open(directory/entry['views']['raw']) as image:rgb[slices]=np.asarray(image.convert('RGB').resize(size))
        sources.append(dict(cell=entry['cell'],source_id=patch.id,source_units=patch.units,
            source_sha256=__import__('hashlib').sha256(store.path(patch.arrays).read_bytes()).hexdigest(),
            destination_box=[x,y,size[0],size[1]],display_offset=offset,display_scale=scale,
            baseline_subtraction='already applied by p5; not repeated' if entry.get('sample_id') else 'source height used as stored'))
    rgb[~mask]=[241,236,223]
    valid_values=height[mask];lo=float(valid_values.min());hi=float(valid_values.max());span=max(hi-lo,1e-9)
    gray=np.rint(np.clip((height-lo)/span,0,1)*255).astype(np.uint8);gray[~mask]=0
    Image.fromarray(gray).save(directory/'stitched-depth.png')
    Image.fromarray(np.dstack((rgb,(mask*255).astype(np.uint8)))).save(directory/'stitched-rgb.png')
    Image.fromarray((mask*255).astype(np.uint8)).save(directory/'stitched-mask.png')
    np.save(directory/'stitched-depth.npy',height,allow_pickle=False)
    np.savez_compressed(directory/'stitched-surface.npz',height=height,mask=mask,cell_ids=cell_ids)
    # Each source remains its own connected component. No arbitrary ShuffleSnap
    # neighbor becomes an observed physical seam, even if tiles touch in image space.
    h,w=height.shape;indices=np.full(shape,-1,int);indices[mask]=np.arange(mask.sum())
    yy,xx=np.nonzero(mask);z=(height[mask]-lo)/span*.18
    vertices=np.column_stack(((xx/(w-1)-.5)*2,(.5-yy/(h-1))*2*h/w,z))
    faces=[]
    for y in range(h-1):
        for x in range(w-1):
            cells=cell_ids[y:y+2,x:x+2]
            if cells[0,0] and np.all(cells==cells[0,0]):
                a,b,c,d=indices[y,x],indices[y,x+1],indices[y+1,x],indices[y+1,x+1]
                faces.extend(((a,c,b),(b,c,d)))
    with (directory/'stitched-mesh.obj').open('w',encoding='utf-8') as out:
        out.write('# ShuffleSnap comparison relief; authored normalized display coordinates, not mm.\n')
        for x,y,z in vertices:out.write(f'v {x:.7g} {y:.7g} {z:.7g}\n')
        for a,b,c in faces:out.write(f'f {a+1} {b+1} {c+1}\n')
    # Share explicit disconnected geometry with the browser, never triangulate gaps.
    mesh={'vertices':vertices.tolist(),'faces':np.asarray(faces,dtype=int).tolist(),'full_triangles':len(faces)}
    (directory/'stitched-mesh.json').write_text(json.dumps(mesh,separators=(',',':')),encoding='utf-8')
    # Optional artistic bridges join facing scan edges without moving any source
    # vertices. They are stored separately and never presented as observed data.
    synthetic_faces=[]
    connected_height=height.copy();bridge_mask=np.zeros(shape,bool)
    present={s['cell'] for s in sources}
    for cell in sorted(present):
        row,col=divmod(cell,columns)
        for axis,neighbor in ((1,cell+1),(0,cell+columns)):
            if neighbor not in present or (axis==1 and col+1>=columns):continue
            previous=None
            for line in range(tile):
                if axis==1:
                    y=row*tile+line;left=np.flatnonzero(cell_ids[y,col*tile:(col+1)*tile]==cell+1);right=np.flatnonzero(cell_ids[y,(col+1)*tile:(col+2)*tile]==neighbor+1)
                    pair=((y,col*tile+int(left[-1])),(y,(col+1)*tile+int(right[0]))) if left.size and right.size else None
                else:
                    x=col*tile+line;top=np.flatnonzero(cell_ids[row*tile:(row+1)*tile,x]==cell+1);bottom=np.flatnonzero(cell_ids[(row+1)*tile:(row+2)*tile,x]==neighbor+1)
                    pair=((row*tile+int(top[-1]),x),((row+1)*tile+int(bottom[0]),x)) if top.size and bottom.size else None
                if pair is None:previous=None;continue
                a,b=pair
                # Fill only the display gap between these facing source edges.
                count=b[axis]-a[axis]+1
                for step,t in enumerate(np.linspace(0,1,count)):
                    p=(a[0],a[1]+step) if axis==1 else (a[0]+step,a[1])
                    if not mask[p]:connected_height[p]=height[a]*(1-t)+height[b]*t;bridge_mask[p]=True
                if previous:
                    c,d=previous;ia,ib,ic,id_=[int(indices[p]) for p in (a,b,c,d)]
                    synthetic_faces.extend(((ic,ia,id_),(id_,ia,ib)) if axis==1 else ((ic,id_,ia),(ia,id_,ib)))
                previous=pair
    connected_faces=np.asarray(faces+synthetic_faces,dtype=int).tolist()
    connected={**mesh,'faces':connected_faces,'full_triangles':len(connected_faces),'synthetic_triangle_start':len(faces),'synthetic_triangles':len(synthetic_faces)}
    (directory/'connected-mesh.json').write_text(json.dumps(connected,separators=(',',':')),encoding='utf-8')
    with (directory/'connected-mesh.obj').open('w',encoding='utf-8') as out:
        out.write('# ARTISTIC connecting seams; authored display coordinates, not measured registration.\n')
        for x,y,z in vertices:out.write(f'v {x:.7g} {y:.7g} {z:.7g}\n')
        out.write('g captured_surfaces\n')
        for a,b,c in faces:out.write(f'f {a+1} {b+1} {c+1}\n')
        out.write('g synthetic_connections\n')
        for a,b,c in synthetic_faces:out.write(f'f {a+1} {b+1} {c+1}\n')
    np.savez_compressed(directory/'connected-surface.npz',height=connected_height,mask=mask|bridge_mask,synthetic_mask=bridge_mask,source_mask=mask)
    connected_gray=np.rint(np.clip((connected_height-lo)/span,0,1)*255).astype(np.uint8);connected_gray[~(mask|bridge_mask)]=0
    Image.fromarray(connected_gray).save(directory/'connected-depth.png')
    spacing=(2/(w-1),2*h/(w*(h-1)))
    normals,normal_mask=display_normals((height-lo)/span*.18,cell_ids,spacing)
    connected_normals,connected_normal_mask=display_normals(
        (connected_height-lo)/span*.18,(mask|bridge_mask).astype(np.uint8),spacing)
    influence=connected_normal_mask&((np.linalg.norm(connected_normals-normals,axis=-1)>1e-7)|bridge_mask|~normal_mask)
    save_normals(directory,'stitched',normals,normal_mask,np.zeros(shape,bool))
    save_normals(directory,'connected',connected_normals,connected_normal_mask,influence)
    board['surface']=dict(sources=sources,width=w,height=h,triangles=len(faces),
        height_units='normalized per source' if mixed else next(iter(units)),
        depth_display_range=[lo,hi],geometry_units='authored normalized display coordinates, not mm',
        interpretation='Actual relief assembled in ShuffleSnap order. Separate source components; gaps and missing heights remain empty. No inferred neighbor is treated as a registered physical seam. OBJ uses authored display scale; NPY/NPZ retain height values and mask.',
        metric_validated=False,missing_cells=[e['cell'] for e in board['items'] if e['cell'] not in {s['cell'] for s in sources}])
    board['surface']['artistic_connections']={'triangles':len(synthetic_faces),'synthetic_triangle_start':len(faces),'method':'Facing edges connected without moving source vertices; display gaps linearly interpolated. Not physical registration.'}
    board['surface']['normal_maps']={
        'conventions':['opengl','directx'],'float_convention':'opengl',
        'spacing':list(spacing),'height_scale':.18/span,'height_offset':lo,
        'encoding':'RGB = round((unit normal * 0.5 + 0.5) * 255); DirectX flips encoded green. Invalid pixels are neutral (128,128,255); use the normal mask.',
        'method':'Finite differences of float depth at authored mesh display scale, never the 8-bit depth preview. Stitched derivatives stay within source cells. Connected derivatives include interpolated artistic gaps; these are depth-raster normals, not exact OBJ triangle normals.',
        'synthetic_influence':'Connected NPZ marks pixels whose normals are changed or introduced by artistic connections, including affected source-edge pixels.',
        'metric_validated':False}
