"""Recover Correction-to-raw affine maps only from verified shared vertex signatures."""
import argparse
import json
from pathlib import Path
from datetime import datetime
import numpy as np
from plyfile import PlyData

from build_catalog import timestamp

BASE=Path(__file__).resolve().parent


def signatures(v):
    fields=['nx','ny','nz','red','green','blue']
    if not all(k in v.dtype.names for k in fields):
        raise ValueError('No exact normal/color signatures available')
    out=np.empty(len(v),dtype=[(k,v.dtype[k]) for k in fields])
    for k in fields:
        out[k]=v[k]
    return out


def xyz(v):
    return np.column_stack([v[k] for k in ('x','y','z')]).astype(float)


def register(corrected, raw):
    cv=PlyData.read(corrected)['vertex'].data
    rv=PlyData.read(raw)['vertex'].data
    sample=cv[np.linspace(0,len(cv)-1,min(2048,len(cv)),dtype=int)]
    common,ri,ci=np.intersect1d(signatures(rv),signatures(sample),return_indices=True)
    result={'shared_signatures':len(common),'sampled_corrected_vertices':len(sample),'status':'REGISTRATION_UNRESOLVED'}
    if len(common)<20:
        return result
    a=xyz(sample[ci]);b=xyz(rv[ri])
    finite=np.isfinite(a).all(axis=1)&np.isfinite(b).all(axis=1)
    a=a[finite];b=b[finite]
    x=np.column_stack([a,np.ones(len(a))])
    scale=max(float(np.linalg.norm(np.ptp(b,axis=0))),1e-12)
    rng=np.random.default_rng(1)
    best=np.zeros(len(a),dtype=bool)
    for _ in range(120):
        ids=rng.choice(len(a),4,replace=False)
        if np.linalg.matrix_rank(x[ids])<4:
            continue
        transform=np.linalg.lstsq(x[ids],b[ids],rcond=None)[0]
        residual=np.linalg.norm(x@transform-b,axis=1)
        inliers=residual<scale*1e-4
        if inliers.sum()>best.sum():
            best=inliers
    if best.sum()<20:
        return result
    transform=np.linalg.lstsq(x[best],b[best],rcond=None)[0]
    residual=np.linalg.norm(x@transform-b,axis=1)
    result.update(inlier_matches=int(best.sum()),inlier_fraction=float(best.mean()),
                  median_relative_residual=float(np.median(residual)/scale),
                  p95_relative_residual=float(np.quantile(residual,.95)/scale))
    if best.mean()>.95 and np.quantile(residual,.95)<scale*1e-4:
        result.update(status='SHARED_VERTEX_GEOMETRY_VERIFIED',correction_to_raw_affine_4x3=transform.tolist())
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-clouds',type=int);parser.add_argument('--capture-id',action='append');args=parser.parse_args()
    inv=json.loads((BASE/'inventory.json').read_text(encoding='utf-8'))
    rows=json.loads((BASE/'ply_derived_traits.json').read_text(encoding='utf-8'))
    rows=[r for r in rows if not r.get('duplicate_of')]
    if args.capture_id:
        rows=[r for r in rows if r['capture_id'] in args.capture_id]
    if args.max_clouds:
        ids=np.linspace(0,len(rows)-1,min(args.max_clouds,len(rows)),dtype=int);rows=[rows[i] for i in ids]
    results=[]
    for row in rows:
        corrected=Path(row['source_path'])
        target=datetime.strptime(row['capture_id'],'%Y-%m-%d_%H-%M-%S')
        candidates=[]
        for p in inv['ply_files']:
            raw=Path(p)
            stamp=timestamp(p)
            if raw.parent==corrected.parent and '_B_3D' in raw.name and stamp:
                delta=abs((datetime.strptime(stamp,'%Y-%m-%d_%H-%M-%S')-target).total_seconds())
                if delta<=2:
                    candidates.append((delta,p))
        entry={'source_corrected':str(corrected),'source_sha256':row['sha256'],'status':'RAW_NOT_FOUND'}
        if candidates:
            raw=sorted(candidates)[0][1]
            try:
                entry.update(register(str(corrected),raw));entry['source_raw']=raw
            except Exception as exc:
                entry.update(status='REGISTRATION_ERROR',error=str(exc))
        results.append(entry)
        print(row['capture_id'],entry['status'],entry.get('shared_signatures',0),flush=True)
        output=BASE/('ply_raw_registration_focus.json' if args.capture_id else 'ply_raw_registration.json')
        output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
