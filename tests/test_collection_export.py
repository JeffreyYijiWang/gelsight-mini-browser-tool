import json
import numpy as np
from PIL import Image
import trimesh
from studio.collection_export import build_board, export_mesh, audit_fidelity


def test_streamed_solid_roundtrip(tmp_path):
    y,x=np.indices((13,19));z=(np.sin(x/3)+np.cos(y/2)).astype(np.float32)
    rgb=np.full((*z.shape,3),150,np.uint8)
    result=export_mesh(tmp_path,z,rgb,.4)
    mesh=trimesh.load(tmp_path/'relief-closed.ply',process=False)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.euler_number==2
    assert len(mesh.split())==1 and mesh.volume>0
    assert result['stl_roundtrip_exact']
    np.testing.assert_allclose(mesh.vertices[:z.size,2].reshape(z.shape),z+2-z.min(),atol=1e-6)


def test_full_resolution_board_flat_gaps_and_normals(tmp_path):
    entries=[]
    for i in range(3):
        y,x=np.indices((24,32));z=(x*.2+y*.1+i).astype(np.float32)
        mask=np.ones(z.shape,bool);mask[10:14,10:14]=False
        rgb=np.stack((x*7,y*9,np.full(z.shape,50+i*50)),axis=-1).astype(np.uint8)
        np.save(tmp_path/f'{i}.npy',z);np.save(tmp_path/f'{i}-mask.npy',mask)
        Image.fromarray(rgb).save(tmp_path/f'{i}.png')
        entries.append(dict(id=str(i),name=f'Tile {i}',rgb=str(tmp_path/f'{i}.png'),
            depth=str(tmp_path/f'{i}.npy'),mask=str(tmp_path/f'{i}-mask.npy')))
    build_board(tmp_path/'board',entries,100,4)
    record=json.loads((tmp_path/'board/manifest.json').read_text())
    z=np.load(tmp_path/'board/height.npy');source=np.array(Image.open(tmp_path/'board/source-mask.png'))>0
    original=np.load(tmp_path/'board/observed-relative-height.npy')
    assert (z[~source]==0).all() and np.isnan(original[~source]).all()
    assert len(set(record['assignment']))==3
    assert record['validation']['manifold_edges']
    n=np.load(tmp_path/'board/normals.npy');spacing=record['construction']['xy_spacing_mm']
    gy,gx=np.gradient(z,spacing,spacing);expected=np.stack((-gx,gy,np.ones_like(z)),axis=-1)
    expected/=np.linalg.norm(expected,axis=-1,keepdims=True)
    np.testing.assert_allclose(n,expected,atol=1e-6)
    for item in record['items']:
        x,y,w,h=item['destination_box'];assert (w,h)==(32,24)
        np.testing.assert_allclose(original[y+5,x+5],np.load(item['depth'])[5,5])
    encoded=np.array(Image.open(tmp_path/'board/height-16bit.png'))
    decoded=encoded/65535*(z.max()-z.min())+z.min()
    assert abs(decoded-z).max() <= (z.max()-z.min())/65535
    audit=audit_fidelity(tmp_path/'board')
    assert len(audit['sources'])==3 and not audit['physical_accuracy_validated']
    assert all(s['maximum_scaled_source_error_mm']>0 for s in audit['sources'])
