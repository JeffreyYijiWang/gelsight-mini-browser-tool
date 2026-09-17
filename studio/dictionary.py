"""Owner-only specimen revisions and allowlisted static publication."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil

from .records import Specimen, uid, now

PUBLIC_ASSETS={"impression","interactive_ink","surface","material","physical_relief"}
DOWNLOADS={"print_png","transparent_png","height_npy","stl","3mf","material_glb"}
EDITABLE={"title","category","tags","body_region","common_name","scientific_name","collection_timestamp","public_location","notes",
          "cover_id","material_id","print_project_id","related_ids","public_assets","downloads","license","attribution","fabrication_status"}


def create_specimen(store,source_id,title=None,source_kind="patch",category="other"):
    source=store.get("patches" if source_kind=="patch" else "frames",source_id)
    title=title or source.get("name",source.get("source_name","Untitled impression"))
    stem=re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-')[:50] or "specimen"
    short=uid()[:8]
    dimensions=None
    if source_kind=="patch" and source.get("pixel_spacing"):
        dimensions=((source["width"]-1)*source["pixel_spacing"][0],(source["height"]-1)*source["pixel_spacing"][1])
    session=store.get("sessions",source["session_id"]) if source.get("session_id") else {}
    record=Specimen(slug=stem+'-'+short,accession='TD-'+short.upper(),title=title,source_id=source_id,source_kind=source_kind,
                    category=category,body_region=source.get("region") if source.get("region") not in (None,"custom") else None,
                    calibration_status=source.get("state","uncalibrated"),source_dimensions_mm=dimensions,
                    synthetic=source.get("synthetic",session.get("synthetic",False)),
                    atlas_id=next((p['atlas_id'] for p in source.get('provenance',[]) if p.get('atlas_id')),None))
    return store.save("specimens",record)


def edit_specimen(store,specimen_id,changes):
    unknown=set(changes)-EDITABLE
    if unknown:raise ValueError("These specimen fields are immutable or unknown: "+', '.join(sorted(unknown)))
    current=store.get("specimens",specimen_id)
    record=Specimen(**{**current,**changes,"updated_at":now()})
    if not set(record.public_assets)<=PUBLIC_ASSETS or not set(record.downloads)<=DOWNLOADS:raise ValueError("Unknown public asset or download permission.")
    if record.cover_id and record.cover_id not in record.impression_ids:raise ValueError("Cover impression must belong to this specimen.")
    if not record.title.strip():raise ValueError("Specimen title cannot be empty.")
    if len(record.title)>200 or len(record.notes)>12000:raise ValueError("Title/story exceeds the display budget.")
    return store.save("specimens",record)


def prepare_public_entry(store,specimen_id,preview=False):
    """Build public data from explicit fields, never by redacting a private record."""
    specimen=Specimen(**store.get("specimens",specimen_id))
    if not specimen.cover_id:raise ValueError("Generate and choose a cover impression before public preview or publication.")
    variant=store.get("impressions",specimen.cover_id)
    revision=uid();directory=store.path(f"publications/{revision}");directory.mkdir(parents=True)
    assets={};downloads={}
    def copy(source,key,name):
        src=Path(source)
        if not src.is_file():raise ValueError(f"Selected public asset is missing: {key}. Regenerate its derivative.")
        shutil.copyfile(src,directory/name)
        return name
    impression_dir=store.path(variant["directory"])
    # The public card itself needs an approved impression display.
    if "impression" not in specimen.public_assets:raise ValueError("A public specimen requires its cover impression to be enabled.")
    for key,name in (("thumbnail","thumbnail.webp"),("impression","display.webp")):
        assets[key]=copy(impression_dir/name,key,name)
    if "interactive_ink" in specimen.public_assets or "surface" in specimen.public_assets:
        if "surface" in specimen.public_assets and specimen.source_kind=="frame":
            raise ValueError("An image-based artistic impression has no source height geometry. Disable the Surface view or import/reconstruct a height field.")
        assets["surface_data"]=copy(impression_dir/"surface-preview.json","interactive ink","surface.json")
    if "material" in specimen.public_assets:
        if not specimen.material_id:raise ValueError("Choose a MaterialAsset before enabling the material sphere.")
        m=store.get("materials",specimen.material_id);base=store.path(m["directory"])
        if not (base/"sphere-preview.png").exists():
            from .materials import sphere_thumbnail,png
            _,arrays=store.patch(m["patch_id"])
            png(base/"sphere-preview.png",sphere_thumbnail(arrays["height"],arrays["mask"],m["descriptor"]["base_color"]))
        for name in ("surface.json","normal_opengl.png","normal_full_opengl.png","roughness.png","bump.png","preview.png","sphere-preview.png"):
            assets["material_"+name]=copy(base/name,"material",'material-'+name)
        # Do not copy material.json: it contains private source linkage.
        assets["material_descriptor"]={"base_color":m["descriptor"]["base_color"],"roughness":m["descriptor"]["roughness"],"ior":m["descriptor"]["ior"],
                                       "source_status":m["state"],"synthetic":m["synthetic"],"roughness_source":m["descriptor"]["roughness_source"]}
    if "physical_relief" in specimen.public_assets:
        if not specimen.print_project_id:raise ValueError("Choose a PrintProject before enabling physical relief.")
        p=store.get("prints",specimen.print_project_id)
        raw=json.loads((store.path(p["directory"])/"mesh-preview.json").read_text(encoding="utf-8"))
        public_mesh={k:raw[k] for k in ("vertices","faces","full_triangles","preview_triangles","units")}
        (directory/"relief.json").write_text(json.dumps(public_mesh),encoding="utf-8");assets["physical_relief"]="relief.json"
        assets["relief_status"]={"geometry_valid":bool((p.get("report") or {}).get("geometry_valid")),"fabrication_status":specimen.fabrication_status,
                                 "is_photograph":False}
    for key in specimen.downloads:
        if key in ("print_png","transparent_png"):
            name="print.png" if key=="print_png" else "ink-transparent.png"
            downloads[key]=copy(impression_dir/name,key,name)
        elif key=="height_npy":
            if "surface" not in specimen.public_assets or specimen.source_kind!="patch":raise ValueError("Height download requires an enabled source surface.")
            patch,a=store.patch(specimen.source_id)
            import numpy as np
            np.save(directory/"height.npy",a["height"]);ImageMask=__import__('PIL.Image',fromlist=['Image'])
            ImageMask.fromarray(a["mask"].astype(np.uint8)*255).save(directory/"height-valid-mask.png")
            downloads[key]="height.npy";downloads["height_valid_mask"]="height-valid-mask.png"
            (directory/"height-metadata.json").write_text(json.dumps({"units":patch.units,"pixel_spacing":patch.pixel_spacing,"sign":"positive object relief outwards","height_reference":patch.height_reference,"calibration_status":patch.state,"version":patch.version},indent=2),encoding="utf-8")
            downloads["height_metadata"]="height-metadata.json"
        elif key in ("stl","3mf"):
            if "physical_relief" not in specimen.public_assets:raise ValueError("Enable physical relief before allowing model downloads.")
            p=store.get("prints",specimen.print_project_id)
            if not (p.get("report") or {}).get("geometry_valid") or key not in p.get("exports",{}):raise ValueError("A failed or unverified print export cannot be published as a manufacturing model.")
            name=p["exports"][key];downloads[key]=copy(store.path(p["directory"])/name,key,name)
        elif key=="material_glb":
            if "material" not in specimen.public_assets:raise ValueError("Enable material display before allowing its GLB download.")
            m=store.get("materials",specimen.material_id)
            downloads[key]=copy(store.path(m["directory"])/"material_baked.glb",key,"material-baked.glb")
    public={"id":specimen.id,"slug":specimen.slug,"accession":specimen.accession,"title":specimen.title,"category":specimen.category,
            "tags":specimen.tags,"body_region":specimen.body_region,"common_name":specimen.common_name,"scientific_name":specimen.scientific_name,
            "collection_timestamp":specimen.collection_timestamp,"public_location":specimen.public_location,"notes":specimen.notes,
            "source_dimensions_mm":specimen.source_dimensions_mm,"calibration_status":specimen.calibration_status,"synthetic":specimen.synthetic,
            "related_ids":specimen.related_ids,"license":specimen.license,"attribution":specimen.attribution,"assets":assets,"downloads":downloads,
            "revision":revision,"impression":{"settings":variant["settings"],"interpretation":variant["interpretation"],"palette":variant["palette"],
                                            "pixel_size":variant["pixel_size"],"print_size_mm":variant["print_size_mm"],"magnification":variant["reproduction_magnification"]},
            "views":[v for v in ("impression","surface","material","physical_relief") if v in specimen.public_assets],
            "interactive_ink":"interactive_ink" in specimen.public_assets}
    (directory/"entry.json").write_text(json.dumps(public,indent=2,allow_nan=False),encoding="utf-8")
    # Private registry points to public snapshot; it is never copied into the site.
    store.save("publications",{"id":revision,"specimen_id":specimen_id,"directory":str(directory.relative_to(store.root)),"preview":preview,"created_at":now()})
    return public


def publish_specimen(store,specimen_id):
    public=prepare_public_entry(store,specimen_id)
    specimen=store.get("specimens",specimen_id);specimen.update(state="published",published_revision=public["revision"],updated_at=now())
    store.save("specimens",specimen)
    return {"specimen":specimen,"public":public,"hosting_status":"selected for the next public build; deploy separately"}


def unpublish_specimen(store,specimen_id,archive=False):
    specimen=store.get("specimens",specimen_id);specimen.update(state="archived" if archive else "draft",updated_at=now())
    return store.save("specimens",specimen)


def build_dictionary(store,output,preview_ids=None,branding=None,origin=None):
    branding=branding or {"title":"Texture Dictionary","subtitle":"A collection of surfaces, recorded through touch.",
                          "intro":"An impression holds a small encounter: a ridge, a fold, the grain of something touched."}
    output=Path(output).resolve()
    if output.exists() and any(output.iterdir()) and not (output/".dictionary-build").exists():
        raise ValueError("Refusing to replace a non-dictionary output directory. Choose an empty folder.")
    stage=output.parent/(output.name+"-stage-"+uid());stage.mkdir(parents=True)
    template=Path(__file__).resolve().parents[1]/"texture-dictionary/site"
    shutil.copytree(template,stage,dirs_exist_ok=True)
    vendor=Path(__file__).parent/"web/vendor"
    if vendor.exists():shutil.copytree(vendor,stage/"vendor",dirs_exist_ok=True)
    viewer=Path(__file__).parent/"web/viewer.js"
    if viewer.exists():shutil.copyfile(viewer,stage/"viewer.js")
    entries=[]
    if preview_ids is not None:
        entries=[prepare_public_entry(store,i,preview=True) for i in preview_ids]
    else:
        for specimen in store.list("specimens"):
            if specimen["state"]!="published" or not specimen["published_revision"]:continue
            publication=store.get("publications",specimen["published_revision"])
            entries.append(json.loads((store.path(publication["directory"])/"entry.json").read_text(encoding="utf-8")))
    for entry in entries:
        publication=store.get("publications",entry["revision"])
        target=stage/"assets"/entry["revision"];shutil.copytree(store.path(publication["directory"]),target)
        entry["asset_base"]="assets/"+entry["revision"]+"/"
    collection={"branding":branding,"preview":preview_ids is not None,"entries":entries,"raw_captures_included":False}
    (stage/"collection.json").write_text(json.dumps(collection,indent=2),encoding="utf-8")
    template_html=(stage/"index.html").read_text(encoding="utf-8")
    def page(title,description,root,entry=None):
        value=template_html.replace("__TITLE__",html.escape(title)).replace("__DESCRIPTION__",html.escape(description,quote=True)).replace("__ROOT__",root)
        image=None
        if entry:image=entry["asset_base"]+entry["assets"]["impression"]
        if image and origin:
            value=value.replace('<!-- SOCIAL_IMAGE -->',f'<meta property="og:image" content="{html.escape(origin.rstrip("/")+"/"+image,quote=True)}">')
        return value
    (stage/"index.html").write_text(page(branding["title"],branding["subtitle"],"./"),encoding="utf-8")
    for route in ("about","compare"):
        folder=stage/route;folder.mkdir(exist_ok=True)
        (folder/"index.html").write_text(page(route.title()+" · "+branding["title"],branding["subtitle"],"../"),encoding="utf-8")
    for entry in entries:
        folder=stage/"specimens"/entry["slug"];folder.mkdir(parents=True)
        (folder/"index.html").write_text(page(entry["title"]+" · "+branding["title"],entry["notes"][:160] or entry["impression"]["interpretation"],"../../",entry),encoding="utf-8")
    # Do not leave template-only placeholders or an owner/admin route in public output.
    (stage/".dictionary-build").write_text("Generated allowlisted static collection; safe to replace by build_dictionary.\n",encoding="utf-8")
    (stage/"_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n/collection.json\n  Cache-Control: no-cache\n",encoding="utf-8")
    (stage/"exhibition-manifest.json").write_text(json.dumps({"title":branding["title"],"preview":preview_ids is not None,"specimens":[{"id":e["id"],"accession":e["accession"],"title":e["title"],"caption":e["notes"],"revision":e["revision"]} for e in entries],"raw_captures_included":False},indent=2),encoding="utf-8")
    if output.exists():
        # Exact resolved generated directory checked above; never traverse source inputs.
        if not output.is_relative_to(Path(__file__).resolve().parents[1]) and not output.is_relative_to(store.root):
            raise ValueError("Existing build replacement must be inside the repository or project store.")
        shutil.rmtree(output)
    stage.rename(output)
    return {"directory":str(output),"entries":len(entries),"preview":preview_ids is not None,"slugs":[e["slug"] for e in entries]}


def export_exhibition(store,selected_ids=None,branding=None):
    """Archive approved public snapshots only, with their approved assets/captions."""
    from .materials import zip_directory
    directory=store.path('exports/exhibition-'+uid())
    build_dictionary(store,directory,branding=branding)
    collection=json.loads((directory/'collection.json').read_text(encoding='utf-8'))
    if selected_ids is not None:
        selected=set(selected_ids)
        public={entry['id'] for entry in collection['entries']}
        if not selected<=public:raise ValueError('Exhibition selection must contain only approved public specimens.')
        # Reuse the snapshot build, remove all unselected entry/assets directories.
        for entry in collection['entries']:
            if entry['id'] not in selected:
                shutil.rmtree(directory/'assets'/entry['revision'])
                shutil.rmtree(directory/'specimens'/entry['slug'])
        collection['entries']=[e for e in collection['entries'] if e['id'] in selected]
        (directory/'collection.json').write_text(json.dumps(collection,indent=2),encoding='utf-8')
    entries=collection['entries']
    captions=[{'id':e['id'],'accession':e['accession'],'title':e['title'],'caption':e['notes'],'license':e['license'],'attribution':e['attribution'],'revision':e['revision']} for e in entries]
    (directory/'exhibition-manifest.json').write_text(json.dumps({'specimens':captions,'raw_captures_included':False},indent=2),encoding='utf-8')
    (directory/'README.md').write_text('# Texture Dictionary exhibition\n\nServe this folder with `python -m http.server 8080`, then open http://localhost:8080. It is a self-contained static site containing only approved public revisions and assets. Captions, credit and licenses are in exhibition-manifest.json. High-resolution downloads appear only when enabled by the owner. Displayed images are always saveable.\n',encoding='utf-8')
    return zip_directory(store,'public-exhibition',[e['id'] for e in entries],directory)
