"""CPU calibration entry point; not the unreleased skin-paper CNN or its weights."""
from pathlib import Path
import json
import numpy as np
from .reconstruction import polynomial_features


def train_polynomial(dataset,output,ridge=.001,seed=7,max_samples=100000):
    with np.load(dataset,allow_pickle=False) as z:
        rgb=z['rgb'];baseline=z['baseline'];normals=z['normals'];mask=z['mask'].astype(bool)
    if rgb.ndim!=4 or rgb.shape[-1]!=3 or len(rgb)<3 or normals.shape!=rgb.shape or mask.shape!=rgb.shape[:-1]:
        raise ValueError('Training needs at least 3 distinct frames: RGB N×H×W×3, normals in surface Y-up coordinates, and a matching valid mask.')
    if baseline.ndim==3:baseline=np.broadcast_to(baseline,rgb.shape)
    if baseline.shape!=rgb.shape:raise ValueError('Baseline must be H×W×3 or N×H×W×3.')
    rng=np.random.default_rng(seed);order=rng.permutation(len(rgb));heldout=order[:max(1,len(rgb)//5)];train=order[len(heldout):]
    def rows(indices):
        features=[];targets=[]
        for index in indices:
            valid=mask[index]&np.isfinite(normals[index]).all(axis=-1)&(normals[index,...,2]>.05)
            feature=polynomial_features(rgb[index],baseline[index])[valid];normal=normals[index][valid]
            if len(feature)>max_samples//len(indices):
                choose=rng.choice(len(feature),max_samples//len(indices),replace=False);feature=feature[choose];normal=normal[choose]
            features.append(feature);targets.append(normal/np.maximum(np.linalg.norm(normal,axis=-1,keepdims=True),1e-12))
        return np.concatenate(features),np.concatenate(targets)
    x,y=rows(train);tx,ty=rows(heldout)
    if len(x)<30 or len(tx)<10:raise ValueError('Too few valid training/held-out normals.')
    coefficients=np.linalg.solve(x.T@x+np.eye(x.shape[1])*ridge,x.T@y)
    predicted=tx@coefficients;predicted/=np.maximum(np.linalg.norm(predicted,axis=-1,keepdims=True),1e-12)
    errors=np.rad2deg(np.arccos(np.clip((predicted*ty).sum(axis=-1),-1,1)))
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);np.savez(output,coefficients=coefficients)
    report={'adapter':'polynomial','validated':False,'seed':seed,'train_frames':train.tolist(),'held_out_frames':heldout.tolist(),
            'training_samples':len(x),'held_out_samples':len(tx),'median_normal_error_degrees':float(np.median(errors)),
            'p95_normal_error_degrees':float(np.percentile(errors,95)),
            'next_step':'Independently validate reconstructed heights and polarity against known geometry, sensor/gel IDs, spacing and force conditions. Training error alone does not validate metric depth.'}
    output.with_suffix('.report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
