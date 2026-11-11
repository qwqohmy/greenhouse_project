"""CPU-only PLY observation proposals with per-object CSV and provenance."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')

import numpy as np
from PIL import Image, ImageDraw
from plyfile import PlyData, PlyElement
from scipy.spatial import ConvexHull, distance
from sklearn.cluster import DBSCAN

BASE=Path(__file__).resolve().parent
OUT=BASE/'ply_singleplant_candidates'
VERSION='spatial_components_v1'


def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def spatial_groups(xyz,allow_scale_sensitive=False):
    # Two scales expose obvious disconnected crowns; components are not plant identity.
    span=np.ptp(xyz,axis=0)
    scale=max(float(np.max(span)),1e-8)
    voxel=scale/120
    cells=np.floor((xyz-xyz.min(axis=0))/voxel).astype(np.int32)
    unique,index,inverse=np.unique(cells,axis=0,return_index=True,return_inverse=True)
    sample=xyz[index]
    if len(sample)>60000:
        voxel=scale/80
        cells=np.floor((xyz-xyz.min(axis=0))/voxel).astype(np.int32)
        unique,index,inverse=np.unique(cells,axis=0,return_index=True,return_inverse=True)
        sample=xyz[index]
    near=DBSCAN(eps=3*voxel,min_samples=3,n_jobs=1).fit_predict(sample)
    far=DBSCAN(eps=6*voxel,min_samples=3,n_jobs=1).fit_predict(sample)
    def substantial(labels):
        full=labels[inverse]
        counts={int(label):int(np.sum(full==label)) for label in np.unique(full) if label>=0}
        main=[label for label,count in counts.items() if count>=max(100,int(len(xyz)*.10))]
        return full,main,counts
    full,main,counts=substantial(near)
    _,far_main,_=substantial(far)
    if len(main)>1 and (len(main)==len(far_main) or allow_scale_sensitive):
        retained=sum(counts[label] for label in main)/len(xyz)
        if retained>=.97:
            groups=[np.flatnonzero(full==label) for label in main]
            groups.sort(key=lambda ids:tuple(xyz[ids].mean(axis=0)))
            return groups,{'status':'STABLE_COMPONENTS_CANDIDATE' if len(main)==len(far_main) else 'SCALE_SENSITIVE_COMPONENTS_REVIEW','near_components':len(main),'far_components':len(far_main),
                           'voxel_size':voxel,'unassigned_fraction':1-retained,
                           'warning':'Disconnected components may be leaves of one plant; touching plants may remain connected.'}
    return [np.arange(len(xyz))],{'status':'WHOLE_CORRECTED_CLOUD_REQUIRES_SINGLE_PLANT_REVIEW',
                                'near_components':len(main),'far_components':len(far_main),
                                'voxel_size':voxel,'unassigned_fraction':0.,
                                'warning':'Whole cloud kept as an observation proposal, not asserted to be one pot. No forced per-plant split.'}


def projection(vertices,path):
    xyz=np.column_stack([vertices[k] for k in ('x','y','z')]).astype(float)
    colors=np.column_stack([vertices[k] for k in ('red','green','blue')]) if all(k in vertices.dtype.names for k in ('red','green','blue')) else np.tile([110,200,80],(len(xyz),1))
    take=np.linspace(0,len(xyz)-1,min(len(xyz),100000),dtype=int)
    xyz=xyz[take];colors=colors[take]
    panel=Image.new('RGB',(1500,530),'white')
    draw=ImageDraw.Draw(panel)
    for column,(a,b,label) in enumerate([(0,1,'XY'),(0,2,'XZ'),(1,2,'YZ')]):
        xy=xyz[:,[a,b]]
        size=np.ptp(xy,axis=0)
        scale=460/max(float(size.max()),1e-8)
        coords=np.round((xy-xy.min(axis=0))*scale).astype(int)
        tile=np.zeros((480,480,3),dtype=np.uint8)
        px=np.clip(coords[:,0]+10,0,479);py=np.clip(469-coords[:,1],0,479)
        tile[py,px]=colors
        panel.paste(Image.fromarray(tile),(column*500,30))
        draw.text((column*500+10,10),label,fill='black')
    panel.save(path)


def extract(vertices,observation,source,sha,split_info,folder):
    xyz=np.column_stack([vertices[k] for k in ('x','y','z')]).astype(float)
    span=np.ptp(xyz,axis=0)
    mean=xyz.mean(axis=0)
    row={'observation_id':observation,'plant_id':'','measurement_source':'PLY_DERIVED',
         'algorithm_version':VERSION,'source_ply':source,'source_sha256':sha,
         'point_count':len(vertices),'coordinate_unit':'UNVERIFIED','vertical_axis':'Z_ASSUMED_CORRECTED_FRAME',
         'scope_status':split_info['status'],'match_status':'MATCH_CANDIDATE','train_eligible':False,
         'pGH_proxy':float(span[2]),'pGH_method':'Z max minus min, not vendor algorithm',
         'extent_x':float(span[0]),'extent_y':float(span[1]),'extent_z':float(span[2]),
         'centroid_x':float(mean[0]),'centroid_y':float(mean[1]),'centroid_z':float(mean[2]),
         'pMW_proxy':None,'xy_convex_hull_area':None,
         'pTLA':None,'pPLA':None,'pLAA':None,'pCHA':None,'pE':None,
         'unavailable_reason':'Area/angle vendor algorithms and calibrated units not validated'}
    if len(xyz)>=4:
        try:
            h=ConvexHull(xyz[:,:2])
            row['pMW_proxy']=float(distance.pdist(xyz[h.vertices,:2]).max())
            row['xy_convex_hull_area']=float(h.volume)
        except Exception:
            row['geometry_warning']='Degenerate horizontal hull'
    if all(k in vertices.dtype.names for k in ('nx','ny','nz')):
        normals=np.column_stack([vertices[k] for k in ('nx','ny','nz')]).astype(float)
        norm=np.linalg.norm(normals,axis=1)
        valid=np.isfinite(norm)&(norm>1e-8)
        if valid.any():
            row['normal_tilt_mean_deg']=float(np.degrees(np.arccos(np.clip(np.abs(normals[valid,2])/norm[valid],0,1))).mean())
            row['normal_tilt_method']='Point-normal mean relative to Z; not mean segmented-leaf angle or vendor pLAA'
    write_csv(folder/'traits.csv',[row])
    return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--max-clouds',type=int)
    args=parser.parse_args()
    candidates=json.loads((BASE/'ply_derived_traits.json').read_text(encoding='utf-8'))
    candidates=[r for r in candidates if not r.get('duplicate_of')]
    if args.max_clouds:
        indices=np.linspace(0,len(candidates)-1,min(args.max_clouds,len(candidates)),dtype=int)
        candidates=[candidates[i] for i in indices]
    OUT.mkdir(exist_ok=True)
    manifest=[];issues=[]
    progress={'status':'running','total_clouds':len(candidates),'done_clouds':0,'observation_proposals':0,'errors':0,'algorithm':VERSION}
    status=BASE/'ply_split_status.json'
    save_json(status,progress)
    for item in candidates:
        p=Path(item['source_path'])
        sha=item['sha256']
        cloud_id=(item.get('capture_id') or 'unknown')+'_'+sha[:10]
        target=OUT/cloud_id
        try:
            existing=target/'cloud_metadata.json'
            if existing.exists():
                meta=json.loads(existing.read_text(encoding='utf-8'))
                if meta.get('algorithm_version')==VERSION and meta.get('status')=='complete':
                    manifest.extend(meta['observations']);progress['done_clouds']+=1
                    progress['observation_proposals']+=len(meta['observations']);save_json(status,progress);continue
            data=PlyData.read(str(p));v=data['vertex'].data
            xyz=np.column_stack([v[k] for k in ('x','y','z')]).astype(float)
            good=np.isfinite(xyz).all(axis=1);original_indices=np.flatnonzero(good);xyz=xyz[good]
            if len(xyz)<4:
                raise ValueError('Too few finite vertices')
            groups,split_info=spatial_groups(xyz)
            target.mkdir(parents=True,exist_ok=True)
            observations=[]
            for number,indices in enumerate(groups,1):
                obs='obs-'+sha[:16]+f'-c{number:02d}'
                folder=target/obs;folder.mkdir(exist_ok=True)
                original=original_indices[indices]
                selected=v[original]
                PlyData([PlyElement.describe(np.asarray(selected),'vertex')],text=False).write(str(folder/'cloud.ply'))
                np.save(folder/'source_vertex_indices.npy',original.astype(np.int64))
                traits=extract(selected,obs,str(p),sha,split_info,folder)
                projection(selected,folder/'projections.png')
                record={'observation_id':obs,'source_capture_id':item.get('capture_id'),
                        'source_ply':str(p),'source_sha256':sha,'component_index':number,
                        'plant_id':None,'scope_status':split_info['status'],'match_status':'MATCH_CANDIDATE',
                        'csv_path':str(folder/'traits.csv'),'ply_path':str(folder/'cloud.ply'),
                        'projection_path':str(folder/'projections.png'),'train_eligible':False}
                save_json(folder/'metadata.json',{'observation':record,'spatial_split':split_info,'traits':traits})
                observations.append(record)
            meta={'status':'complete','algorithm_version':VERSION,'source_path':str(p),'source_sha256':sha,
                  'source_points':len(v),'finite_points':len(xyz),'spatial_split':split_info,'observations':observations}
            save_json(existing,meta)
            manifest.extend(observations)
            progress['observation_proposals']+=len(observations)
        except Exception:
            progress['errors']+=1
            issues.append({'source':str(p),'error':traceback.format_exc()})
        progress['done_clouds']+=1
        progress['current_cloud']=str(p);progress['updated_at']=time.strftime('%Y-%m-%d %H:%M:%S')
        save_json(status,progress)
        print(json.dumps(progress),flush=True)
    if manifest:
        write_csv(OUT/'observations.csv',manifest)
        save_json(OUT/'observations.json',manifest)
    save_json(OUT/'errors.json',issues)
    progress['status']='complete_with_review' if not issues else 'complete_with_errors'
    save_json(status,progress)
    print(json.dumps(progress),flush=True)


if __name__=='__main__':
    main()
