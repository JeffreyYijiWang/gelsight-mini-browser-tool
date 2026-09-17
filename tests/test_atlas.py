import numpy as np
import cv2

from studio.store import Store
from studio.inputs import synthetic_demo
from studio.atlas import build_atlas,match_pair,repetitive,optimize_graph


def test_known_crops_recover_connected_atlas_and_translations(tmp_path):
    store=Store(tmp_path);demo=synthetic_demo(store,size=40)
    atlas=build_atlas(store,demo['session']['frame_ids'])
    assert len(atlas['islands'])==1,atlas['links']
    island=atlas['islands'][0];t=island['transforms']
    origin=np.array(t['0'])[:2,2]
    for i,expected in enumerate(((0,0),(90,0),(180,30),(90,60),(0,60))):
        actual=np.array(t[str(i)])[:2,2]-origin
        assert np.linalg.norm(actual-expected)<1.,(actual,expected)
    assert island['graph_rms_after']<=island['graph_rms_before']+1e-5
    assert not island['geometry_available'] and island['patch_id'] is None


def feature(rgb):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);mask=np.ones(gray.shape,bool);sift=cv2.SIFT_create()
    keypoints,descriptors=sift.detectAndCompute(gray,None)
    return {'gray':gray,'mask':mask,'keypoints':keypoints,'descriptors':descriptors,'repetitive':repetitive(gray,mask)}


def test_unrelated_and_repetitive_pairs_rejected():
    rng=np.random.default_rng(42)
    a=rng.integers(40,230,(160,180,3),dtype=np.uint8);b=rng.integers(40,230,(160,180,3),dtype=np.uint8)
    assert not match_pair(feature(a),feature(b))['accepted']
    y,x=np.mgrid[:160,:180];gray=((x//8+y//8)%2*120+60).astype(np.uint8);rgb=np.repeat(gray[...,None],3,axis=-1)
    assert not match_pair(feature(rgb),feature(rgb.copy()))['accepted']


def test_verified_loop_constraint_reduces_controlled_drift():
    points=np.array([[10,10],[80,10],[10,80],[80,80]],float);links=[]
    for i,j,tx in ((0,1,10.5),(1,2,10.5),(2,3,10.5),(0,3,30.)):
        links.append({'a':i,'b':j,'accepted':True,'transform_b_to_a':[[1,0,tx],[0,1,0],[0,0,1]],'points_a':(points+[tx,0]).tolist(),'points_b':points.tolist()})
    island=optimize_graph(4,links)[0]
    assert island['graph_rms_after']<island['graph_rms_before']
    assert abs(island['transforms'][3][0,2]-30)<.6
