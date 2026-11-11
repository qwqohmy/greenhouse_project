"""Split vegetation in raw PLY using a verified Correction coordinate transform."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from plyfile import PlyData,PlyElement
from scipy.spatial import cKDTree

from split_ply_observations import spatial_groups,extract,projection,save_json,write_csv

BASE=Path(__file__).resolve().parent
OUT=BASE/'ply_from_raw_candidates'
VERSION='raw_registered_vegetation_components_v2'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--focus',action='store_true');args=parser.parse_args()
    records=json.loads((BASE/('ply_raw_registration_focus.json' if args.focus else 'ply_raw_registration.json')).read_text(encoding='utf-8'))
    OUT.mkdir(exist_ok=True)
    observations=[];clouds=[]
    for registration in records:
        if registration['status']!='SHARED_VERTEX_GEOMETRY_VERIFIED':
            clouds.append({'source':registration['source_corrected'],'status':'UNVERIFIED_TRANSFORM_SKIPPED'})
            continue
        raw=Path(registration['source_raw']);sha=hashlib.sha256(raw.read_bytes()).hexdigest()
        folder=OUT/(raw.stem+'_'+sha[:10]);folder.mkdir(exist_ok=True)
        checkpoint=folder/'cloud_metadata.json'
        if checkpoint.exists():
            previous=json.loads(checkpoint.read_text(encoding='utf-8'))
            if previous.get('algorithm')==VERSION:
                observations.extend(previous['observations']);clouds.append(previous)
                continue
        v=PlyData.read(str(raw))['vertex'].data
        xyz=np.column_stack([v[k] for k in ('x','y','z')]).astype(float)
        rgb=np.column_stack([v[k] for k in ('red','green','blue')]).astype(float)
        r,g,b=rgb.T
        # Explicitly a weak color proposal, not a validated plant segmentation.
        keep=np.isfinite(xyz).all(axis=1)&(r>35)&(g>35)&(g>.65*r)&(b<.9*np.maximum(r,g))&(r<1.6*g)
        raw_indices=np.flatnonzero(keep)
        transform=np.asarray(registration['correction_to_raw_affine_4x3'])
        matrix,offset=transform[:3],transform[3]
        inverse=np.linalg.inv(matrix)
        aligned=(xyz[keep]-offset)@inverse
        if len(aligned)<100:
            clouds.append({'source':str(raw),'status':'TOO_FEW_VEGETATION_POINTS'})
            continue
        groups,split_info=spatial_groups(aligned,allow_scale_sensitive=True)
        corrected=PlyData.read(registration['source_corrected'])['vertex'].data
        sample=corrected[np.linspace(0,len(corrected)-1,min(len(corrected),2048),dtype=int)]
        corrected_xyz=np.column_stack([sample[k] for k in ('x','y','z')]).astype(float)
        distances,nearest=cKDTree(aligned).query(corrected_xyz)
        close=distances<max(float(np.ptp(aligned,axis=0).max())*1e-4,1e-8)
        point_labels=np.full(len(aligned),-1,dtype=int)
        for group_number,indices in enumerate(groups,1):
            point_labels[indices]=group_number
        local=[]
        for index,indices in enumerate(groups,1):
            observation='rawobs-'+sha[:16]+f'-c{index:02d}'
            target=folder/observation;target.mkdir(exist_ok=True)
            source_indices=raw_indices[indices]
            vertices=np.asarray(v[source_indices]).copy()
            for axis,column in zip(('x','y','z'),aligned[indices].T):
                vertices[axis]=column
            if all(k in vertices.dtype.names for k in ('nx','ny','nz')):
                normals=np.column_stack([vertices[k] for k in ('nx','ny','nz')]).astype(float)@matrix.T
                normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
                for axis,column in zip(('nx','ny','nz'),normals.T):
                    vertices[axis]=column
            PlyData([PlyElement.describe(vertices,'vertex')],text=False).write(str(target/'cloud.ply'))
            np.save(target/'source_vertex_indices.npy',source_indices)
            traits=extract(vertices,observation,str(raw),sha,split_info,target)
            traits.update(algorithm_version=VERSION,source_corrected_reference=registration['source_corrected'],
                          coordinate_frame='verified affine into Correction coordinate frame',
                          plant_color_mask='weak RGB vegetation threshold; requires review',
                          corrected_sample_match_fraction=float(close.mean()),
                          vendor_selected_component_overlap=float(np.mean(point_labels[nearest[close]]==index)) if close.any() else None)
            write_csv(target/'traits.csv',[traits])
            projection(vertices,target/'projections.png')
            record={'observation_id':observation,'source_raw':str(raw),'source_sha256':sha,
                    'source_corrected_reference':registration['source_corrected'],'component_index':index,
                    'vendor_selected_component_overlap':traits['vendor_selected_component_overlap'],
                    'plant_id':None,'scope_status':split_info['status'],'csv_path':str(target/'traits.csv'),
                    'ply_path':str(target/'cloud.ply'),'projection_path':str(target/'projections.png'),
                    'match_status':'MATCH_CANDIDATE','train_eligible':False}
            save_json(target/'metadata.json',{'observation':record,'traits':traits,'spatial_split':split_info,
                                            'registration':registration,'raw_to_corrected_linear':inverse.tolist(),
                                            'raw_offset_before_linear':offset.tolist()})
            local.append(record)
        cloud={'source':str(raw),'algorithm':VERSION,'color_selected_points':len(aligned),
               'source_points':len(v),'spatial_split':split_info,'observations':local,'status':'CANDIDATES_NEED_REVIEW'}
        save_json(checkpoint,cloud);observations.extend(local);clouds.append(cloud)
        print(raw.stem,'objects',len(local),'near/far',split_info['near_components'],split_info['far_components'],flush=True)
    if observations:
        write_csv(OUT/'observations.csv',observations);save_json(OUT/'observations.json',observations)
    save_json(OUT/'cloud_review.json',clouds)
    save_json(OUT/'summary.json',{'source_registrations':len(records),'observation_proposals':len(observations),
                                'verified_image_matches':0,'train_eligible':0})


if __name__=='__main__':
    main()
