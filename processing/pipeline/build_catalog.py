import collections
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
from plyfile import PlyData
from scipy.spatial import ConvexHull, distance

BASE = Path(__file__).resolve().parent
STAMP = re.compile(r'(20\d{2}-\d{2}-\d{2})[_ ](\d{2}[-:]\d{2}[-:]\d{2})')
CONFLICT = {'2026-07-21_14-51-25', '2026-07-21_15-14-20'}


def timestamp(text):
    m = STAMP.search(text)
    return m[1]+'_'+m[2].replace(':','-') if m else None


def domain(path):
    if 'lettuce 3D' in path:
        return 'lettuce_new_202609', 'lettuce'
    if '\\tomato\\' in path:
        return 'tomato_unassigned_batch', 'tomato'
    stamp = timestamp(path)
    if stamp and stamp.startswith('2026-09'):
        return 'legacy_rgb_september_species_unverified', 'unknown'
    return 'lettuce_legacy_202606_08', 'lettuce'


def write_csv(name, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (BASE/name).open('w',encoding='utf-8-sig',newline='') as f:
        w = csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    inv = json.loads((BASE/'inventory.json').read_text(encoding='utf-8'))
    groups = collections.defaultdict(lambda:collections.defaultdict(list))
    for path in inv['camera_images']:
        p = Path(path)
        m = re.match(r'CAM(\d+)_',p.name,re.I)
        if m:
            groups[str(p.parent)][m[1]].append(path)
    captures = []
    for folder, cameras in sorted(groups.items()):
        capture_id = timestamp(folder)
        if not capture_id:
            continue
        batch, crop = domain(folder)
        selected = {}
        for cam, paths in sorted(cameras.items()):
            paths.sort()
            indices = np.linspace(0,len(paths)-1,min(6,len(paths)),dtype=int)
            selected[cam] = [paths[i] for i in indices]
        captures.append({'capture_id':capture_id,'folder':folder,'dataset_id':batch,
                         'crop':crop,'plant_id':None,'light_condition':None,
                         'camera_counts':{c:len(p) for c,p in cameras.items()},
                         'selected_images':selected,'match_status':'MATCH_CONFLICT' if capture_id in CONFLICT else 'UNREVIEWED'})
    (BASE/'capture_catalog.json').write_text(json.dumps(captures,ensure_ascii=False,indent=2),encoding='utf-8')

    derived = []
    vendor = []
    signatures = {}
    for path in inv['csv_files']:
        try:
            with Path(path).open(encoding='utf-8-sig') as f:
                for row in csv.reader(f):
                    if len(row) == 2:
                        vendor.append({'capture_id':timestamp(path),'source_path':path,'trait':row[0],
                                       'value_raw':row[1],'label_source':'VENDOR_CSV','unit_status':'VENDOR_UNIT_UNVERIFIED'})
        except Exception as exc:
            print('CSV_ERROR',path,str(exc),flush=True)
    corrections = [p for p in inv['ply_files'] if 'correction' in Path(p).name.lower()
                   and '\\多光譜\\' not in p]
    for index, path in enumerate(corrections,1):
        p = Path(path)
        row = {'capture_id':timestamp(path),'source_path':path,'label_source':'PLY_DERIVED',
               'algorithm_version':'geometry_proxy_v1','coordinate_unit':'UNVERIFIED',
               'vertical_axis':'Z_ASSUMED_CORRECTED_FRAME',
               'plant_scope':'PLY_CONTENT_UNVERIFIED','train_eligible':False}
        try:
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            row['sha256'] = sha
            row['duplicate_of'] = signatures.get(sha,'')
            signatures.setdefault(sha,path)
            data = PlyData.read(str(p))
            v = data['vertex'].data
            xyz = np.column_stack([v[k] for k in ('x','y','z')]).astype(np.float64)
            xyz = xyz[np.isfinite(xyz).all(axis=1)]
            row['point_count'] = len(xyz)
            row['has_mesh_faces'] = any(e.name == 'face' for e in data.elements)
            row['has_color'] = all(c in v.dtype.names for c in ('red','green','blue'))
            if len(xyz) < 4:
                raise ValueError('Too few points')
            extent = np.ptp(xyz,axis=0)
            row.update(extent_x=extent[0],extent_y=extent[1],extent_z=extent[2],pGH_proxy=extent[2])
            h = ConvexHull(xyz[:,:2])
            row['pMW_proxy'] = float(distance.pdist(xyz[h.vertices,:2]).max())
            row['xy_convex_hull_area'] = h.volume
            row['pGH_method'] = 'max(Z)-min(Z); not vendor algorithm'
            row['pMW_method'] = 'maximum XY point distance; not vendor algorithm'
            row['pTLA'] = row['pPLA'] = row['pLAA'] = row['pCHA'] = row['pE'] = None
            row['unavailable_reason'] = 'Vendor algorithm/scale/plant scope not validated; no fabricated target values'
            row['status'] = 'COMPUTED_NEEDS_REVIEW'
        except Exception as exc:
            row['status'] = 'FAILED'
            row['error'] = str(exc)
        derived.append(row)
        if index % 10 == 0 or index == len(corrections):
            print(f'PLY {index}/{len(corrections)}',flush=True)
    write_csv('ply_derived_traits.csv',derived)
    write_csv('vendor_measurements.csv',vendor)

    pair_rows = []
    for g in captures:
        day = g['capture_id'][:10]
        t = datetime.strptime(g['capture_id'],'%Y-%m-%d_%H-%M-%S')
        candidates = []
        for ply in derived:
            pt = ply['capture_id']
            if not pt or pt[:10] != day or ply.get('duplicate_of'):
                continue
            if domain(ply['source_path'])[0] != g['dataset_id']:
                continue
            delta = (datetime.strptime(pt,'%Y-%m-%d_%H-%M-%S')-t).total_seconds()
            if abs(delta) <= 3600:
                candidates.append((abs(delta),delta,ply))
        for rank, (_,delta,ply) in enumerate(sorted(candidates,key=lambda a:a[0])[:3],1):
            pair_rows.append({'rgb_capture_id':g['capture_id'],'rgb_folder':g['folder'],
                              'ply_capture_id':ply['capture_id'],'ply_path':ply['source_path'],
                              'dataset_id':g['dataset_id'],'delta_seconds':delta,'candidate_rank':rank,
                              'match_status':'MATCH_CONFLICT' if g['capture_id'] in CONFLICT else 'MATCH_CANDIDATE',
                              'evidence':'timestamp_exact' if delta == 0 else 'same_day_within_1h',
                              'train_eligible':False,'plant_id':None})
        if not candidates:
            pair_rows.append({'rgb_capture_id':g['capture_id'],'rgb_folder':g['folder'],
                              'dataset_id':g['dataset_id'],'match_status':'UNMATCHED','train_eligible':False})
    write_csv('pair_candidates.csv',pair_rows)
    (BASE/'ply_derived_traits.json').write_text(json.dumps(derived,ensure_ascii=False,indent=2),encoding='utf-8')
    summary = {'capture_groups':len(captures),'captures_by_dataset':dict(collections.Counter(g['dataset_id'] for g in captures)),
               'selected_images':sum(sum(len(p) for p in g['selected_images'].values()) for g in captures),
               'corrected_ply_files':len(derived),'unique_ply_content':len(signatures),
               'ply_status':dict(collections.Counter(r['status'] for r in derived)),
               'vendor_csv_files':len(inv['csv_files']),'vendor_measurement_rows':len(vendor),
               'pair_candidates_rows':len(pair_rows),'train_eligible':0}
    (BASE/'catalog_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2),flush=True)


if __name__ == '__main__':
    main()
