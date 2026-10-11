"""Private fixed-order 12-capture study and explicitly artistic load animations.

python -m studio.twelve_study --manifest PATH --output NEW_FOLDER
No sensor acquisition, publication, or force estimation is performed.
"""
from __future__ import annotations
import os
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_key, '2')
import argparse
import html
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh
from .collection_export import build_board, audit_fidelity, digest, write_json, image
from .typology_surface import display_normals

MODES = ('loading', 'shear', 'torsion', 'height-layers', 'particle-wave', 'pixel-tearing', 'layer-stack')
SEED = 20261008
GIF_PALETTE = Image.new('P',(1,1))
GIF_PALETTE.putpalette([c for r in range(6) for g in range(6) for b in range(6)
                       for c in (r*51,g*51,b*51)]+[0]*120)
RESEARCH = [
    dict(title='Measurement of Shear and Slip with a GelSight Tactile Sensor (2015)',
         url='https://people.csail.mit.edu/yuan_wz/GelSight1/ICRA15_2740_FI.pdf'),
    dict(title='GelSight: High-Resolution Robot Tactile Sensors for Estimating Geometry and Force (2017)',
         url='https://doi.org/10.3390/s17122762'),
    dict(title='Wenzhen Yuan: Force, Shear and Slip',
         url='https://people.csail.mit.edu/yuan_wz/force-shear-and-slip.htm')]


def select_entries(manifest, cells):
    if len(cells) != 12 or len(set(cells)) != 12:
        raise ValueError('Select exactly 12 distinct source cells.')
    lookup = {e['cell']: e for e in manifest['items']}
    if any(c not in lookup for c in cells):
        raise ValueError('A requested cell is empty or absent in this manifest.')
    return [{**lookup[c], 'source_cell': c, 'name': f'{i:02d} | {lookup[c]["name"]}'}
            for i, c in enumerate(cells)]


def palette(u):
    stops = np.array([[26, 31, 75], [42, 105, 178], [36, 197, 194],
                      [230, 219, 122], [244, 137, 76], [191, 49, 81]])
    return np.stack([np.interp(np.clip(u, 0, 1), np.linspace(0, 1, len(stops)), stops[:, k])
                     for k in range(3)], -1).astype(np.uint8)


def normalize(z, mask):
    lo, hi = np.percentile(z[mask], [2, 98])
    return np.where(mask, np.clip((z-lo)/max(float(hi-lo), 1e-9), 0, 1), 0).astype(np.float32), [float(lo), float(hi)]


def observed_mesh(z, mask, rgb, spacing=1.):
    h, w = z.shape
    y, x = np.indices(z.shape)
    vertices = np.column_stack((x.ravel()*spacing, -y.ravel()*spacing, np.where(mask, z, 0).ravel()))
    a = (y[:-1, :-1]*w+x[:-1, :-1]).ravel()
    faces = np.vstack((np.column_stack((a, a+w, a+1)), np.column_stack((a+1, a+w, a+w+1))))
    faces = faces[mask.ravel()[faces].all(axis=1)]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, vertex_colors=rgb.reshape(-1, 3), process=False)
    mesh.remove_unreferenced_vertices()
    return mesh


@lru_cache(maxsize=32)
def font(size):
    path = Path('C:/Windows/Fonts/arial.ttf')
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


@lru_cache(maxsize=256)
def caption_header(width, text, subtitle):
    extra = 52 if subtitle else 30
    out = Image.new('RGB', (width, extra), '#121a27'); d = ImageDraw.Draw(out)
    def fitted(value, maximum):
        size=maximum
        while size>8 and d.textlength(value,font=font(size))>width-20:size-=1
        return font(size)
    d.text((10, 6), text, font=fitted(text,16), fill='#f4ead8')
    if subtitle: d.text((10, 29), subtitle, font=fitted(subtitle,12), fill='#b9c8d7')
    return out


def caption(im, text, subtitle=None):
    header=caption_header(im.width,text,subtitle)
    out=Image.new('RGB',(im.width,im.height+header.height))
    out.paste(header,(0,0));out.paste(im,(0,header.height))
    return out


def sheet(images, title, ids=None, tile=(512, 384)):
    canvas = Image.new('RGB', (3*tile[0], 4*(tile[1]+30)), '#121a27')
    for i, im in enumerate(images):
        im = im.convert('RGB').resize(tile, Image.Resampling.LANCZOS)
        canvas.paste(caption(im, f'{i:02d}' if ids is None else ids[i]), ((i%3)*tile[0], (i//3)*(tile[1]+30)))
    return caption(canvas, title, 'Fixed order 0-11 | Private capture study | Relative geometry')


def shade(z, mask):
    normals, valid = display_normals(z, mask.astype(np.int32), (1., 1.))
    light = np.array([-.4, .5, .76]); light /= np.linalg.norm(light)
    strength = np.clip(normals @ light, 0, 1)*.8+.2
    u, _ = normalize(z, mask)
    pic = (palette(u)*strength[..., None]).astype(np.uint8)
    pic[~valid] = (18, 26, 39)
    return pic


def prepare_cell(out, entry, index):
    folder = out/'cells'/f'{index:02d}'; folder.mkdir(parents=True)
    frozen = {}
    for key, expected in [('source', entry['source_sha256']), ('depth', entry['depth_sha256'])]:
        if digest(entry[key]) != expected: raise ValueError(f'Changed source {entry[key]}')
    for key, name in [('source', 'source.png'), ('rgb', 'rgb.png'), ('depth', 'height.npy'), ('mask', 'mask.npy')]:
        if entry.get(key):
            src = Path(entry[key]); shutil.copyfile(src, folder/name)
            frozen[key] = dict(path=str(src), sha256=digest(src), snapshot=name)
    z = np.load(folder/'height.npy', allow_pickle=False)
    if z.ndim != 2 or min(z.shape)<2 or z.size>2_000_000: raise ValueError('Invalid or oversized height field.')
    mask = np.load(folder/'mask.npy').astype(bool) if (folder/'mask.npy').exists() else np.isfinite(z)
    mask &= np.isfinite(z)
    if not mask.any(): raise ValueError('Capture has no valid geometry.')
    np.save(folder/'mask.npy', mask)
    rgb = np.asarray(image(folder/'rgb.png').resize((z.shape[1], z.shape[0]), Image.Resampling.LANCZOS))
    u, limits = normalize(z, mask)
    Image.fromarray(np.rint(u*255).astype(np.uint8)).save(folder/'height.png')
    Image.fromarray(palette(u)).save(folder/'height-color.png')
    Image.fromarray(mask.astype(np.uint8)*255).save(folder/'validity.png')
    normals, normal_mask = display_normals(np.where(mask,z,0), mask.astype(np.int32), (1., 1.))
    np.save(folder/'normals.npy', normals)
    for name, n in [('normal-opengl', normals), ('normal-directx', normals*[1, -1, 1])]:
        encoded = np.rint((n*.5+.5)*255).astype(np.uint8); encoded[~normal_mask] = (128, 128, 255)
        Image.fromarray(encoded).save(folder/f'{name}.png')
    Image.fromarray(normal_mask.astype(np.uint8)*255).save(folder/'normal-validity.png')
    Image.fromarray(shade(np.where(mask,z,0),mask)).save(folder/'relief-shaded.png')
    mesh = observed_mesh(z,mask,rgb)
    mesh.export(folder/'surface.ply'); mesh.export(folder/'surface.obj',digits=9)
    reload = trimesh.load(folder/'surface.ply',process=False)
    if not np.allclose(reload.vertices,mesh.vertices,atol=1e-5) or not np.array_equal(reload.faces,mesh.faces):
        raise ValueError('Surface PLY round trip failed.')
    # Each model pixel is authored as 1 mm for interchange; GLB uses meters.
    mesh.apply_scale(.001); mesh.export(folder/'surface.glb')
    extra = []
    srcdir = Path(entry['depth']).parent
    if entry['collection'].startswith('native-'):
        for name in ('background-subtracted.png', 'interpolated-markers.png', 'normal-material.glb'):
            if (srcdir/name).exists():
                shutil.copyfile(srcdir/name,folder/name);extra.append(name)
                frozen[name]=dict(path=str(srcdir/name),sha256=digest(srcdir/name),snapshot=name)
    record = dict(index=index,source_cell=entry['source_cell'],id=entry['id'],collection=entry['collection'],
        frozen_inputs=frozen,height_shape=list(z.shape),display_percentiles_2_98=limits,
        geometry=dict(vertices=len(mesh.vertices),triangles=len(mesh.faces),ply_roundtrip=True,
            source_height_unchanged=True,unit_model_pixel_xy=True,glb_meters_per_model_unit=.001,
            metric_sensor_calibration=False,closed=False,normal_relief_added_to_mesh=False),
        available_capture_extras=extra,measured_force_available=False,measured_shear_available=False,
        shear_image='Authored lateral displacement illustration; no marker tracking or force inference.')
    write_json(folder/'cell.json',record)
    return record


def animation_state(folder, size=(288,216)):
    z = np.load(folder/'height.npy'); mask=np.load(folder/'mask.npy')
    u, _ = normalize(z,mask)
    u=cv2.resize(u,size); valid=cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
    rgb=np.asarray(image(folder/'rgb.png').resize(size,Image.Resampling.LANCZOS))
    y,x=np.indices(u.shape,dtype=np.float32);h,w=u.shape
    cx=float((x*u).sum()/max(u.sum(),1));cy=float((y*u).sum()/max(u.sum(),1))
    dx=(x-cx)/w;dy=(y-cy)/h;r=np.sqrt(dx*dx+dy*dy)
    gy,gx=np.gradient(u);weight=(.18+.82*u)*valid
    layers=[]
    for names in [('rgb.png',),('normal_map.png','normal-opengl.png'),('height.png',),
                  ('reference_image.png',),('difference_image.png',),('shear_field.png','shear-still.png')]:
        path=next((folder/n for n in names if (folder/n).exists()),None)
        pic=image(path).resize(size) if path else Image.new('RGB',size,'#121a27')
        if path is None:ImageDraw.Draw(pic).text((20,80),'Layer not supplied',font=font(16),fill='white')
        layers.append(np.asarray(pic))
    return dict(u=u,rgb=rgb,x=x,y=y,dx=dx,dy=dy,r=r,gx=gx,gy=gy,weight=weight,valid=valid,layers=np.stack(layers))


def render_frame(s, mode, phase):
    u=s['u'];rgb=s['rgb'];h,w=u.shape;x=s['x'];y=s['y']
    amount=.5-.5*np.cos(2*np.pi*phase)
    # All fields below are authored display effects, never measured motion.
    if mode in ('loading','shear','torsion'):
        if mode=='loading':
            vx=s['dx']*amount*32*s['weight'];vy=s['dy']*amount*32*s['weight']
        elif mode=='shear':
            vx=amount*26*s['weight'];vy=amount*5*np.sin(y/h*np.pi)*s['weight']
        else:
            vx=-s['dy']*amount*38*s['weight'];vy=s['dx']*amount*38*s['weight']
        warped=cv2.remap(rgb,(x-vx).astype(np.float32),(y-vy).astype(np.float32),cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT,borderValue=(18,26,39))
        pic=(warped*.63+palette(u*amount)*.37).astype(np.uint8)
        for yy in range(12,h,22):
            for xx in range(12,w,22):
                if s['valid'][yy,xx]:
                    cv2.arrowedLine(pic,(xx,yy),(round(xx+float(vx[yy,xx])),round(yy+float(vy[yy,xx]))),
                                   (247,234,198),1,cv2.LINE_AA,tipLength=.3)
    elif mode=='height-layers':
        band=np.exp(-((u-amount)/.09)**2)*s['valid']
        pic=(rgb*(.16+.84*band[...,None])*.65+palette(u)*band[...,None]*.35).clip(0,255).astype(np.uint8)
        contour=(np.abs(np.mod(u*12,1)-.5)<.045)&s['valid']
        pic[contour]=(239,225,173)
    elif mode=='particle-wave':
        pic=np.full_like(rgb,(18,26,39));ys,xs=np.mgrid[2:h:4,2:w:4]
        v=u[ys,xs];sort=np.argsort(v.ravel(),kind='stable');ranks=np.empty(v.size,int);ranks[sort]=np.arange(v.size)
        target_x=(ranks/(max(v.size-1,1))*(w-16)+8).reshape(v.shape)
        target_y=h*.5+np.sin(v*np.pi*5-2*np.pi*phase)*h*.22
        px=xs*(1-amount)+target_x*amount;py=ys*(1-amount)+target_y*amount
        colors=palette(v);ix=np.rint(px).astype(int);iy=np.rint(py).astype(int)
        good=s['valid'][ys,xs]&(ix>=1)&(ix<w-1)&(iy>=1)&(iy<h-1)
        for ox,oy in ((0,0),(-1,0),(1,0),(0,-1),(0,1)):
            pic[iy[good]+oy,ix[good]+ox]=colors[good]
    elif mode=='layer-stack':
        position=(phase%1)*6;i=int(position);mix=position-i
        mix=np.clip((mix-.65)/.35,0,1)
        pic=np.rint(s['layers'][i]*(1-mix)+s['layers'][(i+1)%6]*mix).astype(np.uint8)
        names=('RGB','SUPPLIED / DERIVED NORMAL','HEIGHT','REFERENCE','DIFFERENCE','SHEAR LAYER')
        cv2.rectangle(pic,(0,0),(w,21),(18,26,39),-1)
        cv2.putText(pic,names[i],(7,15),cv2.FONT_HERSHEY_SIMPLEX,.38,(238,229,207),1,cv2.LINE_AA)
    elif mode=='pixel-tearing':
        pic=np.full_like(rgb,(18,26,39));ys,xs=np.mgrid[0:h:3,0:w:3];v=u[ys,xs]
        # Whole RGB (including its background) becomes tiles, sorted by height for painter ordering.
        rng=np.random.default_rng(SEED);jitter=rng.uniform(-.24,.24,v.shape)
        angle=np.arctan2(s['dy'][ys,xs],s['dx'][ys,xs])+jitter
        travel=amount*(12+58*v+14*np.sin(xs*.075+ys*.06)**2)
        px=xs+np.cos(angle)*travel+s['gx'][ys,xs]*amount*75
        py=ys+np.sin(angle)*travel+s['gy'][ys,xs]*amount*75
        order=np.argsort(v.ravel(),kind='stable');px=np.rint(px.ravel()[order]).astype(int);py=np.rint(py.ravel()[order]).astype(int)
        colors=rgb[ys.ravel()[order],xs.ravel()[order]]
        for ox in range(3):
            for oy in range(3):
                good=(px+ox>=0)&(px+ox<w)&(py+oy>=0)&(py+oy<h)
                pic[py[good]+oy,px[good]+ox]=colors[good]
    else:raise ValueError('Unknown animation mode.')
    if mode!='pixel-tearing':pic[~s['valid']]=(18,26,39)
    return Image.fromarray(pic)


class Movie:
    def __init__(self,path,size,fps):
        self.process=subprocess.Popen([shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-nostdin',
            '-f','rawvideo','-pix_fmt','rgb24','-s',f'{size[0]}x{size[1]}','-r',str(fps),'-i','pipe:0',
            '-an','-c:v','libx264','-threads','2','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],stdin=subprocess.PIPE)
    def write(self,im):self.process.stdin.write(im.tobytes())
    def close(self):
        self.process.stdin.close()
        if self.process.wait()!=0:raise RuntimeError('FFmpeg encoding failed.')
    def abort(self):
        self.process.kill();self.process.communicate()


def animations(out, frames=72, fps=12, indices=None, label=''):
    indices=list(range(12)) if indices is None else indices
    states=[animation_state(out/'cells'/f'{i:02d}') for i in indices]
    for mode in MODES:
        print(f'Animation: {mode}',flush=True)
        cell_frames=[[] for _ in states];board_frames=[];movie=None
        try:
            for f in range(frames):
                ims=[]
                for i,s in enumerate(states):
                    im=render_frame(s,mode,f/frames)
                    if f==frames//2: im.save(out/'cells'/f'{indices[i]:02d}'/f'{mode}-still.png')
                    tile=caption(im,f'{label} / scan {indices[i]:02d}', mode+' | ARTISTIC - NOT MEASURED FORCE')
                    cell_frames[i].append(tile.quantize(palette=GIF_PALETTE,dither=Image.Dither.NONE));ims.append(im)
                slots=[Image.new('RGB',(288,216),'#121a27') for _ in range(12)]
                for i,im in zip(indices,ims):slots[i]=im
                board=sheet(slots,f'{label} | {mode.upper()} | ARTISTIC',
                            ids=[f'Scan {i:02d}'+(' | NOT PROVIDED' if i not in indices else '') for i in range(12)],tile=(288,216))
                if movie is None:movie=Movie(out/f'{mode}.mp4',board.size,fps)
                movie.write(board)
                board_frames.append(board.resize((576,round(board.height*576/board.width))).quantize(palette=GIF_PALETTE,dither=Image.Dither.NONE))
            movie.close();movie=None
        finally:
            if movie is not None:movie.abort()
        duration=round(1000/fps)
        for i,seq in enumerate(cell_frames):
            seq[0].save(out/'cells'/f'{indices[i]:02d}'/f'{mode}.gif',save_all=True,append_images=seq[1:],duration=duration,loop=0,disposal=2,optimize=False)
        board_frames[0].save(out/f'{mode}.gif',save_all=True,append_images=board_frames[1:],duration=duration,loop=0,disposal=2,optimize=False)
        print(f'Encoded {mode}: {len(indices)} individual GIFs, collective GIF and MP4',flush=True)


def gallery(out, records):
    layers=['rgb','source','height','height-color','normal-opengl','normal-directx','relief-shaded','shear-still','validity']
    for layer in layers:
        ims=[image(out/'cells'/f'{i:02d}'/f'{layer}.png') for i in range(12)]
        title=layer.upper()+(' | SYNTHETIC LATERAL MOTION' if layer=='shear-still' else '')
        sheet(ims,title).save(out/f'sheet-{layer}.png')
    sections=''.join(f'<section><h2>{mode}</h2><video controls loop muted playsinline preload="none" poster="cells/00/{mode}-still.png" src="{mode}.mp4"></video><p><a href="{mode}.gif">Collective GIF</a> · <a href="{mode}.mp4">MP4</a></p></section>' for mode in MODES)
    cards=''.join('<article><h3>Cell '+f'{r["index"]:02d}'+'</h3><img loading="lazy" src="cells/'+f'{r["index"]:02d}'+'/rgb.png"><p>'+html.escape(r['id'])+'</p>'+''.join(f'<a href="cells/{r["index"]:02d}/{mode}.gif">{mode} GIF</a> ' for mode in MODES)+f'<p><a href="cells/{r["index"]:02d}/surface.glb">3D GLB</a> · <a href="cells/{r["index"]:02d}/surface.obj">OBJ</a> · <a href="cells/{r["index"]:02d}/height.npy">Float height</a> · <a href="cells/{r["index"]:02d}/cell.json">Provenance</a></p></article>' for r in records)
    refs=''.join(f'<li><a href="{r["url"]}">{r["title"]}</a></li>' for r in RESEARCH)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Twelve tactile studies</title><style>
    body{background:#101722;color:#e9e2d3;font:16px/1.6 system-ui;max-width:1200px;margin:auto;padding:40px}h1{font-size:48px;line-height:1.1}h2{margin-top:45px}a{color:#68d8d0}img,video{max-width:100%;height:auto}video{width:650px}nav{display:flex;gap:18px;flex-wrap:wrap}button,select{background:#263448;color:white;border:1px solid #65758b;padding:12px;font:inherit}.cells{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}article{padding:14px;background:#1c2838;overflow-wrap:anywhere}article a{display:inline-block;margin-right:8px}small{color:#b3c1d4}#sheet{max-height:1000px;display:block;margin:20px auto}strong{color:#ffcc8e}@media(max-width:700px){.cells{grid-template-columns:1fr}body{padding:16px}}</style>
    <p>GELSIGHT / PRIVATE MATERIAL STUDY</p><h1>Twelve captures.<br>One shared arrangement.</h1><p>0 1 2 / 3 4 5 / 6 7 8 / 9 10 11. Selected from the previous all-collection board.</p>
    <p><strong>All loading, shear, torsion, waves and tearing are artistic animation.</strong> No measured force, pressure, shear, slip or material failure is inferred. Geometry retains relative captured height. Damaged or missing measurements are not repaired.</p>
    <nav><a href="#layers">Image layers</a><a href="#motion">Motion studies</a><a href="#cells">Individual cells</a><a href="board/relief-closed.stl">Combined relief STL</a><a href="board/relief-closed.ply">Colored PLY</a><a href="manifest.json">Manifest</a></nav>
    <h2 id="layers">Aligned image layers</h2><select id="layer" aria-label="Image layer">'''+''.join(f'<option value="{x}">{x}</option>' for x in layers)+'''</select><a id="download" href="sheet-rgb.png">Open full sheet</a><img id="sheet" src="sheet-rgb.png" alt="Twelve captures in four rows of three"><script>document.querySelector('#layer').onchange=e=>{const src='sheet-'+e.target.value+'.png';document.querySelector('#sheet').src=src;document.querySelector('#download').href=src;};</script>
    <h2 id="motion">Motion studies</h2><p>Six-second loops. Color and particle sorting follow each capture's relative-height ranks; the order of cells stays fixed. Arrows show authored pixel motion. Particle waves and tearing are visual effects.</p>'''+sections+'<h2 id="cells">Individual cells</h2><div class="cells">'+cards+'</div><h2>Research context</h2><p>GelSight studies track markers through image sequences to study lateral deformation and load patterns. This export borrows the visual vocabulary of outward, lateral and rotational displacement. Its formulas are authored, not a reproduction of the papers’ force estimators.</p><ul>'+refs+'</ul></html>'
    (out/'index.html').write_text(page,encoding='utf-8')


def run(manifest_path, out, cells, frames=72):
    if not shutil.which('ffmpeg'):raise ValueError('Install FFmpeg for MP4 encoding.')
    if not 12<=frames<=120:raise ValueError('Use 12-120 animation frames.')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));entries=select_entries(manifest,cells)
    out.mkdir(parents=True,exist_ok=False)
    write_json(out/'selection.json',dict(source_manifest=str(manifest_path.resolve()),sha256=digest(manifest_path),cells=cells,entries=entries))
    records=[];frozen_entries=[]
    for i,e in enumerate(entries):
        print(f'Preparing cell {i:02d} from source cell {e["source_cell"]}',flush=True)
        records.append(prepare_cell(out,e,i));folder=out/'cells'/f'{i:02d}'
        frozen_entries.append({**e,'rgb':str(folder/'rgb.png'),'depth':str(folder/'height.npy'),'mask':str(folder/'mask.npy')})
    build_board(out/'board',frozen_entries,300.,5.,fixed_layout=(3,4));audit_fidelity(out/'board')
    animations(out,frames);gallery(out,records)
    settings=dict(seed=SEED,frames=frames,fps=12,render_tile=[288,216],grid=[3,4],
        amplitude_cycle='0.5 - 0.5*cos(2*pi*t)',height_color='per-cell 2nd/98th percentiles, display only',
        particle_order='stable ascending normalized relative height within each cell; no force sorting',
        load_arrows='authored radial / lateral / rotational displacement, pixels, not marker tracks',
        tearing='3x3 RGB tiles including background; authored radial motion plus height slopes',
        gif_duration_ms=round(1000/12),video_frame_duration_seconds=1/12,
        measured_force=False,physical_simulation=False,source_geometry_animated=False)
    files={str(p.relative_to(out)).replace('\\','/'):dict(bytes=p.stat().st_size,sha256=digest(p))
           for p in out.rglob('*') if p.is_file()}
    write_json(out/'manifest.json',dict(format='gelsight-twelve-artistic-study-v1',complete=True,
        source_manifest_sha256=digest(manifest_path),selection=cells,records=records,animation=settings,
        research=RESEARCH,files=files,public=False,engine_source_sha256=digest(__file__)))
    print(f'COMPLETE: {out}',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cells',default=','.join(map(str,range(12))))
    p.add_argument('--frames',type=int,default=72)
    a=p.parse_args();run(a.manifest.resolve(),a.output.resolve(),[int(x) for x in a.cells.split(',')],a.frames)


if __name__=='__main__':main()
