"""Real relief solids, source fidelity, topology checks, and STL/3MF round trips."""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import Delaunay, cKDTree
import trimesh

from .records import MeshValidationReport, PrintProject, PrinterProfile, SurfacePatch
from .surface import check, fill_nearest

MAX_TRIANGLES = 400_000


def load_mesh(path, units=None):
    path=Path(path)
    if path.suffix.lower()==".stl" and units is None:
        raise ValueError("STL has no reliable unit declaration. Assign mm, cm, m or inch explicitly.")
    scene=trimesh.load(path,force="scene",process=False)
    if not scene.geometry: raise ValueError("Mesh file contains no supported triangle geometry.")
    mesh=scene.to_mesh()  # Applies each scene instance's transform.
    if not isinstance(mesh,trimesh.Trimesh) or len(mesh.faces)==0:
        raise ValueError("Expected a triangle mesh; point clouds need surface reconstruction first.")
    if len(mesh.faces)>MAX_TRIANGLES:
        raise ValueError(f"Mesh exceeds the {MAX_TRIANGLES:,}-triangle import budget. Decimate with a documented tolerance before import.")
    if not np.isfinite(mesh.vertices).all(): raise ValueError("Mesh contains non-finite coordinates.")
    inferred=scene.units or mesh.units
    if units is None and path.suffix.lower()==".glb": units="m"
    units=units or inferred
    factor={"mm":1.,"millimeter":1.,"millimeters":1.,"cm":10.,"m":1000.,"meter":1000.,"meters":1000.,"inch":25.4,"inches":25.4}.get(units)
    if factor is None: raise ValueError("Mesh units are unknown. Assign mm, cm, m or inch explicitly.")
    original=mesh.bounds.tolist()
    mesh.apply_scale(factor)
    # Welding coincident serialized STL vertices is lossless to 8 decimal mm places.
    mesh.merge_vertices(digits_vertex=8)
    mesh.remove_unreferenced_vertices()
    return mesh,{"source_units":units,"unit_factor_to_mm":factor,"source_bounds":original,
                 "dimensions_mm":mesh.extents.tolist(),"triangles":len(mesh.faces),"vertices":len(mesh.vertices),
                 "scene_transforms_applied":True,"watertight":bool(mesh.is_watertight),"winding_consistent":bool(mesh.is_winding_consistent),
                 "estimated_mean_edge_mm":float(np.mean(mesh.edges_unique_length))}


def sample_field(height,xy):
    return ndimage.map_coordinates(height,[xy[:,1],xy[:,0]],order=1,mode="nearest")


def triangle_samples(xy,faces,z):
    # Include vertices, edge midpoints, centroid, and off-center interior samples.
    weights=np.array([[1,0,0],[0,1,0],[0,0,1],[.5,.5,0],[0,.5,.5],[.5,0,.5],
                      [1/3,1/3,1/3],[.6,.2,.2],[.2,.6,.2],[.2,.2,.6]])
    points=np.einsum('sk,fkj->fsj',weights,xy[faces]).reshape(-1,2)
    values=np.einsum('sk,fk->fs',weights,z[faces]).reshape(-1)
    return points,values


def adaptive_top(height, mask, tolerance, budget, shape="rectangle", progress=None):
    h,w=height.shape
    if min(h,w)<2: raise ValueError("Height needs at least two samples per side.")
    if height.size>500_000: raise ValueError("Print source budget is 500,000 height samples; crop or resample explicitly.")
    if not mask.all():
        # Keep the native grid around holes; do not bridge invalid data with Delaunay.
        y,x=np.indices(height.shape)
        xy=np.column_stack((x.ravel(),y.ravel())).astype(float)
        ids=np.arange(h*w).reshape(h,w);a=ids[:-1,:-1].ravel();b=a+1;c=a+w;d=c+1
        faces=np.vstack((np.column_stack((a,b,c)),np.column_stack((b,d,c))))
        good=mask.ravel()[faces].all(axis=1)
        if shape=="circle":
            ellipse=((xy[:,0]/(w-1)-.5)*2)**2+((xy[:,1]/(h-1)-.5)*2)**2<=1
            good &= ellipse[faces].all(axis=1)
        faces=faces[good]
        if len(faces)*2+4*(h+w)>budget: raise ValueError("Triangle budget cannot preserve masked boundaries at source resolution. Increase budget or crop.")
        if not len(faces): raise ValueError("No valid connected triangles remain after masking.")
        points,values=triangle_samples(xy,faces,height.ravel())
        errors=abs(sample_field(height,points)-values)
    else:
        y,x=np.meshgrid(np.linspace(0,h-1,min(h,10)),np.linspace(0,w-1,min(w,10)),indexing="ij")
        xy=np.column_stack((x.ravel(),y.ravel()))
        if shape=="circle":
            xy=xy[(((xy[:,0]/(w-1)-.5)*2)**2+((xy[:,1]/(h-1)-.5)*2)**2)<.98]
            angle=np.linspace(0,2*np.pi,129)[:-1]
            xy=np.vstack((xy,np.column_stack(((1+np.cos(angle))*(w-1)/2,(1+np.sin(angle))*(h-1)/2))))
        yy,xx=np.indices(height.shape)
        all_points=np.column_stack((xx.ravel(),yy.ravel())).astype(float)
        max_top=max(8,(budget-8*(h+w))//2)
        for iteration in range(16):
            tri=Delaunay(xy)
            faces=tri.simplices
            z=sample_field(height,xy)
            points,values=triangle_samples(xy,faces,z)
            errors=abs(sample_field(height,points)-values)
            # Also test every observed source sample, so narrow valleys cannot be skipped.
            simplex=tri.find_simplex(all_points)
            chosen=all_points[simplex>=0];s=simplex[simplex>=0]
            bary=np.einsum('ijk,ik->ij',tri.transform[s,:2,:],chosen-tri.transform[s,2,:])
            bary=np.column_stack((bary,1-bary.sum(axis=1)))
            predicted=(z[faces[s]]*bary).sum(axis=1)
            observed_error=abs(sample_field(height,chosen)-predicted)
            both=np.r_[errors,observed_error]
            if both.max(initial=0)<=tolerance or len(faces)>=max_top:
                errors=both;break
            candidates=np.vstack((points,chosen))
            bad=np.flatnonzero(both>tolerance)
            keep=min(len(bad),max(20,len(xy)//2),max(0,(max_top-len(faces))//2))
            if keep==0: errors=both;break
            new=candidates[bad[np.argsort(both[bad])[-keep:]]]
            xy=np.unique(np.round(np.vstack((xy,new)),8),axis=0)
            check(progress,.15+.45*(iteration/16),f"Refining relief: {len(faces):,} top triangles")
        else:
            tri=Delaunay(xy);faces=tri.simplices
            points,values=triangle_samples(xy,faces,sample_field(height,xy))
            errors=abs(sample_field(height,points)-values)
            simplex=tri.find_simplex(all_points);chosen=all_points[simplex>=0];s=simplex[simplex>=0]
            bary=np.einsum('ijk,ik->ij',tri.transform[s,:2,:],chosen-tri.transform[s,2,:]);bary=np.column_stack((bary,1-bary.sum(axis=1)))
            errors=np.r_[errors,abs(sample_field(height,chosen)-(sample_field(height,xy)[faces[s]]*bary).sum(axis=1))]
    used=np.unique(faces);lookup=np.full(len(xy),-1,int);lookup[used]=np.arange(len(used))
    return xy[used],lookup[faces],{"max_error_mm":float(errors.max(initial=0)),"p95_error_mm":float(np.percentile(errors,95)) if len(errors) else 0.,
                                 "p99_error_mm":float(np.percentile(errors,99)) if len(errors) else 0.,"samples":len(errors),
                                 "tolerance_mm":tolerance,"tolerance_met":bool(errors.max(initial=0)<=tolerance),
                                 "reference":"bilinear interpolation of appropriately scaled original samples; processing fidelity, not sensor accuracy",
                                 "interior_samples_per_triangle":7}


def solid_from_top(xy,faces,z,base=0.):
    """XY are already world coordinates with Y up; faces are outward top winding."""
    vertices=np.column_stack((xy,z))
    n=len(vertices)
    vertices=np.vstack((vertices,np.column_stack((xy,np.full(n,base)))))
    edges=np.vstack((faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]))
    _,inverse,counts=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    boundary=edges[counts[inverse]==1]
    walls=[]
    for a,b in boundary: walls.extend(((b,a,a+n),(b,a+n,b+n)))
    all_faces=np.vstack((faces,faces[:,[0,2,1]]+n,np.asarray(walls)))
    return trimesh.Trimesh(vertices=vertices,faces=all_faces,process=False)


def relief_mesh(height,mask,width_mm,height_mm,base_mm,tolerance=.02,budget=120_000,shape="rectangle",progress=None):
    xy,faces,fidelity=adaptive_top(height,mask,tolerance,budget,shape,progress)
    z=base_mm+sample_field(height,xy)
    world=xy.copy();world[:,0]*=width_mm/(height.shape[1]-1);world[:,1]*=-height_mm/(height.shape[0]-1)
    faces=faces[:,[0,2,1]]
    # Native-grid faces already use row-down CCW order; same swap is correct.
    mesh=solid_from_top(world,faces,z)
    if len(mesh.faces)>budget:
        fidelity["tolerance_met"]=False
        fidelity["budget_exceeded"]=True
    mesh.metadata["construction"]="injective planar height-field solid with positive vertical thickness"
    mesh.metadata["minimum_thickness_mm"]=float(np.min(z))
    return mesh,fidelity


def sphere_mesh(height,radius=25.,relief_scale=1.,segments=128,rings=96):
    """Welded seam and single vertices at each pole; positive radial relief."""
    segments=int(np.clip(segments,12,512));rings=int(np.clip(rings,8,256))
    if radius<=0 or not np.isfinite(height).all(): raise ValueError("Sphere radius must be positive and height finite.")
    minimum=float(np.min(height));maximum=float(np.max(height))
    vertices=[[0,0,radius+relief_scale*(float(np.mean(height[0]))-minimum)]];uv=[[.5,1.]]
    for j in range(1,rings):
        theta=np.pi*j/rings
        for i in range(segments):
            u=i/segments;phi=2*np.pi*u
            value=float(ndimage.map_coordinates(height,[[j/rings*(height.shape[0]-1)],[u*(height.shape[1]-1)]],order=1)[0])
            # Blend seam samples locally; mark this presentation distortion in metadata.
            if i==0: value=(float(np.interp(j/rings*(height.shape[0]-1),np.arange(len(height)),height[:,0]))+float(np.interp(j/rings*(height.shape[0]-1),np.arange(len(height)),height[:,-1])))/2
            r=radius+relief_scale*(value-minimum)
            if r<=0: raise ValueError("Radial displacement produces non-positive sphere radius.")
            vertices.append([r*np.sin(theta)*np.cos(phi),r*np.sin(theta)*np.sin(phi),r*np.cos(theta)]);uv.append([u,1-j/rings])
    bottom=len(vertices);vertices.append([0,0,-(radius+relief_scale*(float(np.mean(height[-1]))-minimum))]);uv.append([.5,0.])
    faces=[]
    for i in range(segments): faces.append([0,1+i,1+(i+1)%segments])
    for j in range(rings-2):
        a=1+j*segments;b=a+segments
        for i in range(segments):
            n=(i+1)%segments;faces.extend(([a+i,b+i,b+n],[a+i,b+n,a+n]))
    last=1+(rings-2)*segments
    for i in range(segments): faces.append([last+i,bottom,last+(i+1)%segments])
    mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    mesh.metadata.update(uv=uv,construction="positive-radius radial embedding on nonoverlapping angular triangles",minimum_thickness_mm=2*radius)
    return mesh,{"seam_welded":True,"poles_welded":True,"seam_and_poles":"artistic blending; excludes original metric distances",
                 "source_relief_range":maximum-minimum,"radial_min_mm":float(np.linalg.norm(mesh.vertices,axis=1).min())}


def vertex_manifold(mesh):
    # Each vertex link must be one cycle (closed mesh) or one path (open mesh).
    incident=[[] for _ in mesh.vertices]
    for face in mesh.faces:
        a,b,c=map(int,face)
        incident[a].append((b,c));incident[b].append((c,a));incident[c].append((a,b))
    for links in incident:
        if not links: continue
        graph={}
        for a,b in links:
            graph.setdefault(a,[]).append(b);graph.setdefault(b,[]).append(a)
        if any(len(v)>2 for v in graph.values()): return False
        seen=set();stack=[next(iter(graph))]
        while stack:
            at=stack.pop()
            if at not in seen: seen.add(at);stack.extend(graph[at])
        if len(seen)!=len(graph): return False
    return True


def triangles_intersect(a,b,eps=1e-8):
    # Separating-axis test for two triangles, including coplanar in-plane axes.
    ea=np.roll(a,-1,axis=0)-a;eb=np.roll(b,-1,axis=0)-b
    na=np.cross(ea[0],ea[1]);nb=np.cross(eb[0],eb[1])
    axes=[na,nb]+[np.cross(x,y) for x in ea for y in eb]
    if np.linalg.norm(np.cross(na,nb))<eps*max(np.linalg.norm(na)*np.linalg.norm(nb),1):
        axes += [np.cross(na,e) for e in np.vstack((ea,eb))]
    for axis in axes:
        length=np.linalg.norm(axis)
        if length<1e-14: continue
        pa=a@(axis/length);pb=b@(axis/length)
        if pa.max()<pb.min()-eps or pb.max()<pa.min()-eps: return False
    return True


def self_intersections(mesh,limit=400_000,progress=None):
    """AABB hierarchy, then triangle SAT, including overlapping vertex neighbors.

    Returns None when the candidate budget is exhausted, never a false 'passed'.
    """
    triangles=np.asarray(mesh.triangles)
    lo,hi=triangles.min(axis=1),triangles.max(axis=1)
    center=(lo+hi)/2
    def tree(indices):
        bounds=(lo[indices].min(axis=0),hi[indices].max(axis=0))
        if len(indices)<=8: return (*bounds,indices,None)
        axis=int(np.argmax(bounds[1]-bounds[0]));order=indices[np.argsort(center[indices,axis])];mid=len(order)//2
        return (*bounds,tree(order[:mid]),tree(order[mid:]))
    root=tree(np.arange(len(triangles)));stack=[(root,root)];tested=0;hits=[]
    while stack:
        a,b=stack.pop()
        if np.any(a[1]<b[0]-1e-9) or np.any(b[1]<a[0]-1e-9): continue
        if a[3] is None and b[3] is None:
            for i in a[2]:
                for j in b[2]:
                    if i==j or (a is b and i>j): continue
                    if np.any(hi[i]<lo[j]-1e-9) or np.any(hi[j]<lo[i]-1e-9): continue
                    tested+=1
                    if tested>limit: return None,{"candidate_budget_exceeded":True,"tested":tested}
                    first,second=triangles[i],triangles[j]
                    shared=np.intersect1d(mesh.faces[i],mesh.faces[j])
                    if shared.size:
                        # Exclude only the shared boundary, not the entire pair.
                        # Overlap away from an ordinary shared edge/vertex is a defect.
                        first=first.copy();second=second.copy()
                        for vertices,face in ((first,mesh.faces[i]),(second,mesh.faces[j])):
                            chosen=np.isin(face,shared)
                            vertices[chosen]+=(vertices.mean(axis=0)-vertices[chosen])*1e-6
                    if triangles_intersect(first,second,eps=1e-10 if shared.size else 1e-8):
                        hits.append([int(i),int(j)])
                        if len(hits)>=12: return hits,{"tested":tested,"truncated":True}
        elif a is b:
            stack.extend(((a[2],a[2]),(a[2],a[3]),(a[3],a[3])))
        elif a[3] is None:
            stack.extend(((a,b[2]),(a,b[3])))
        elif b[3] is None:
            stack.extend(((a[2],b),(a[3],b)))
        else:
            stack.extend(((a[2],b[2]),(a[2],b[3]),(a[3],b[2]),(a[3],b[3])))
        if progress and tested%500==0: check(progress,.82,"Checking mesh intersections")
    return hits,{"tested":tested,"method":"AABB hierarchy + triangle separating axes"}


def validate_mesh(mesh,fidelity=None,printer=None,construction=None,min_thickness=None,progress=None):
    report=MeshValidationReport(triangles=len(mesh.faces),fidelity=fidelity or {})
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        report.errors.append("Empty mesh or non-finite coordinates.");return report
    report.dimensions_mm=mesh.extents.tolist();report.volume_mm3=float(mesh.volume)
    unique_faces=np.unique(np.sort(mesh.faces,axis=1),axis=0)
    edge_counts=np.bincount(mesh.edges_unique_inverse)
    checks={"finite_coordinates":bool(np.isfinite(mesh.vertices).all()),"no_degenerate_faces":bool(np.all(mesh.area_faces>1e-12)),
            "no_duplicate_faces":len(unique_faces)==len(mesh.faces),"edge_incidence_two":bool(np.all(edge_counts==2)),
            "closed_boundaries":bool(mesh.is_watertight),"consistent_winding":bool(mesh.is_winding_consistent),
            "vertex_manifold":vertex_manifold(mesh),"positive_volume":bool(mesh.volume>1e-10)}
    report.components=len(mesh.split(only_watertight=False))
    checks["single_component"]=report.components==1
    if construction:
        checks["self_intersections"]={"passed":True,"method":construction}
    else:
        hits,detail=self_intersections(mesh,progress=progress)
        checks["self_intersections"]={"passed":hits==[],"intersections":hits,**detail}
    checks["minimum_thickness"]={"verified":min_thickness is not None,"minimum_mm":min_thickness,
                                  "method":"construction lower bound" if min_thickness is not None else "unverified for arbitrary mesh"}
    for key,value in checks.items():
        if value is False: report.errors.append(key.replace('_',' ')+" failed")
    if not checks["self_intersections"]["passed"]: report.errors.append("Self-intersections detected or intersection validation budget exceeded.")
    if fidelity and not fidelity.get("tolerance_met",False): report.errors.append("Requested geometric tolerance or triangle budget was not met.")
    report.geometry_valid=not report.errors
    if min_thickness is None: report.warnings.append("Minimum wall thickness is unverified for this arbitrary mesh; print-ready status is withheld.")
    report.checks=checks
    if printer:
        printer=PrinterProfile(**printer) if isinstance(printer,dict) else printer
        fits=bool(np.all(mesh.extents<=printer.build_volume_mm))
        thickness_ok=min_thickness is not None and min_thickness>=printer.min_wall_mm
        report.printer_assessment={"name":printer.name,"fits_build_volume":fits,"minimum_thickness_ok":thickness_ok,
                                   "source_notes":printer.source_notes,"status":"estimates; physical print unverified"}
        if not fits: report.errors.append("Model exceeds the selected printer build volume in this orientation.")
        if not thickness_ok: report.errors.append("Wall/base thickness is insufficient or unverified for the selected printer.")
        report.print_ready=report.geometry_valid and fits and thickness_ok
    else:
        report.warnings.append("No printer profile selected. Geometry can be exported; process readiness is unverified.")
    return report


def write_3mf(mesh,path):
    import lib3mf
    wrapper=lib3mf.get_wrapper();model=wrapper.CreateModel();model.SetUnit(lib3mf.ModelUnit.MilliMeter)
    obj=model.AddMeshObject()
    vertices=[]
    for xyz in mesh.vertices:
        position=lib3mf.Position();position.Coordinates=tuple(map(float,xyz));vertices.append(position)
    triangles=[]
    for abc in mesh.faces:
        triangle=lib3mf.Triangle();triangle.Indices=tuple(map(int,abc));triangles.append(triangle)
    obj.SetGeometry(vertices,triangles);obj.SetName("Material Studio relief (mm)")
    model.AddBuildItem(obj,wrapper.GetIdentityTransform())
    model.QueryWriter("3mf").WriteToFile(str(path))


def read_3mf(path):
    import lib3mf
    wrapper=lib3mf.get_wrapper();model=wrapper.CreateModel();model.QueryReader("3mf").ReadFromFile(str(path))
    if model.GetUnit()!=lib3mf.ModelUnit.MilliMeter: raise ValueError("Round-trip 3MF units are not millimeters.")
    iterator=model.GetMeshObjects();meshes=[]
    while iterator.MoveNext():
        obj=iterator.GetCurrentMeshObject()
        meshes.append(trimesh.Trimesh(vertices=[list(p.Coordinates) for p in obj.GetVertices()],faces=[list(t.Indices) for t in obj.GetTriangleIndices()],process=False))
    if not meshes: raise ValueError("3MF has no mesh objects.")
    return trimesh.util.concatenate(meshes)


def roundtrip(mesh,directory,construction=None,min_thickness=None):
    path=Path(directory)
    mesh.export(path/"relief_mm.stl",file_type="stl")
    write_3mf(mesh,path/"relief_mm.3mf")
    results={}
    for kind in ("stl","3mf"):
        loaded=read_3mf(path/"relief_mm.3mf") if kind=="3mf" else trimesh.load_mesh(path/"relief_mm.stl",process=True)
        # Serialization preserves faces and positions; check both directions and
        # face-count/topology to avoid a vertex-only false positive.
        distance=cKDTree(mesh.vertices).query(loaded.vertices)[0]
        reverse=cKDTree(loaded.vertices).query(mesh.vertices)[0]
        report=validate_mesh(loaded,construction=construction,min_thickness=min_thickness)
        dim_error=float(abs(loaded.extents-mesh.extents).max())
        results[kind]={"dimensions_mm":loaded.extents.tolist(),"max_dimension_error_mm":dim_error,
                       "max_vertex_error_mm":float(max(distance.max(),reverse.max())),"p95_vertex_error_mm":float(np.percentile(distance,95)),
                       "triangles_preserved":len(loaded.faces)==len(mesh.faces),"orientation_preserved":bool(loaded.is_winding_consistent and loaded.volume>0),
                       "geometry_valid":report.geometry_valid,"units":"mm","passed":bool(report.geometry_valid and dim_error<1e-4 and max(distance.max(),reverse.max())<1e-4 and len(loaded.faces)==len(mesh.faces))}
    return results


def project_mesh_to_patch(store,frame_id,settings):
    frame=store.get("frames",frame_id)
    mesh,inspection=load_mesh(store.path(frame["raw_file"]),settings.get("mesh_units") or frame["settings"].get("mesh_units"))
    # Local plane via PCA; optional explicit Euler orientation takes precedence.
    vertices=mesh.vertices.copy();center=vertices.mean(axis=0)
    if settings.get("rotation_deg"):
        angles=np.deg2rad(settings["rotation_deg"])
        rotation=trimesh.transformations.euler_matrix(*angles)[:3,:3]
    else:
        _,_,basis=np.linalg.svd(vertices-center,full_matrices=False);rotation=basis
        if np.linalg.det(rotation)<0: rotation[2]*=-1
    points=(vertices-center)@rotation.T
    if np.median(mesh.face_normals@rotation[2])<0: points[:,2]*=-1;rotation[2]*=-1
    projected=points[mesh.faces]
    area=np.cross(projected[:,1]-projected[:,0],projected[:,2]-projected[:,0])[:,2]
    if np.any(area<-1e-8) or np.any(abs(area)<1e-12):
        raise ValueError("Projection has overhangs, reversed or vertical faces. Orient/crop a single-valued open patch, or use the mesh-preserving branch.")
    # Rasterize triangles with ownership, rejecting overlapping projected interiors.
    size=int(np.clip(settings.get("resolution",192),16,512))
    low,high=points.min(axis=0),points.max(axis=0)
    roi=settings.get("roi",[0,0,1,1]);span=high-low
    low[:2]+=span[:2]*np.asarray(roi[:2]);high[:2]=points.max(axis=0)[:2]-span[:2]*(1-np.asarray(roi[2:]))
    if min(high[:2]-low[:2])<=0: raise ValueError("Mesh projection crop is empty.")
    ny=max(2,int(round(size*(high[1]-low[1])/(high[0]-low[0]))));ny=min(512,ny)
    xs=np.linspace(low[0],high[0],size);ys=np.linspace(high[1],low[1],ny)
    out=np.zeros((ny,size));mask=np.zeros_like(out,bool);owner=np.full(out.shape,-1)
    for index,triangle in enumerate(projected):
        a,b,c=triangle
        ix=np.where((xs>=triangle[:,0].min()-1e-9)&(xs<=triangle[:,0].max()+1e-9))[0]
        iy=np.where((ys>=triangle[:,1].min()-1e-9)&(ys<=triangle[:,1].max()+1e-9))[0]
        if not len(ix) or not len(iy): continue
        gx,gy=np.meshgrid(xs[ix],ys[iy]);xy=np.column_stack((gx.ravel(),gy.ravel()))
        bc=np.linalg.solve(np.column_stack((a[:2]-c[:2],b[:2]-c[:2])),(xy-c[:2]).T).T
        inside=(bc.min(axis=1)>=-1e-8)&(bc.sum(axis=1)<=1+1e-8)
        py,px=np.meshgrid(iy,ix,indexing="ij");py,px=py.ravel()[inside],px.ravel()[inside]
        z=bc[inside,0]*a[2]+bc[inside,1]*b[2]+(1-bc[inside].sum(axis=1))*c[2]
        if np.any(mask[py,px] & (abs(out[py,px]-z)>1e-5)): raise ValueError("Mesh has multiple heights at the same projected location. Keep it in the mesh-preserving branch.")
        out[py,px]=z;mask[py,px]=True;owner[py,px]=index
    patch=SurfacePatch(name=frame["source_name"]+" • projected",source_ids=[frame_id],width=size,height=ny,state="calibrated",units="mm",
                       pixel_spacing=((high[0]-low[0])/(size-1),(high[1]-low[1])/(ny-1)),validation_notes="Imported mesh units explicitly assigned; geometry reference only, sensor accuracy unknown.",
                       provenance=[{"operation":"local plane mesh projection","rotation":rotation.tolist(),"origin":center.tolist(),"inspection":inspection}],
                       quality={"measurement_allowed":False})
    return store.put_patch(patch,out,mask)


def union_meshes(meshes):
    result=trimesh.boolean.union(meshes,engine="manifold",check_volume=True)
    if not isinstance(result,trimesh.Trimesh) or not result.is_volume:
        raise ValueError("Solid union failed. Adjust attachment overlap or remove the addition.")
    return result


def label_plate(text,width=40.,height=7.,thickness=1.5):
    """Emboss actual label geometry on a shared solid plate, outside sampled data."""
    image=Image.new('L',(max(64,int(width*3)),24),0)
    draw=ImageDraw.Draw(image);draw.text((3,4),str(text)[:35],fill=255)
    relief=np.array(image,dtype=float)/255*.45
    plate,_=relief_mesh(relief,np.ones(relief.shape,bool),width,height,thickness,.08,40_000)
    return plate


def border_frame(width,height,base,border,corner):
    """Rounded exterior in plan, outside the scan; the measured top stays intact."""
    if not 0<border<=50 or not 0<=corner<=border:raise ValueError('Border must be 0–50 mm; corner radius cannot exceed border width.')
    w,h=width+2*border,height+2*border
    center=np.array([width/2,-height/2,base/2])
    if corner==0:
        outer=trimesh.creation.box(extents=[w,h,base]);outer.apply_translation(center)
    else:
        parts=[]
        for extents in ([w-2*corner,h,base],[w,h-2*corner,base]):
            part=trimesh.creation.box(extents=extents);part.apply_translation(center);parts.append(part)
        for x in (-1,1):
            for y in (-1,1):
                part=trimesh.creation.cylinder(radius=corner,height=base,sections=48)
                part.apply_translation(center+[x*(w/2-corner),y*(h/2-corner),0]);parts.append(part)
        outer=union_meshes(parts)
    # A narrow overlap below the relief ensures a real connected union. The ring
    # is never taller than the minimum scanned top (base).
    inner=trimesh.creation.box(extents=[width-.2,height-.2,base+2]);inner.apply_translation(center)
    return trimesh.boolean.difference([outer,inner],engine='manifold',check_volume=True)


def printer_detail(height,mask,width,height_mm,printer,directory=None):
    dx=width/(height.shape[1]-1);dy=height_mm/(height.shape[0]-1)
    trend=ndimage.gaussian_filter(height,2)
    valleys=(height<trend-float(np.std(height[mask]))*.15)&mask
    ridges=(height>trend+float(np.std(height[mask]))*.15)&mask
    groove_width=2*ndimage.distance_transform_edt(valleys,sampling=(dy,dx))
    ridge_width=2*ndimage.distance_transform_edt(ridges,sampling=(dy,dx))
    lost=((valleys&(groove_width<printer.min_groove_mm))|(ridges&(ridge_width<printer.min_raised_line_mm)))&mask
    if directory:
        Image.fromarray(lost.astype(np.uint8)*255).save(Path(directory)/"detail_loss.png")
    span=float(np.ptp(height[mask]));layers=span/printer.layer_height_mm
    feature_values=groove_width[valleys]
    resolved_width=float(np.percentile(feature_values,50)) if len(feature_values) else min(dx,dy)*2
    return {"relief_layers":layers,"estimated_lost_fraction":float(lost[mask].mean()),
            "lateral_sample_spacing_mm":[dx,dy],"effective_lateral_limit_mm":printer.lateral_limit_mm,
            "suggested_xy_multiplier":max(1.,printer.min_groove_mm/max(resolved_width,1e-8)),
            "suggested_z_multiplier":max(1.,3/max(layers,1e-8)) if span>0 else None,
            "method":"thresholded local ridges/valleys and distance-transform widths; not print validation"}


def _scaled_field(patch,arrays,settings,common_min=None):
    source=arrays["height"].astype(float);mask=arrays["mask"].copy()
    if arrays["synthetic_mask"].any() and not settings.get("accept_derived"):
        raise ValueError("Source includes synthesized pixels. Explicitly accept derived repair geometry or choose the original patch.")
    repair=[]
    if not mask.all():
        policy=settings.get("holes","exclude")
        if policy=="fill":
            source=fill_nearest(source,mask);repair.append({"operation":"explicit nearest valid fill","pixels":int((~mask).sum())});mask[:]=True
        elif policy not in ("exclude","split"):
            raise ValueError("Missing regions must be excluded, split, or explicitly filled.")
    outlier=float(settings.get("outlier_mm",0))
    if outlier>0:
        if patch.units!="mm": raise ValueError("Physical outlier threshold requires a metric source.")
        median=ndimage.median_filter(source,3);changed=(abs(source-median)>outlier)&mask
        source[changed]=median[changed];repair.append({"operation":"outlier median replacement","threshold_mm":outlier,"pixels":int(changed.sum())})
    denoise=float(settings.get("denoise",0))
    if denoise>0:
        source=cv2.bilateralFilter(source.astype(np.float32),5,denoise,2).astype(float)
        repair.append({"operation":"bilateral denoising","sigma_height":denoise})
    if settings.get("inverse_relief"): source=-source
    if patch.state=="calibrated":
        sx=float(settings.get("xy_scale",5.));sz=float(settings.get("z_scale",sx))
        if settings.get("scale_mode")=="true":sx=sz=1.
        elif settings.get("scale_mode")=="uniform":sz=sx
        width=(patch.width-1)*patch.pixel_spacing[0]*sx
        height=(patch.height-1)*patch.pixel_spacing[1]*sx
        reference=float(source[mask].min()) if common_min is None else common_min
        scaled=(source-reference)*sz
        original=(arrays["height"]*(-1 if settings.get("inverse_relief") else 1)-reference)*sz
        mode="true scale" if sx==sz==1 else "uniform enlargement" if sx==sz else "authored Z exaggeration"
    else:
        if "width_mm" not in settings or "relief_mm" not in settings:
            raise ValueError("Relative source requires an authored output width and relief range in mm.")
        width=float(settings["width_mm"]);height=float(settings.get("height_mm",width*(patch.height-1)/(patch.width-1)))
        if settings.get("aspect_lock",True):height=width*(patch.height-1)/(patch.width-1)
        reference=float(source[mask].min()) if common_min is None else common_min
        span=float(settings.get("shared_source_span",np.ptp(source[mask])))
        sz=float(settings["relief_mm"])/max(span,1e-12)
        scaled=(source-reference)*sz;original=(arrays["height"]*(-1 if settings.get("inverse_relief") else 1)-reference)*sz
        sx=None;mode="authored dimensions from relative relief"
    if min(width,height)<=0 or sz<=0 or max(width,height)>2000: raise ValueError("Output dimensions/scales must be positive, at most 2000 mm.")
    errors=abs(scaled-original)
    return scaled,mask,width,height,{"mode":mode,"xy_scale":sx,"z_scale":sz,"source_reference":reference,"source_units":patch.units,
                                     "output_units":"mm","inverse_relief":bool(settings.get("inverse_relief")),
                                     "width_mm":width,"height_mm":height,"height_reference":patch.height_reference},repair,errors


def make_print(store,source_id,settings=None,progress=None):
    settings=settings or {}
    base=float(settings.get("base_mm",2.))
    tolerance=float(settings.get("tolerance_mm",.03))
    budget=int(settings.get("triangle_budget",120_000))
    if not (.1<=base<=100 and .00001<=tolerance<=10 and 2000<=budget<=MAX_TRIANGLES):
        raise ValueError("Base must be 0.1–100 mm, tolerance 0.00001–10 mm, and triangle budget 2,000–400,000.")
    source_kind=settings.get("source_kind","patch")
    project=PrintProject(name=settings.get("name","Relief print"),source_id=source_id,source_kind=source_kind,settings=settings,
                         printer=PrinterProfile(**settings["printer"]) if settings.get("printer") else None)
    project.directory=f"prints/{project.id}"
    directory=store.path(project.directory);directory.mkdir()
    # Save before processing so a failure is editable and inspectable.
    store.save("prints",project)
    construction=None;minimum_thickness=None;detail=None
    try:
        if source_kind=="mesh":
            frame=store.get("frames",source_id)
            mesh,inspection=load_mesh(store.path(frame["raw_file"]),settings.get("mesh_units") or frame["settings"].get("mesh_units"))
            original=mesh.copy()
            factor=float(settings.get("mesh_scale",1.))
            if not 0<factor<=1000: raise ValueError("Mesh scale must be positive and at most 1000.")
            mesh.apply_scale(factor);original.apply_scale(factor)
            if settings.get("repair_winding"):
                trimesh.repair.fix_normals(mesh,multibody=True)
                project.repairs.append({"operation":"explicit orientation repair","vertices_moved":False})
            if settings.get("simplify"):
                import manifold3d as m3d
                solid=m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(mesh.vertices,np.float32),tri_verts=np.asarray(mesh.faces,np.uint32)))
                if str(solid.status()).split('.')[-1]!="NoError": raise ValueError("Error-bounded simplification requires a valid closed solid; preserve this mesh or project a single-valued patch.")
                candidate=solid.simplify(tolerance).to_mesh()
                simplified=trimesh.Trimesh(vertices=candidate.vert_properties[:,:3],faces=candidate.tri_verts,process=False)
                # Bidirectional dense surface distances using proximity_naive in chunks;
                # this is bounded for imported meshes to keep memory predictable.
                if len(mesh.faces)>12_000 or len(simplified.faces)>12_000: raise ValueError("Distance-verified mesh simplification supports up to 12,000 faces. Preserve the dense source for export.")
                def surface_points(m):
                    weights=np.array([[1/3]*3,[.6,.2,.2],[.2,.6,.2],[.2,.2,.6]])
                    return np.vstack((m.vertices,np.einsum('sk,fkj->fsj',weights,m.triangles).reshape(-1,3)))
                distances=[]
                for target,points in ((mesh,surface_points(simplified)),(simplified,surface_points(mesh))):
                    for i in range(0,len(points),32):
                        distances.extend(trimesh.proximity.closest_point_naive(target,points[i:i+32])[1].tolist())
                fidelity={"max_error_mm":max(distances),"p95_error_mm":float(np.percentile(distances,95)),"p99_error_mm":float(np.percentile(distances,99)),
                          "tolerance_mm":tolerance,"tolerance_met":max(distances)<=tolerance,"samples":len(distances),"reference":"scaled original mesh, bidirectional surface samples"}
                mesh=simplified;project.repairs.append({"operation":"manifold simplification","triangles_before":len(original.faces),"triangles_after":len(mesh.faces)})
            else:
                fidelity={"max_error_mm":0.,"p95_error_mm":0.,"p99_error_mm":0.,"tolerance_mm":tolerance,"tolerance_met":True,"reference":"unchanged scaled source vertices and faces"}
            project.transforms={"uniform_scale":factor,"inspection":inspection}
        else:
            patch,arrays=store.patch(source_id)
            shape=settings.get("shape","rectangle")
            if shape not in ("rectangle","circle","curved","sphere","coupon"): raise ValueError("Unknown print substrate.")
            scaled,mask,width,height,transforms,repairs,filter_error=_scaled_field(patch,arrays,settings)
            project.transforms=transforms;project.repairs=repairs
            np.save(directory/"filter_error_mm.npy",filter_error.astype(np.float32))
            Image.fromarray((~arrays["mask"]|arrays["synthetic_mask"]).astype(np.uint8)*255).save(directory/"source_missing_or_synthetic.png")
            np.save(directory/"source_height.npy",arrays["height"])
            (directory/"source.json").write_text(json.dumps(patch.model_dump(mode="json"),indent=2),encoding="utf-8")
            minimum_thickness=base
            if shape=="sphere":
                if not mask.all(): raise ValueError("Sphere requires complete coverage. Explicitly fill a derived source first.")
                segments=min(256,max(16,int(np.sqrt(budget/2))))
                rings=max(8,segments//2)
                mesh,info=sphere_mesh(scaled,radius=float(settings.get("radius_mm",25)),relief_scale=1.,segments=segments,rings=rings)
                project.transforms.update(info)
                # Compare triangle interior radius to the mapped bilinear source.
                bary=np.array([[1/3]*3,[.6,.2,.2],[.2,.6,.2],[.2,.2,.6]])
                samples=np.einsum('sk,fkj->fsj',bary,mesh.triangles).reshape(-1,3)
                radii=np.linalg.norm(samples,axis=1)
                u=(np.arctan2(samples[:,1],samples[:,0])%(2*np.pi))/(2*np.pi)
                v=np.arccos(np.clip(samples[:,2]/radii,-1,1))/np.pi
                expected=float(settings.get("radius_mm",25))+sample_field(scaled,np.column_stack((u*(scaled.shape[1]-1),v*(scaled.shape[0]-1))))-float(scaled.min())
                errors=abs(radii-expected)
                fidelity={"max_error_mm":float(errors.max()),"p95_error_mm":float(np.percentile(errors,95)),"p99_error_mm":float(np.percentile(errors,99)),
                          "tolerance_mm":tolerance,"tolerance_met":bool(errors.max()<=tolerance),"samples":len(errors),
                          "reference":"scaled radial height field including mapped seam/pole differences"}
                minimum_thickness=2*float(settings.get("radius_mm",25))
            elif shape=="coupon":
                mesh,fidelity,coupon_records=make_coupon(store,patch,arrays,settings,progress)
                project.transforms["coupon_variants"]=coupon_records
            else:
                mesh,fidelity=relief_mesh(scaled,mask,width,height,base,tolerance,budget,"circle" if shape=="circle" else "rectangle",progress)
                if shape=="curved":
                    radius=float(settings.get("curve_radius_mm",max(width,40)))
                    if width/radius>math.radians(150): raise ValueError("Curved swatch is limited to a 150° arc. Increase the curve radius.")
                    angle=(mesh.vertices[:,0]-width/2)/radius
                    radial=radius+mesh.vertices[:,2]
                    mesh.vertices[:,0]=radial*np.sin(angle);mesh.vertices[:,2]=radial*np.cos(angle)-radius
                    mesh.metadata["construction"]="injective cylindrical swatch, positive radial wall and arc below 150 degrees"
                    # Curvature adds chord error; test against actual curved mapping.
                    radial_samples=np.einsum('sk,fkj->fsj',np.array([[1/3]*3,[.6,.2,.2],[.2,.6,.2],[.2,.2,.6]]),mesh.triangles).reshape(-1,3)
                    # Conservative bound for curved chord deflection, applied to source error.
                    max_edge=float(mesh.edges_unique_length.max())
                    bound=max_edge**2/(8*radius)
                    fidelity["curvature_chord_bound_mm"]=bound
                    fidelity["max_error_mm"]+=bound;fidelity["tolerance_met"]=fidelity["max_error_mm"]<=tolerance
                    project.transforms["curve_radius_mm"]=radius
            # Preserve achieved error after filtering, not just meshing error.
            fidelity["filter_max_error_mm"]=float(filter_error[mask].max())
            fidelity["max_error_mm"]+=float(filter_error[mask].max())
            fidelity["tolerance_met"]=fidelity["max_error_mm"]<=tolerance and len(mesh.faces)<=budget
            construction=mesh.metadata.get("construction")
            if float(settings.get('border_mm',0))>0:
                if shape!='rectangle':raise ValueError('Rounded exterior borders currently require a rectangular tile.')
                border=float(settings['border_mm']);corner=float(settings.get('corner_radius_mm',0))
                mesh=union_meshes([mesh,border_frame(width,height,base,border,corner)])
                construction='boolean union of positive-thickness height solid and exterior border'
                project.repairs.append({'operation':'exterior border union; source top unchanged','border_mm':border,'corner_radius_mm':corner,'rounding':'plan-view exterior corners only'})
            if settings.get("label") and shape in ("rectangle","circle"):
                plate=label_plate(settings["label"],width,7,base)
                plate.apply_translation([0,6.8,0])
                mesh=union_meshes([mesh,plate]);construction="boolean union of verified relief and embossed label plate"
                project.repairs.append({"operation":"union label plate outside sample","label":settings["label"]})
            if settings.get("stand") and shape=="sphere":
                bottom=float(mesh.bounds[0,2]);radius=float(settings.get("radius_mm",25))
                stand=trimesh.creation.cylinder(radius=radius*.4,height=base*2,sections=64)
                stand.apply_translation([0,0,bottom+base*.7])
                mesh=union_meshes([mesh,stand]);construction="boolean union of positive radial sphere and overlapping display base"
                project.repairs.append({"operation":"union display stand"})
            fidelity['tolerance_met']=fidelity['tolerance_met'] and len(mesh.faces)<=budget
            if project.printer:detail=printer_detail(scaled,mask,width,height,project.printer,directory)
            shade=(scaled-float(scaled[mask].min()))/max(float(np.ptp(scaled[mask])),1e-12)
            image=Image.fromarray(np.rint(np.clip(shade,0,1)*255).astype(np.uint8)).convert('RGB')
            image.thumbnail((600,600));canvas=Image.new('RGB',(640,700),'#eff0e9');canvas.paste(image,((640-image.width)//2,25))
            draw=ImageDraw.Draw(canvas);draw.text((20,640),f"{shape} | {width:.2f} x {height:.2f} mm | {transforms['mode']}",fill='#172724')
            draw.text((20,662),"Source overview; physical printing and slicing unverified",fill='#172724');canvas.save(directory/"overview.png")
        check(progress,.78,"Validating topology and geometry")
        center_y=float(mesh.bounds[:,1].mean())
        section=trimesh.intersections.mesh_plane(mesh,[0,1,0],[0,center_y,0])
        cross_section={'units':'mm','plane_y_mm':center_y,'segments':section[:20000][:,:,[0,2]].tolist(),'source':None}
        if source_kind=='patch' and shape in ('rectangle','circle'):
            row=scaled.shape[0]//2
            cross_section['source']=[[float(x),float(base+z)] if ok else None for x,z,ok in zip(np.linspace(0,width,scaled.shape[1]),scaled[row],mask[row])]
            cross_section['source_description']='Scaled, processed source row near the central section; mesh segments show actual exported geometry.'
        (directory/'cross-section.json').write_text(json.dumps(cross_section),encoding='utf-8')
        report=validate_mesh(mesh,fidelity,project.printer,construction,minimum_thickness,progress)
        if detail:report.printer_assessment.update(detail)
        if settings.get("holes")=="split" and report.components>1:
            # Each closed island is exportable separately; parent stays explicitly multi-component.
            for i,part in enumerate(mesh.split(only_watertight=False)):
                if part.is_volume:part.export(directory/f"island-{i+1}_mm.stl")
            report.warnings.append("Disconnected valid islands exported separately. The combined model is not labeled print-ready.")
        project.report=report
        mesh.export(directory/"editing.ply")
        mesh.export(directory/"editing.obj")
        # GLB uses meters, unlike STL/3MF. Bake mm→m conversion explicitly.
        webmesh=mesh.copy();webmesh.apply_scale(.001);webmesh.export(directory/"editing.glb")
        # Limit UI geometry independently, retaining dense export mesh on disk.
        if len(mesh.faces)<=90_000:
            preview_mesh=mesh
        else:
            # Point/triangle subset is a wireframe inspection preview, never an export.
            preview_mesh=mesh.submesh([np.arange(0,len(mesh.faces),math.ceil(len(mesh.faces)/90_000))],append=True)
        (directory/"mesh-preview.json").write_text(json.dumps({"vertices":np.round(preview_mesh.vertices,6).tolist(),"faces":preview_mesh.faces.tolist(),
                                                               "full_triangles":len(mesh.faces),"preview_triangles":len(preview_mesh.faces),"units":"mm","report":report.model_dump(mode="json")}),encoding="utf-8")
        if report.geometry_valid:
            check(progress,.9,"Reloading STL and 3MF for verification")
            verification=roundtrip(mesh,directory,construction,minimum_thickness)
            project.exports={"stl":"relief_mm.stl","3mf":"relief_mm.3mf","ply":"editing.ply","obj":"editing.obj","glb":"editing.glb","roundtrip":verification}
            if not all(v["passed"] for v in verification.values()):
                project.report.errors.append("An exported file failed round-trip verification.");project.report.print_ready=False;project.report.geometry_valid=False
        else:
            project.report.warnings.append("Manufacturing export withheld; editing meshes and failed project are preserved.")
        (directory/"project.json").write_text(json.dumps(project.model_dump(mode="json"),indent=2),encoding="utf-8")
        (directory/"README.md").write_text("# Print package\n\nSTL coordinates are millimeters; select mm in your slicer. 3MF declares mm explicitly. GLB editing geometry is in meters. Review project.json validation and printer assessment before slicing. Place supports away from featured relief where practical. No G-code, slicer smoke test, or physical printing is claimed. Error measures compare processed geometry to the appropriately scaled digital source, not to original sensor truth. Editing meshes may include failed geometry: use the validation report.\n",encoding="utf-8")
        return store.save("prints",project)
    except Exception as exc:
        project.report=MeshValidationReport(errors=[str(exc)],warnings=["Failed project retained for editing."])
        store.save("prints",project)
        raise


def make_coupon(store,patch,arrays,settings,progress=None):
    second_id=settings.get("paired_id")
    sources=[(patch,arrays)]
    if second_id:
        second,b=store.patch(second_id)
        if second.state!=patch.state or second.units!=patch.units: raise ValueError("Paired coupons need sources with matching units and calibration state.")
        if second.pixel_spacing!=patch.pixel_spacing or b["height"].shape!=arrays["height"].shape:
            raise ValueError("Paired coupons require identical sample dimensions and spacing; crop both to a matching region first.")
        sources.append((second,b))
    base=float(settings.get("base_mm",2));parts=[];records=[];errors=[]
    variants=settings.get("variants",[[1.,1.],[1.5,1.],[1.5,2.]])
    if len(variants)>4: raise ValueError("Coupon supports at most four scale variants.")
    shared_span=max(float(a["height"][a["mask"]].max()) for _,a in sources)-min(float(a["height"][a["mask"]].min()) for _,a in sources)
    x_offset=0.;max_height=0.
    for i,(xy_multiplier,z_multiplier) in enumerate(variants):
        if min(xy_multiplier,z_multiplier)<=0:raise ValueError("Coupon multipliers must be positive.")
        row_offset=0.;column_width=0.
        for row,(p,a) in enumerate(sources):
            config={**settings,"shape":"rectangle","xy_scale":float(settings.get("xy_scale",3))*xy_multiplier,
                    "z_scale":float(settings.get("z_scale",3))*z_multiplier,"scale_mode":"exaggerated","shared_source_span":shared_span,
                    "width_mm":float(settings.get("width_mm",30))*xy_multiplier,"relief_mm":float(settings.get("relief_mm",1))*z_multiplier}
            h,mask,w,hh,t,_,_= _scaled_field(p,a,config)
            tile,f=relief_mesh(h,mask,w,hh,base,float(settings.get("tolerance_mm",.03)),int(settings.get("triangle_budget",120_000))//(len(sources)*len(variants)),progress=progress)
            tile.apply_translation([x_offset,-row_offset,base*.4]);parts.append(tile)
            label=f"{'A' if row==0 else 'B'} XYx{xy_multiplier:g} Zx{z_multiplier:g}"
            plate=label_plate(label,w,7,base);plate.apply_translation([x_offset,6.8-row_offset,base*.4]);parts.append(plate)
            records.append({"source_id":p.id,"label":label,"transform":t,"xy_multiplier":xy_multiplier,"z_multiplier":z_multiplier,
                            "relief_range_mm":float(np.ptp(h[mask])),"fidelity":f})
            errors.append(f["max_error_mm"]);column_width=max(w,column_width);row_offset+=hh+11
        max_height=max(max_height,row_offset);x_offset+=column_width+5
    support=trimesh.creation.box(extents=[x_offset+2,max_height+2,base])
    support.apply_translation([(x_offset-5)/2,(-max_height+11)/2,base/2])
    mesh=union_meshes([support,*parts]);mesh.metadata["construction"]="boolean union of positive-thickness coupon tiles, label plates, and common backing"
    tolerance=float(settings.get("tolerance_mm",.03))
    return mesh,{"max_error_mm":max(errors),"p95_error_mm":float(np.percentile(errors,95)),"p99_error_mm":float(np.percentile(errors,99)),
                 "tolerance_mm":tolerance,"tolerance_met":all(r["fidelity"]["tolerance_met"] for r in records),
                 "reference":"each coupon's appropriately scaled source; paired sources share XY/Z factors and relative encoding range"},records
