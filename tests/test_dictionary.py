import json
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient

from studio.store import Store
from studio.records import SurfacePatch
from studio.ink import contact_coverage,render_ink,create_impression
from studio.dictionary import create_specimen,edit_specimen,prepare_public_entry,publish_specimen,unpublish_specimen,build_dictionary
from studio.api import create_app


def test_pressure_monotonic_flat_masked_and_inverted():
    h=np.linspace(-1,1,120).reshape(10,12);mask=np.ones(h.shape,bool);mask[3:5,4:7]=False
    stack=np.array([contact_coverage(h,mask,p,.02) for p in np.linspace(0,1,15)])
    assert np.all(np.diff(stack,axis=0)>=-1e-7)
    assert not stack[:,~mask].any()
    assert stack[0].sum()==0 and stack[-1].sum()==mask.sum()
    assert np.allclose(contact_coverage(np.ones((4,5)),np.ones((4,5),bool),.3),.3)
    normal=contact_coverage(h,mask,.5,0);inverse=contact_coverage(h,mask,.5,0,True)
    assert np.array_equal((normal+inverse)[mask],np.ones(mask.sum()))
    with pytest.raises(ValueError):contact_coverage(h,np.zeros_like(mask),.5)


def test_same_seed_and_inputs_reproduce_without_modifying_geometry():
    rng=np.random.default_rng(7);h=rng.normal(size=(48,56));mask=np.ones(h.shape,bool);original=h.copy()
    settings={'seed':21,'pressure':.6,'dry_brush':.3,'spread':1,'edge_softness':.5,'paper_grain':.05}
    a,ca,_=render_ink(h,mask,settings);b,cb,_=render_ink(h,mask,settings)
    assert np.array_equal(a,b) and np.array_equal(ca,cb) and np.array_equal(h,original)
    c,_,_=render_ink(h,mask,{**settings,'seed':22});assert not np.array_equal(a,c)


def fixture(store):
    y,x=np.mgrid[:32,:40];h=-.1*np.exp(-((x-18)/2)**2)
    patch=SurfacePatch(name='private-original-name-should-not-leak',source_ids=['private-source-id'],width=40,height=32,synthetic=True,
                       settings={'sensor_serial':'PRIVATE-SENSOR-SECRET','force_notes':'PRIVATE-FORCE-NOTE'})
    store.put_patch(patch,h)
    specimen=create_specimen(store,patch.id,'Public impression',category='test surface')
    impression=create_impression(store,specimen['id'],{'output_px':256,'pressure':.6,'seed':13})
    return specimen,impression,patch


def test_draft_preview_publish_revision_unpublish_and_private_exclusion(tmp_path):
    store=Store(tmp_path);s,v,p=fixture(store);slug=s['slug']
    empty=build_dictionary(store,store.path('public-build'))
    assert empty['entries']==0
    preview=prepare_public_entry(store,s['id'],True)
    assert store.get('specimens',s['id'])['state']=='draft'
    assert 'source_id' not in preview and 'surface_data' not in preview['assets']
    published=publish_specimen(store,s['id']);first=published['public']['revision']
    output=build_dictionary(store,store.path('public-build'));root=Path(output['directory'])
    assert (root/'specimens'/slug/'index.html').is_file()
    corpus=''.join(p.read_text(errors='ignore') for p in root.rglob('*') if p.is_file() and p.suffix in ('.json','.html'))
    for secret in ('PRIVATE-SENSOR-SECRET','PRIVATE-FORCE-NOTE','private-source-id','private-original-name-should-not-leak'):
        assert secret not in corpus
    assert not list(root.rglob('height.npy')) and not list(root.rglob('print.png')) and not list(root.rglob('raw'))
    edit_specimen(store,s['id'],{'notes':'Unapproved draft story','downloads':['print_png']})
    build_dictionary(store,root)
    live=json.loads((root/'collection.json').read_text())['entries'][0]
    assert live['notes']=='' and live['downloads']=={} and live['revision']==first
    second=publish_specimen(store,s['id'])['public'];assert second['slug']==slug and second['revision']!=first
    build_dictionary(store,root);assert not (root/'assets'/first).exists()
    assert list(root.rglob('print.png'))
    unpublish_specimen(store,s['id']);build_dictionary(store,root)
    assert not (root/'specimens'/slug).exists() and not list((root/'assets').rglob('*')) if (root/'assets').exists() else True
    assert json.loads((root/'collection.json').read_text())['entries']==[]
    republished=publish_specimen(store,s['id']);assert republished['public']['slug']==slug


def test_uncalibrated_scalebar_is_rejected_and_no_implicit_location(tmp_path):
    store=Store(tmp_path);s,v,p=fixture(store)
    assert s['public_location'] is None and s['collection_timestamp'] is None and s['source_dimensions_mm'] is None
    with pytest.raises(ValueError,match='scale bar'):create_impression(store,s['id'],{'output_px':256,'scale_bar':True})


def test_owner_api_protects_private_records_and_mutations(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/state').status_code==401
        assert client.get('/').status_code==200
        assert client.get('/api/state').status_code==200
        assert client.post('/api/sessions',json={'name':'no token'}).status_code==403
        headers={'X-Studio-Token':app.state.token}
        assert client.post('/api/sessions',json={'name':'Owner session'},headers=headers).status_code==200
        assert client.post('/api/sessions',json={'name':'cross-origin'},headers={**headers,'Origin':'https://evil.example'}).status_code==403
        assert client.get('/api/state',headers={'Host':'evil.example'}).status_code==400
        assert client.get('/api/files/materials/../../raw/file').status_code in (404,422)
