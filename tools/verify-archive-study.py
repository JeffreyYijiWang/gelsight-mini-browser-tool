"""Validate generated archive studies without modifying source or export manifests."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ.setdefault(key,'2')
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
import cv2
from studio.collection_export import digest,write_json
from studio.typology_surface import display_normals
from studio.twelve_study import MODES


def verify_gif(path,frames):
    with Image.open(path) as gif:
        assert 2<=gif.n_frames<=frames
        duration=0
        for i in range(gif.n_frames):
            gif.seek(i);duration+=gif.info['duration']
        gif.load()
        # Pillow combines repeated frames before GIF's 10 ms time quantization.
        assert frames*80<=duration<=frames*83,(path,duration)
        return dict(frames=gif.n_frames,duration_ms=duration)


def verify(root, report_path):
    manifest=json.loads((root/'manifest.json').read_text());assert manifest['complete']
    snapshot=json.loads((root/'archive.json').read_text())
    assert digest(snapshot['path'])==snapshot['sha256']
    for record in snapshot['files']:assert digest(root/'source'/record['path'])==record['sha256']
    result=dict(panels=0,captures=0,gifs=0,videos=0,video_frames=0,source_files=len(snapshot['files']),
                exact_height_copies=True,normals_match_spacing=True,hashes_verified=True,gif_timing={})
    for panel in manifest['panels']:
        folder=root/panel['key'];pm=json.loads((folder/'manifest.json').read_text())
        for path,sha in pm['files'].items():assert digest(folder/path)==sha,path
        board=json.loads((folder/'board/manifest.json').read_text())
        assert board['columns']==3 and board['rows']==4
        assert board['assignment']==panel['indices']
        assert not board['solver']['executed']
        assert board['validation']['stl_roundtrip_exact'] and board['validation']['manifold_edges']
        for cell in pm['records']:
            c=folder/'cells'/f'{cell["scan"]:02d}'
            z=np.load(c/'height.npy');np.testing.assert_array_equal(z,np.load(c/'depth_mm.npy'))
            spacing=cell['source_units']['declared_xy_mm']
            n,_=display_normals(z,np.ones(z.shape,np.int32),(spacing,spacing))
            np.testing.assert_allclose(n,np.load(c/'normals.npy'),atol=1e-7)
            assert cell['force_report']['markers_tracked']==0 and cell['force_report']['normal_force_N'] is None
            assert not cell['force_calibrated']
            for mode in MODES:
                path=c/f'{mode}.gif'
                result['gif_timing'][str(path.relative_to(root)).replace('\\','/')]=verify_gif(path,manifest['animation']['frames'])
                result['gifs']+=1
            result['captures']+=1
        for mode in MODES:
            path=folder/f'{mode}.gif'
            result['gif_timing'][str(path.relative_to(root)).replace('\\','/')]=verify_gif(path,manifest['animation']['frames'])
            result['gifs']+=1
            cap=cv2.VideoCapture(str(folder/f'{mode}.mp4'));assert cap.isOpened()
            assert abs(cap.get(cv2.CAP_PROP_FPS)-12)<.001
            count=0
            while True:
                ok,frame=cap.read()
                if not ok:break
                assert frame.shape[:2]==(1036,864);count+=1
            cap.release();assert count==manifest['animation']['frames']
            result['videos']+=1;result['video_frames']+=count
        result['panels']+=1;print(f'Validated {panel["title"]}',flush=True)
    assert result['captures']==manifest['captures']
    result['passed']=True;write_json(report_path,result);print(json.dumps({k:v for k,v in result.items() if k!='gif_timing'},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();verify(a.directory,a.report)
