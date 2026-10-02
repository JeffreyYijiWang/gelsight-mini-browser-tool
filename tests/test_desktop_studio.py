import json
from pathlib import Path
import shutil
import subprocess
import numpy as np
from PIL import Image
import pytest
import trimesh

from desktop_studio.reconstruction import crop_rgb, fill_markers, poisson, Reconstructor
from desktop_studio.project import Project, save_surface, export_print, sha


def test_golan_marker_and_dct_recipe_against_javascript(tmp_path):
    """Execute unchanged JS core; inject a tiny orthonormal DCT test adapter."""
    if not shutil.which('node'): pytest.skip('Node required for upstream parity check')
    script = r'''
const C=require(process.argv[2]);
const w=8,h=6,gx=Float32Array.from({length:w*h},(_,i)=>Math.sin(i*.7)),gy=Float32Array.from({length:w*h},(_,i)=>Math.cos(i*.3));
const mask=Uint8Array.from({length:w*h},(_,i)=>i%7<3?1:0);
C.applyMarkerMaskToGradients(gx,gy,mask,w,h);
const fill=[Array.from(gx),Array.from(gy)];
function Mat(rows,cols){this.data32F=new Float32Array((rows||h)*(cols||w));this.delete=()=>{};}
function transform(src,dst,inverse){
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){
 let sum=0;
 for(let j=0;j<h;j++)for(let i=0;i<w;i++){
 const kx=inverse?i:x, ky=inverse?j:y, sx=inverse?x:i,sy=inverse?y:j;
 const ax=kx===0?Math.sqrt(1/w):Math.sqrt(2/w),ay=ky===0?Math.sqrt(1/h):Math.sqrt(2/h);
 sum+=src.data32F[j*w+i]*ax*ay*Math.cos(Math.PI*(sx+.5)*kx/w)*Math.cos(Math.PI*(sy+.5)*ky/h);
 }dst.data32F[y*w+x]=sum;
 }
}
const cv={Mat,CV_32F:0,matFromArray:(h,w,t,a)=>{let m=new Mat(h,w);m.data32F.set(a);return m;},dct:(a,b)=>transform(a,b,false),idct:(a,b)=>transform(a,b,true)};
console.log(JSON.stringify({fill,depth:Array.from(C.poissonDctNeumann(cv,gx,gy,w,h,.0005))}));
'''
    path = tmp_path/'parity.cjs'; path.write_text(script)
    core = Path(__file__).resolve().parents[1]/'gelsight_p5/gelsight-core.js'
    expected = json.loads(subprocess.check_output(['node', str(path), str(core)], text=True))
    i = np.arange(48); mask = (i%7<3).reshape(6, 8)
    gx = fill_markers(np.sin(i*.7).astype(np.float32).reshape(6, 8), mask)
    gy = fill_markers(np.cos(i*.3).astype(np.float32).reshape(6, 8), mask)
    assert np.allclose(gx.ravel(), expected['fill'][0], atol=1e-6)
    assert np.allclose(gy.ravel(), expected['fill'][1], atol=1e-6)
    assert np.allclose(poisson(gx, gy).ravel(), expected['depth'], atol=2e-6)


def test_crop_real_model_and_normal_geometry(tmp_path):
    y, x = np.indices((80, 100))
    rgb = np.stack((130+20*np.sin(x*.2), 150+25*np.cos(y*.2), 120+20*np.sin((x+y)*.1)), -1).astype(np.uint8)
    crop, box = crop_rgb(rgb)
    assert box==[10, 8, 90, 72] and crop.shape==(64, 80, 3)
    result = Reconstructor().raw_depth(rgb)
    assert result['depth'].shape==(240, 320) and np.isfinite(result['depth']).all()
    assert result['rgb'].shape==(240, 320, 3)
    z = (.2*x+.3*y).astype(np.float32)
    save_surface(tmp_path, z, rgb)
    n = np.load(tmp_path/'normals.npy')
    expected = np.array([-.2, .3, 1]); expected /= np.linalg.norm(expected)
    assert np.allclose(n, expected, atol=1e-5)
    mesh = trimesh.load(tmp_path/'surface.ply', force='mesh', process=False)
    points = trimesh.load(tmp_path/'points.ply', process=False)
    assert len(points.vertices)==z.size and len(mesh.faces)==2*79*99
    assert np.allclose(mesh.vertices[:, 2], z.ravel())
    assert np.all(mesh.face_normals[:, 2]>0)
    scene = trimesh.load(tmp_path/'normal-material.glb')
    plane = next(iter(scene.geometry.values()))
    assert np.ptp(plane.vertices[:, 2])==0 and plane.visual.material.normalTexture is not None
    exported = export_print(tmp_path, width_mm=80, relief_mm=3, base_mm=1)
    solid = trimesh.load(exported/'relief_mm.stl', force='mesh')
    assert solid.is_volume and solid.is_watertight and len(solid.split())==1
    assert np.allclose(solid.extents, [80, 79*80/99, 4])
    report = json.loads((exported/'validation.json').read_text())
    assert report['roundtrip_passed'] and not report['print_ready']


def add_fixture(project, row, col, z, identifier):
    folder = project.root/'captures'/identifier; folder.mkdir(parents=True)
    rgb = np.repeat((np.clip(z*20+128, 0, 255).astype(np.uint8))[..., None], 3, axis=2)
    save_surface(folder, z, rgb)
    record = dict(id=identifier, row=row, column=col, device='SYNTHETIC fixture', config={'synthetic':True},
                  files={p.name:sha(p) for p in folder.iterdir()})
    project.data['rows'][row].append(record); project.save()
    return folder


def test_ragged_rows_missing_cells_rejection_and_revisions(tmp_path):
    project = Project(tmp_path)
    z = np.zeros((24, 32), np.float32)
    add_fixture(project, 0, 0, z, 'a'); add_fixture(project, 0, 1, z+1, 'b')
    project.new_row(); add_fixture(project, 1, 0, z+2, 'c')
    output = project.assemble()
    report = json.loads((output/'assembly.json').read_text())
    assert report['row_lengths']==[2, 1]
    assert {(e['a'], e['b']) for e in report['neighbors']}=={(0, 1), (0, 2)}
    assert not any(e['accepted'] for e in report['neighbors'])
    assert report['positions']==[[0, 0], [24, 0], [0, 18]]
    observed = np.asarray(Image.open(output/'observed-mask.png'))>0
    synthetic = np.asarray(Image.open(output/'synthetic-mask.png'))>0
    assert not observed[-1, -1] and synthetic[-1, -1]
    assert np.all(synthetic[~observed])
    surface = trimesh.load(output/'surface.ply', force='mesh')
    assert len(surface.split(only_watertight=False))==1
    assert surface.euler_number==1  # rectangular disk, no interior holes
    assert project.assemble()!=output and len(project.data['assemblies'])==2
    resumed = Project(tmp_path); assert list(map(len, resumed.data['rows']))==[2, 1]
    (tmp_path/'captures/a/depth.npy').write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='has changed'): resumed.assemble()


def test_distinctive_normal_overlap_recovers_neighbor_translation(tmp_path):
    from scipy.ndimage import gaussian_filter
    rng = np.random.default_rng(428)
    z = (gaussian_filter(rng.normal(size=(240, 520)), 2)*100).astype(np.float32)
    project = Project(tmp_path)
    add_fixture(project, 0, 0, z[:, :320], 'left')
    add_fixture(project, 0, 1, z[:, 200:520], 'right')
    output = project.assemble(overlap=.375)
    report = json.loads((output/'assembly.json').read_text())
    assert report['neighbors'][0]['accepted'], report['neighbors']
    assert np.allclose(np.array(report['positions'])[1]-np.array(report['positions'])[0], [200, 0], atol=1)
    assert not report['metric_validated']  # matching does not create a physical calibration


def test_calibration_capture_crop_and_cancellation(tmp_path, monkeypatch):
    import desktop_studio.project as module
    from desktop_studio.reconstruction import CONFIG
    class FakeModel:
        config = CONFIG
        def raw_depth(self, raw):
            crop, box = crop_rgb(raw)
            return dict(depth=np.full((240, 320), raw[0, 0, 0]/10, np.float32),
                        rgb=np.full((240, 320, 3), raw[0, 0, 0], np.uint8), crop=crop,
                        crop_box=box, marker=np.zeros((240, 320), bool))
    monkeypatch.setattr(module, 'Reconstructor', FakeModel)
    project = Project(tmp_path)
    frames = [np.full((40, 50, 3), i+100, np.uint8) for i in range(50)]
    baseline = project.calibrate(frames, 'synthetic')
    assert len(baseline['frame_sha256'])==50
    assert np.allclose(np.load(tmp_path/'calibrations'/baseline['id']/'depth.npy'), 12.45)
    folder = project.capture(np.full((40, 50, 3), 150, np.uint8), baseline, 'synthetic')
    assert Image.open(folder/'source.png').size==(50, 40)
    assert Image.open(folder/'cropped-source.png').size==(40, 32)
    assert np.allclose(np.load(folder/'depth.npy'), 2.55)
    assert Image.open(folder/'normal.png').size==(320, 240)
    with pytest.raises(ValueError, match='Device or resolution'): project.capture(frames[0], baseline, 'other')
    def cancel(*args): raise InterruptedError('cancelled')
    with pytest.raises(InterruptedError): project.capture(frames[0], baseline, 'synthetic', cancel)
    assert len(project.data['rows'][0])==1
    with pytest.raises(ValueError): export_print(folder, relief_mm=float('nan'))
