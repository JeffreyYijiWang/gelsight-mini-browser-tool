import io
import numpy as np
from PIL import Image
import pytest
import trimesh
from studio.store import Store
from studio.camera import save_capture
from studio.samples import save_p5_sample
from studio.sensor_damage import damage_mask, validate_regions
from studio.typology import source_image, build_typology


def png(array):
    output=io.BytesIO();Image.fromarray(array).save(output,format='PNG');return output.getvalue()


def test_mask_coordinates_limits_and_guard():
    mask=damage_mask((240,320),[[.5,.5,.03,.04]],(.1,.1,.8,.8))
    assert mask[120,160] and not mask[30,30]
    assert not damage_mask((240,320),[[.03,.03,.01,.01]],(.1,.1,.8,.8)).any()
    for regions in ([],[[float('nan'),.5,.1,.1]],[[.5,.5,0,.1]]):
        with pytest.raises(ValueError):validate_regions(regions)
    with pytest.raises(ValueError,match='half'):damage_mask((80,80),[[.5,.5,.5,.5]])


def test_quick_reference_is_frozen_and_geometry_excludes_damage(tmp_path):
    from studio.reconstruction import reconstruct
    store=Store(tmp_path);y,x=np.indices((72,96))
    base=np.stack((110+25*np.sin(x*.3),120+25*np.cos(y*.4),110+25*np.sin((x+y)*.2)),-1).astype(np.uint8)
    device={'name':'GelSight synthetic test','id':'fixture-device'}
    reference=save_capture(store,png(base),device,baseline=True)
    profile={'baseline_id':reference['frame']['id'],'regions':[[.5,.5,.06,.07]]}
    raw=png(base+20)
    capture=save_capture(store,raw,device,session_id=reference['session']['id'],damage=profile)
    frame=capture['frame'];assert store.path(frame['raw_file']).read_bytes()==raw
    preview,_=source_image(store,'frames',frame['id']);assert preview.size==(77,58)
    save_capture(store,png(base+5),device,session_id=reference['session']['id'],baseline=True)
    patch=reconstruct(store,frame['id'])
    _,arrays=store.patch(patch['id']);h,w=arrays['mask'].shape
    assert not arrays['mask'][h//2,w//2] and arrays['mask'].sum()>100
    assert patch['settings']['sensor_damage']['baseline_id']==reference['frame']['id']
    with pytest.raises(ValueError,match='baseline'):reconstruct(store,frame['id'],{'baseline_id':store.get('sessions',reference['session']['id'])['baseline_id']})
    with pytest.raises(ValueError,match='Resolution'):save_capture(store,png(base[:60]),device,session_id=reference['session']['id'],damage=profile)


def test_p5_damage_preserves_source_excludes_mesh_and_follows_typology(tmp_path):
    store=Store(tmp_path);y,x=np.indices((240,320));depth=(np.sin(x*.05)+np.cos(y*.08)).astype(np.float32)
    rgb=np.stack((110+30*np.sin(x*.1),130+30*np.cos(y*.1),110+20*np.sin((x+y)*.1)),-1).astype(np.uint8);raw=png(rgb)
    payload=dict(depth=depth.tolist(),baseline=np.zeros_like(depth).tolist(),demo=True,crop=[.1,.1,.8,.8],metadata={},sensor_damage={'regions':[[.5,.5,.06,.08]]})
    with pytest.raises(ValueError,match='matching untouched'):save_p5_sample(store,raw,raw,raw,payload)
    result=save_p5_sample(store,raw,raw,raw,payload,color_baseline=raw,model_rgb=raw)
    directory=store.path(result['sample']['directory']);invalid=np.asarray(Image.open(directory/'damage-mask.png'))>0
    assert store.path(result['frame']['raw_file']).read_bytes()==raw
    assert np.array_equal(np.load(directory/'depth.npy'),depth)
    _,arrays=store.patch(result['patch']['id']);assert not arrays['mask'][invalid].any()
    normals=np.asarray(Image.open(directory/'normal.png'));assert np.all(normals[invalid]==[128,128,255])
    mesh=trimesh.load(directory/'mesh.obj',force='mesh',process=False)
    ix=np.rint(mesh.vertices[:,0]+159.5).astype(int);iy=np.rint(119.5-mesh.vertices[:,1]).astype(int)
    assert not invalid[iy,ix].any() and len(mesh.vertices)==(~invalid).sum()
    assert np.all(np.asarray(Image.open(directory/'depth.png'))[invalid,3]==0)
    second=save_p5_sample(store,raw,raw,raw,{**payload,'sensor_damage':None})
    board=build_typology(store,[{'kind':'frames','id':r['frame']['id']} for r in (result,second)])
    damaged=next(e for e in board['items'] if e['id']==result['frame']['id'])
    assert damaged['sensor_damage']['reference_sha256'] and 'mesh' not in damaged['views']
    with np.load(store.path(board['directory'])/'stitched-surface.npz') as surface:
        src=next(s for s in board['surface']['sources'] if s['source_id']==result['patch']['id'])
        bx,by,bw,bh=src['destination_box'];assert not surface['mask'][by+bh//2,bx+bw//2]
