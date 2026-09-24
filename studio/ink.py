"""Reproducible, source-preserving gyotaku-inspired digital impressions.

Version 1 remains available for replay of earlier variants. Version 2 renders
effects in source coordinates before composing the page, including live previews.
"""
from __future__ import annotations

import hashlib
import json
import math

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
from scipy import ndimage

from . import ink_v1
from .ink_v1 import contact_coverage
from .records import ImpressionVariant
from .surface import normals_from_height


DEFAULTS = dict(engine_version=2, style="ink", pressure=.55, softness=.035,
                ink_amount=.9, dry_brush=.12, spread=0., edge_softness=0.,
                paper_grain=.025, pigment="#293d32", paper="#f1e8d5", seed=7,
                invert=False, rotation=0., crop=[0., 0., 1., 1.], margin=.1,
                output_px=2400, print_width_mm=150., scale_bar=False)
PRESETS = [
    dict(id="sumi", name="Soot ink · warm paper", settings=dict(style="ink", pigment="#242725", paper="#f2ebdb", dry_brush=.18, paper_grain=.025, ink_amount=.94, spread=0., edge_softness=0.)),
    dict(id="indigo", name="Indigo · rice paper", settings=dict(style="ink", pigment="#243b59", paper="#f3eedf", dry_brush=.10, paper_grain=.02, ink_amount=.92, spread=.2, edge_softness=0.)),
    dict(id="ochre", name="Iron oxide · cream", settings=dict(style="ink", pigment="#874630", paper="#f4e6cc", dry_brush=.24, paper_grain=.03, ink_amount=.9, spread=0., edge_softness=0.)),
    dict(id="specimen", name="Clean specimen", settings=dict(style="clean", pigment="#25382f", paper="#f6f2e7", dry_brush=0., paper_grain=0., ink_amount=1., spread=0., edge_softness=0.)),
]
LEGACY_DEFAULTS = {**DEFAULTS, "engine_version": 1, "output_px": 1600,
                   "dry_brush": 0., "paper_grain": 0., "pigment": "#243530", "paper": "#eee7d6"}


def resolve_settings(settings=None):
    supplied = settings or {}
    version = supplied.get("engine_version", 2)
    if version not in (1, 2):
        raise ValueError("Unsupported print engine version. Use engine 1 or 2.")
    unknown = supplied.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError("Unknown impression settings: " + ", ".join(sorted(unknown)))
    result = {**(LEGACY_DEFAULTS if version == 1 else DEFAULTS), **supplied}
    bounds = dict(pressure=(0, 1), softness=(0, 1), ink_amount=(0, 1),
                  dry_brush=(0, .95), spread=(0, 3), edge_softness=(0, 5),
                  paper_grain=(0, .1), margin=(0, .35), output_px=(128, 6000),
                  print_width_mm=(1, 2000), seed=(0, 2**32-1), rotation=(-3600, 3600))
    for key, (low, high) in bounds.items():
        value = float(result[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be finite and between {low} and {high}.")
        if key in ("output_px", "seed"):
            if not value.is_integer():
                raise ValueError(f"{key} must be an integer.")
            value = int(value)
        result[key] = value
    if result["style"] not in ("ink", "clean", "relief"):
        raise ValueError("Presentation must be ink, clean or relief.")
    for key in ("invert", "scale_bar"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key} must be true or false.")
    for key in ("pigment", "paper"):
        try:
            color = ImageColor.getrgb(result[key])
            if len(color) != 3:
                raise ValueError()
            result[key] = "#%02x%02x%02x" % color
        except (ValueError, TypeError):
            raise ValueError(f"{key} must be an opaque RGB color.") from None
    crop = result["crop"]
    if not isinstance(crop, (list, tuple)) or len(crop) != 4:
        raise ValueError("Crop must be normalized x0,y0,x1,y1.")
    x0, y0, x1, y1 = map(float, crop)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("Crop must be normalized x0,y0,x1,y1.")
    result["crop"] = [x0, y0, x1, y1]
    return result


def render_ink(height, mask, settings=None, spacing=None):
    settings = resolve_settings(settings)
    if settings["engine_version"] == 1:
        return ink_v1.render_ink(height, mask, settings)
    h = np.array(height, dtype=float, copy=True)
    valid = np.asarray(mask, bool) & np.isfinite(h)
    coverage = contact_coverage(h, valid, settings["pressure"], settings["softness"], settings["invert"])
    base = coverage.copy()
    rng = np.random.default_rng(settings["seed"])
    # Separate RNG draws regardless of enabled effects: toggling paper does not
    # change the dry-brush layer, and clean style suppresses every ink artifact.
    noise = ndimage.gaussian_filter(rng.random(h.shape), .6)
    dry_layer = np.clip((noise - .2) / .6, 0, 1).astype(np.float32)
    paper_layer = ((rng.random(h.shape) - .5) * 255 * settings["paper_grain"]).astype(np.float32)
    if settings["style"] == "ink":
        coverage *= 1 - settings["dry_brush"] * (1 - dry_layer)
        spread = settings["spread"]
        if spread:
            expanded = ndimage.maximum_filter(coverage, size=3)
            coverage = (coverage + spread * ndimage.gaussian_filter(expanded, spread)) / (1 + spread)
        if settings["edge_softness"]:
            coverage = ndimage.gaussian_filter(coverage, settings["edge_softness"])
    else:
        paper_layer[:] = 0
    coverage *= settings["ink_amount"]
    coverage[~valid] = 0
    pigment = np.array(ImageColor.getrgb(settings["pigment"]), float)
    paper = np.array(ImageColor.getrgb(settings["paper"]), float)
    backdrop = np.clip(paper + paper_layer[..., None], 0, 255)
    if settings["style"] == "relief":
        h[~valid] = 0
        normals, _ = normals_from_height(-h if settings["invert"] else h, spacing or (1, 1), valid)
        light = np.array([-.5, .5, .70710678])
        shade = np.clip(.25 + .75 * (normals @ light), 0, 1)
        composite = backdrop * shade[..., None]
        composite[~valid] = backdrop[~valid]
    else:
        composite = backdrop * (1 - coverage[..., None]) + pigment * coverage[..., None]
    layers = dict(base_coverage=base, dry_brush=dry_layer, paper_grain=paper_layer,
                  valid_mask=valid.astype(np.uint8))
    return np.rint(np.clip(composite, 0, 255)).astype(np.uint8), coverage, layers


def _source(store, specimen_id, settings):
    specimen = store.get("specimens", specimen_id)
    spacing = None
    if specimen["source_kind"] == "frame":
        from .inputs import image_array
        frame = store.get("frames", specimen["source_id"])
        rgb = image_array(store.path(frame["raw_file"]).read_bytes())
        h = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        # RGB artistic input can exceed the surface budget. Both preview and
        # master use this same explicit cap; no measured geometry is produced.
        ratio = min(1, 2048 / max(h.shape))
        if ratio < 1:
            h = cv2.resize(h, (round(h.shape[1]*ratio), round(h.shape[0]*ratio)), interpolation=cv2.INTER_AREA)
        mask = np.ones(h.shape, bool)
        digest, version = frame["sha256"], "original RGB image"
        interpretation = "image-based artistic impression; no height or contact-physics claim"
    else:
        patch, arrays = store.patch(specimen["source_id"])
        h, mask = arrays["height"], arrays["mask"]
        spacing = patch.pixel_spacing
        digest = hashlib.sha256(store.path(patch.arrays).read_bytes()).hexdigest()
        version = patch.version
        interpretation = "height-based artistic ink coverage; not measured ink physics"
    rows, cols = h.shape
    x0, y0, x1, y1 = settings["crop"]
    left, top, right, bottom = int(x0*cols), int(y0*rows), int(x1*cols), int(y1*rows)
    h, mask = h[top:bottom, left:right].copy(), mask[top:bottom, left:right].copy()
    if min(h.shape) < 2:
        raise ValueError("Crop must contain at least two samples per axis.")
    mask &= np.isfinite(h)
    if not mask.any():
        raise ValueError("No finite valid samples for an impression.")
    h[~mask] = 0
    dimensions = ((h.shape[1]-1)*spacing[0], (h.shape[0]-1)*spacing[1]) if spacing else None
    if settings["scale_bar"] and dimensions is None:
        raise ValueError("Uncalibrated impressions cannot have a physical source scale bar.")
    return dict(specimen=specimen, height=h, mask=mask, spacing=spacing,
                dimensions=dimensions, digest=digest, version=version,
                interpretation=interpretation, crop_samples=[left, top, right, bottom])


def _layout(source, settings):
    h = source["height"]
    width, height = source["dimensions"] or (h.shape[1]-1, h.shape[0]-1)
    angle = math.radians(settings["rotation"] % 360)
    cos, sin = math.cos(angle), math.sin(angle)
    extent_x = abs(cos)*width + abs(sin)*height
    extent_y = abs(sin)*width + abs(cos)*height
    pixels = settings["output_px"]
    pad = round(pixels*settings["margin"])
    scale = (pixels-2*pad-1)/extent_x
    art_height = round(extent_y*scale)+1
    footer = max(pad, round(pixels*.07)) if settings["scale_bar"] else pad
    page_height = pad+art_height+footer
    if page_height > 8000 or pixels*page_height > 32_000_000:
        raise ValueError("Impression exceeds the 8000-pixel height or 32-megapixel page limit. Reduce width or crop the source.")
    return dict(width=pixels, height=page_height, scale=scale, cos=cos, sin=sin,
                pad=pad, art_height=art_height, extent=[extent_x, extent_y],
                magnification=scale*settings["print_width_mm"]/pixels if source["dimensions"] else None)


def _font(size, caption=False):
    # Pillow's bundled font keeps raster exports portable without a system font.
    if caption:
        for name in ('DejaVuSans.ttf', 'C:/Windows/Fonts/segoeui.ttf'):
            try:
                return ImageFont.truetype(name, max(10, round(size)))
            except OSError:
                pass
    return ImageFont.load_default(size=max(10, round(size)))


def _compose(source, settings, pixels, coverage, maximum=None):
    layout = _layout(source, settings)
    ratio = min(1, maximum/max(layout["width"], layout["height"])) if maximum else 1
    size = (max(1, round(layout["width"]*ratio)), max(1, round(layout["height"]*ratio)))
    k = layout["scale"]*ratio
    cx = (layout["width"]-1)*ratio/2
    cy = (layout["pad"]+(layout["art_height"]-1)/2)*ratio
    dx, dy = source["spacing"] or (1, 1)
    cos, sin = layout["cos"], layout["sin"]
    # Inverse affine maps the *same* rotated metric sample rectangle onto all
    # page sizes, so non-square samples retain their physical proportions.
    a, b, d, e = cos/k/dx, -sin/k/dx, sin/k/dy, cos/k/dy
    rows, cols = source["height"].shape
    matrix = (a, b, (cols-1)/2-a*cx-b*cy, d, e, (rows-1)/2-d*cx-e*cy)
    page = Image.fromarray(pixels).transform(size, Image.Transform.AFFINE, matrix,
                   resample=Image.Resampling.BICUBIC, fillcolor=settings["paper"])
    alpha = Image.fromarray(np.rint(coverage*255).astype(np.uint8)).transform(size,
                   Image.Transform.AFFINE, matrix, resample=Image.Resampling.BILINEAR, fillcolor=0)
    # Nearest mask prevents interpolation from painting into missing samples.
    valid = Image.fromarray(source["mask"].astype(np.uint8)*255).transform(size,
                   Image.Transform.AFFINE, matrix, resample=Image.Resampling.NEAREST, fillcolor=0)
    alpha = Image.fromarray(np.where(np.asarray(valid)>0, np.asarray(alpha), 0).astype(np.uint8))
    page.paste(settings["paper"], mask=Image.fromarray(255-np.asarray(valid)))
    if settings["scale_bar"]:
        # A metric ruler in page space stays valid at arbitrary source rotation.
        target = layout["extent"][0]/5
        power = 10**math.floor(math.log10(target))
        bar_mm = max(v*power for v in (1, 2, 5, 10) if v*power <= target*(1+1e-12))
        x = max(layout["pad"], settings["output_px"]*.02)*ratio
        y = (layout["pad"]+layout["art_height"]+max(layout["pad"], settings["output_px"]*.07)*.72)*ratio
        draw = ImageDraw.Draw(page)
        draw.line((x, y, x+bar_mm*k, y), fill=settings["pigment"], width=max(1, round(settings["output_px"]*.0015*ratio)))
        draw.text((x, y-settings["output_px"]*.023*ratio), f"{bar_mm:.3g} mm source", font=_font(settings["output_px"]*.014*ratio), fill=settings["pigment"])
    return page, alpha, layout


def preview_ink(store, specimen_id, settings):
    settings = resolve_settings(settings)
    if settings["engine_version"] == 1:
        return ink_v1.preview_ink(store, specimen_id, settings)
    source = _source(store, specimen_id, settings)
    pixels, coverage, _ = render_ink(source["height"], source["mask"], settings, source["spacing"])
    return _compose(source, settings, pixels, coverage, maximum=640)[0]


def pressure_proof(store, specimen_id, settings):
    """Read-only PNG proof: three pressures, no specimen/variant/public changes."""
    settings = resolve_settings(settings)
    if settings["style"] == "relief":
        raise ValueError("Choose an ink or clean impression to compare printing pressure.")
    source = _source(store, specimen_id, settings)
    pictures = []
    pressures = (.25, .55, .85)
    for pressure in pressures:
        current = {**settings, "pressure": pressure}
        if settings["engine_version"] == 1:
            picture = ink_v1.preview_ink(store, specimen_id, current)
        else:
            pixels, coverage, _ = render_ink(source["height"], source["mask"], current, source["spacing"])
            picture = _compose(source, current, pixels, coverage, maximum=560)[0]
        picture.thumbnail((560, 620))
        pictures.append(picture)
    paper = settings["paper"]
    sheet = Image.new("RGB", (1800, max(p.height for p in pictures)+220), paper)
    draw = ImageDraw.Draw(sheet)
    title = source["specimen"]["title"]
    draw.text((40, 25), f"{title[:60]} / pressure proof", font=_font(30, caption=True), fill=settings["pigment"])
    draw.text((40, 70), "Gyotaku-inspired digital impression / virtual pressure / source unchanged", font=_font(18), fill=settings["pigment"])
    for i, (picture, pressure) in enumerate(zip(pictures, pressures)):
        x = i*600+(600-picture.width)//2
        sheet.paste(picture, (x, 110))
        draw.text((i*600+40, sheet.height-65), f"Pressure {pressure:.2f}", font=_font(22), fill=settings["pigment"])
    return sheet


def create_impression(store, specimen_id, settings=None, progress=None):
    settings = resolve_settings(settings)
    if settings["engine_version"] == 1:
        return ink_v1.create_impression(store, specimen_id, settings, progress)
    source = _source(store, specimen_id, settings)
    if progress:
        progress(.15, "Rendering source contact and removable ink layers")
    pixels, coverage, layers = render_ink(source["height"], source["mask"], settings, source["spacing"])
    page, alpha, layout = _compose(source, settings, pixels, coverage)
    rgba = Image.new("RGBA", page.size, ImageColor.getrgb(settings["pigment"])+(0,))
    rgba.putalpha(alpha)
    specimen = source["specimen"]
    variant = ImpressionVariant(specimen_id=specimen_id, source_id=specimen["source_id"],
        source_version=source["version"], source_sha256=source["digest"], settings=settings,
        seed=settings["seed"], pixel_size=page.size,
        print_size_mm=(settings["print_width_mm"], settings["print_width_mm"]*page.height/page.width),
        reproduction_magnification=layout["magnification"], source_dimensions_mm=source["dimensions"],
        palette={"pigment": settings["pigment"], "paper": settings["paper"]},
        directory="", interpretation=source["interpretation"])
    variant.directory = f"impressions/{variant.id}"
    directory = store.path(variant.directory)
    directory.mkdir(parents=True)
    dpi = (page.width/settings["print_width_mm"]*25.4,)*2
    page.save(directory/"print.png", dpi=dpi)
    rgba.save(directory/"ink-transparent.png", dpi=dpi)
    alpha.save(directory/"coverage.png", dpi=dpi)
    for maximum, name in ((480, "thumbnail.webp"), (1200, "display.webp")):
        smaller = page.copy()
        smaller.thumbnail((maximum, maximum))
        smaller.save(directory/name, quality=90)
    np.savez_compressed(directory/"artistic_layers.npz", coverage=coverage, **layers)
    h, mask = source["height"], source["mask"]
    step = max(1, int(np.ceil(max(h.shape)/192)))
    valid_h = h[mask]
    relative = (h-float(valid_h.min()))/max(float(np.ptp(valid_h)), 1e-12)
    (directory/"surface-preview.json").write_text(json.dumps(dict(
        height=relative[::step, ::step].tolist(), mask=mask[::step, ::step].astype(int).tolist(),
        width=relative[::step, ::step].shape[1], height_px=relative[::step, ::step].shape[0],
        interpretation=source["interpretation"], units="relative display values")), encoding="utf-8")
    variant.exports = dict(print="print.png", transparent="ink-transparent.png", coverage="coverage.png",
                           layers="artistic_layers.npz", recipe="variant.json", process="process.json")
    (directory/"process.json").write_text(json.dumps(dict(engine_version=2,
        crop_sample_bounds=source["crop_samples"], render_grid=list(h.shape),
        layout=layout, layer_coordinates="cropped source array, before rotation and page layout",
        transparent_export="pigment and contact coverage; relief shading and scale bar excluded",
        source_preserved=True), indent=2), encoding="utf-8")
    (directory/"variant.json").write_text(json.dumps(variant.model_dump(mode="json"), indent=2), encoding="utf-8")
    store.save("impressions", variant)
    specimen["impression_ids"].append(variant.id)
    if not specimen["cover_id"]:
        specimen["cover_id"] = variant.id
    store.save("specimens", specimen)
    return variant.model_dump(mode="json")
