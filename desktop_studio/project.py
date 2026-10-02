"""Versioned native projects, matrix assembly and manufacture exports."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
import cv2
import numpy as np
from PIL import Image
from scipy import ndimage
import trimesh
from studio.atlas import match_pair, repetitive
from studio.surface import normals_from_height
from studio.printing import solid_from_top
from .reconstruction import Reconstructor

MAX_PIXELS = 600_000
MAX_CAPTURES = 100


def json_write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def checkpoint(progress, value, message):
    if progress: progress(value, message)


def display_depth(z):
    lo, hi = np.percentile(z, [1, 99])
    return np.rint(np.clip((z-lo)/max(float(hi-lo), 1e-9), 0, 1)*255).astype(np.uint8)


def surface_mesh(z, rgb=None, spacing=1.):
    h, w = z.shape
    y, x = np.indices((h, w))
    vertices = np.column_stack((x.ravel()*spacing, -y.ravel()*spacing, z.ravel()))
    a = (y[:-1, :-1]*w+x[:-1, :-1]).ravel()
    faces = np.vstack((np.column_stack((a, a+w, a+1)), np.column_stack((a+1, a+w, a+w+1))))
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False,
                          vertex_colors=rgb.reshape(-1, 3) if rgb is not None else None)


def save_surface(directory, z, rgb, progress=None):
    """One finite field drives normals, mesh and point cloud (no second crop)."""
    if z.ndim!=2 or min(z.shape)<2 or z.size>MAX_PIXELS or not np.isfinite(z).all():
        raise ValueError('Surface must be finite and contain 4–600,000 pixels.')
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory/'depth.npy', z.astype(np.float32))
    Image.fromarray(display_depth(z)).save(directory/'depth.png')
    Image.fromarray(rgb).save(directory/'rgb.png')
    normals, _ = normals_from_height(z)
    np.save(directory/'normals.npy', normals.astype(np.float32))
    for name, n in [('normal.png', normals), ('normal-directx.png', normals*[1, -1, 1])]:
        Image.fromarray(np.rint(np.clip(n*.5+.5, 0, 1)*255).astype(np.uint8)).save(directory/name)
    checkpoint(progress, .75, 'Writing mesh and point cloud')
    mesh = surface_mesh(z, rgb)
    mesh.export(directory/'surface.ply')
    # Binary PLY retains floats and colors without enormous ASCII OBJ files.
    trimesh.points.PointCloud(mesh.vertices, colors=rgb.reshape(-1, 3)).export(directory/'points.ply')
    bake_normal_material(directory, z, rgb)
    return mesh


def bake_normal_material(directory, z, rgb):
    """UV-bound normal texture on a flat inspection mesh; never double relief."""
    from trimesh.visual.material import PBRMaterial
    from trimesh.visual.texture import TextureVisuals
    if z.ndim!=2 or z.size>MAX_PIXELS or not np.isfinite(z).all() or rgb.shape!=(*z.shape, 3):
        raise ValueError('Normal material requires a matching finite field and RGB within the pixel budget.')
    h, w = z.shape
    plane = surface_mesh(np.zeros((2, 2), np.float32))
    plane.vertices[:, 0] *= w-1; plane.vertices[:, 1] *= h-1
    uv = np.array([[0, 1], [1, 1], [0, 0], [1, 0]], float)
    material = PBRMaterial(baseColorTexture=Image.fromarray(rgb),
                           normalTexture=Image.open(directory/'normal.png').copy(),
                           metallicFactor=0, roughnessFactor=.8, doubleSided=True)
    plane.visual = TextureVisuals(uv=uv, material=material)
    # GLB meters are authored display coordinates, not a sensor measurement.
    plane.apply_scale(.001)
    plane.export(directory/'normal-material.glb')


class Project:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root/'project.json'
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(
            format='gelsight-native-matrix-v1', rows=[[]], calibrations=[], assemblies=[])
        if self.data.get('format')!='gelsight-native-matrix-v1':
            raise ValueError('This folder is not a native GelSight matrix project.')
        self.save()

    def save(self): json_write(self.root/'project.json', self.data)

    def new_row(self):
        if not self.data['rows'][-1]: raise ValueError('Capture this row before starting another.')
        if len(self.data['rows'])>=MAX_CAPTURES: raise ValueError('100-row limit reached.')
        self.data['rows'].append([]); self.save()

    def calibrate(self, frames, device, progress=None):
        if len(frames)!=50: raise ValueError('Calibration needs 50 distinct delivered camera frames.')
        model = Reconstructor(); shape = frames[0].shape
        identifier = uuid4().hex
        folder = self.root/'calibrations'/identifier; folder.mkdir(parents=True)
        dz = np.zeros((240, 320), float); color = np.zeros((240, 320, 3), float)
        hashes = []
        for i, raw in enumerate(frames):
            checkpoint(progress, i/55, f'Calibrating untouched gel: {i+1}/50')
            if raw.shape!=shape: raise ValueError('Camera resolution changed during calibration.')
            Image.fromarray(raw).save(folder/f'reference-{i:02}.png')
            hashes.append(sha(folder/f'reference-{i:02}.png'))
            result = model.raw_depth(raw); dz += result['depth']/50; color += result['rgb']/50
        np.save(folder/'depth.npy', dz.astype(np.float32))
        np.save(folder/'rgb.npy', color.astype(np.float32))
        record = dict(id=identifier, device=device, source_shape=list(shape), config=model.config,
                      frame_sha256=hashes, no_contact='explicit user instruction; not inferred',
                      physical_calibration=False, files={name:sha(folder/name) for name in ('depth.npy', 'rgb.npy')})
        json_write(folder/'calibration.json', record)
        checkpoint(progress, .99, 'Saving calibration revision')
        self.data['calibrations'].append(record); self.save()
        return record

    def capture(self, raw, calibration, device, progress=None):
        if sum(map(len, self.data['rows']))>=MAX_CAPTURES: raise ValueError('100-capture budget reached. Start another project.')
        if calibration['device']!=device or list(raw.shape)!=calibration['source_shape']:
            raise ValueError('Device or resolution changed. Recalibrate the untouched gel.')
        model = Reconstructor()
        if calibration['config']!=model.config: raise ValueError('Reconstruction settings changed. Recalibrate first.')
        checkpoint(progress, .1, 'Reconstructing the frozen RGB frame')
        result = model.raw_depth(raw)
        baseline = self.root/'calibrations'/calibration['id']
        for name, digest in calibration['files'].items():
            if sha(baseline/name)!=digest: raise ValueError('Baseline file changed. Recalibrate the untouched gel.')
        z = result['depth']-np.load(baseline/'depth.npy', allow_pickle=False)
        folder = self.root/'captures'/uuid4().hex; folder.mkdir(parents=True)
        Image.fromarray(raw).save(folder/'source.png')
        Image.fromarray(result['crop']).save(folder/'cropped-source.png')
        save_surface(folder, z, result['rgb'], progress)
        Image.fromarray(result['marker'].astype(np.uint8)*255).save(folder/'interpolated-markers.png')
        difference = np.max(abs(result['rgb'].astype(float)-np.load(baseline/'rgb.npy')), axis=-1)
        Image.fromarray(np.dstack((result['rgb'], (difference>=12).astype(np.uint8)*255))).save(folder/'background-subtracted.png')
        row = len(self.data['rows'])-1; col = len(self.data['rows'][-1])
        record = dict(id=folder.name, row=row, column=col, calibration_id=calibration['id'],
                      device=device, config=model.config, crop_box=result['crop_box'],
                      coordinates='X right, Y up, Z out; unit model-pixel XY; relative Z',
                      files={p.name:sha(p) for p in folder.iterdir() if p.is_file()})
        json_write(folder/'capture.json', record)
        checkpoint(progress, .99, 'Saving matrix cell')
        self.data['rows'][-1].append(record); self.save()
        return folder

    def assemble(self, overlap=.25, progress=None):
        if not .1<=overlap<=.6: raise ValueError('Overlap must be between 10% and 60%.')
        records = [r for row in self.data['rows'] for r in row]
        if not 2<=len(records)<=MAX_CAPTURES: raise ValueError('Capture 2–100 samples first.')
        first = records[0]
        if any(r['device']!=first['device'] or r['config']!=first['config'] for r in records):
            raise ValueError('Assembly requires one device and reconstruction configuration.')
        folder = self.root/'assemblies'/uuid4().hex; folder.mkdir(parents=True)
        tiles = []
        for i, record in enumerate(records):
            checkpoint(progress, .15*i/len(records), 'Loading and verifying immutable captures')
            source = self.root/'captures'/record['id']
            for name in ('depth.npy', 'rgb.png', 'normal.png'):
                if sha(source/name)!=record['files'][name]: raise ValueError(f'Capture {record["id"]} has changed: {name}')
            z = np.load(source/'depth.npy', allow_pickle=False)
            normal = np.asarray(Image.open(source/'normal.png').convert('RGB'))
            # Use all three normal channels as orientation features, not RGB lighting.
            gray = cv2.cvtColor(normal, cv2.COLOR_RGB2GRAY)
            gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
            kp, descriptors = cv2.SIFT_create(nfeatures=1500).detectAndCompute(gray, None)
            tiles.append(dict(depth=z, rgb=np.asarray(Image.open(source/'rgb.png').convert('RGB')),
                              mask=np.ones(z.shape, bool), repetitive=repetitive(gray, np.ones(z.shape, bool)),
                              keypoints=kp, descriptors=descriptors))
        h, w = tiles[0]['depth'].shape
        lookup = {(r['row'], r['column']):i for i, r in enumerate(records)}
        expected = np.array([[r['column']*w*(1-overlap), r['row']*h*(1-overlap)] for r in records])
        links = []
        for (row, col), i in lookup.items():
            checkpoint(progress, .15+.2*i/len(records), 'Matching neighboring normal maps')
            for cell, direction in [((row, col+1), 'right'), ((row+1, col), 'down')]:
                if cell not in lookup: continue
                j = lookup[cell]; link = match_pair(tiles[i], tiles[j])
                if link['accepted']:
                    matrix = np.array(link['transform_b_to_a'])
                    delta = matrix[:2, 2]; target = expected[j]-expected[i]
                    angle = abs(np.arctan2(matrix[1, 0], matrix[0, 0]))
                    # The matrix workflow uses translations; rotations need a different atlas.
                    if angle>.015 or np.linalg.norm(delta-target)>min(w, h)*.3 or link['duplicate']:
                        link.update(accepted=False, reason='Rotation, duplicate, or displacement conflicts with indexed neighbors')
                links.append(dict(a=i, b=j, direction=direction, **link))
        # Solve translations jointly. Grid priors explicitly anchor unmatched regions.
        equations = [np.eye(len(records))[i]*.1 for i in range(len(records))]
        targets = [p*.1 for p in expected]
        for link in links:
            if link['accepted']:
                equation = np.zeros(len(records)); equation[link['b']] = 1; equation[link['a']] = -1
                equations.append(equation); targets.append(np.array(link['transform_b_to_a'])[:2, 2])
        positions = np.linalg.lstsq(equations, targets, rcond=None)[0]
        positions = np.rint(positions-positions.min(axis=0)).astype(int)
        width, height = positions.max(axis=0)+[w, h]
        if width*height>MAX_PIXELS:
            raise ValueError(f'Panorama would be {width} × {height}; maximum is {MAX_PIXELS:,} pixels. Use smaller collections or more overlap.')
        total = np.zeros((height, width), np.float32); zs = total.copy()
        colors = np.zeros((height, width, 3), np.float32); counts = np.zeros_like(total, np.uint16)
        yy, xx = np.indices((h, w)); weight = np.maximum(.001, np.minimum.reduce([xx+1, w-xx, yy+1, h-yy])/min(h, w))
        offsets = []
        for i, (tile, (x, y)) in enumerate(zip(tiles, positions)):
            checkpoint(progress, .4+.2*i/len(tiles), 'Blending relative fields and leveling overlaps')
            sl = np.s_[y:y+h, x:x+w]; existing = total[sl]>0
            offset = float(np.median(zs[sl][existing]/total[sl][existing]-tile['depth'][existing])) if existing.any() else 0.
            offsets.append(offset)
            zs[sl] += (tile['depth']+offset)*weight
            colors[sl] += tile['rgb']*weight[..., None]; total[sl] += weight; counts[sl] += 1
        observed = total>0; denominator = np.maximum(total, 1e-9)
        z = zs/denominator; rgb = colors/denominator[..., None]
        if not observed.all():
            nearest = ndimage.distance_transform_edt(~observed, return_distances=False, return_indices=True)
            z[~observed] = z[tuple(nearest[:, ~observed])]
            rgb[~observed] = rgb[tuple(nearest[:, ~observed])]
        # Continuous artistic surface: localized smoothing of overlaps and missing area.
        synthetic = ndimage.binary_dilation((counts!=1), iterations=2)
        z[synthetic] = ndimage.gaussian_filter(z, 1.2)[synthetic]
        rgb = np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)
        save_surface(folder, z, rgb, progress)
        Image.fromarray(observed.astype(np.uint8)*255).save(folder/'observed-mask.png')
        Image.fromarray(synthetic.astype(np.uint8)*255).save(folder/'synthetic-mask.png')
        report = dict(id=folder.name, type='artistic continuous matrix panorama', metric_validated=False,
                      source_ids=[r['id'] for r in records], source_hashes=[r['files'] for r in records],
                      row_lengths=[len(row) for row in self.data['rows']], neighbors=links,
                      positions=positions.tolist(), depth_offsets=offsets, expected_overlap=overlap,
                      source_size=[w, h], output_size=[int(width), int(height)],
                      missing_fraction=float((~observed).mean()), synthetic_fraction=float(synthetic.mean()),
                      normal_method='Finite differences of fused depth; normal images guide registration. Not independent normal integration.',
                      limitation='Grid priors place unmatched tiles; leveling, blending and missing-cell fills are synthetic. No recovered physical topology.',
                      files={p.name:sha(p) for p in folder.iterdir() if p.is_file()})
        json_write(folder/'assembly.json', report)
        checkpoint(progress, .99, 'Saving assembly revision')
        self.data['assemblies'].append(report); self.save()
        return folder


def export_print(source, width_mm=100., relief_mm=2., base_mm=2., progress=None):
    source = Path(source)
    if not all(np.isfinite([width_mm, relief_mm, base_mm])) or not (1<=width_mm<=1000 and 0<=relief_mm<=50 and .5<=base_mm<=50):
        raise ValueError('Width 1–1000 mm, relief 0–50 mm, base 0.5–50 mm required.')
    z = np.load(source/'depth.npy', allow_pickle=False)
    if z.size>MAX_PIXELS or not np.isfinite(z).all(): raise ValueError('Invalid or oversized source field.')
    checkpoint(progress, .1, 'Building full-resolution print solid')
    normalized = (z-z.min())/max(float(np.ptp(z)), 1e-12)*relief_mm
    top = surface_mesh(normalized, spacing=width_mm/(z.shape[1]-1))
    mesh = solid_from_top(top.vertices[:, :2], top.faces, top.vertices[:, 2]+base_mm)
    if not mesh.is_watertight or not mesh.is_winding_consistent or not mesh.is_volume:
        raise ValueError('Print topology validation failed; manufacturing export withheld.')
    checkpoint(progress, .6, 'Exporting and reloading STL')
    folder = source/'prints'/uuid4().hex; folder.mkdir(parents=True)
    mesh.export(folder/'relief_mm.stl')
    loaded = trimesh.load(folder/'relief_mm.stl', force='mesh', process=True)
    passed = bool(loaded.is_watertight and loaded.is_volume and len(loaded.faces)==len(mesh.faces)
                  and np.allclose(loaded.bounds, mesh.bounds, atol=1e-4))
    report = dict(width_mm=width_mm, relief_mm=relief_mm, base_mm=base_mm,
                  height_mm=(z.shape[0]-1)*width_mm/(z.shape[1]-1),
                  source_sha256=sha(source/'depth.npy'), authored_dimensions=True,
                  metric_sensor_calibration=False, triangles=len(mesh.faces), vertices=len(mesh.vertices),
                  watertight=bool(mesh.is_watertight), single_component=True, roundtrip_passed=passed,
                  construction='Full regular-grid top and bottom plus all exterior walls; injective XY heightfield, positive thickness.',
                  fidelity='Every source sample retained; piecewise-linear interpolation between samples. No detail invented by upsampling.',
                  source_z_range=[float(z.min()), float(z.max())], print_ready=False,
                  remaining_validation='Printer feature limits, slicer inspection and physical print not verified.')
    json_write(folder/'validation.json', report)
    if not passed:
        (folder/'relief_mm.stl').rename(folder/'failed-roundtrip.stl')
        raise ValueError('STL round-trip failed. See validation.json; export is marked failed.')
    checkpoint(progress, 1., 'Validated digital solid saved; physical print unverified')
    return folder
