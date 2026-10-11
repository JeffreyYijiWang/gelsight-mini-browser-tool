"""Read-only collection snapshots -> full-resolution ShuffleSnap relief exports.

Run with python -m studio.collection_export. Outputs are private artistic layouts,
not registered mosaics or metric sensor measurements. Sources are never rewritten.
"""
from __future__ import annotations
import os
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_key, '2')
import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, binary_dilation
from .typology import descriptor, project_features

MAX_HEIGHT_PIXELS = 32_000_000
MAX_RGB_PIXELS = 256_000_000


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, data):
    path=Path(path);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def image(path):
    with Image.open(path) as im:
        return im.convert('RGB').copy()


def inventory(root, cache):
    """Snapshot indexed native captures and real Mini browser captures only."""
    from .store import Store
    from desktop_studio.reconstruction import Reconstructor
    from .samples import crop_box
    from .sensor_damage import damage_mask
    collections, excluded = {}, []
    for project in sorted((root/'desktop-data').glob('*/project.json')):
        data = json.loads(project.read_text(encoding='utf-8'))
        key = 'native-'+project.parent.name
        entries = []
        for row in data['rows']:
            for record in row:
                folder = project.parent/'captures'/record['id']
                for name in ('source.png', 'cropped-source.png', 'depth.npy'):
                    if digest(folder/name) != record['files'][name]:
                        raise ValueError(f'Changed source: {folder/name}')
                entries.append(dict(id=record['id'], name=f'R{record["row"]+1:02} C{record["column"]+1:02}',
                    collection=key, rgb=str(folder/'cropped-source.png'), depth=str(folder/'depth.npy'),
                    source=str(folder/'source.png'), source_sha256=record['files']['source.png'],
                    depth_sha256=record['files']['depth.npy'], source_grid=[record['row'], record['column']],
                    provenance='Native frozen baseline-subtracted relative depth; no second crop or subtraction.',
                    config=record['config']))
        if entries: collections[key] = entries
    store = Store(root/'studio-data')
    frames = store.list('frames'); patches = store.list('patches')
    model = None
    for session in store.list('sessions'):
        # Fixture/import sessions are not sensor collections even when old fixtures
        # were incorrectly left with synthetic=false.
        if session.get('synthetic') or not session.get('sensor_id'):
            excluded.append(dict(session=session['id'], name=session['name'], reason='Synthetic or not a sensor collection'))
            continue
        entries = []; key = 'browser-'+session['id']
        for frame in frames:
            if frame['session_id'] != session['id'] or frame['kind'] != 'rgb': continue
            settings = frame['settings']
            if frame['id'] == session.get('baseline_id') or settings.get('capture_role') == 'baseline':
                excluded.append(dict(id=frame['id'], reason='Untouched calibration reference')); continue
            raw = store.path(frame['raw_file'])
            if digest(raw) != frame['sha256']: raise ValueError(f'Changed source: {raw}')
            folder = cache/frame['id']; folder.mkdir(parents=True,exist_ok=True)
            full = image(raw)
            crop = settings.get('sample_crop', [.1, .1, .8, .8])
            box = crop_box(full.size, crop); cropped = full.crop(box)
            cropped.save(folder/'rgb.png')
            matching = [p for p in patches if frame['id'] in p['source_ids']]
            sample = store.get('samples', settings['sample_id']) if settings.get('sample_id') else None
            patch_id = sample['patch_id'] if sample else (matching[-1]['id'] if matching else None)
            if patch_id:
                patch, arrays = store.patch(patch_id)
                if patch.units!='relative':
                    raise ValueError('This batch combines relative Mini captures only; metric patches need explicit display conversion.')
                z = arrays['height'].copy(); valid = arrays['mask'].astype(bool)
                provenance = dict(mode='existing frozen reconstruction', patch_id=patch_id,
                    arrays_sha256=digest(store.path(patch.arrays)), units=patch.units, settings=patch.settings)
            else:
                if settings.get('sensor_damage'):
                    raise ValueError('Reconstruct this damage-marked RGB frame in Surface Capture first so its mask is applied before integration.')
                if crop != [.1, .1, .8, .8]:
                    raise ValueError('Offline RGB-only inference currently requires the standard 10% crop.')
                if model is None: model = Reconstructor()
                result = model.raw_depth(np.asarray(full)); z = result['depth']
                # No untouched state is guessed. Baselines are used only if explicitly saved.
                baseline_id = settings.get('baseline_id') or session.get('baseline_id')
                baseline_hash = None
                if baseline_id:
                    base = store.get('frames', baseline_id); base_path = store.path(base['raw_file'])
                    if base['session_id']!=session['id'] or base['settings'].get('capture_device_id')!=settings.get('capture_device_id'):
                        raise ValueError('Baseline does not belong to this sensor/session.')
                    if digest(base_path) != base['sha256']: raise ValueError('Changed baseline source.')
                    baseline = image(base_path)
                    if baseline.size != full.size: raise ValueError('Baseline/source resolution mismatch.')
                    z -= model.raw_depth(np.asarray(baseline))['depth']; baseline_hash = base['sha256']
                valid = np.isfinite(z)
                provenance = dict(mode='offline full-resolution CPU Mini inference', config=model.config,
                    baseline_id=baseline_id, baseline_sha256=baseline_hash,
                    warning='Relative, not metric. No baseline subtraction when no explicit baseline exists.')
                if settings.get('sensor_damage'):
                    w, h = full.size; x0, y0, x1, y1 = box
                    valid &= ~damage_mask(z.shape, settings['sensor_damage']['regions'],
                                          [x0/w, y0/h, (x1-x0)/w, (y1-y0)/h])
                    provenance['damage'] = settings['sensor_damage']
            if not np.isfinite(z[valid]).all() or not valid.any(): raise ValueError('Invalid source reconstruction.')
            np.save(folder/'depth.npy', z); np.save(folder/'mask.npy', valid)
            entry = dict(id=frame['id'], name=sample['name'] if sample else Path(frame['source_name']).stem,
                collection=key, collection_name=session['name'], rgb=str(folder/'rgb.png'), depth=str(folder/'depth.npy'),
                mask=str(folder/'mask.npy'), source=str(raw), source_sha256=frame['sha256'],
                depth_sha256=digest(folder/'depth.npy'), crop_pixels=list(box), provenance=provenance)
            entries.append(entry)
            write_json(folder/'source-record.json',entry)
            print(f'Prepared {session["name"]}: {len(entries)}', flush=True)
        if entries: collections[key] = entries
    return collections, excluded


def arrange(entries):
    import shufflesnap
    n = len(entries)
    if not 1<=n<=2000: raise ValueError('Select 1-2000 captures per batch board.')
    columns = math.ceil(math.sqrt(n*3/4)); rows = math.ceil(n/columns)
    features = [descriptor(image(e['rgb']), 'texture') for e in entries]
    points, variance = project_features(features)
    if n == 1: assignment = np.array([0]); grid = np.array([[.5, .5]])
    else:
        grid, assignment, _ = shufflesnap.snap_to_grid(points, width=columns, height=rows,
            margin=0., cleanup_seconds=None, num_threads=2)
    assignment = np.asarray(assignment, int)
    if len(set(assignment.tolist())) != n or np.any(assignment < 0) or np.any(assignment >= columns*rows):
        raise ValueError('Invalid ShuffleSnap assignment.')
    return columns, rows, assignment, np.asarray(features), points, grid, variance


def perimeter(h, w):
    return np.concatenate((np.arange(h)*w, (h-1)*w+np.arange(1,w),
                           np.arange(h-2,-1,-1)*w+w-1, np.arange(w-2,0,-1))).astype(np.int32)


def face_chunks(h, w, block=32):
    for y in range(0,h-1,block):
        a = (np.arange(y,min(y+block,h-1))[:,None]*w+np.arange(w-1)).ravel()
        yield np.concatenate((np.column_stack((a,a+w,a+1)),np.column_stack((a+1,a+w,a+w+1)))).astype(np.int32)
    p = perimeter(h,w); q = np.roll(p,-1); b = h*w+np.arange(len(p)); c = np.roll(b,-1)
    yield np.concatenate((np.column_stack((q,p,b)),np.column_stack((q,b,c)),
                          np.column_stack((np.full(len(p),h*w+len(p)),c,b)))).astype(np.int32)


def export_mesh(folder, z, rgb, spacing):
    """Stream a closed grid solid, then validate the serialized PLY and STL."""
    if z.ndim!=2 or min(z.shape)<2 or z.size>MAX_HEIGHT_PIXELS or not np.isfinite(z).all():
        raise ValueError('Mesh requires a finite field within the 32-million-sample budget.')
    if rgb.shape!=(*z.shape,3) or not np.isfinite(spacing) or spacing<=0:
        raise ValueError('Mesh requires matching RGB and positive authored spacing.')
    h,w=z.shape; p=perimeter(h,w); nv=h*w+len(p)+1; nf=2*(h-1)*(w-1)+3*len(p)
    vertex_dtype=np.dtype([('position','<f4',(3,)),('rgb','u1',(3,))])
    face_dtype=np.dtype([('count','u1'),('indices','<i4',(3,))])
    header=(f'ply\nformat binary_little_endian 1.0\nelement vertex {nv}\nproperty float x\n'
            f'property float y\nproperty float z\nproperty uchar red\nproperty uchar green\n'
            f'property uchar blue\nelement face {nf}\nproperty list uchar int vertex_indices\nend_header\n').encode()
    path=folder/'relief-closed.ply'; offset=2-float(z.min())
    with path.open('wb') as f:
        f.write(header)
        for y in range(h):
            v=np.zeros(w,vertex_dtype);v['position']=np.column_stack((np.arange(w)*spacing,np.full(w,-y*spacing),z[y]+offset));v['rgb']=rgb[y];f.write(v.tobytes())
        v=np.zeros(len(p)+1,vertex_dtype);v['position'][:-1,:2]=np.column_stack((p%w*spacing,-(p//w)*spacing))
        v['position'][-1,:2]=[(w-1)*spacing/2,-(h-1)*spacing/2];v['rgb']=180;f.write(v.tobytes())
        for faces in face_chunks(h,w):
            packed=np.empty(len(faces),face_dtype);packed['count']=3;packed['indices']=faces;f.write(packed.tobytes())
    vertices=np.memmap(path,dtype=vertex_dtype,mode='r',offset=len(header),shape=(nv,))
    faces=np.memmap(path,dtype=face_dtype,mode='r',offset=len(header)+nv*vertex_dtype.itemsize,shape=(nf,))
    if path.stat().st_size != len(header)+nv*vertex_dtype.itemsize+nf*face_dtype.itemsize: raise ValueError('PLY reload size mismatch.')
    edges_path=folder/'validation-edges.tmp'
    edges=np.memmap(edges_path,dtype='<u8',mode='w+',shape=(nf*3,))
    stl_dtype=np.dtype([('normal','<f4',(3,)),('points','<f4',(3,3)),('attribute','<u2')])
    volume=0.; cursor=0
    with (folder/'relief-closed.stl').open('wb') as f:
        f.write(b'Authored display mm; synthetic joins; not measured or print-ready'.ljust(80,b' '));f.write(np.uint32(nf).tobytes())
        for start in range(0,nf,100_000):
            face=faces[start:start+100_000]['indices'].copy()
            if face.min()<0 or face.max()>=nv: raise ValueError('PLY index out of range.')
            tri=vertices['position'][face].astype(np.float64)
            cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);length=np.linalg.norm(cross,axis=1)
            if np.any(length<=0): raise ValueError('Degenerate triangle.')
            volume+=np.einsum('ij,ij->i',tri[:,0],np.cross(tri[:,1],tri[:,2])).sum()/6
            record=np.zeros(len(face),stl_dtype);record['points']=tri;record['normal']=cross/length[:,None];f.write(record.tobytes())
            a=face[:,[0,1,2]].astype(np.uint64).ravel();b=face[:,[1,2,0]].astype(np.uint64).ravel()
            edges[cursor:cursor+len(a)]=(np.minimum(a,b)*nv+np.maximum(a,b))*2+(a<b);cursor+=len(a)
    edges.sort()
    # Every undirected edge has exactly two oppositely directed incident faces.
    previous=-1
    for start in range(0,len(edges),600_000):
        pairs=np.asarray(edges[start:start+600_000]).reshape(-1,2)
        keys=pairs[:,0]//2
        if not (np.all(pairs[:,0]%2==0) and np.all(pairs[:,1]==pairs[:,0]+1)
                and np.all(np.diff(keys)>0) and int(keys[0])>previous): raise ValueError('Nonmanifold edge or inconsistent winding.')
        previous=int(keys[-1])
    if nv-nf//2 != 2 or volume<=0: raise ValueError('Closed topology/volume validation failed.')
    stl=np.memmap(folder/'relief-closed.stl',dtype=stl_dtype,mode='r',offset=84,shape=(nf,))
    if (folder/'relief-closed.stl').stat().st_size!=84+nf*50: raise ValueError('STL reload size mismatch.')
    for start in range(0,nf,100_000):
        expected=vertices['position'][faces[start:start+100_000]['indices']]
        if not np.array_equal(stl[start:start+100_000]['points'],expected): raise ValueError('STL round-trip mismatch.')
    del pairs,keys
    edges.flush();edges._mmap.close()
    del edges,vertices,faces,stl
    edges_path.unlink()
    return dict(vertices=nv,triangles=nf,closed=True,manifold_edges=True,consistent_winding=True,
        connected=True,connectivity_evidence='Complete rectangular grid, perimeter walls and bottom fan',
        euler_characteristic=2,volume_mm3=float(volume),stl_roundtrip_exact=True,
        top_offset_mm=offset,minimum_thickness_mm=2.,units='authored mm, not measured',physical_print_validation=False)


def build_board(folder, entries, width_mm=300., relief_mm=5., *, fixed_layout=None, source_height_units='relative solver values'):
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'manifest.json').exists(): raise ValueError('Completed export is immutable; use a new output folder.')
    if fixed_layout is None:
        columns,rows,assignment,features,points,grid,variance=arrange(entries)
    else:
        columns,rows=fixed_layout
        if not (isinstance(columns,int) and isinstance(rows,int) and columns>0 and rows>0
                and 1<=len(entries)<=columns*rows<=2000):
            raise ValueError('Fixed layout requires positive integer dimensions and enough cells (maximum 2000).')
        assignment=np.arange(len(entries));features=np.empty((len(entries),0))
        points=np.column_stack((assignment%columns,assignment//columns));grid=points.copy();variance=[]
    shapes=[np.load(e['depth'],mmap_mode='r').shape for e in entries]
    th=max(s[0] for s in shapes);tw=max(s[1] for s in shapes);gap=4
    h=rows*(th+gap)+gap;w=columns*(tw+gap)+gap
    if h*w>MAX_HEIGHT_PIXELS: raise ValueError('32-million-sample surface budget exceeded; split collections.')
    sizes=[image(e['rgb']).size for e in entries];rw=max(s[0] for s in sizes);rh=max(s[1] for s in sizes)
    # Preserve the geometry canvas aspect, using source RGB detail where available.
    rgb_scale=max(rw/tw,rh/th);ow=math.ceil(w*rgb_scale);oh=math.ceil(h*rgb_scale)
    if ow*oh>MAX_RGB_PIXELS: raise ValueError('256-million-pixel RGB budget exceeded; split collections.')
    z=np.zeros((h,w),np.float32);observed=np.full((h,w),np.nan,np.float32)
    valid=np.zeros((h,w),bool);synthetic=np.ones((h,w),bool)
    rgb=np.full((h,w,3),235,np.uint8)
    panorama=Image.new('RGB',(ow,oh),(235,235,235));items=[]
    for i,e in enumerate(entries):
        local=np.load(e['depth']).astype(np.float32);mask=np.load(e['mask']).astype(bool) if e.get('mask') else np.isfinite(local)
        mask &= np.isfinite(local);lh,lw=local.shape
        x=gap+int(assignment[i]%columns)*(tw+gap)+(tw-lw)//2;y=gap+int(assignment[i]//columns)*(th+gap)+(th-lh)//2
        target=np.s_[y:y+lh,x:x+lw]
        # Zero outside observations, and taper an eight-pixel inside rim to zero.
        # This makes flat empty cells and smooth synthetic transitions explicit.
        distance=distance_transform_edt(np.pad(mask,1))[1:-1,1:-1]
        weight=np.clip((distance-1)/8,0,1);weight=weight*weight*(3-2*weight)
        z[target]=np.where(mask,local,0)*weight;observed[target]=np.where(mask,local,np.nan)
        valid[target]=mask;synthetic[target]=~mask|(weight<1)
        pic=image(e['rgb']);rgb[target]=np.asarray(pic.resize((lw,lh),Image.Resampling.LANCZOS))
        left,top=round(x*rgb_scale),round(y*rgb_scale);right,bottom=round((x+lw)*rgb_scale),round((y+lh)*rgb_scale)
        panorama.paste(pic.resize((right-left,bottom-top),Image.Resampling.LANCZOS),(left,top))
        items.append({**e,'cell':int(assignment[i]),'destination_box':[x,y,lw,lh],
                      'rgb_destination_box':[left,top,right,bottom],'point':points[i].tolist()})
    # A single authored scale per board preserves relative source amplitudes.
    span=float(np.ptp(z));scale=relief_mm/span if span>1e-12 else 1.
    z*=scale;spacing=width_mm/(w-1)
    panorama.save(folder/'rgb-panorama.png');preview=panorama.copy();preview.thumbnail((1600,1600));preview.save(folder/'rgb-preview.jpg',quality=93)
    draw=ImageDraw.Draw(panorama)
    for item in items:
        x,y,_,_=item['rgb_destination_box'];label=item['name'][:45]
        draw.rectangle((x,y,x+min(340,len(label)*7+8),y+18),fill='white');draw.text((x+3,y+2),label,fill='black')
    panorama.save(folder/'typology-labeled.png');del panorama,draw
    observed_file='observed-relative-height.npy' if source_height_units=='relative solver values' else 'observed-source-height.npy'
    np.save(folder/'height.npy',z);np.save(folder/observed_file,observed);del observed
    Image.fromarray(valid.astype(np.uint8)*255).save(folder/'source-mask.png')
    Image.fromarray(synthetic.astype(np.uint8)*255).save(folder/'synthetic-mask.png')
    Image.fromarray(binary_dilation(synthetic).astype(np.uint8)*255).save(folder/'normal-synthetic-influence-mask.png')
    lo=float(z.min());hi=float(z.max());height_codes=np.rint((z-lo)/max(hi-lo,1e-12)*65535).astype(np.uint16)
    Image.fromarray(height_codes).save(folder/'height-16bit.png');del height_codes
    normals=np.lib.format.open_memmap(folder/'normals.npy',mode='w+',dtype='float32',shape=(h,w,3))
    encoded=np.empty((h,w,3),np.uint8)
    for start in range(0,h,64):
        end=min(h,start+64);a=max(0,start-1);b=min(h,end+1)
        gy,gx=np.gradient(z[a:b],spacing,spacing)
        n=np.stack((-gx,gy,np.ones_like(gx)),axis=-1);n/=np.linalg.norm(n,axis=-1,keepdims=True);n=n[start-a:end-a]
        normals[start:end]=n;encoded[start:end]=np.rint((n*.5+.5)*255).astype(np.uint8)
    normals.flush();del normals
    Image.fromarray(encoded).save(folder/'normal-opengl.png');encoded[...,1]=255-encoded[...,1]
    Image.fromarray(encoded).save(folder/'normal-directx.png');del encoded
    print(f'Writing/validating {folder.name}: {w} x {h}, {len(entries)} captures',flush=True)
    validation=export_mesh(folder,z,rgb,spacing)
    record=dict(format='gelsight-collection-relief-v1',name=folder.name,items=items,columns=columns,rows=rows,
        shape=[h,w],rgb_shape=[oh,ow],solver=dict(name='shufflesnap',version=importlib.metadata.version('shufflesnap'),
        comparison='texture',feature_version=1,projection='PCA',margin=0,cleanup_seconds=None,num_threads=2,
        executed=len(entries)>1,singleton_note='A single image requires no arrangement' if len(entries)==1 else None),
        explained_variance_fraction=variance,assignment=assignment.tolist(),
        coordinates='X right, Y up, Z out; OpenGL normals; DirectX flips green',
        height_encoding=dict(file='height-16bit.png',decode=f'code / 65535 * {hi-lo!r} + {lo!r}',zero_height=0,
                             float_file='height.npy',units='authored display mm'),
        construction=dict(physical_registration=False,gap_pixels=gap,inside_taper_pixels=8,
            empty_height=0,source_to_authored_z_scale=scale,xy_spacing_mm=spacing,width_mm=width_mm,
            relief_span_mm=relief_mm,original_depth=observed_file+'; NaN outside source mask',
            original_depth_file=observed_file,source_height_units=source_height_units,
            warning='Artistic layout. Synthetic flat fills and tapered rims are not measurements. No new sensor damage location inferred.'),
        validation=validation)
    if fixed_layout is not None:
        record['solver']=dict(name='explicit row-major selection',executed=False,
                              reason='User-authored order; no similarity sorting applied.')
    np.savez_compressed(folder/'features.npz',features=features,points=points,grid=grid)
    record['files']={p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in folder.iterdir() if p.is_file()}
    write_json(folder/'manifest.json',record)
    (folder/'README.txt').write_text(('Private fixed-order collection composition\n' if fixed_layout is not None else 'Private ShuffleSnap collection composition\n')+
        'rgb-panorama.png: full RGB mosaic; typology-labeled.png: same assignment with names.\n'
        'height.npy: float authored relief in mm; height-16bit.png: use manifest decode.\n'
        f'{observed_file}: original source heights on the layout ({source_height_units}), NaN elsewhere.\n'
        'normal-opengl.png / normal-directx.png / normals.npy: normals of the constructed height field.\n'
        'source-mask.png: observed locations. synthetic-mask.png: flat gaps, missing values and tapered rims.\n'
        'relief-closed.ply: colored closed displaced solid. relief-closed.stl: matching authored-mm solid.\n'
        'The top is a continuous deformed plane. Empty areas are flat at height zero.\n'
        'Closed manifold topology and STL reload were checked. No physical print-ready claim.\n'
        'Sources and historical projects were not edited. Layout is not physical registration.\n',encoding='utf-8')
    return {k:record[k] for k in ('name','shape','rgb_shape','validation')}


def audit_fidelity(folder):
    """Add a separate error report without modifying the completed manifest."""
    folder=Path(folder);record=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    z=np.load(folder/'height.npy',mmap_mode='r');original=np.load(folder/record['construction'].get('original_depth_file','observed-relative-height.npy'),mmap_mode='r')
    scale=record['construction']['source_to_authored_z_scale'];reports=[]
    for item in record['items']:
        x,y,w,h=item['destination_box'];source=np.asarray(original[y:y+h,x:x+w]);valid=np.isfinite(source)
        error=np.abs(np.asarray(z[y:y+h,x:x+w],np.float64)-source.astype(np.float64)*scale)[valid]
        reports.append(dict(id=item['id'],maximum_scaled_source_error_mm=float(error.max()),
            p95_scaled_source_error_mm=float(np.percentile(error,95)),
            maximum_source_units_error=float(error.max()/scale),
            explanation='Includes deliberate synthetic rim taper. Original source values retained separately.'))
    report=dict(manifest_sha256=digest(folder/'manifest.json'),sources=reports,physical_accuracy_validated=False)
    write_json(folder/'fidelity.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--width-mm',type=float,default=300.)
    parser.add_argument('--relief-mm',type=float,default=5.)
    parser.add_argument('--resume',action='store_true',help='Continue an interrupted export, verifying completed outputs.')
    args=parser.parse_args()
    if not (0<args.width_mm<=10000 and 0<args.relief_mm<=100): parser.error('Use positive authored width <=10000 mm and relief <=100 mm.')
    root=args.root.resolve();output=(args.output or root/'desktop-data'/('typology-export-'+datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    output.mkdir(parents=True,exist_ok=args.resume);cache=output/'derived-sources';cache.mkdir(exist_ok=args.resume)
    if args.resume and (output/'inventory.json').exists():
        snapshot=json.loads((output/'inventory.json').read_text(encoding='utf-8'))
        collections,excluded=snapshot['collections'],snapshot['excluded']
        for entries in collections.values():
            for entry in entries:
                if digest(entry['source'])!=entry['source_sha256'] or digest(entry['depth'])!=entry['depth_sha256']:
                    raise ValueError('A frozen source changed; resume stopped.')
    else:
        collections,excluded=inventory(root,cache)
        write_json(output/'inventory.json',dict(collections=collections,excluded=excluded))
    def run_board(key,entries):
        manifest=output/key/'manifest.json'
        if args.resume and manifest.exists():
            record=json.loads(manifest.read_text(encoding='utf-8'))
            if record['construction']['width_mm']!=args.width_mm or record['construction']['relief_span_mm']!=args.relief_mm:
                raise ValueError('Resume requires the same authored dimensions.')
            for name,info in record['files'].items():
                if digest(output/key/name)!=info['sha256']: raise ValueError('Completed export changed.')
            print(f'Verified completed board: {key}',flush=True)
            return {k:record[k] for k in ('name','shape','rgb_shape','validation')}
        return build_board(output/key,entries,args.width_mm,args.relief_mm)
    boards=[]
    # Make the user's highlighted collection first, then the remaining snapshots.
    keys=sorted(collections,key=lambda k:('131650-1ca942' not in k,k))
    for key in keys:
        boards.append(run_board(key,collections[key]))
        write_json(output/'export-index.json',dict(boards=boards,complete=False))
    all_entries=[entry for entries in collections.values() for entry in entries]
    if not all_entries: raise ValueError('No indexed sensor captures found.')
    boards.append(run_board('ALL-COLLECTIONS',all_entries))
    for board in boards: audit_fidelity(output/board['name'])
    write_json(output/'export-index.json',dict(boards=boards,captures=len(all_entries),excluded=excluded,complete=True))
    print(f'COMPLETE: {output}',flush=True)


if __name__=='__main__': main()
