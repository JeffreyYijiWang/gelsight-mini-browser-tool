import hashlib
import io
import json

import numpy as np
import pytest
from PIL import Image

from studio.store import Store
from studio.samples import save_p5_sample
from studio.typology import build_typology, source_image
from studio.unfolding import build_unfolding


def capture(store,index=0):
    y,x=np.mgrid[:240,:320];z=(np.sin(x*.08+index)+np.cos(y*.11)).astype(np.float32)
    rgb=np.stack((np.where(x<160,190,40)+y//10,np.where(x<160,70,170)+x//10,np.rint(90+50*np.sin(y*.2))),-1).astype(np.uint8)
    out=io.BytesIO();Image.fromarray(rgb).save(out,format='PNG');raw=out.getvalue()
    payload=dict(depth=z.tolist(),baseline=np.zeros_like(z).tolist(),demo=True,device='Synthetic p5 fixture',crop=[.1,.1,.8,.8],metadata={'calibration':{'dirty':False}})
    result=save_p5_sample(store,raw,raw,raw,payload,'Texture '+str(index))
    return result,raw,payload


def test_sample_keeps_original_and_exact_crop_and_relative_depth(tmp_path):
    store=Store(tmp_path);result,raw,payload=capture(store)
    sample=result['sample'];frame=result['frame'];patch,arrays=store.patch(result['patch']['id'])
    assert store.path(frame['raw_file']).read_bytes()==raw
    assert frame['sha256']==hashlib.sha256(raw).hexdigest()
    assert sample['crop_pixels']==[32,24,288,216]
    assert Image.open(store.path(sample['directory'])/'raw.png').size==(256,192)
    assert source_image(store,'frames',frame['id'])[0].size==(256,192)
    assert np.allclose(arrays['height'],payload['depth']) and 'baseline' in arrays
    assert patch.units=='relative' and patch.state=='uncalibrated' and patch.pixel_spacing is None


def test_synchronized_sheet_order_all_views_and_names(tmp_path):
    store=Store(tmp_path);samples=[capture(store,i)[0] for i in range(3)]
    board=build_typology(store,[{'kind':'frames','id':s['frame']['id']} for s in samples])
    for item in board['items']:
        assert set(item['views'])=={'raw','depth','mesh'}
    for view in ('raw','depth','mesh'):
        assert (store.path(board['directory'])/(view+'-sheet.png')).is_file()
        assert (store.path(board['directory'])/(view+'-sheet-named.png')).is_file()
    assert all(s['frame']['sha256']==hashlib.sha256(store.path(s['frame']['raw_file']).read_bytes()).hexdigest() for s in samples)
    page=(store.path(board['directory'])/'index.html').read_text()
    assert 'Texture 0' in page and 'mesh-sheet-named.png' in page
    assert board['surface']['triangles']>0 and not board['surface']['metric_validated']
    with np.load(store.path(board['directory'])/'stitched-surface.npz') as surface:
        ids=set(np.unique(surface['cell_ids']))
        assert ids=={0,*[i['cell']+1 for i in board['items']]}
        for src in board['surface']['sources']:
            x,y,w,h=src['destination_box']
            assert np.all(surface['cell_ids'][y:y+h,x:x+w]==src['cell']+1)
            assert src['baseline_subtraction']=='already applied by p5; not repeated'
    import trimesh
    mesh=trimesh.load(store.path(board['directory'])/'stitched-mesh.obj',force='mesh',process=False)
    assert len(mesh.faces)==board['surface']['triangles'] and np.isfinite(mesh.vertices).all()
    assert len(mesh.split(only_watertight=False))==3 # no fabricated bridges across scans
    connected=trimesh.load(store.path(board['directory'])/'connected-mesh.obj',force='mesh',process=False)
    assert board['surface']['artistic_connections']['triangles']>0
    assert len(connected.faces)>len(mesh.faces) and len(connected.split(only_watertight=False))<3
    assert np.allclose(connected.vertices,mesh.vertices)
    with np.load(store.path(board['directory'])/'connected-surface.npz') as display:
        assert not np.any(display['synthetic_mask']&display['source_mask'])
    folder=store.path(board['directory'])
    assert board['surface']['normal_maps']['float_convention']=='opengl'
    assert 'connected-normal-directx.png' in page
    for prefix in ('stitched','connected'):
        gl=np.asarray(Image.open(folder/f'{prefix}-normal-opengl.png'))
        dx=np.asarray(Image.open(folder/f'{prefix}-normal-directx.png'))
        with np.load(folder/f'{prefix}-normals.npz') as normal_data:
            normals=normal_data['normals'];valid=normal_data['mask']
            assert np.allclose(np.linalg.norm(normals,axis=-1),1,atol=1e-6)
            assert np.allclose(gl[valid]/255*2-1,normals[valid],atol=1/255+1e-7)
            assert np.array_equal(gl[...,0],dx[...,0]) and np.array_equal(gl[...,2],dx[...,2])
            assert np.all(gl[...,1][valid].astype(int)+dx[...,1][valid]==255)
            assert np.all(gl[~valid]==[128,128,255]) and np.all(dx[~valid]==[128,128,255])
            assert np.array_equal(np.asarray(Image.open(folder/f'{prefix}-normal-mask.png'))>0,valid)
            assert normal_data['synthetic_influence_mask'].any()==(prefix=='connected')
            assert gl.shape[:2]==(board['surface']['height'],board['surface']['width'])


def test_display_normals_orientation_spacing_holes_and_source_boundaries():
    from studio.typology_surface import display_normals
    y,x=np.mgrid[:9,:12];z=(x*.2*2+y*.5*3).astype(np.float32)
    labels=np.ones(z.shape,np.uint16);labels[:,6:]=2;z[:,6:]+=100
    normals,valid=display_normals(z,labels,(.2,.5))
    expected=np.array([-2,3,1])/np.sqrt(14)
    assert valid.all() and np.allclose(normals,expected,atol=1e-5)
    labels[3:6,2:5]=0;z[labels==0]=10000
    normals,valid=display_normals(z,labels,(.2,.5))
    assert np.allclose(normals[valid],expected,atol=1e-5)
    assert not valid[labels==0].any() and np.all(normals[~valid]==[0,0,1])
    connected,connected_valid=display_normals(z,(labels>0).astype(np.uint8),(.2,.5))
    assert connected_valid[:,5:7].all() and not np.allclose(connected[:,5:7],normals[:,5:7])
    isolated=np.zeros((3,3),np.uint8);isolated[1,1]=1
    _,supported=display_normals(np.zeros((3,3)),isolated,(1,1))
    assert not supported.any()


def test_capture_rejects_stale_baseline_invalid_depth_device_crop(tmp_path):
    store=Store(tmp_path);_,raw,p=capture(store)
    p['metadata']['calibration']['dirty']=True
    with pytest.raises(ValueError,match='calibration'):save_p5_sample(store,raw,raw,raw,p)
    p['metadata']['calibration']['dirty']=False;p['demo']=False;p['device']='Integrated webcam'
    with pytest.raises(ValueError,match='named GelSight'):save_p5_sample(store,raw,raw,raw,p)
    p['demo']=True;p['crop']=[.9,.1,.8,.8]
    with pytest.raises(ValueError,match='Crop'):save_p5_sample(store,raw,raw,raw,p)
    p['depth'][0][0]=float('nan')
    with pytest.raises(ValueError,match='finite'):save_p5_sample(store,raw,raw,raw,p)


def test_unfold_regions_reproducible_traceable_not_metric(tmp_path):
    store=Store(tmp_path);result,_,_=capture(store)
    items=[dict(kind='frames',id=result['frame']['id'])]
    a=build_unfolding(store,items,settings={'groups':2});b=build_unfolding(store,items,settings={'groups':2})
    assert a['regions']==b['regions'] and a['seams']==b['seams']
    assert a['synthetic'] and not a['metric_validated']
    assert len(a['regions'])>=2 and len(set(r['group'] for r in a['regions']))==2
    assert all(s['verified'] is False for s in a['seams'])
    assert all(0<c['fraction']<=1 for c in a['coverage'])
    assert a['sources'][0]['depth_present'] and a['sources'][0]['patch_id']==result['patch']['id']
    with np.load(store.path(a['directory'])/'assembly.npz') as arrays:
        assert np.array_equal(arrays['synthetic_mask'],arrays['mask'])
        assert set(np.unique(arrays['region_ids']))=={0,*[r['id'] for r in a['regions']]}
    assert len(store.list('patches'))==1 # artistic assembly must not become a measured patch
    assert hashlib.sha256((store.path(a['directory'])/'flat.png').read_bytes()).digest()==hashlib.sha256((store.path(b['directory'])/'flat.png').read_bytes()).digest()


def test_unfold_limits_and_no_depth_case(tmp_path):
    from studio.inputs import import_bytes
    store=Store(tmp_path);_,raw,_=capture(store)
    frame=import_bytes(store,'RGB-only.png',raw)['frame'];item=dict(kind='frames',id=frame['id'])
    record=build_unfolding(store,[item],settings={'groups':2})
    assert not record['sources'][0]['depth_present']
    surface=json.loads((store.path(record['directory'])/'surface.json').read_text())
    assert np.count_nonzero(surface['height'])==0
    with pytest.raises(ValueError,match='once'):build_unfolding(store,[item,item])
    with pytest.raises(ValueError,match='1–32'):build_unfolding(store,[item]*33)


def test_rgb_background_removal_has_transparency_and_does_not_double_subtract_depth(tmp_path):
    store=Store(tmp_path);_,raw,p=capture(store)
    base=np.full((240,320,3),100,np.uint8);sample=base.copy();sample[80:160,100:220]=180
    def encode(a):
        b=io.BytesIO();Image.fromarray(a).save(b,format='PNG');return b.getvalue()
    result=save_p5_sample(store,raw,raw,raw,p,'Contact',color_baseline=encode(base),model_rgb=encode(sample))
    folder=store.path(result['sample']['directory']);clean=np.asarray(Image.open(folder/'clean.png'))
    assert clean.shape==(240,320,4) and clean[0,0,3]==0 and clean[120,150,3]==255
    assert np.all(clean[120,150,:3]==180)
    assert np.allclose(np.load(folder/'depth.npy'),p['depth'])
    assert result['sample']['background']['available']
    board=build_typology(store,[dict(kind='frames',id=result['frame']['id']),dict(kind='frames',id=store.list('frames')[0]['id'])])
    assert any('clean' in e.get('views',{}) for e in board['items'])


def test_upgrade_preserves_frozen_layout_and_original_record(tmp_path):
    from studio.typology import upgrade_typology
    store=Store(tmp_path);samples=[capture(store,i)[0] for i in range(2)]
    old=build_typology(store,[dict(kind='frames',id=s['frame']['id']) for s in samples])
    before=json.dumps(store.get('typologies',old['id']),sort_keys=True)
    new=upgrade_typology(store,old['id'])
    assert new['id']!=old['id'] and new['parent_id']==old['id']
    assert new['assignment']==old['assignment'] and new['items']==old['items']
    assert before==json.dumps(store.get('typologies',old['id']),sort_keys=True)
    assert new['surface']['triangles']>0
    assert (store.path(new['directory'])/'stitched-normal-opengl.png').is_file()
