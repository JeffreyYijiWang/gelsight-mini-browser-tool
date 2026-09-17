"""Deterministic artistic ink model. This module never modifies source arrays."""
from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageDraw
from scipy import ndimage
from scipy.special import expit

from .records import ImpressionVariant
from .surface import normals_from_height


def contact_coverage(height,mask,pressure=.5,softness=.035,invert=False):
    h=np.array(height,dtype=float,copy=True)
    valid=np.asarray(mask,bool)&np.isfinite(h)
    if not valid.any(): raise ValueError("No finite valid samples for an impression.")
    if not 0<=pressure<=1 or not 0<=softness<=1: raise ValueError("Virtual pressure and contact softness must be in [0,1].")
    if invert:h=-h
    lo,hi=float(h[valid].min()),float(h[valid].max());span=hi-lo
    if span<=max(abs(lo),1)*1e-12:
        # A flat field has no ordering of heights. Continuous pressure controls
        # uniform coverage rather than dividing by zero or inventing texture.
        out=np.full(h.shape,pressure,dtype=float)
    else:
        normalized=(h-lo)/span
        threshold=1-pressure
        if softness==0:out=(normalized>=threshold).astype(float)
        else:out=expit((normalized-threshold)/softness)
        if pressure==0:out[:]=0
        if pressure==1:out[:]=1
    return np.where(valid,out,0).astype(np.float32)


def render_ink(height,mask,settings=None):
    settings=settings or {}
    h=np.array(height,dtype=float,copy=True);valid=np.asarray(mask,bool).copy()
    coverage=contact_coverage(h,valid,float(settings.get("pressure",.55)),float(settings.get("softness",.035)),bool(settings.get("invert",False)))
    seed=int(settings.get("seed",7));rng=np.random.default_rng(seed)
    # All effects are removable coverage/paper layers; never a height modification.
    breakup=float(np.clip(settings.get("dry_brush",0),0,.95))
    noise=ndimage.gaussian_filter(rng.random(h.shape),.6)
    dry_layer=np.clip((noise-.2)/.6,0,1)
    if breakup:coverage*=1-breakup*(1-dry_layer)
    spread=float(np.clip(settings.get("spread",0),0,3))
    if spread:
        expanded=ndimage.maximum_filter(coverage,size=3)
        coverage=(coverage+spread*ndimage.gaussian_filter(expanded,spread))/(1+spread)
    edge=float(np.clip(settings.get("edge_softness",0),0,5))
    if edge:coverage=ndimage.gaussian_filter(coverage,edge)
    coverage*=float(np.clip(settings.get("ink_amount",.9),0,1))
    coverage[~valid]=0
    pigment=np.array(ImageColor.getrgb(settings.get("pigment","#243530")),float)
    paper=np.array(ImageColor.getrgb(settings.get("paper","#eee7d6")),float)
    paper_layer=np.zeros(h.shape)
    grain=float(np.clip(settings.get("paper_grain",0),0,.1))
    if grain:paper_layer=(rng.random(h.shape)-.5)*255*grain
    backdrop=np.clip(paper+paper_layer[...,None],0,255)
    style=settings.get("style","ink")
    if style=="clean":backdrop[:]=paper;paper_layer[:]=0
    if style=="relief":
        normals,_=normals_from_height(h,mask=valid)
        light=np.array([-.5,.5,.707]);shade=np.clip(.25+.75*(normals@light),0,1)
        composite=backdrop*shade[...,None];composite[~valid]=backdrop[~valid]
    else:composite=backdrop*(1-coverage[...,None])+pigment*coverage[...,None]
    return np.rint(np.clip(composite,0,255)).astype(np.uint8),coverage,{"dry_brush":dry_layer.astype(np.float32),"paper_grain":paper_layer.astype(np.float32)}


def preview_ink(store,specimen_id,settings):
    """Bounded owner preview; no file, variant, measurement or source mutations."""
    specimen=store.get('specimens',specimen_id)
    if specimen['source_kind']=='frame':
        from .inputs import image_array
        frame=store.get('frames',specimen['source_id'])
        h=cv2.cvtColor(image_array(store.path(frame['raw_file']).read_bytes()),cv2.COLOR_RGB2GRAY).astype(float)/255
        mask=np.ones(h.shape,bool)
    else:
        _,a=store.patch(specimen['source_id']);h,mask=a['height'],a['mask']
    x0,y0,x1,y1=settings.get('crop',[0,0,1,1])
    if not(0<=x0<x1<=1 and 0<=y0<y1<=1):raise ValueError('Crop must be normalized x0,y0,x1,y1.')
    ys=slice(int(y0*h.shape[0]),int(y1*h.shape[0]));xs=slice(int(x0*h.shape[1]),int(x1*h.shape[1]))
    h,mask=h[ys,xs],mask[ys,xs]
    if min(h.shape)<2:raise ValueError('Crop must contain at least two samples per axis.')
    ratio=min(1,384/max(h.shape));size=(max(2,round(h.shape[1]*ratio)),max(2,round(h.shape[0]*ratio)))
    h=cv2.resize(h,size);mask=cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
    pixels,_,_=render_ink(h,mask,settings)
    paper=settings.get('paper','#eee7d6')
    picture=Image.fromarray(pixels).rotate(float(settings.get('rotation',0)),resample=Image.Resampling.BICUBIC,expand=True,fillcolor=paper)
    margin=float(np.clip(settings.get('margin',.1),0,.35));pad=round(picture.width*margin/max(1-2*margin,.1))
    page=Image.new('RGB',(picture.width+pad*2,picture.height+pad*2),paper);page.paste(picture,(pad,pad))
    return page


def create_impression(store,specimen_id,settings=None,progress=None):
    settings=settings or {}
    specimen=store.get("specimens",specimen_id)
    if specimen["source_kind"]=="frame":
        from .inputs import image_array
        frame=store.get("frames",specimen["source_id"])
        rgb=image_array(store.path(frame["raw_file"]).read_bytes())
        # Explicit image-based artistic interpretation; this never creates a SurfacePatch.
        height=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(float)/255
        mask=np.ones(height.shape,bool);source_hash=frame["sha256"];version="original RGB image";dimensions=None
        interpretation="image-based artistic impression; no height or contact-physics claim"
    else:
        patch,a=store.patch(specimen["source_id"]);height=a["height"].copy();mask=a["mask"].copy()
        source_hash=hashlib.sha256(store.path(patch.arrays).read_bytes()).hexdigest();version=patch.version
        dimensions=((patch.width-1)*patch.pixel_spacing[0],(patch.height-1)*patch.pixel_spacing[1]) if patch.pixel_spacing else None
        interpretation="height-based artistic ink coverage; not measured ink physics"
    roi=settings.get("crop",[0,0,1,1]);x0,y0,x1,y1=map(float,roi)
    if not(0<=x0<x1<=1 and 0<=y0<y1<=1):raise ValueError("Impression crop must be normalized x0,y0,x1,y1.")
    rows,cols=height.shape;left,right=int(x0*cols),max(int(x1*cols),int(x0*cols)+2);top,bottom=int(y0*rows),max(int(y1*rows),int(y0*rows)+2)
    height,mask=height[top:bottom,left:right],mask[top:bottom,left:right]
    if dimensions:dimensions=(dimensions[0]*(height.shape[1]-1)/(cols-1),dimensions[1]*(height.shape[0]-1)/(rows-1))
    rotation=float(settings.get("rotation",0))
    image,coverage,layers=render_ink(height,mask,settings)
    paper=settings.get("paper","#eee7d6")
    img=Image.fromarray(image)
    alpha=Image.fromarray(np.rint(coverage*255).astype(np.uint8))
    if rotation:
        img=img.rotate(rotation,resample=Image.Resampling.BICUBIC,expand=True,fillcolor=paper)
        alpha=alpha.rotate(rotation,resample=Image.Resampling.BILINEAR,expand=True,fillcolor=0)
    output_px=int(settings.get("output_px",1600))
    if not 128<=output_px<=6000:raise ValueError("Impression output width must be between 128 and 6000 pixels.")
    margin=float(np.clip(settings.get("margin",.1),0,.35));art_width=round(output_px*(1-2*margin));art_height=round(art_width*img.height/img.width)
    page_height=art_height+round(2*margin*output_px)
    if page_height>8000:raise ValueError("Impression aspect ratio exceeds the 8000-pixel page limit.")
    img=img.resize((art_width,art_height),Image.Resampling.LANCZOS);alpha=alpha.resize(img.size,Image.Resampling.LANCZOS)
    composite=Image.new('RGB',(output_px,page_height),paper);offset=(round(margin*output_px),round(margin*output_px));composite.paste(img,offset)
    alpha_page=Image.new('L',composite.size,0);alpha_page.paste(alpha,offset)
    rgba=Image.new('RGBA',composite.size,ImageColor.getrgb(settings.get("pigment","#243530"))+(0,));rgba.putalpha(alpha_page)
    print_width=float(settings.get("print_width_mm",150.))
    if not 1<=print_width<=2000:raise ValueError("Authored page width must be 1–2000 mm.")
    magnification=(print_width*(1-2*margin)/dimensions[0]) if dimensions else None
    if settings.get("scale_bar"):
        if dimensions is None:raise ValueError("Uncalibrated impressions cannot have a physical source scale bar.")
        if rotation%180!=0:raise ValueError("Source scale bars require 0° or 180° orientation; rotate after export if needed.")
        bar_mm=dimensions[0]/5;bar_pixels=round(art_width/5)
        draw=ImageDraw.Draw(composite);yy=page_height-max(15,offset[1]//2)
        draw.line((offset[0],yy,offset[0]+bar_pixels,yy),fill=settings.get("pigment","#243530"),width=max(2,output_px//600))
        draw.text((offset[0],yy-14),f"{bar_mm:.3g} mm source",fill=settings.get("pigment","#243530"))
    variant=ImpressionVariant(specimen_id=specimen_id,source_id=specimen["source_id"],source_version=version,source_sha256=source_hash,
                              settings=settings,seed=int(settings.get("seed",7)),pixel_size=composite.size,
                              print_size_mm=(print_width,print_width*composite.height/composite.width),reproduction_magnification=magnification,
                              source_dimensions_mm=dimensions,palette={"pigment":settings.get("pigment","#243530"),"paper":paper},directory="",interpretation=interpretation)
    variant.directory=f"impressions/{variant.id}";directory=store.path(variant.directory);directory.mkdir(parents=True)
    composite.save(directory/"print.png",dpi=(output_px/print_width*25.4,)*2);rgba.save(directory/"ink-transparent.png")
    alpha_page.save(directory/"coverage.png")
    for maximum,name in ((480,"thumbnail.webp"),(1200,"display.webp")):
        smaller=composite.copy();smaller.thumbnail((maximum,maximum));smaller.save(directory/name,quality=90)
    np.savez_compressed(directory/"artistic_layers.npz",coverage=coverage,**layers)
    # Public interactive data is only generated when surface display is enabled.
    step=max(1,int(np.ceil(max(height.shape)/192)))
    (directory/"surface-preview.json").write_text(json.dumps({"height":height[::step,::step].tolist(),"mask":mask[::step,::step].astype(int).tolist(),
                                                           "width":height[::step,::step].shape[1],"height_px":height[::step,::step].shape[0],
                                                           "interpretation":interpretation,"units":"relative display values"}),encoding="utf-8")
    variant.exports={"print":"print.png","transparent":"ink-transparent.png","coverage":"coverage.png"}
    (directory/"variant.json").write_text(json.dumps(variant.model_dump(mode="json"),indent=2),encoding="utf-8")
    store.save("impressions",variant)
    specimen["impression_ids"].append(variant.id)
    if not specimen["cover_id"]:specimen["cover_id"]=variant.id
    store.save("specimens",specimen)
    return variant.model_dump(mode="json")
