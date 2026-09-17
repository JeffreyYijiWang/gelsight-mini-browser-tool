"""Reproducible examples, separate from private captures and public approval."""
from pathlib import Path
import json
import shutil

from .inputs import synthetic_demo
from .materials import build_material,export_textures,export_gallery,zip_directory
from .printing import make_print
from .atlas import build_atlas
from .dictionary import create_specimen,edit_specimen,build_dictionary
from .ink import create_impression


def generate_examples(store,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    demo=synthetic_demo(store,size=64);a,b=demo['patches']
    material=build_material(store,a['id'],{'name':'Synthetic valley material'})
    textures=export_textures(store,material['id']);gallery=export_gallery(store,[material['id']])
    tile=make_print(store,a['id'],{'name':'Synthetic relief tile','xy_scale':4,'z_scale':6,'base_mm':2,'tolerance_mm':.05,'triangle_budget':100000})
    coupon=make_print(store,a['id'],{'name':'Synthetic paired comparison coupon','shape':'coupon','paired_id':b['id'],'xy_scale':2,'z_scale':3,'base_mm':2,'tolerance_mm':.06,'triangle_budget':300000})
    atlas=build_atlas(store,demo['session']['frame_ids'])
    specimen=create_specimen(store,a['id'],'Synthetic valley specimen',category='synthetic study')
    impression=create_impression(store,specimen['id'],{'output_px':1600,'pressure':.55,'scale_bar':True})
    edit_specimen(store,specimen['id'],{'material_id':material['id'],'print_project_id':tile['id'],'public_assets':['impression','surface','interactive_ink','material','physical_relief']})
    preview=build_dictionary(store,store.path('example-dictionary-preview'),preview_ids=[specimen['id']])
    for name,record in (('textures.zip',textures),('static-gallery.zip',gallery)):
        shutil.copyfile(store.path(record['file']),output/name)
    for name,record in (('relief-tile',tile),('paired-coupon',coupon)):
        result=zip_directory(store,'print-package',[record['id']],store.path(record['directory']))
        shutil.copyfile(store.path(result['file']),output/(name+'.zip'))
        for file in ('relief_mm.stl','relief_mm.3mf','overview.png'):
            source=store.path(record['directory'])/file
            if source.exists():shutil.copyfile(source,output/(name+'-'+file))
    result={'synthetic':True,'not_human_data':True,'patch_ids':[a['id'],b['id']],'material_id':material['id'],'tile':tile['report'],
            'paired_coupon':coupon['report'],'atlas':{'islands':len(atlas['islands']),'accepted_links':sum(l['accepted'] for l in atlas['links'])},
            'dictionary_preview':preview,'specimen_state':'draft','physical_printing':'unverified','slicing':'unverified','photoshop_import':'unverified','deployment':'not performed by example generation'}
    (output/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
