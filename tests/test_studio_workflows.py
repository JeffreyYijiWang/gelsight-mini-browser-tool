import io
import json
import time
import zipfile

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from studio.api import create_app
from studio.dictionary import create_specimen,edit_specimen,publish_specimen,export_exhibition
from studio.ink import create_impression
from studio.inputs import synthetic_demo,import_bytes
from studio.jobs import Jobs
from studio.materials import build_material
from studio.printing import project_mesh_to_patch,make_print,border_frame,validate_mesh,make_coupon,self_intersections
from studio.store import Store


def test_open_mesh_projection_then_closed_solid(tmp_path):
    store=Store(tmp_path)
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[10,0,.5],[10,8,.8],[0,8,.3]],faces=[[0,1,2],[0,2,3]],process=False)
    imported=import_bytes(store,'open.obj',mesh.export(file_type='obj').encode(),'mesh',settings={'mesh_units':'mm'})
    projected=project_mesh_to_patch(store,imported['frame']['id'],{'rotation_deg':[0,0,0],'resolution':32})
    p,a=store.patch(projected['id']);assert a['mask'].all()
    result=make_print(store,p.id,{'xy_scale':1,'z_scale':1,'tolerance_mm':.01,'base_mm':1.5,'triangle_budget':20000})
    assert result['report']['geometry_valid'],result['report']
    assert all(v['passed'] for v in result['exports']['roundtrip'].values())
    assert result['report']['dimensions_mm']==pytest.approx([10,8,2.3],abs=.001)


def test_rounded_border_is_closed_and_outside_sample():
    mesh=border_frame(30,20,2,3,2)
    report=validate_mesh(mesh,construction='boolean difference of positive-thickness exterior rounded frame',min_thickness=2)
    assert report.geometry_valid,report.errors
    assert mesh.extents==pytest.approx([36,26,2])
    assert mesh.volume<36*26*2-29*19*2


def test_paired_coupon_retains_known_depth_ratio(tmp_path):
    store=Store(tmp_path);demo=synthetic_demo(store,size=24)
    p,a=store.patch(demo['patches'][0]['id'])
    mesh,fidelity,variants=make_coupon(store,p,a,{'paired_id':demo['patches'][1]['id'],'xy_scale':2,'z_scale':3,'base_mm':2,'tolerance_mm':.06,'triangle_budget':100000,'variants':[[1,1]]})
    # Matched rows must not be independently normalized to equal ranges.
    first,second=variants[:2]
    assert second['relief_range_mm']/first['relief_range_mm']==pytest.approx(.55,abs=.0001)
    assert mesh.is_volume and fidelity['tolerance_met']


def test_baked_material_uses_meter_gltf_and_no_duplicate_normal_relief(tmp_path):
    store=Store(tmp_path);demo=synthetic_demo(store,size=24)
    m=build_material(store,demo['patches'][0]['id'])
    scene=trimesh.load(store.path(m['directory'])/'material_baked.glb',force='scene')
    assert .049<max(scene.extents)<.055
    assert all(g.visual.material.normalTexture is None for g in scene.geometry.values())
    assert (store.path(m['directory'])/'sphere-preview.png').is_file()


def test_preview_is_read_only_and_exhibition_is_allowlisted(tmp_path):
    app=create_app(tmp_path);store=app.state.store;demo=synthetic_demo(store,size=24)
    specimen=create_specimen(store,demo['patches'][0]['id'],'Exhibition study')
    original=store.path(store.get('patches',specimen['source_id'])['arrays']).read_bytes()
    with TestClient(app) as client:
        client.get('/');headers={'X-Studio-Token':app.state.token}
        a=client.post(f"/api/specimens/{specimen['id']}/ink-preview",json={'pressure':.2},headers=headers)
        b=client.post(f"/api/specimens/{specimen['id']}/ink-preview",json={'pressure':.8},headers=headers)
        assert a.status_code==b.status_code==200 and a.content!=b.content
        assert store.list('impressions')==[]
    assert original==store.path(store.get('patches',specimen['source_id'])['arrays']).read_bytes()
    create_impression(store,specimen['id'],{'output_px':256})
    empty=export_exhibition(store)
    with zipfile.ZipFile(store.path(empty['file'])) as archive:
        assert json.loads(archive.read('collection.json'))['entries']==[]
    publish_specimen(store,specimen['id'])
    bundle=export_exhibition(store,[specimen['id']])
    with zipfile.ZipFile(store.path(bundle['file'])) as archive:
        assert len(json.loads(archive.read('collection.json'))['entries'])==1
        assert not any(name.endswith('height.npy') or name.endswith('/print.png') or 'raw/' in name for name in archive.namelist())
        assert 'exhibition-manifest.json' in archive.namelist()


def test_cancel_terminates_real_worker_and_preserves_status(tmp_path):
    store=Store(tmp_path);jobs=Jobs(store)
    job=jobs.start('demo',{'size':384});process=jobs.processes[job['id']]
    result=jobs.cancel(job['id'])
    assert process.poll() is not None
    assert result['status']=='cancelled'
    time.sleep(.6)
    assert store.get('jobs',job['id'])['status']=='cancelled'
    jobs.close()


def test_intersecting_faces_sharing_a_vertex_are_not_skipped():
    mesh=trimesh.Trimesh(vertices=[[0,0,0],[2,0,0],[0,2,0],[1,1,-1],[1,1,1]],faces=[[0,1,2],[0,3,4]],process=False)
    hits,_=self_intersections(mesh)
    assert hits
    ordinary=trimesh.creation.box()
    hits,_=self_intersections(ordinary)
    assert not hits
