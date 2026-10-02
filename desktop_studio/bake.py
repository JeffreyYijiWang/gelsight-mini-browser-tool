"""Rebuild the normal-textured GLB inspection plane for a saved surface."""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
from .project import bake_normal_material

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('surface_folder', type=Path)
    args = parser.parse_args()
    folder = args.surface_folder.resolve()
    bake_normal_material(folder, np.load(folder/'depth.npy', allow_pickle=False),
                         np.asarray(Image.open(folder/'rgb.png').convert('RGB')))
    print(folder/'normal-material.glb')
