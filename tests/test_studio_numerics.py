import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
import trimesh

from studio.store import Store
from studio.records import SurfacePatch, CalibrationProfile
from studio.surface import encode_height, integrate_normals, normals_from_height, seamless, wrinkles
from studio.inputs import import_bytes, synthetic_demo, quality
from studio.reconstruction import MiniMLP
from studio.materials import build_material, derive_patch, export_textures
from studio.printing import relief_mesh, sphere_mesh, validate_mesh, roundtrip, load_mesh, self_intersections, make_print


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def test_flat_and_ramp_normal_orientation_and_spacing():
    y,x=np.mgrid[:30,:40]
    flat,_=normals_from_height(np.ones((30,40)),(.1,.2))
    assert np.allclose(flat,(0,0,1))
    ramp=.3*(x*.1)+.4*(y*.2)
    normal,_=normals_from_height(ramp,(.1,.2))
    target=np.array([-.3,.4,1]);target/=np.linalg.norm(target)
    assert np.allclose(normal,target,atol=1e-6)
    dx,_=normals_from_height(ramp,(.1,.2),convention="directx")
    assert np.allclose(dx[...,1],-normal[...,1])
    recovered,valid=integrate_normals(normal,np.ones(ramp.shape,bool),(.1,.2))
    assert np.max(abs(recovered-(ramp-ramp.mean())))<1e-5


def test_integration_keeps_holes_and_independent_offsets():
    y,x=np.mgrid[:18,:30];h=.2*x+.1*y
    n,_=normals_from_height(h)
    mask=np.ones(h.shape,bool);mask[:,14:16]=False;mask[4:8,4:8]=False
    out,valid=integrate_normals(n,mask)
    assert np.array_equal(valid,mask)
    for region in (np.indices(h.shape)[1]<14,np.indices(h.shape)[1]>15):
        region &= mask
        assert abs(out[region].mean())<1e-6
        assert np.std((out-h)[region])<1e-4


def test_height_precision_bias_no_clipping():
    rng=np.random.default_rng(4);h=rng.uniform(-.17,.43,(30,40)).astype(np.float32);mask=np.ones(h.shape,bool)
    encoded,meta=encode_height(h,mask)
    decoded=encoded.astype(float)*meta["scale_per_code"]+meta["bias"]
    assert np.max(abs(decoded-h))<=meta["max_quantization_error"]+1e-7
    assert encoded.min()==0 and encoded.max()==65535


def test_metric_gates_and_missing_weights(store):
    with pytest.raises(ValueError):SurfacePatch(name="bad",width=5,height=5,state="calibrated",units="mm")
    with pytest.raises(ValueError):SurfacePatch(name="bad",width=5,height=5,pixel_spacing=(1,1))
    with pytest.raises(ValueError,match="missing"):MiniMLP(Path('no-such-weights.bin'))
    with pytest.raises(ValueError):CalibrationProfile(name="bad",sensor_id="s",gel_id="g",width=10,height=10,pixel_spacing_mm=(.1,.1),weights="x",validated=True)
    buf=io.BytesIO();np.save(buf,np.ones((5,5)))
    with pytest.raises(ValueError,match="validation"):import_bytes(store,'h.npy',buf.getvalue(),'height',settings={"units":"mm","pixel_spacing":[.1,.1]})


def test_mini_model_finite_and_not_brightness_height():
    model=MiniMLP();rgb=np.full((12,16,3),100,np.uint8)
    n=model.predict(rgb)
    assert n.shape==(12,16,3) and np.isfinite(n).all()
    assert np.allclose(np.linalg.norm(n,axis=-1),1)


def test_markers_and_contact_loss_excluded():
    rgb=np.full((48,64,3),120,np.uint8);rgb[20:23,30:33]=0
    mask,q=quality(rgb,baseline=rgb.copy())
    assert not mask.any() and q["rejected"]
    mask,_=quality(rgb)
    assert not mask[19:24,29:34].any()


def test_seamless_is_derived_and_marks_invention(store):
    demo=synthetic_demo(store,size=48);p,a=store.patch(demo['patches'][0]['id']);before=a['height'].copy()
    result=derive_patch(store,p.id,{"seamless":True})
    _,after=store.patch(result['id']);_,original=store.patch(p.id)
    assert np.array_equal(original['height'],before)
    assert np.allclose(after['height'][0],after['height'][-1])
    assert np.allclose(after['height'][:,0],after['height'][:,-1])
    assert after['synthetic_mask'].any() and result['parent_id']==p.id


def test_wrinkles_never_measure_synthetic_or_uncalibrated():
    y,x=np.mgrid[:64,:64];h=-np.exp(-((x-32)/2)**2)*.08;mask=np.ones(h.shape,bool)
    valleys,summary=wrinkles(h,mask,6,.005,False)
    assert valleys.sum()>0 and 'p80_depth_mm' not in summary
    _,measured=wrinkles(h,mask,6,.005,True)
    assert .06<measured['p80_depth_mm']<.09
    valleys,_=wrinkles(h,mask,6,.005,True,np.ones_like(mask))
    assert not valleys.any()


def test_relief_geometry_narrow_valley_roundtrip(tmp_path):
    y,x=np.mgrid[:40,:48];h=.15-.12*np.exp(-((x-24)/1.2)**2)
    mesh,fidelity=relief_mesh(h,np.ones(h.shape,bool),47,39,2,.025,30000)
    report=validate_mesh(mesh,fidelity,construction=mesh.metadata['construction'],min_thickness=2)
    assert report.geometry_valid,report.errors
    assert report.checks['vertex_manifold'] and report.volume_mm3>0
    assert mesh.vertices[:,2].max()>2.14
    assert fidelity['max_error_mm']<=.025
    result=roundtrip(mesh,tmp_path,mesh.metadata['construction'],2)
    assert all(r['passed'] for r in result.values()),result


def test_masked_holes_have_walls_not_fills():
    h=np.ones((12,14))*.4;mask=np.ones(h.shape,bool);mask[4:7,5:8]=False
    mesh,f=relief_mesh(h,mask,13,11,2,.01,10000)
    report=validate_mesh(mesh,f,construction=mesh.metadata['construction'],min_thickness=2)
    assert report.geometry_valid,report.errors
    assert not np.any((mesh.vertices[:,0]>5)&(mesh.vertices[:,0]<7)&(mesh.vertices[:,1]<-4)&(mesh.vertices[:,1]>-6))


def test_sphere_seam_and_poles():
    h=np.zeros((20,24));h[:,10:14]=.8
    mesh,info=sphere_mesh(h,radius=15,segments=24,rings=16)
    assert info['seam_welded'] and mesh.is_watertight and mesh.is_winding_consistent
    assert len(mesh.vertices)==2+24*15
    assert mesh.volume>0
    assert np.linalg.norm(mesh.vertices,axis=1).max()>15.7
    report=validate_mesh(mesh,construction=mesh.metadata['construction'],min_thickness=30)
    assert report.geometry_valid,report.errors


def test_self_intersecting_solids_are_rejected():
    a=trimesh.creation.box();b=trimesh.creation.box();b.apply_translation([.35,.25,.1])
    mesh=trimesh.util.concatenate([a,b])
    hits,_=self_intersections(mesh)
    assert hits
    report=validate_mesh(mesh)
    assert not report.geometry_valid and not report.print_ready


def test_mesh_unknown_units_are_rejected_and_explicit_units_applied(tmp_path):
    path=tmp_path/'cube.stl';trimesh.creation.box(extents=[1,2,3]).export(path)
    with pytest.raises(ValueError,match="unit"):load_mesh(path)
    mesh,inspection=load_mesh(path,'inch')
    assert np.allclose(mesh.extents,[25.4,50.8,76.2])


def test_material_export_contains_only_selected_derived_files(store):
    import zipfile
    demo=synthetic_demo(store,size=40)
    material=build_material(store,demo['patches'][0]['id'])
    output=export_textures(store,material['id'])
    with zipfile.ZipFile(store.path(output['file'])) as z:
        names=z.namelist()
        assert 'height.npy' in names and 'normal_opengl.png' in names and 'material_baked.glb' in names
        assert not any('raw/' in n or 'capture.png' in n for n in names)
        manifest=json.loads(z.read('export-manifest.json'))
        assert manifest['selected_ids']==[material['id']] and not manifest['raw_captures_included']


def test_relative_print_needs_authored_size_and_preserves_failure(store):
    p=SurfacePatch(name='relative',width=10,height=10)
    store.put_patch(p,np.ones((10,10)))
    with pytest.raises(ValueError,match='authored'):make_print(store,p.id,{})
    assert store.list('prints')[0]['report']['errors']
