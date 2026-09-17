"""Create local-only demo specimens. This does not approve them for publication."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from studio.store import Store
from studio.inputs import synthetic_demo,import_bytes
from studio.dictionary import create_specimen,build_dictionary
from studio.ink import create_impression

store=Store(ROOT/'studio-data')
existing=store.list('specimens')
if not existing:
    demo=synthetic_demo(store,size=96)
    for i,patch in enumerate(demo['patches']):
        specimen=create_specimen(store,patch['id'],title=['Valley study — synthetic','Shallower valleys — synthetic'][i],category='synthetic study')
        create_impression(store,specimen['id'],{'pressure':.53,'softness':.025,'dry_brush':.12,'paper_grain':.025,'pigment':'#293d32','paper':'#f1e8d5','output_px':1600})
    coin=ROOT/'gelsight_p5/captures/gelsight_demo.zip'
    if coin.exists():
        imported=import_bytes(store,coin.name,coin.read_bytes())
        specimen=create_specimen(store,imported['patch']['id'],title='Coin — bundled tactile capture',category='manufactured surface')
        create_impression(store,specimen['id'],{'pressure':.52,'softness':.025,'dry_brush':.08,'paper_grain':.025,'pigment':'#523c2b','paper':'#eee4ce','output_px':1600})
ids=[s['id'] for s in store.list('specimens') if s.get('cover_id')]
result=build_dictionary(store,ROOT/'texture-dictionary/preview',preview_ids=ids)
print(result)
