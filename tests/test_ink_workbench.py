import hashlib
import io

import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from studio import ink_v1
from studio.api import create_app
from studio.dictionary import create_specimen
from studio.ink import create_impression, preview_ink, pressure_proof, render_ink, resolve_settings
from studio.records import SurfacePatch
from studio.store import Store


def specimen(store, metric=False):
    y, x = np.mgrid[:41, :61]
    h = .2*np.sin(x*.3) + .1*np.cos(y*.4)
    mask = np.ones(h.shape, bool)
    mask[12:19, 22:30] = False
    patch = SurfacePatch(name='Analytic ink fixture', width=61, height=41, synthetic=True,
        **dict(state='calibrated', units='mm', pixel_spacing=(.4, .2),
               validation_notes='Analytic fixture; no sensor claim') if metric else {})
    store.put_patch(patch, h, mask)
    return create_specimen(store, patch.id, 'Analytic ink fixture'), patch


def hashes(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}


def test_clean_effects_are_removable_and_relief_polarity_handles_missing_data():
    y, x = np.mgrid[:40, :50]
    h = x.astype(float)*.02
    h[10:15, 12:16] = np.nan
    mask = np.isfinite(h)
    original = h.copy()
    plain, coverage, _ = render_ink(h, mask, dict(style='clean', dry_brush=0, paper_grain=0))
    decorated, same, _ = render_ink(h, mask, dict(style='clean', dry_brush=.9, spread=3, edge_softness=5, paper_grain=.1))
    assert np.array_equal(plain, decorated) and np.array_equal(coverage, same)
    assert not coverage[~mask].any()
    positive, _, _ = render_ink(h, mask, dict(style='relief'), spacing=(.1, .2))
    negative, _, _ = render_ink(h, mask, dict(style='relief', invert=True), spacing=(.1, .2))
    assert not np.array_equal(positive[mask], negative[mask])
    assert np.array_equal(h, original, equal_nan=True)


def test_master_and_preview_agree_with_complete_replay_and_dpi(tmp_path):
    store = Store(tmp_path)
    s, patch = specimen(store)
    source = store.path(patch.arrays).read_bytes()
    settings = dict(output_px=384, pressure=.68, rotation=31, crop=[.1, .2, .9, 1],
                    pigment='#314f71', dry_brush=.3, seed=827, print_width_mm=120)
    preview = preview_ink(store, s['id'], settings)
    first = create_impression(store, s['id'], settings)
    second = create_impression(store, s['id'], first['settings'])
    a, b = store.path(first['directory']), store.path(second['directory'])
    with Image.open(a/'print.png') as page:
        assert np.array_equal(np.asarray(preview), np.asarray(page))
        assert page.info['dpi'][0] == pytest.approx(384/120*25.4, abs=.02)
        with Image.open(a/'ink-transparent.png') as transparent, Image.open(a/'coverage.png') as mask:
            assert np.array_equal(np.asarray(transparent)[..., 3], np.asarray(mask))
            assert transparent.info['dpi'] == page.info['dpi'] == mask.info['dpi']
    assert (a/'print.png').read_bytes() == (b/'print.png').read_bytes()
    assert source == store.path(patch.arrays).read_bytes()
    assert first['settings'] == resolve_settings(settings) and first['settings']['engine_version'] == 2
    with np.load(a/'artistic_layers.npz') as layers:
        assert {'coverage', 'base_coverage', 'valid_mask', 'dry_brush', 'paper_grain'} <= set(layers.files)


def test_metric_page_aspect_magnification_and_rotated_scale_bar(tmp_path):
    store = Store(tmp_path)
    s, _ = specimen(store, metric=True)
    settings = dict(output_px=600, print_width_mm=150, margin=.1)
    horizontal = create_impression(store, s['id'], settings)
    vertical = create_impression(store, s['id'], {**settings, 'rotation':90, 'scale_bar':True})
    assert horizontal['source_dimensions_mm'] == [24., 8.]
    assert horizontal['pixel_size'] == [600, 281]
    assert horizontal['reproduction_magnification'] == pytest.approx(479/24*150/600)
    assert vertical['reproduction_magnification'] == pytest.approx(horizontal['reproduction_magnification']*3)
    assert vertical['pixel_size'][1] > vertical['pixel_size'][0]*2.5
    diagonal = create_impression(store, s['id'], {**settings, 'rotation':45, 'scale_bar':True})
    assert diagonal['reproduction_magnification'] == pytest.approx(479/(32/np.sqrt(2))*150/600)


def test_degenerate_crop_and_unknown_physical_scale_are_rejected_consistently(tmp_path):
    store = Store(tmp_path)
    s, _ = specimen(store)
    for fn in (preview_ink, create_impression, pressure_proof):
        with pytest.raises(ValueError, match='two samples'):
            fn(store, s['id'], dict(crop=[.999, 0, 1, 1]))
        with pytest.raises(ValueError, match='scale bar'):
            fn(store, s['id'], dict(scale_bar=True))
    with pytest.raises(ValueError, match='page limit'):
        preview_ink(store, s['id'], dict(output_px=6000, crop=[0, 0, .04, 1]))


def test_proof_is_read_only_and_pressure_panels_are_distinct(tmp_path):
    store = Store(tmp_path)
    s, _ = specimen(store)
    before = hashes(tmp_path)
    proof = pressure_proof(store, s['id'], dict(output_px=400, style='clean'))
    assert proof.width == 1800 and hashes(tmp_path) == before
    picture = np.asarray(proof)
    assert not np.array_equal(picture[110:-110, :600], picture[110:-110, 600:1200])
    assert not store.list('impressions') and store.get('specimens', s['id'])['state'] == 'draft'
    with pytest.raises(ValueError, match='ink or clean'):
        pressure_proof(store, s['id'], dict(style='relief'))


def test_legacy_recipe_keeps_original_pixels(tmp_path):
    store = Store(tmp_path)
    s, _ = specimen(store)
    settings = dict(output_px=256, pressure=.4, seed=8, spread=.3, paper_grain=.04)
    original = ink_v1.create_impression(store, s['id'], settings)
    replay = create_impression(store, s['id'], {**original['settings'], 'engine_version':1})
    assert (store.path(original['directory'])/'print.png').read_bytes() == (store.path(replay['directory'])/'print.png').read_bytes()
    assert replay['settings']['engine_version'] == 1


def test_workbench_api_is_private_and_proof_has_no_side_effects(tmp_path):
    app = create_app(tmp_path)
    s, _ = specimen(Store(tmp_path))
    with TestClient(app) as client:
        assert client.get('/api/ink-settings').status_code == 401
        assert client.post(f"/api/specimens/{s['id']}/pressure-proof", json={}).status_code in (401, 403)
        client.get('/')
        headers = {'X-Studio-Token':app.state.token}
        config = client.get('/api/ink-settings').json()
        assert len(config['presets']) == 4
        before = hashes(tmp_path)
        result = client.post(f"/api/specimens/{s['id']}/pressure-proof", json={'output_px':256}, headers=headers)
        assert result.status_code == 200 and Image.open(io.BytesIO(result.content)).width == 1800
        assert hashes(tmp_path) == before


@pytest.mark.parametrize('settings', [{'seed':-1}, {'rotation':float('inf')}, {'crop':[0,0,0,1]}, {'output_px':128.5}, {'engine_version':3}, {'typo':1}])
def test_invalid_recipes_fail_early(settings):
    with pytest.raises(ValueError):
        resolve_settings(settings)
