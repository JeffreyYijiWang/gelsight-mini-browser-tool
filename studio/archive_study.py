"""Labeled 3x4 studies for every panel in a supplied GelSight data ZIP.

Preserves archive bytes, source names, provided layers and declared (unvalidated)
spacing. Reuses stored depth; never recrops, reconstructs, or invents force data.
"""
from __future__ import annotations
import os
for _key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(_key,'2')
import argparse
import csv
import html
import json
import re
import shutil
import zipfile
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw
import trimesh
from .collection_export import digest, write_json, image, build_board, audit_fidelity
from .typology_surface import display_normals
from .twelve_study import (observed_mesh, normalize, palette, shade, sheet, caption,
                           animations, MODES, RESEARCH, SEED, font)

LAYERS={
    'tactile':'tactile_image.png', 'normal-supplied':'normal_map.png',
    'height-supplied':'depth_colormap.png', 'shear-supplied':'shear_field.png',
    'reference':'reference_image.png', 'difference':'difference_image.png',
    'contact-mask':'contact_mask.png', 'marker-mask':'marker_mask.png',
    'height-grayscale':'height.png','normal-derived':'normal-opengl.png',
    'relief-shaded':'relief-shaded.png','model-preview':'model-preview.png',
    'shear-artistic':'shear-still.png'}


def safe_extract(archive, destination):
    destination=destination.resolve(); records=[]
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist())>20000 or sum(i.file_size for i in z.infolist())>5_000_000_000:
            raise ValueError('Archive exceeds 20,000 files or 5 GB uncompressed.')
        targets=set()
        for info in z.infolist():
            target=(destination/info.filename).resolve()
            if not target.is_relative_to(destination) or target in targets or '\\' in info.filename:
                raise ValueError('Unsafe or duplicate archive member.')
            targets.add(target)
            if (info.external_attr >> 16)&0o170000==0o120000:raise ValueError('Archive symlinks are unsupported.')
        for info in z.infolist():
            target=destination/info.filename
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
            records.append(dict(path=info.filename,bytes=info.file_size,sha256=digest(target)))
    return records


def find_groups(source):
    groups={}
    for path in source.glob('gel_sight_data/*/panel_*/scan_*/metadata.json'):
        meta=json.loads(path.read_text(encoding='utf-8'))
        session=path.parents[2].name;panel=int(path.parent.parent.name.removeprefix('panel_'))
        scan=int(path.parent.name.removeprefix('scan_'))
        if not 0<=scan<12 or meta['scan']!=scan or meta['panel']!=panel:
            raise ValueError('Scan/panel identity mismatch or scan outside 0-11.')
        key=f'{session}/panel_{panel}'
        groups.setdefault(key,[]).append((scan,path.parent,meta))
    if not groups:raise ValueError('No GelSight panel/scan metadata found.')
    return {k:sorted(v,key=lambda x:x[0]) for k,v in sorted(groups.items())}


def preview(z, rgb, spacing):
    # Orthographic triangle rendering from an explicitly reduced display mesh.
    step=5;local=z[::step,::step];color=rgb[::step,::step]
    h,w=local.shape;y,x=np.indices(local.shape)
    xx=x*step*spacing;yy=y*step*spacing;zz=local*12
    px=xx*.82-yy*.58;py=xx*.28+yy*.40-zz
    scale=min(440/max(float(np.ptp(px)),1e-5),330/max(float(np.ptp(py)),1e-5))
    pts=np.stack(((px-px.min())*scale+20,(py-py.min())*scale+25),-1).reshape(-1,2)
    a=(y[:-1,:-1]*w+x[:-1,:-1]).ravel()
    faces=np.vstack((np.column_stack((a,a+w,a+1)),np.column_stack((a+1,a+w,a+w+1))))
    colors=color.reshape(-1,3)[faces].mean(axis=1)
    order=np.argsort((xx+yy).ravel()[faces].mean(axis=1))
    canvas=np.full((400,480,3),(18,26,39),np.uint8)
    for k in order:cv2.fillConvexPoly(canvas,np.rint(pts[faces[k]]).astype(np.int32),tuple(int(c) for c in colors[k]),cv2.LINE_AA)
    return caption(Image.fromarray(canvas),'3D height surface | preview Z x12','Model files retain supplied heights; preview samples every fifth pixel')


def prepare_scan(folder, src, meta, session, scan):
    folder.mkdir(parents=True)
    # Files remain available exactly as supplied, including all source NPY/NPZ/CSV metadata.
    for path in src.iterdir():
        if path.is_file() and path.name!='tactile_image_uncropped.png':shutil.copyfile(path,folder/path.name)
    shutil.copyfile(src/'tactile_image.png',folder/'rgb.png')
    z=np.load(src/'depth_mm.npy',allow_pickle=False)
    spacing=float(meta['mm_per_pixel'])
    if z.ndim!=2 or z.size>2_000_000 or not np.isfinite(z).all() or min(z.shape)<2 or not 0<spacing<10:
        raise ValueError(f'Invalid supplied depth/spacing: {src}')
    mask=np.isfinite(z);np.save(folder/'height.npy',z);np.save(folder/'mask.npy',mask)
    rgb=np.asarray(image(src/'tactile_image.png'))
    if rgb.shape!=(*z.shape,3):raise ValueError('Source RGB and height dimensions disagree.')
    u,limits=normalize(z,mask);Image.fromarray(np.rint(u*255).astype(np.uint8)).save(folder/'height.png')
    n,valid=display_normals(z,mask.astype(np.int32),(spacing,spacing));np.save(folder/'normals.npy',n)
    for name,normal in [('normal-opengl',n),('normal-directx',n*[1,-1,1])]:
        Image.fromarray(np.rint((normal*.5+.5)*255).astype(np.uint8)).save(folder/f'{name}.png')
    Image.fromarray(shade(z/spacing,mask)).save(folder/'relief-shaded.png')
    mesh=observed_mesh(z,mask,rgb,spacing)
    mesh.export(folder/'surface.ply');mesh.export(folder/'surface.obj',digits=9)
    loaded=trimesh.load(folder/'surface.ply',process=False)
    if not np.array_equal(mesh.faces,loaded.faces) or not np.allclose(mesh.vertices,loaded.vertices,atol=1e-6):
        raise ValueError('Surface reload mismatch.')
    mesh.apply_scale(.001);mesh.export(folder/'surface.glb')
    glb=trimesh.load(folder/'surface.glb',force='mesh',process=False)
    if not np.allclose(glb.bounds,mesh.bounds,atol=1e-7):raise ValueError('GLB bounds mismatch.')
    preview(z,rgb,spacing).save(folder/'model-preview.png')
    force=json.loads((src/'force_estimate.json').read_text())
    flow=np.load(src/'marker_flow_px.npy',allow_pickle=False)
    if flow.shape!=(*z.shape,2) or not np.isfinite(flow).all():raise ValueError('Invalid supplied flow.')
    record=dict(session_folder=session,metadata_session=meta['session'],panel=meta['panel'],scan=scan,
        label=f'{session} / panel {meta["panel"]} / scan {scan:02d}',source_folder=str(src),
        source_files={p.name:digest(p) for p in src.iterdir() if p.is_file()},
        source_units=dict(declared_height='mm, indentation positive',declared_xy_mm=spacing,
                          physical_calibration_verified=False,depth_sign_applied_by_source=meta['depth_sign_applied'],
                          handling='Reuse supplied depth unchanged; no crop, baseline subtraction or sign change.'),
        geometry=dict(vertices=len(mesh.vertices),triangles=len(mesh.faces),ply_roundtrip=True,glb_bounds_roundtrip=True,
                      obj_ply_units='source-declared mm',glb_units='meters',open_surface=True,normal_relief_added=False),
        display_height_percentiles=limits,force_report=force,
        supplied_flow=dict(nonzero=int(np.count_nonzero(flow)),range_px=[float(flow.min()),float(flow.max())],
                           reliability='Unvalidated dense displacement array; zero tracked markers in this archive.'),
        force_calibrated=False,shear_measured=False,animation_is_synthetic=True)
    write_json(folder/'cell.json',record)
    return record


def short_name(key):
    session,panel=key.split('/')
    return session.removeprefix('scan_').replace('_20261008','').replace('_200261008','')+' / '+panel.replace('_',' ')


def panel_gallery(folder, key, records):
    title=short_name(key);indices=[r['scan'] for r in records]
    for layer,filename in LAYERS.items():
        ims=[]
        for i in range(12):
            path=folder/'cells'/f'{i:02d}'/filename
            ims.append(image(path) if path.exists() else Image.new('RGB',(320,240),'#121a27'))
        ids=[f'Scan {i:02d}'+(' | NOT PROVIDED' if i not in indices else '') for i in range(12)]
        sheet(ims,title+' | '+layer,ids=ids,tile=(480,360)).save(folder/f'sheet-{layer}.png')
    videos=''.join(f'<section><h2>{mode}</h2><video controls loop muted preload="none" src="{mode}.mp4" poster="cells/{indices[0]:02d}/{mode}-still.png"></video><p><a href="{mode}.gif">Labeled collective GIF</a> · <a href="{mode}.mp4">MP4</a></p></section>' for mode in MODES)
    cards=''
    for i in range(12):
        if i not in indices:cards+=f'<article><h3>Scan {i:02d}</h3><p>Not provided in the archive.</p></article>';continue
        root=f'cells/{i:02d}'
        links=' '.join(f'<a href="{root}/{m}.gif">{m} GIF</a>' for m in MODES)
        cards+=f'<article><h3>{html.escape(title)} / scan {i:02d}</h3><img loading="lazy" src="{root}/model-preview.png"><p>{links}</p><p><a href="{root}/surface.glb">GLB</a> · <a href="{root}/surface.obj">OBJ</a> · <a href="{root}/surface.ply">PLY</a> · <a href="{root}/depth_mm.npy">Supplied float height</a> · <a href="{root}/cell.json">Provenance</a></p><details><summary>All supplied layers</summary>'+''.join(f'<p><a href="{root}/{v}">{k}</a></p>' for k,v in LAYERS.items())+'</details></article>'
    options=''.join(f'<option value="{k}">{k}</option>' for k in LAYERS)
    body=f'<p><a href="../../index.html">All collections</a></p><h1>{html.escape(title)}</h1><p>Scans 0–2 / 3–5 / 6–8 / 9–11. Missing scans stay empty.</p><p class="note">Force is uncalibrated. Supplied shear images have no tracked-marker arrows. All moving loads, waves and tearing below are artistic.</p><select id="layer" aria-label="Image layer">{options}</select> <a id="download" href="sheet-tactile.png">Full-resolution labeled sheet</a><img id="sheet" src="sheet-tactile.png"><p><a href="board/relief-closed.stl">Combined authored relief STL</a> · <a href="board/relief-closed.ply">Combined colored PLY</a></p><script>document.querySelector("#layer").onchange=e=>{{let s="sheet-"+e.target.value+".png";document.querySelector("#sheet").src=s;document.querySelector("#download").href=s;}};</script>'+videos+'<h2>Every scan</h2><div class="grid">'+cards+'</div>'
    (folder/'index.html').write_text(page(title,body),encoding='utf-8')


def page(title,body):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+html.escape(title)+'''</title><style>body{background:#111a27;color:#f0e7d9;max-width:1300px;margin:auto;padding:35px;font:16px/1.65 system-ui}h1{font-size:44px;line-height:1.15}a{color:#79ded3}img,video{max-width:100%;height:auto}video{width:720px}#sheet{display:block;max-height:1100px;margin:22px auto}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}article{background:#1c2a3b;padding:18px;overflow-wrap:anywhere}article a{display:inline-block;margin-right:8px}.note{border-left:3px solid #f2c487;padding-left:18px;color:#ffddae}select{font:inherit;padding:12px;background:#22324b;color:white}h2{margin-top:40px}@media(max-width:760px){.grid{grid-template-columns:1fr}body{padding:15px}}</style>'''+body+'</html>'


def gallery_revision(root):
    """Add responsive presentation views without changing frozen panel assets."""
    css='<style>body{overflow-wrap:anywhere}select{max-width:100%}article{min-width:0}@media(max-width:760px){h1{font-size:32px}}</style>'
    sources=list(root.glob('*/panel_*/index.html'))
    if (root/'index.html').exists():sources.append(root/'index.html')
    revision=dict(format='gelsight-gallery-presentation-v2',files={})
    for src in sources:
        target=src.with_name('gallery.html')
        if target.exists():continue
        text=src.read_text(encoding='utf-8').replace('</style>','</style>'+css,1)
        text=text.replace('/index.html','/gallery.html')
        if src.parent==root:
            text=text.replace('<h1>','<p><a href="models-labeled.zip">Download every labeled GLB model</a></p><h1>',1)
        target.write_text(text,encoding='utf-8')
        revision['files'][str(target.relative_to(root)).replace('\\','/')]=dict(sha256=digest(target),original_index_sha256=digest(src))
    # Each invocation records its own additive presentation revision.
    if revision['files']:
        path=root/'gallery-revision.json'
        if path.exists():
            old=json.loads(path.read_text());revision['files']={**old['files'],**revision['files']}
        write_json(path,revision)


def package_models(root, manifest=None):
    """Convenience model bundle with self-identifying filenames; no source images."""
    destination=root/'models-labeled.zip';receipt=root/'model-bundle.json'
    if receipt.exists():
        record=json.loads(receipt.read_text())
        if digest(destination)!=record['sha256']:raise ValueError('Completed model bundle changed.')
        return
    if manifest is None:
        manifest=json.loads((root/'manifest.json').read_text());assert manifest['complete']
    index=[]
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for panel in manifest['panels']:
            records=json.loads((root/panel['key']/'manifest.json').read_text())['records']
            for cell in records:
                name=f'{cell["session_folder"]}__panel-{cell["panel"]}__scan-{cell["scan"]:02d}.glb'
                src=root/panel['key']/'cells'/f'{cell["scan"]:02d}'/'surface.glb'
                z.write(src,name)
                index.append(dict(file=name,label=cell['label'],sha256=digest(src),units='meters',
                                  source_units=cell['source_units'],geometry=cell['geometry']))
        z.writestr('model-index.json',json.dumps(index,indent=2))
        z.writestr('README.txt','Full-resolution colored height surfaces.\n'
            'GLB uses meters, converted from source-declared millimeters. Physical calibration is unverified.\n'
            'These are open surfaces, not closed printable solids. No extra normal relief is added.\n'
            'Filenames identify collection, panel and scan; see model-index.json for provenance.\n')
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None:raise ValueError('Model ZIP integrity failure.')
    write_json(receipt,dict(file=destination.name,sha256=digest(destination),models=len(index),zip_crc_verified=True))


def run(archive,out,frames=48,resume=False):
    if not shutil.which('ffmpeg'):raise ValueError('FFmpeg is required.')
    if not 12<=frames<=120:raise ValueError('Frame budget is 12-120.')
    out=out.resolve();out.mkdir(parents=True,exist_ok=resume)
    archive_hash=digest(archive);source=out/'source'
    if resume:
        snapshot=json.loads((out/'archive.json').read_text())
        if snapshot['sha256']!=archive_hash or snapshot['frames']!=frames:raise ValueError('Resume source/settings changed.')
        for item in snapshot['files']:
            if digest(source/item['path'])!=item['sha256']:raise ValueError('Extracted source changed.')
    else:
        files=safe_extract(archive,source)
        write_json(out/'archive.json',dict(path=str(archive.resolve()),sha256=archive_hash,frames=frames,files=files))
    groups=find_groups(source);panels=[];all_records=[]
    for key,scans in groups.items():
        folder=out/key
        if resume and (folder/'manifest.json').exists():
            previous=json.loads((folder/'manifest.json').read_text())
            for path,sha in previous['files'].items():
                if digest(folder/path)!=sha:raise ValueError('Completed panel changed.')
            panels.append(previous['panel']);all_records.extend(previous['records']);continue
        if folder.exists():
            # Only this command's incomplete derived panel may be regenerated.
            if not folder.resolve().is_relative_to(out) or (folder/'manifest.json').exists():raise ValueError('Unsafe partial panel.')
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        title=short_name(key);records=[];entries=[]
        for scan,src,meta in scans:
            print(f'{title} / scan {scan:02d}',flush=True)
            record=prepare_scan(folder/'cells'/f'{scan:02d}',src,meta,key.split('/')[0],scan);records.append(record)
            entries.append(dict(id=record['label'],name=f'Scan {scan:02d}',source_cell=scan,
                rgb=str(src/'tactile_image.png'),depth=str(src/'depth_mm.npy'),source=str(src/'tactile_image.png'),
                source_sha256=digest(src/'tactile_image.png'),depth_sha256=digest(src/'depth_mm.npy')))
        # These data groups contain contiguous scan numbers, including partial groups.
        if [r['scan'] for r in records]!=list(range(len(records))):raise ValueError('Noncontiguous scan IDs need explicit empty-cell layout support.')
        build_board(folder/'board',entries,300.,5.,fixed_layout=(3,4),
                    source_height_units='source-declared mm; physical calibration unverified');audit_fidelity(folder/'board')
        animations(folder,frames,indices=[r['scan'] for r in records],label=title)
        panel_gallery(folder,key,records)
        panel=dict(key=key,title=title,captures=len(records),indices=[r['scan'] for r in records],grid=[3,4])
        hashes={str(p.relative_to(folder)).replace('\\','/'):digest(p) for p in folder.rglob('*') if p.is_file()}
        write_json(folder/'manifest.json',dict(complete=True,panel=panel,records=records,files=hashes))
        panels.append(panel);all_records.extend(records)
        write_json(out/'progress.json',dict(complete=False,panels=panels,total_panels=len(groups)))
    if (out/'manifest.json').exists():
        previous=json.loads((out/'manifest.json').read_text())
        if not previous['complete'] or previous['panels']!=panels or previous['archive_sha256']!=archive_hash:
            raise ValueError('Completed root manifest does not match this snapshot.')
        package_models(out);gallery_revision(out)
        print(f'VERIFIED COMPLETE: {out}',flush=True)
        return
    cards=''.join(f'<article><h2>{html.escape(p["title"])}</h2><a href="{p["key"]}/index.html"><img loading="lazy" src="{p["key"]}/sheet-tactile.png"></a><p>{p["captures"]} captures · <a href="{p["key"]}/index.html">Open labeled layers, models and animations</a></p></article>' for p in panels)
    refs=''.join(f'<li><a href="{r["url"]}">{r["title"]}</a></li>' for r in RESEARCH)
    body=f'<p>GELSIGHT / OCTOBER 8, 2026 / PRIVATE ARCHIVE STUDIES</p><h1>Every collection.<br>Every panel. Every scan.</h1><p>{len(all_records)} supplied captures · {len(panels)} panel boards · exact 3-column × 4-row layout.</p><p class="note">All 124 source force reports contain zero tracked markers and null force values. Supplied depth files declare mm and 0.0634 mm/pixel; physical calibration is unverified. Source shear images and arrays are preserved, but they do not establish measured shear forces. Loading, shear, torsion, particle waves and pixel tearing are explicitly artistic animation.</p><p>Each collection keeps its original folder name and panel/scan labels. Nine panels contain all scans 0–11; missing scans remain labeled empty slots. The Spring folder’s internal session name says stats; both names are recorded rather than silently reconciled.</p><div class="grid">{cards}</div><h2>Research and interpretation</h2><p>The GelSight papers track marker motion through sequences to study outward, lateral and rotational deformation. Our animation uses those visual patterns with authored displacements. Height-sorted particles do not represent force rank. No Newton values, friction coefficients, damage or failure predictions are invented.</p><ul>{refs}</ul><p><a href="manifest.json">Export manifest</a> · <a href="capture-index.csv">All capture labels and source proxies</a></p>'
    (out/'index.html').write_text(page('GelSight archive studies',body),encoding='utf-8')
    with (out/'capture-index.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['collection','metadata_session','panel','scan','label','markers_tracked','normal_force_N','shear_force_N','source_reported_indentation_volume_mm3','physical_calibration_verified'])
        for r in all_records:writer.writerow([r['session_folder'],r['metadata_session'],r['panel'],r['scan'],r['label'],r['force_report']['markers_tracked'],r['force_report']['normal_force_N'],r['force_report']['shear_force_N'],r['force_report']['indentation_volume_mm3'],False])
    result=dict(format='gelsight-archive-study-v1',complete=True,archive_sha256=archive_hash,
        panels=panels,captures=len(all_records),research=RESEARCH,public=False,
        animation=dict(seed=SEED,frames=frames,video_fps=12,gif_frame_ms=80,tile=[288,216],
                       modes=list(MODES),synthetic=True,force_inference=False,per_cell_height_percentiles=[2,98],
                       pixel_tearing_tile_size=3,particle_sort='ascending relative height within each scan'),
        source_code={p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name('twelve_study.py'),Path(__file__).with_name('collection_export.py')]})
    package_models(out,result);gallery_revision(out)
    write_json(out/'manifest.json',result);write_json(out/'progress.json',dict(complete=True,panels=len(panels)))
    print(f'COMPLETE: {out}',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--frames',type=int,default=48);p.add_argument('--resume',action='store_true');a=p.parse_args()
    run(a.archive,a.output,a.frames,a.resume)


if __name__=='__main__':main()
