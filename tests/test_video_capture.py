import hashlib
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from studio.store import Store
from studio.video_capture import save_recording, extract_recording
from studio.samples import crop_box, export_capture_surface


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg not installed')
def test_ffmpeg_photos_link_depth_normals_mesh_and_share_crop(tmp_path):
    y,x=np.mgrid[:72,:96]
    rgb=np.stack((120+40*np.sin(x*.4),130+35*np.cos(y*.5),100+25*np.sin((x+y)*.2)),axis=-1).astype(np.uint8)
    Image.fromarray(rgb).save(tmp_path/'input.png')
    subprocess.run([shutil.which('ffmpeg'),'-v','error','-nostdin','-threads','2','-loop','1','-framerate','10',
        '-i',str(tmp_path/'input.png'),'-t','1','-c:v','ffv1','-threads','2',str(tmp_path/'fixture.avi')],check=True,timeout=30)
    data=(tmp_path/'fixture.avi').read_bytes();store=Store(tmp_path/'store')
    recording=save_recording(store,data,'fixture.avi','Synthetic GelSight fixture',synthetic=True)
    run=extract_recording(store,recording['id'],stride=2,max_frames=3)
    assert run['ready']==3 and run['rejected']==0 and run['frame_limit_reached']
    assert run['source_sha256']==hashlib.sha256(data).hexdigest()
    assert [i['original_frame'] for i in run['items']]==[0,2,4]
    assert np.allclose([i['timestamp_seconds'] for i in run['items']],[0,.2,.4])
    for item in run['items']:
        sample=store.get('samples',item['sample_id']);frame=store.get('frames',item['frame_id'])
        folder=store.path(sample['directory']);patch,arrays=store.patch(sample['patch_id'])
        assert sample['crop']==[.1,.1,.8,.8] and sample['crop_pixels']==list(crop_box((96,72)))
        assert np.array_equal(np.asarray(Image.open(folder/'raw.png')),rgb[7:65,10:87])
        assert arrays['height'].shape==(58,77) and np.load(folder/'depth.npy').shape==(58,77)
        assert Image.open(folder/'normal.png').size==Image.open(folder/'depth.png').size==(77,58)
        import trimesh
        mesh=trimesh.load(folder/'mesh.obj',process=False,force='mesh')
        assert np.allclose(mesh.vertices[:,2],arrays['height'][arrays['mask']])
        assert len(mesh.faces)>0 and np.all(mesh.face_normals[:,2]>0)
        assert frame['settings']['sample_id']==sample['id'] and patch.synthetic
        assert 'mesh_view' not in sample['assets'] # no fictitious live screenshot
    assert store.path(recording['raw_file']).read_bytes()==data
    second=extract_recording(store,recording['id'],stride=5,max_frames=1)
    assert second['id']!=run['id'] and store.get('video_runs',run['id'])==run
    with pytest.raises(ValueError,match='interval'):extract_recording(store,recording['id'],stride=0)
    with pytest.raises(ValueError,match='1–120'):extract_recording(store,recording['id'],max_frames=121)
    same_reference=save_recording(store,data,'no-contact.avi','Synthetic GelSight fixture',baseline=(tmp_path/'input.png').read_bytes(),synthetic=True)
    rejected=extract_recording(store,same_reference['id'],stride=5,max_frames=1)
    assert rejected['ready']==0 and rejected['rejected']==1 and rejected['items'][0]['error']
    assert 'sample_id' not in rejected['items'][0] and store.get('frames',rejected['items'][0]['frame_id'])
    bad=save_recording(store,b'not a video','bad.webm','Synthetic GelSight fixture',synthetic=True)
    with pytest.raises(ValueError,match='FFmpeg could not decode'):extract_recording(store,bad['id'])
    assert next(r for r in store.list('video_runs') if r['recording_id']==bad['id'])['status']=='failed'


def test_mesh_does_not_fill_excluded_pixels(tmp_path):
    height=np.arange(36,dtype=np.float32).reshape(6,6);mask=np.ones((6,6),bool);mask[2:4,2:4]=False
    assets=export_capture_surface(tmp_path,height,mask)
    import trimesh
    mesh=trimesh.load(tmp_path/'mesh.obj',process=False,force='mesh')
    assert len(mesh.vertices)==32 and len(mesh.faces)==32
    assert assets['geometry']['triangles']==32
    assert not (np.asarray(Image.open(tmp_path/'normal-mask.png'))[~mask]>0).any()
