import hashlib
import io
import json
import zipfile

import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from studio.api import create_app
from studio.camera import save_capture
from studio.dictionary import build_dictionary
from studio.inputs import import_bytes
from studio.jobs import dispatch
from studio.records import CaptureSession
from studio.store import Store
from studio.typology import build_typology, catalog, descriptor, project_features


def png(index=0):
    y,x=np.mgrid[:64,:64]
    gray=((np.sin((x if index%2 else y)*(index+1)*.12)+1)*100+20).astype(np.uint8)
    rgb=np.stack([gray,np.roll(gray,index+1,axis=0),gray],axis=-1)
    out=io.BytesIO();Image.fromarray(rgb).save(out,format='PNG');return out.getvalue()


def fixtures(store, count=7):
    session=CaptureSession(name='Synthetic typology fixtures',synthetic=True)
    store.save('sessions',session)
    return [import_bytes(store,f'fixture-{i}.png',png(i),'rgb',session.id)['frame'] for i in range(count)]


def test_real_shufflesnap_unique_reproducible_assignments_and_unchanged_sources(tmp_path):
    store=Store(tmp_path);frames=fixtures(store)
    hashes={frame['raw_file']:hashlib.sha256(store.path(frame['raw_file']).read_bytes()).hexdigest() for frame in frames}
    items=[dict(kind='frames',id=frame['id']) for frame in frames]
    a=build_typology(store,items,'Test board',dict(columns=3))
    b=build_typology(store,items,'Repeat',dict(columns=3))
    assert a['assignment']==b['assignment']
    assert sorted(a['assignment'])==sorted(set(a['assignment'])) and len(a['assignment'])==7
    assert max(a['assignment'])<9 and a['width']==3 and a['height']==3
    assert a['settings']['solver']=='shufflesnap' and a['settings']['solver_version']=='0.3.0'
    for item in a['items']:
        assert item['row']*a['width']+item['column']==item['cell']
    assert all(hashlib.sha256(store.path(path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
    assert Image.open(store.path(a['directory'])/'contact-sheet.png').width>0
    assert json.loads((store.path(a['directory'])/'typology.json').read_text())['assignment']==a['assignment']


def test_identical_and_two_image_projection_has_no_nan():
    picture=Image.open(io.BytesIO(png()))
    feature=descriptor(picture,'texture')
    points,fraction=project_features([feature,feature])
    assert np.isfinite(points).all() and np.allclose(points,.5) and fraction==0
    other=descriptor(Image.open(io.BytesIO(png(3))),'texture')
    points,fraction=project_features([feature,other])
    assert np.isfinite(points).all() and np.min(points)>=0 and np.max(points)<=1 and fraction>.99


def test_selected_board_export_stays_private_and_omits_unselected(tmp_path):
    store=Store(tmp_path);frames=fixtures(store,3)
    items=[dict(kind='frames',id=frame['id']) for frame in frames[:2]]
    board=build_typology(store,items,'<script>alert(1)</script>')
    archive=dispatch(store,'typology_export',{'id':board['id']})
    with zipfile.ZipFile(store.path(archive['file'])) as bundle:
        assert 'index.html' in bundle.namelist() and 'contact-sheet.png' in bundle.namelist()
        assert len([name for name in bundle.namelist() if name.endswith('.webp')])==2
        assert frames[-1]['id'] not in bundle.read('typology.json').decode()
        assert '<script>alert(1)</script>' not in bundle.read('index.html').decode()
        assert not any(name.startswith('raw/') for name in bundle.namelist())
    result=build_dictionary(store,store.path('public-check'))
    assert result['entries']==0 and not list(store.path('public-check').rglob('image-*.webp'))


def test_browser_capture_sessions_baseline_and_sensor_gating(tmp_path):
    store=Store(tmp_path)
    device=dict(name='GelSight Mini mock fixture',id='test-device')
    baseline=save_capture(store,png(),device,baseline=True)
    sample=save_capture(store,png(1),device,name='Fabric',session_id=baseline['session']['id'])
    session=store.get('sessions',sample['session']['id'])
    assert session['baseline_id']==baseline['frame']['id'] and len(session['frame_ids'])==2
    assert sample['frame']['settings']['capture_role']=='sample'
    items=catalog(store)
    assert next(i for i in items if i['id']==baseline['frame']['id'])['baseline'] is True
    assert next(i for i in items if i['id']==sample['frame']['id'])['baseline'] is False
    with pytest.raises(ValueError,match='named GelSight'):
        save_capture(store,png(),dict(name='Integrated Webcam'))
    with pytest.raises(ValueError,match='session'):
        save_capture(store,png(),dict(name='GelSight other'),session_id=session['id'])
    assert not store.list('patches') and not store.list('specimens')


def test_typology_input_limits_and_missing_records(tmp_path):
    store=Store(tmp_path);frames=fixtures(store,2)
    item=dict(kind='frames',id=frames[0]['id'])
    with pytest.raises(ValueError,match='between 2'):
        build_typology(store,[item])
    with pytest.raises(ValueError,match='only once'):
        build_typology(store,[item,item])
    with pytest.raises(ValueError,match='available'):
        build_typology(store,[item,dict(kind='frames',id='missing')])
    with pytest.raises(ValueError,match='columns'):
        build_typology(store,[item,dict(kind='frames',id=frames[1]['id'])],settings={'columns':1000})


def test_private_typology_api_and_browser_capture(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/typology/items').status_code==401
        assert client.get('/api/camera/status').status_code==401
        assert client.post('/api/camera/browser-capture').status_code in (401,403)
        client.get('/')
        headers={'X-Studio-Token':app.state.token}
        data={'device_name':'GelSight Mini API fixture','name':'Test sample'}
        result=client.post('/api/camera/browser-capture',headers=headers,data=data,files={'file':('frame.png',png(),'image/png')})
        assert result.status_code==200
        frame=result.json()['frame']
        assert client.get('/api/typology/thumbnail/frames/'+frame['id']).status_code==200
        assert client.get('/api/typology/thumbnail/raw/'+frame['id']).status_code==422
        assert len(client.get('/api/typology/items').json())==1
