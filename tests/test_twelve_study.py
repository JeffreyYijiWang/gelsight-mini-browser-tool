import json
import numpy as np
import pytest
from PIL import Image
from studio.twelve_study import select_entries, observed_mesh, render_frame, animation_state, MODES
from studio.collection_export import build_board


def test_twelve_selection_keeps_explicit_order_and_rejects_missing_cells():
    source={'items':[dict(cell=i,id=str(i),name=f'Capture {i}') for i in reversed(range(15))]}
    selected=select_entries(source,list(range(12)))
    assert [e['id'] for e in selected]==list(map(str,range(12)))
    assert source['items'][0]['name']=='Capture 14'
    with pytest.raises(ValueError):select_entries(source,[0]*12)
    with pytest.raises(ValueError):select_entries(source,list(range(11))+[88])


def test_fixed_layout_preserves_original_height_and_masks(tmp_path):
    entries=[]
    for i in range(12):
        y,x=np.indices((12,16));z=(i+x*.1+y*.2).astype(np.float32)
        path=tmp_path/f'{i}.npy';np.save(path,z)
        pic=tmp_path/f'{i}.png';Image.new('RGB',(16,12),(i*20,120,30)).save(pic)
        entries.append(dict(id=str(i),name=str(i),rgb=str(pic),depth=str(path)))
    build_board(tmp_path/'board',entries,fixed_layout=(3,4))
    m=json.loads((tmp_path/'board/manifest.json').read_text())
    assert m['assignment']==list(range(12)) and (m['columns'],m['rows'])==(3,4)
    assert not m['solver']['executed']
    z=np.load(tmp_path/'board/observed-relative-height.npy')
    for i,e in enumerate(m['items']):
        x,y,w,h=e['destination_box']
        assert (x,y)==(4+(i%3)*20,4+(i//3)*16)
        np.testing.assert_array_equal(z[y:y+h,x:x+w],np.load(entries[i]['depth']))


def test_observed_mesh_excludes_holes_and_preserves_heights():
    y,x=np.indices((7,9));z=(x*.3+y*.6).astype(np.float32);mask=np.ones(z.shape,bool);mask[3,4]=False
    mesh=observed_mesh(z,mask,np.full((*z.shape,3),100,np.uint8))
    pixels=np.column_stack((mesh.vertices[:,0],-mesh.vertices[:,1])).astype(int)
    assert mask[pixels[:,1],pixels[:,0]].all()
    np.testing.assert_array_equal(mesh.vertices[:,2],z[pixels[:,1],pixels[:,0]])
    assert (mesh.face_normals[:,2]>0).all()


def test_declared_metric_source_is_not_relabelled_as_solver_units(tmp_path):
    z=np.arange(48,dtype=np.float32).reshape(6,8)*.001
    np.save(tmp_path/'z.npy',z);Image.new('RGB',(8,6),'gray').save(tmp_path/'rgb.png')
    entry=dict(id='source',name='source',depth=str(tmp_path/'z.npy'),rgb=str(tmp_path/'rgb.png'))
    build_board(tmp_path/'board',[entry],fixed_layout=(3,4),source_height_units='declared mm, unverified')
    m=json.loads((tmp_path/'board/manifest.json').read_text())
    assert m['construction']['source_height_units']=='declared mm, unverified'
    assert m['construction']['original_depth_file']=='observed-source-height.npy'
    original=np.load(tmp_path/'board/observed-source-height.npy')
    np.testing.assert_array_equal(original[4:10,4:12],z)


def test_animation_is_deterministic_periodic_and_does_not_modify_sources(tmp_path):
    y,x=np.indices((48,64));z=(np.sin(x/5)+np.cos(y/7)).astype(np.float32)
    mask=np.ones(z.shape,bool);mask[20:24,20:24]=False
    np.save(tmp_path/'height.npy',z);np.save(tmp_path/'mask.npy',mask)
    Image.fromarray(np.stack((x*3,y*4,x+y),-1).astype(np.uint8)).save(tmp_path/'rgb.png')
    s=animation_state(tmp_path,(64,48));before={k:v.copy() for k,v in s.items()}
    for mode in MODES:
        a=np.asarray(render_frame(s,mode,.25));b=np.asarray(render_frame(s,mode,.25))
        np.testing.assert_array_equal(a,b)
        np.testing.assert_allclose(np.asarray(render_frame(s,mode,0)),np.asarray(render_frame(s,mode,1)),atol=1)
        assert a.shape==(48,64,3)
    for k,v in before.items():np.testing.assert_array_equal(v,s[k])
    np.testing.assert_array_equal(np.load(tmp_path/'height.npy'),z)
