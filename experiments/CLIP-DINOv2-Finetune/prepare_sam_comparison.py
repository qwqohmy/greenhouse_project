"""Pair available SAM views with their exact original frames, without DB writes."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from train import BASE, ROOT, digest, write_json

OUT = BASE / 'outputs' / 'sam_comparison_20261111'


def main():
    original = json.loads((BASE / 'user_confirmed_samples_manifest.json').read_text(encoding='utf-8'))
    inventory = json.loads((OUT / 'sam_inventory.json').read_text(encoding='utf-8'))
    lookup = {r['capture_id']: r for r in original['samples']}
    sys.path.insert(0, str(ROOT / 'database'))
    from database import connect
    db = connect(readonly=True)
    rows = []
    try:
        for item in inventory['rows']:
            row = lookup[item['capture_id']]
            with db.cursor() as cur:
                cur.execute('SELECT a.file_path FROM p3d_user_sample_images l JOIN p3d_images i ON i.id=l.image_id JOIN p3d_assets a ON a.id=i.asset_id WHERE l.sample_id=%s', (row['sample_id'],))
                allowed = {p.casefold() for p, in cur.fetchall()}
            views = []
            for camera in ('1', '2', '3', '4'):
                frames = sorted((f for f in item['frames'] if f['camera'] == camera and f['valid_instances'] == 1), key=lambda f: f['source'])
                indices = np.linspace(0, len(frames)-1, min(6, len(frames)), dtype=int) if frames else []
                for index in indices:
                    frame = frames[index]
                    meta = json.loads(Path(frame['metadata']).read_text(encoding='utf-8'))
                    assert str(Path(frame['source'])).casefold() in allowed
                    instance = meta['instances'][0]
                    directory = Path(instance['output_directory'])
                    rgb, mask, segmented = [directory / n for n in ('rgb.png', 'mask.png', 'segmented.png')]
                    with Image.open(rgb) as im, Image.open(mask) as m, Image.open(segmented) as seg:
                        assert im.size == m.size == seg.size and m.convert('L').getbbox() is not None
                        binary = np.asarray(m.convert('L')) > 0
                        assert int(binary.sum()) == instance['mask_pixels']
                        assert np.all(np.asarray(seg.convert('RGB'))[~binary] == 0)
                    views.append({'camera': camera, 'original': frame['source'], 'crop': str(rgb), 'sam': str(segmented),
                                  'mask': str(mask), 'metadata': frame['metadata'],
                                  'sha256': {k: digest(p) for k,p in [('original',frame['source']),('crop',rgb),('sam',segmented),('mask',mask),('metadata',frame['metadata'])]},
                                  'source_edge_truncated_candidate': instance['source_edge_truncated_candidate']})
            assert views and len({v['original'] for v in views}) == len(views)
            for source in row['sources'].values():
                if source['trial_eligible']:
                    assert digest(source['path']) == source['sha256']
            rows.append({**row, 'views': views, 'available_views_by_camera': dict(Counter(v['camera'] for v in views)),
                         'partial_camera_coverage': len({v['camera'] for v in views}) < 4,
                         'both_top_and_side': any(v['camera'] in ('1','2') for v in views) and any(v['camera'] in ('3','4') for v in views)})
    finally:
        db.close()
    report = {'samples': len(rows), 'selected_unique_frames': sum(len(r['views']) for r in rows),
              'view_count_range': [min(len(r['views']) for r in rows), max(len(r['views']) for r in rows)],
              'four_camera_samples': sum(not r['partial_camera_coverage'] for r in rows),
              'both_top_and_side_samples': sum(r['both_top_and_side'] for r in rows),
              'near_time_samples': sum(abs(r['csv_minus_rgb_seconds']) > 1 for r in rows),
              'source_manifest_sha256': digest(BASE / 'user_confirmed_samples_manifest.json'),
              'selection': 'Up to six unique SAM-detected frames per available camera, evenly spaced through valid frame order. Missing views are omitted, never duplicated or replaced by black/raw frames.',
              'database_modified': False}
    write_json(OUT / 'paired_manifest.private.json', {'report': report, 'target_definitions': original['target_definitions'], 'samples': rows})
    write_json(OUT / 'input_report.json', {**report, 'rows': [{'capture_id':r['capture_id'],'views':len(r['views']), 'cameras':r['available_views_by_camera'], 'both_top_and_side':r['both_top_and_side']} for r in rows]})
    for start in range(0, len(rows), 8):
        sheet = Image.new('RGB', (1000, 8*190+35), 'white'); draw = ImageDraw.Draw(sheet)
        draw.text((8,5), 'Exact paired source / existing SAM mask: top and side, when available', fill='black')
        for offset, row in enumerate(rows[start:start+8]):
            y = 35+offset*190
            draw.text((5,y), row['capture_id']+'  views='+str(len(row['views']))+'  '+str(row['available_views_by_camera']), fill='black')
            top = next((v for v in row['views'] if v['camera'] in ('1','2')), None)
            side = next((v for v in row['views'] if v['camera'] in ('3','4')), None)
            for j, view in enumerate((top,side)):
                if view is None: continue
                for k, variant in enumerate(('original','sam')):
                    with Image.open(view[variant]) as image:
                        tile = ImageOps.contain(image.convert('RGB'), (245,155))
                    x = (j*2+k)*250
                    sheet.paste(tile,(x,y+22)); draw.text((x,y+177), 'CAM'+view['camera']+' '+variant,fill='black')
        sheet.save(OUT / ('contact_'+str(start//8+1)+'.jpg'), quality=92)
    print(json.dumps(report), flush=True)


if __name__ == '__main__': main()
