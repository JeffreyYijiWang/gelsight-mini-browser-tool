"""Image-only planar tactile mosaics with verified links and explicit islands."""
from __future__ import annotations

import json

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.optimize import least_squares

from .inputs import image_array, quality
from .records import Atlas, SurfacePatch
from .surface import check, normals_from_height


def texture_image(rgb):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(float)
    detail=gray-cv2.GaussianBlur(gray,(0,0),9)
    return np.rint(np.clip(detail+128,0,255)).astype(np.uint8)


def repetitive(gray,mask):
    """High off-center autocorrelation peaks flag ambiguous periodic textures."""
    h,w=gray.shape
    small=cv2.resize(gray,(min(w,128),min(h,128))).astype(float)
    m=cv2.resize(mask.astype(np.uint8),(small.shape[1],small.shape[0]),interpolation=cv2.INTER_NEAREST)>0
    if m.sum()<20 or np.std(small[m])<2: return True
    small=np.where(m,small-np.mean(small[m]),0)
    power=abs(np.fft.fft2(small))**2
    corr=np.fft.ifft2(power).real;corr/=max(corr[0,0],1e-12)
    y,x=np.indices(corr.shape)
    distance=np.minimum(x,corr.shape[1]-x)**2+np.minimum(y,corr.shape[0]-y)**2
    values=corr[(distance>8**2)&(distance<min(corr.shape)**2/9)]
    return bool(values.max(initial=0)>.78)


def rigid_fit(source,target):
    src=source-source.mean(axis=0);dst=target-target.mean(axis=0)
    u,_,vh=np.linalg.svd(src.T@dst);rotation=vh.T@u.T
    if np.linalg.det(rotation)<0:vh[-1]*=-1;rotation=vh.T@u.T
    translation=target.mean(axis=0)-source.mean(axis=0)@rotation.T
    return np.column_stack((rotation,translation))


def match_pair(a,b,settings=None,manual=None):
    """Return the affine transform from b to a, plus geometric evidence."""
    settings=settings or {}
    if manual:
        pa=np.asarray(manual["points_a"],np.float32);pb=np.asarray(manual["points_b"],np.float32)
        if pa.shape!=pb.shape or pa.ndim!=2 or pa.shape[1]!=2 or len(pa)<3:raise ValueError("Manual correction needs at least three matching 2D point pairs.")
        matrix=rigid_fit(pb,pa);good=np.ones(len(pa),bool)
    else:
        if a["repetitive"] or b["repetitive"]:return {"accepted":False,"reason":"uniform or repetitive texture; ambiguous correspondence"}
        if a["descriptors"] is None or b["descriptors"] is None:return {"accepted":False,"reason":"insufficient object features"}
        matcher=cv2.BFMatcher(cv2.NORM_L2)
        forward=matcher.knnMatch(b["descriptors"],a["descriptors"],k=2)
        backward=matcher.knnMatch(a["descriptors"],b["descriptors"],k=2)
        reverse={m.queryIdx:m.trainIdx for pair in backward if len(pair)==2 for m,n in [pair] if m.distance<.68*n.distance}
        matches=[m for pair in forward if len(pair)==2 for m,n in [pair] if m.distance<.68*n.distance and reverse.get(m.trainIdx)==m.queryIdx]
        if len(matches)<10:return {"accepted":False,"reason":"fewer than 10 mutually distinctive matches"}
        pa=np.array([a["keypoints"][m.trainIdx].pt for m in matches],np.float32)
        pb=np.array([b["keypoints"][m.queryIdx].pt for m in matches],np.float32)
        estimator=cv2.estimateAffine2D if settings.get("bounded_affine") else cv2.estimateAffinePartial2D
        matrix,inliers=estimator(pb,pa,method=cv2.RANSAC,ransacReprojThreshold=2.,maxIters=3000,confidence=.995)
        if matrix is None:return {"accepted":False,"reason":"robust transform estimation failed"}
        good=inliers.ravel()>0
    if good.sum()<3 or (not manual and (good.sum()<10 or good.mean()<.5)):
        return {"accepted":False,"reason":"insufficient geometrically consistent matches"}
    singular=np.linalg.svd(matrix[:,:2],compute_uv=False)
    bound=.06 if settings.get("bounded_affine") else .025
    if np.max(abs(singular-1))>bound or np.linalg.det(matrix[:,:2])<=0:
        return {"accepted":False,"reason":"scale/shear exceeds bounded contact deformation"}
    if not settings.get("bounded_affine"):matrix=rigid_fit(pb[good],pa[good])
    residual=np.linalg.norm(pb[good]@matrix[:,:2].T+matrix[:,2]-pa[good],axis=1)
    coverage=min(cv2.contourArea(cv2.convexHull(pa[good]))/max(a["mask"].sum(),1),cv2.contourArea(cv2.convexHull(pb[good]))/max(b["mask"].sum(),1))
    warp=cv2.warpAffine(b["mask"].astype(np.uint8),matrix,(a["mask"].shape[1],a["mask"].shape[0]),flags=cv2.INTER_NEAREST)>0
    overlap=(warp&a["mask"]).sum()/max(min(a["mask"].sum(),b["mask"].sum()),1)
    if residual.max()>4 or np.median(residual)>1.5 or coverage<.04 or overlap<.12:
        return {"accepted":False,"reason":"poor residual, spatial coverage or overlap","overlap":float(overlap),"coverage":float(coverage),"median_residual_px":float(np.median(residual))}
    duplicate=bool(np.linalg.norm(matrix[:,2])<2.5 and abs(np.arctan2(matrix[1,0],matrix[0,0]))<.01 and overlap>.94)
    return {"accepted":True,"manual":bool(manual),"transform_b_to_a":np.vstack((matrix,[0,0,1])).tolist(),
            "overlap":float(overlap),"coverage":float(coverage),"median_residual_px":float(np.median(residual)),
            "inliers":int(good.sum()),"duplicate":duplicate,"points_a":pa[good][::max(1,int(good.sum())//60)].tolist(),
            "points_b":pb[good][::max(1,int(good.sum())//60)].tolist()}


def optimize_graph(count,links):
    adjacency=[[] for _ in range(count)]
    for link in links:
        if not link["accepted"]:continue
        i,j=link["a"],link["b"];t=np.array(link["transform_b_to_a"])
        adjacency[i].append((j,t));adjacency[j].append((i,np.linalg.inv(t)))
    unseen=set(range(count));islands=[]
    while unseen:
        root=min(unseen);unseen.remove(root);poses={root:np.eye(3)};queue=[root]
        for i in queue:
            for j,t in adjacency[i]:
                if j in unseen:poses[j]=poses[i]@t;unseen.remove(j);queue.append(j)
        nodes=sorted(poses);free=[i for i in nodes if i!=root];index={n:k for k,n in enumerate(free)}
        edges=[l for l in links if l["accepted"] and l["a"] in nodes and l["b"] in nodes]
        def transformed(params):
            result={root:poses[root]}
            for i in free:
                tx,ty,theta=params[index[i]*3:index[i]*3+3]
                c,s=np.cos(theta),np.sin(theta);correction=np.array([[c,-s,tx],[s,c,ty],[0,0,1.]])
                result[i]=correction@poses[i]
            return result
        def residual(params):
            current=transformed(params);values=[]
            for edge in edges:
                i,j=edge["a"],edge["b"];a=np.array(edge["points_a"]);b=np.array(edge["points_b"])
                va=a@current[i][:2,:2].T+current[i][:2,2];vb=b@current[j][:2,:2].T+current[j][:2,2]
                values.extend(((va-vb)/np.sqrt(len(a))).ravel())
            return np.asarray(values)
        before=float(np.sqrt(np.mean(residual(np.zeros(len(free)*3))**2))) if edges else 0.
        if free and edges:
            solution=least_squares(residual,np.zeros(len(free)*3),loss="huber",f_scale=1.,max_nfev=100)
            solved=transformed(solution.x);after=float(np.sqrt(np.mean(residual(solution.x)**2)))
        else:solved=poses;after=before
        islands.append({"nodes":nodes,"transforms":solved,"graph_rms_before":before,"graph_rms_after":after})
    return islands


def _fuse(store,atlas,group,frames,settings,island_index,progress):
    nodes=group["nodes"];transforms=group["transforms"]
    corners=[]
    for i in nodes:
        h,w=frames[i]["mask"].shape
        pts=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
        corners.append(pts@transforms[i][:2,:2].T+transforms[i][:2,2])
    all_corners=np.concatenate(corners);low=np.floor(all_corners.min(axis=0));high=np.ceil(all_corners.max(axis=0))
    width,height=(high-low+1).astype(int)
    if width*height>4_000_000 or width>5000 or height>5000:raise ValueError("Atlas exceeds the 4-million-pixel budget. Exclude drifted frames or form smaller islands.")
    translate=np.array([[1.,0,-low[0]],[0,1,-low[1]],[0,0,1.]])
    transformed={i:translate@transforms[i] for i in nodes}
    coverage=np.zeros((height,width),np.uint16);weights=np.zeros((height,width));sums=np.zeros((height,width,3))
    strongest=np.zeros_like(weights);source=np.full((height,width),-1,np.int16);warped=[]
    for i in nodes:
        f=frames[i];t=transformed[i]
        m=cv2.warpAffine(f["mask"].astype(np.uint8),t[:2],(width,height),flags=cv2.INTER_NEAREST)>0
        distance=ndimage.distance_transform_edt(f["mask"])
        weight=cv2.warpAffine((np.minimum(distance/15,1)*max(.05,f["quality"]["quality_score"])).astype(np.float32),t[:2],(width,height))*m
        image=cv2.warpAffine(f["rgb"],t[:2],(width,height)).astype(float)
        coverage+=m.astype(np.uint16);sums+=image*weight[...,None];weights+=weight
        better=weight>strongest;source[better]=i;strongest[better]=weight[better]
        item={"i":i,"rgb":image,"mask":m,"weight":weight}
        if f.get("height") is not None:
            item["height"]=cv2.warpAffine(f["height"],t[:2],(width,height)).astype(float)
        warped.append(item)
    rigid=sums/np.maximum(weights[...,None],1e-12);valid=weights>0
    directory=store.path(f"atlases/{atlas.id}/island-{island_index}");directory.mkdir(parents=True)
    Image.fromarray(np.clip(rigid,0,255).astype(np.uint8)).save(directory/"rigid.png")
    deformation=np.zeros((height,width),np.float32);invented=np.zeros((height,width),bool)
    if settings.get("artistic_refine") and len(warped)>1:
        target=cv2.cvtColor(rigid.astype(np.uint8),cv2.COLOR_RGB2GRAY)
        sums[:]=0;weights[:]=0
        yy,xx=np.indices(valid.shape,dtype=np.float32)
        max_warp=float(np.clip(settings.get("max_warp_px",1.5),.1,3))
        for item in warped:
            gray=cv2.cvtColor(item["rgb"].astype(np.uint8),cv2.COLOR_RGB2GRAY)
            flow=cv2.calcOpticalFlowFarneback(target,gray,None,.5,2,25,3,5,1.2,0)
            flow=np.clip(cv2.GaussianBlur(flow,(0,0),5),-max_warp,max_warp)
            allow=ndimage.binary_erosion(item["mask"]&(coverage>1),iterations=8)
            flow*=allow[...,None]
            magnitude=np.linalg.norm(flow,axis=-1)
            gxx=np.gradient(flow[...,0],axis=1);gyy=np.gradient(flow[...,1],axis=0)
            jac=(1+gxx)*(1+gyy)-np.gradient(flow[...,0],axis=0)*np.gradient(flow[...,1],axis=1)
            flow[(jac<.85)|(jac>1.15)]=0
            image=cv2.remap(item["rgb"].astype(np.float32),xx+flow[...,0],yy+flow[...,1],cv2.INTER_LINEAR)
            if "height" in item:item["height"]=cv2.remap(item["height"].astype(np.float32),xx+flow[...,0],yy+flow[...,1],cv2.INTER_LINEAR)
            sums+=image*item["weight"][...,None];weights+=item["weight"]
            deformation=np.maximum(deformation,np.linalg.norm(flow,axis=-1));invented|=np.linalg.norm(flow,axis=-1)>.01
        fused=sums/np.maximum(weights[...,None],1e-12)
    else:fused=rigid
    geometry=all("height" in item for item in warped)
    patch_id=None;height_offsets={}
    if geometry:
        # Solve all overlap offsets together; first source is anchored at zero.
        rows=[];rhs=[]
        for ia,a in enumerate(warped):
            for ib in range(ia+1,len(warped)):
                b=warped[ib];overlap=a["mask"]&b["mask"]
                if overlap.sum()<20:continue
                row=np.zeros(len(warped));row[ia]=1;row[ib]=-1
                rows.append(row);rhs.append(float(np.median(b["height"][overlap]-a["height"][overlap])))
        anchor=np.zeros(len(warped));anchor[0]=1;rows.append(anchor);rhs.append(0.)
        offsets=np.linalg.lstsq(np.array(rows),np.array(rhs),rcond=None)[0]
        hs=np.zeros_like(weights)
        for i,item in enumerate(warped):hs+=(item["height"]+offsets[i])*item["weight"];height_offsets[str(item["i"])]=float(offsets[i])
        fused_height=hs/np.maximum(weights,1e-12)
        metric=all(frames[i].get("metric",False) for i in nodes) and not settings.get("artistic_refine") and not settings.get("bounded_affine")
        spacings=[frames[i].get("spacing") for i in nodes]
        metric &= all(s is not None and np.allclose(s,spacings[0]) for s in spacings)
        patch=SurfacePatch(name=atlas.name+f" • island {island_index+1}",source_ids=[frames[i]["id"] for i in nodes],width=width,height=height,
                           state="calibrated" if metric else "uncalibrated",units="mm" if metric else "relative",pixel_spacing=spacings[0] if metric else None,
                           validation_notes="Rigid fusion of compatible metric source patches; measure original patches only." if metric else "",
                           synthetic=all(frames[i].get("synthetic",False) for i in nodes),version="atlas",quality={"measurement_allowed":False},
                           height_reference="global overlap offsets, first source offset=0",settings=settings,
                           provenance=[{"operation":"planar relief fusion","atlas_id":atlas.id,"offsets":height_offsets,"synthetic_warp":bool(settings.get("artistic_refine"))}])
        store.put_patch(patch,fused_height,valid,invented,rgb=np.clip(fused,0,255).astype(np.uint8));patch_id=patch.id
    seam=np.zeros_like(valid);seam[:,1:]|=source[:,1:]!=source[:,:-1];seam[1:]|=source[1:]!=source[:-1]
    for name,array in (("appearance.png",np.clip(fused,0,255).astype(np.uint8)),("coverage.png",coverage),
                       ("seams.png",(seam&valid).astype(np.uint8)*255),("valid_mask.png",valid.astype(np.uint8)*255),
                       ("quality.png",np.rint(np.clip(strongest,0,1)*255).astype(np.uint8)),("distortion.png",np.rint(np.clip(deformation/3,0,1)*255).astype(np.uint8))):
        Image.fromarray(array).save(directory/name)
    np.save(directory/"source_frame_index.npy",source);np.save(directory/"distortion_px.npy",deformation)
    footprint={str(i):(corners[n]-low).tolist() for n,i in enumerate(nodes)}
    record={"index":island_index,"frame_indices":nodes,"frame_ids":[frames[i]["id"] for i in nodes],"width":int(width),"height":int(height),
            "directory":directory.relative_to(store.root).as_posix(),"transforms":{str(i):transformed[i].tolist() for i in nodes},
            "footprints":footprint,"patch_id":patch_id,"geometry_available":geometry,"height_offsets":height_offsets,
            "manual":any(l.get("manual") for l in atlas.links if l["a"] in nodes and l["b"] in nodes),
            "graph_rms_before":group["graph_rms_before"],"graph_rms_after":group["graph_rms_after"]}
    (directory/"island.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
    return record


def build_atlas(store,frame_ids,settings=None,progress=None):
    settings=settings or {}
    frame_ids=[i for i in dict.fromkeys(frame_ids) if i not in settings.get("exclude",[])]
    if not 2<=len(frame_ids)<=60:raise ValueError("Atlas needs 2–60 ordered overlapping frames; a single frame is a local patch.")
    cv2.setRNGSeed(7)
    frames=[];rejected=[]
    patches=store.list("patches")
    for index,frame_id in enumerate(frame_ids):
        frame=store.get("frames",frame_id)
        if frame["kind"]!="rgb":raise ValueError("Select tactile RGB frames for image-only registration.")
        rgb=image_array(store.path(frame["raw_file"]).read_bytes());baseline=None
        session=store.get("sessions",frame["session_id"])
        if session.get("baseline_id"):
            b=store.get("frames",session["baseline_id"]);baseline=image_array(store.path(b["raw_file"]).read_bytes())
        scale=min(1.,512/max(rgb.shape[:2]));size=(round(rgb.shape[1]*scale),round(rgb.shape[0]*scale))
        rgb=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA)
        if baseline is not None:baseline=cv2.resize(baseline,size,interpolation=cv2.INTER_AREA)
        mask,q=quality(rgb,baseline,marker_high=int(settings.get("marker_high",45)),border=int(settings.get("border",4)))
        if q["rejected"]:rejected.append({"id":frame_id,"reason":"poor contact or sharpness"});continue
        gray=texture_image(rgb);sift=cv2.SIFT_create(nfeatures=2000,contrastThreshold=.02)
        keypoints,descriptors=sift.detectAndCompute(gray,mask.astype(np.uint8)*255)
        f={"id":frame_id,"rgb":rgb,"gray":gray,"mask":mask,"quality":q,"keypoints":keypoints,"descriptors":descriptors,
           "repetitive":repetitive(gray,mask),"synthetic":session.get("synthetic",False)}
        linked=[p for p in patches if frame_id in p["source_ids"] and p["version"]=="original"]
        if linked:
            p,a=store.patch(linked[-1]["id"])
            f["height"]=cv2.resize(a["height"],size,interpolation=cv2.INTER_LINEAR)
            f["mask"] &= cv2.resize(a["mask"].astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
            f["metric"]=p.state=="calibrated"
            f["spacing"]=[p.pixel_spacing[0]*(p.width-1)/max(size[0]-1,1),p.pixel_spacing[1]*(p.height-1)/max(size[1]-1,1)] if p.pixel_spacing else None
        frames.append(f);check(progress,.1*(index+1)/len(frame_ids),"Selecting masked object features")
    if not frames:raise ValueError("All frames were rejected. Inspect contact masks, baseline and focus.")
    links=[];manuals=settings.get("manual_links",[])
    pairs=[(i,j) for i in range(len(frames)) for j in range(i+1,len(frames)) if j-i<=4 or settings.get("loop_closure",True)]
    for at,(i,j) in enumerate(pairs):
        manual=next((m for m in manuals if m["a"]==frames[i]["id"] and m["b"]==frames[j]["id"]),None)
        result=match_pair(frames[i],frames[j],settings,manual)
        result.update(a=i,b=j,frame_a=frames[i]["id"],frame_b=frames[j]["id"],loop_closure=j-i>1)
        if result.get("duplicate"):
            result.update(accepted=False,reason="duplicate observation; no useful motion")
            if j==i+1:rejected.append({"id":frames[j]["id"],"reason":"duplicate adjacent frame"})
        links.append(result)
        check(progress,.1+.5*(at+1)/max(1,len(pairs)),f"Verifying frame links {at+1}/{len(pairs)}")
    duplicate_ids={r['id'] for r in rejected if r['reason']=='duplicate adjacent frame'}
    excluded={i for i,f in enumerate(frames) if f['id'] in duplicate_ids}
    for link in links:
        if link['a'] in excluded or link['b'] in excluded:
            link.update(accepted=False,reason='duplicate adjacent frame excluded from fusion')
    groups=[g for g in optimize_graph(len(frames),links) if any(n not in excluded for n in g['nodes'])]
    atlas=Atlas(name=settings.get("name","Planar tactile atlas"),source_ids=[f["id"] for f in frames if f['id'] not in duplicate_ids],islands=[],links=links,rejected_frames=rejected,settings=settings)
    for i,group in enumerate(groups):
        check(progress,.65+.3*i/len(groups),f"Fusing independent island {i+1}/{len(groups)}")
        atlas.islands.append(_fuse(store,atlas,group,frames,settings,i,progress))
    atlas.mode="planar relief + appearance atlas" if any(i["geometry_available"] for i in atlas.islands) else "planar appearance atlas (no inferred height)"
    directory=store.path(f"atlases/{atlas.id}");directory.mkdir(exist_ok=True)
    (directory/"atlas.json").write_text(json.dumps(atlas.model_dump(mode="json"),indent=2),encoding="utf-8")
    return store.save("atlases",atlas)
