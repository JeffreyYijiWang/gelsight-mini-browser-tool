"""Private image typologies: explicit descriptors -> PCA -> real ShuffleSnap."""
from __future__ import annotations

import hashlib
import html
import importlib.metadata
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .records import uid, now

KINDS = ('frames', 'patches', 'impressions')


def catalog(store):
    sessions = {s['id']: s for s in store.list('sessions')}
    specimens = {s['id']: s for s in store.list('specimens')}
    patches = {p['id']: p for p in store.list('patches')}
    result = []
    for frame in store.list('frames'):
        if frame['kind'] != 'rgb':
            continue
        session = sessions.get(frame['session_id'], {})
        baseline = frame['id']==session.get('baseline_id') or frame['settings'].get('capture_role')=='baseline'
        result.append(dict(kind='frames', id=frame['id'], name=Path(frame['source_name']).stem,
                           session_id=frame['session_id'], synthetic=session.get('synthetic', False),
                           baseline=baseline, created_at=frame['created_at']))
    for patch in patches.values():
        result.append(dict(kind='patches', id=patch['id'], name=patch['name'], session_id=patch['session_id'],
                           synthetic=patch['synthetic'], baseline=False, created_at=patch['created_at']))
    for impression in store.list('impressions'):
        specimen = specimens.get(impression['specimen_id'], {})
        patch = patches.get(specimen.get('source_id'), {})
        result.append(dict(kind='impressions', id=impression['id'], name=specimen.get('title', 'Ink impression'),
                           session_id=patch.get('session_id'), synthetic=specimen.get('synthetic', False),
                           baseline=False, created_at=impression['created_at']))
    return result


def source_image(store, kind, record_id):
    if kind not in KINDS:
        raise ValueError('Typologies accept tactile RGB frames, height patches and ink impressions.')
    record = store.get(kind, record_id)
    if kind=='frames':
        if record['kind']!='rgb':
            raise ValueError('Only RGB frames are images for this comparison.')
        path = store.path(record['raw_file'])
    elif kind=='impressions':
        path = store.path(record['directory'])/'print.png'
    else:
        patch, arrays = store.patch(record_id)
        values, mask = arrays['height'], arrays['mask'].astype(bool)
        mask &= np.isfinite(values)
        if not mask.any():
            raise ValueError('Surface has no valid samples to compare.')
        low, high = np.percentile(values[mask], [1, 99])
        gray = np.clip((values-low)/max(high-low, 1e-12), 0, 1)
        gray[~mask] = .5
        picture = Image.fromarray(np.rint(gray*255).astype(np.uint8)).convert('RGB')
        return picture, hashlib.sha256(store.path(patch.arrays).read_bytes()).hexdigest()
    with Image.open(path) as opened:
        opened.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        picture = opened.convert('RGB')
    return picture, hashlib.sha256(path.read_bytes()).hexdigest()


def descriptor(picture, mode):
    rgb = np.asarray(picture.resize((64, 64), Image.Resampling.LANCZOS), np.float32)/255
    if mode=='appearance':
        return cv2.resize(rgb, (8, 8), interpolation=cv2.INTER_AREA).ravel().astype(np.float64)
    if mode!='texture':
        raise ValueError('Comparison must be texture or appearance.')
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = (gray-gray.mean())/max(float(gray.std()), .02)
    coarse = cv2.dct(gray)[:8, :8].ravel()[1:]/64
    gx, gy = np.gradient(gray)
    magnitude = np.hypot(gx, gy)
    angle = (np.arctan2(gy, gx)+np.pi)%(2*np.pi)
    histograms = []
    for y in (0, 32):
        for x in (0, 32):
            hist = np.histogram(angle[y:y+32, x:x+32], bins=12, range=(0, 2*np.pi),
                                weights=magnitude[y:y+32, x:x+32])[0]
            histograms.extend(hist/max(float(hist.sum()), 1e-8))
    contrast = np.array([gray[y:y+16, x:x+16].std() for y in range(0, 64, 16) for x in range(0, 64, 16)])
    groups = [coarse, np.array(histograms), contrast]
    return np.concatenate([g/max(float(np.linalg.norm(g)), 1e-9) for g in groups]).astype(np.float64)


def project_features(features):
    features = np.asarray(features, np.float64)
    centered = features-features.mean(axis=0)
    # Small feature covariance avoids allocating an N-by-N distance matrix.
    values, vectors = np.linalg.eigh(centered.T@centered)
    basis = vectors[:, -2:][:, ::-1]
    for i in range(2):
        pivot = np.argmax(np.abs(basis[:, i]))
        if basis[pivot, i] < 0:
            basis[:, i] *= -1
    scores = centered@basis
    points = np.full((len(features), 2), .5)
    for axis in range(2):
        span = np.ptp(scores[:, axis])
        if span > 1e-10:
            points[:, axis] = (scores[:, axis]-scores[:, axis].min())/span
    variance = np.maximum(values, 0)
    fraction = float(variance[-2:].sum()/variance.sum()) if variance.sum()>1e-15 else 0.
    return points, fraction


def build_typology(store, items, name='Texture typology', settings=None, progress=None):
    import shufflesnap
    settings = settings or {}
    if not isinstance(items, list) or not 2<=len(items)<=2000:
        raise ValueError('Select between 2 and 2000 images for a typology.')
    keys = [(item['kind'], item['id']) for item in items]
    if len(set(keys)) != len(keys):
        raise ValueError('Each image can appear only once in a typology.')
    mode = settings.get('comparison', 'texture')
    columns = int(settings.get('columns') or math.ceil(math.sqrt(len(items)*4/3)))
    if not 1<=columns<=100:
        raise ValueError('Choose 1–100 columns, or 0 for automatic.')
    rows = math.ceil(len(items)/columns)
    lookup = {(item['kind'], item['id']):item for item in catalog(store)}
    for key in keys:
        if key not in lookup:
            raise ValueError('A selected image is no longer available.')
    record_id = uid()
    directory = store.path('typologies/'+record_id)
    directory.mkdir(parents=True)
    features, entries = [], []
    for i, (kind, item_id) in enumerate(keys):
        picture, digest = source_image(store, kind, item_id)
        features.append(descriptor(picture, mode))
        picture.thumbnail((384, 384), Image.Resampling.LANCZOS)
        filename = f'image-{i:04}.webp'
        picture.save(directory/filename, quality=88)
        entries.append({**lookup[kind, item_id], 'source_sha256':digest, 'image':filename})
        if progress:
            progress(.1+.55*(i+1)/len(keys), f'Comparing image {i+1} of {len(keys)}')
    points, fraction = project_features(features)
    if progress:
        progress(.7, 'ShuffleSnap: assigning similar images to distinct grid cells')
    # Pin the released API and explicitly remove 0.3.0's default inset. Run to
    # convergence for reproducibility; the enclosing worker is cancellable.
    grid, assignment, shape = shufflesnap.snap_to_grid(points, width=columns, height=rows,
                            margin=0., cleanup_seconds=None, num_threads=2)
    assignment = np.asarray(assignment, dtype=int)
    if len(set(assignment.tolist())) != len(keys) or np.any(assignment<0) or np.any(assignment>=columns*rows):
        raise ValueError('ShuffleSnap returned an invalid grid assignment.')
    for i, entry in enumerate(entries):
        entry.update(cell=int(assignment[i]), row=int(assignment[i]//columns), column=int(assignment[i]%columns), point=points[i].tolist())
    record = dict(id=record_id, created_at=now(), name=str(name).strip()[:160] or 'Texture typology',
        directory='typologies/'+record_id, width=columns, height=rows, items=entries,
        settings=dict(comparison=mode, columns=columns, feature_version=1, projection='PCA',
                      solver='shufflesnap', solver_version=importlib.metadata.version('shufflesnap'),
                      margin=0., cleanup_seconds=None, num_threads=2),
        explained_variance_fraction=fraction, assignment=assignment.tolist(),
        interpretation='Visual similarity of selected images; not physical material identity, calibrated distance or a health assessment.',
        exports=dict(sheet='contact-sheet.png', collection='index.html', manifest='typology.json'))
    _contact_sheet(directory, record)
    _standalone(directory, record)
    (directory/'typology.json').write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
    np.savez_compressed(directory/'features.npz', features=np.asarray(features), points=points, grid_points=grid)
    store.save('typologies', record)
    return record


def _contact_sheet(directory, record):
    columns, rows = record['width'], record['height']
    tile = min(260, int(math.sqrt(24_000_000/(columns*rows))), 8000//max(columns, rows))
    if tile < 32:
        raise ValueError('Grid is too elongated for a readable contact sheet. Use more columns.')
    sheet = Image.new('RGB', (columns*tile, rows*tile), '#f1ecdf')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=max(8, min(14, tile//16)))
    for index, entry in enumerate(record['items']):
        with Image.open(directory/entry['image']) as picture:
            inset = max(2, tile//32)
            thumb = ImageOps.contain(picture.convert('RGB'), (tile-2*inset, tile-2*inset-20))
            x, y = entry['column']*tile, entry['row']*tile
            sheet.paste(thumb, (x+(tile-thumb.width)//2, y+inset))
            # Numbered key avoids losing long or non-Latin names in small cells;
            # complete names remain in the interactive page and JSON manifest.
            label = str(index+1).zfill(3)
            draw.text((x+inset, y+tile-18), label, font=font, fill='#26372f')
    sheet.save(directory/'contact-sheet.png')


def _standalone(directory, record):
    figures = []
    for i, entry in enumerate(record['items']):
        figures.append(f'<a href="{entry["image"]}" target="_blank" rel="noopener" style="grid-column:{entry["column"]+1};grid-row:{entry["row"]+1}"><img loading="lazy" src="{entry["image"]}" alt="{html.escape(entry["name"], quote=True)}"><span>{i+1:03} {html.escape(entry["name"])}<small>{entry["kind"]}{" · synthetic" if entry["synthetic"] else ""}</small></span></a>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title><style>
body{background:#eee9dc;color:#26372f;font:16px system-ui;margin:28px}h1{font:40px Georgia}p{max-width:900px;line-height:1.6}a{color:inherit}main{overflow:auto}section{display:grid;gap:12px;grid-template-columns:repeat(__COLS__,minmax(120px,1fr));min-width:__MIN__px}section a{background:#faf6ec;text-decoration:none;padding:8px}img{display:block;width:100%;aspect-ratio:1;object-fit:contain}span,small{display:block;font-size:12px;overflow-wrap:anywhere}small{opacity:.6}a:focus-visible{outline:3px solid #8b682d}</style><h1>__TITLE__</h1><p>Private image typology · visual descriptors → PCA → <a href="https://github.com/kylemcdonald/shufflesnap">ShuffleSnap</a>. Nearby images share visual features, not a measured material class. The recorded order remains fixed; click an image to inspect it.</p><p><a href="contact-sheet.png" download>Download contact sheet</a> · <a href="typology.json" download>Download layout and source references</a></p><main><section>__ITEMS__</section></main></html>'''
    page = page.replace('__TITLE__', html.escape(record['name'])).replace('__COLS__', str(record['width'])).replace('__MIN__', str(record['width']*132)).replace('__ITEMS__', ''.join(figures))
    (directory/'index.html').write_text(page, encoding='utf-8')
