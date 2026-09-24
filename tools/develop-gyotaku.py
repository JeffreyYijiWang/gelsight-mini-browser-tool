"""Make private, reproducible print studies from an existing collected specimen.

Usage: python tools/develop-gyotaku.py --specimen ID --data studio-data
This appends three variants, without changing the cover or publication state.
"""
import argparse
import html
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.ink import PRESETS, create_impression, pressure_proof, resolve_settings
from studio.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='studio-data')
    parser.add_argument('--specimen', required=True)
    parser.add_argument('--output', type=Path, default=Path('examples/generated/gyotaku'))
    args = parser.parse_args()
    store = Store(args.data)
    specimen = store.get('specimens', args.specimen)
    args.output.mkdir(parents=True, exist_ok=True)
    studies = []
    for preset in PRESETS[:3]:
        settings = dict(preset['settings'], output_px=2400, print_width_mm=180, margin=.13, pressure=.55, seed=7)
        variant = next((v for v in store.list('impressions') if v['specimen_id']==args.specimen and v['settings']==resolve_settings(settings)), None)
        if variant is None:
            variant = create_impression(store, args.specimen, settings)
        destination = args.output/preset['id']
        destination.mkdir(exist_ok=True)
        for name in ('print.png', 'ink-transparent.png', 'coverage.png', 'variant.json', 'process.json', 'artistic_layers.npz'):
            shutil.copy2(store.path(variant['directory'])/name, destination/name)
        proof = pressure_proof(store, args.specimen, variant['settings'])
        proof.save(destination/'pressure-proof.png', dpi=(152.4, 152.4))
        studies.append(dict(name=preset['name'], folder=preset['id'], variant_id=variant['id'], settings=variant['settings']))
    summary = dict(specimen_id=specimen['id'], title=specimen['title'], source_kind=specimen['source_kind'],
                   source_dimensions_mm=specimen['source_dimensions_mm'], studies=studies,
                   publication='Private local studies. No public entries changed.')
    (args.output/'studies.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    cards = ''.join(f'<section><h2>{html.escape(s["name"])}</h2><a href="{s["folder"]}/print.png"><img src="{s["folder"]}/print.png" alt="{html.escape(s["name"])} impression"></a><p><a href="{s["folder"]}/print.png">Master PNG</a> · <a href="{s["folder"]}/ink-transparent.png">Transparent ink</a> · <a href="{s["folder"]}/pressure-proof.png">Pressure proof</a> · <a href="{s["folder"]}/variant.json">Recipe</a></p></section>' for s in studies)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Local print studies</title>
<style>body{{margin:0;background:#f2ebdc;color:#26352e;font:17px Georgia,serif;padding:5vw}}main{{max-width:1450px;margin:auto}}h1{{font-weight:400;font-size:clamp(30px,4vw,60px)}}h2{{font-size:20px;font-weight:400}}p{{line-height:1.7;max-width:850px}}a{{color:inherit}}.studies{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:28px;margin-top:50px}}img{{width:100%;height:auto}}small{{font:12px Arial,sans-serif;letter-spacing:.1em}}</style>
<main><small>TEXTURE DICTIONARY / PRIVATE PRINT STUDIES</small><h1>{html.escape(specimen['title'])}</h1><p>Three gyotaku-inspired digital impressions of the same provided tactile relief. Ink and paper are authored layers. No generated replacement surface is used.</p><p>Source physical scale: {html.escape(str(specimen['source_dimensions_mm']) if specimen['source_dimensions_mm'] else 'unknown; the 180 mm page width is an authored display size')}. These studies remain local.</p><div class="studies">{cards}</div></main></html>'''
    (args.output/'index.html').write_text(page, encoding='utf-8')
    print(json.dumps(dict(output=str(args.output.resolve()), **summary), indent=2))


if __name__ == '__main__':
    main()
