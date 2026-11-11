import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from plyfile import PlyData
from scipy.spatial import ConvexHull, distance

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'ply_label_audit'
OUT.mkdir(exist_ok=True)


def load(path):
    ply = PlyData.read(str(path))
    v = ply['vertex'].data
    xyz = np.column_stack([v[a] for a in ('x', 'y', 'z')]).astype(float)
    color = np.column_stack([v[a] for a in ('red', 'green', 'blue')]) / 255.
    valid = np.isfinite(xyz).all(axis=1)
    return xyz[valid], color[valid], ply


def plot_cloud(ax, xyz, colors, dims, title):
    take = np.linspace(0, len(xyz)-1, min(45000, len(xyz)), dtype=int)
    ax.scatter(xyz[take, dims[0]], xyz[take, dims[1]], c=colors[take], s=.2, rasterized=True)
    ax.set_aspect('equal', adjustable='datalim')
    ax.set_title(title, fontsize=10)
    ax.tick_params(labelsize=7)


def main():
    m = json.loads((ROOT/'plant-project-staging/manifest.json').read_text(encoding='utf-8'))
    rows = []
    for g in m['groups']:
        cid = g['capture_id']
        folder = Path(g['csv_path']).parent
        paths = sorted(folder.glob(cid+'*.ply'))
        corrected = [p for p in paths if 'Correction' in p.name]
        raw = [p for p in paths if '_B_3D' in p.name]
        if len(corrected) != 1 or len(raw) != 1:
            raise ValueError((cid, paths))
        xyz, colors, ply = load(corrected[0])
        rawxyz, rawcolors, rawply = load(raw[0])
        labels = {}
        with Path(g['csv_path']).open(encoding='utf-8-sig') as f:
            for name, value in csv.reader(f):
                if name != 'pC':
                    labels[name] = float(value)
        span = np.ptp(xyz, axis=0)
        hull = ConvexHull(xyz)
        xyhull = ConvexHull(xyz[:, :2])
        width = float(distance.pdist(xyz[xyhull.vertices, :2]).max())
        row = {
            'capture_id':cid, 'raw_points':len(rawxyz), 'corrected_points':len(xyz),
            'correction_ply':str(corrected[0]), 'csv':g['csv_path'],
            'has_color':True, 'ply_elements':','.join(e.name for e in ply.elements),
            'span_x':span[0], 'span_y':span[1], 'span_z':span[2],
            'csv_pGH':labels['pGH'], 'height_z_relative_error':abs(span[2]-labels['pGH'])/labels['pGH'],
            'xy_max_diameter':width, 'csv_pMW':labels['pMW'],
            'width_relative_error':abs(width-labels['pMW'])/labels['pMW'],
            'hull_xy_area':xyhull.volume, 'hull_3d_surface':hull.area,
            'hull_3d_volume':hull.volume, 'csv_pCHA':labels['pCHA'],
            'hull_volume_relative_error':abs(hull.volume-labels['pCHA'])/labels['pCHA'],
            'identity_status':'Needs visual review; no explicit plant ID in CSV',
        }
        rows.append(row)
        fig, axes = plt.subplots(2, 4, figsize=(16, 8), layout='constrained')
        plot_cloud(axes[0,0], rawxyz, rawcolors, (0,1), 'Raw PLY XY')
        plot_cloud(axes[0,1], xyz, colors, (0,1), 'Correction PLY XY')
        plot_cloud(axes[0,2], xyz, colors, (0,2), 'Correction PLY XZ')
        plot_cloud(axes[0,3], xyz, colors, (1,2), 'Correction PLY YZ')
        for cam in range(1,5):
            with Image.open(g['selected_images'][str(cam)][0]) as image:
                axes[1,cam-1].imshow(image)
            axes[1,cam-1].axis('off')
            axes[1,cam-1].set_title(f'CAM{cam} full RGB - first selected view', fontsize=10)
        fig.suptitle(f'{cid} | PLY height {span[2]:.2f} / CSV {labels["pGH"]:.2f} | '
                     f'XY diameter {width:.2f} / CSV {labels["pMW"]:.2f}', fontsize=13)
        fig.savefig(OUT/(cid+'.png'), dpi=140)
        plt.close(fig)
        print(json.dumps(row), flush=True)
    with (OUT/'geometry_checks.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT/'geometry_checks.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
