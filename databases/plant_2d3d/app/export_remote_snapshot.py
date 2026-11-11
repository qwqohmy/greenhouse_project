import os
"""Read remote experiment outputs into a portable, compressed metadata snapshot."""
import csv
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
from collections import defaultdict

BASE=Path(__file__).resolve().parent
PIPELINE=Path(os.environ.get('PIPELINE_ROOT','data/pipeline'))
RGB=Path(os.environ.get('RGB_SAM_ROOT','data/rgb_sam'))


def load(name):
    return json.loads((PIPELINE/name).read_text(encoding='utf-8'))


def main():
    policy=load('rgb_processing_policy.json');catalog=load('capture_catalog.json')
    inventory=load('inventory.json');coverage=load('all_ply_csv_coverage.json')
    strict=load('single_pot_audit/strict_targets_review.json')
    links=load('plant_observation_links/observations.json')
    assets={};sessions=[];images=[];segmentations=[];exports=[]
    def asset(path,kind,sha=None):
        if not path:
            return None
        path=str(Path(path));key=path.casefold()
        if key not in assets:
            try:
                size=Path(path).stat().st_size;exists=True
            except FileNotFoundError:
                size=None;exists=False
            assets[key]={'path':path,'kind':kind,'content_sha256':sha,'size':size,'exists':exists}
        elif sha:
            assets[key]['content_sha256']=sha
        return key
    for row in coverage['files']:
        asset(row['source_ply'],'PLY_CORRECTED' if 'correction' in row['source_ply'].lower() else 'PLY_RAW',row['sha256'])
    for group in catalog:
        scene=group['capture_id'];batch=None
        if group['crop']=='lettuce':
            batch='lettuce_run3' if group['dataset_id']=='lettuce_new_202609' else ('lettuce_run1' if scene<'2026-07-01' else 'lettuce_run2')
        elif group['crop']=='tomato':
            batch='tomato_run1' if scene<'2026-10-01' else 'tomato_run2'
        status='HOLD' if scene in policy['hold_capture_ids'] else ('CONFLICT' if scene in policy['conflict_capture_ids'] else ('SUSPECTED_CONFLICT' if scene in policy.get('suspected_conflict_capture_ids',[]) else 'CAPTURE_CATALOG'))
        crop=group['crop']
        if status=='HOLD':
            crop='unknown';batch=None
        key='rgb:'+group['dataset_id']+':'+scene
        sessions.append({'key':key,'kind':'RGB','capture_code':scene,'crop':crop,'batch':batch,
                         'folder':group['folder'],'dataset':group['dataset_id'],'expected':sum(group['camera_counts'].values()),'review_status':status,'evidence':group})
        for camera in sorted(group['camera_counts']):
            paths=sorted(path for path in Path(group['folder']).glob('CAM'+camera+'_*') if path.suffix.lower() in ('.jpg','.jpeg','.png'))
            for index,path in enumerate(paths,1):
                raw_key=asset(path,'RGB_RAW')
                images.append({'asset':raw_key,'session':key,'kind':'RAW','camera':camera,'frame_index':index,
                               'quality':'UNREVIEWED','source':None,'mask':None,'segmented':None,'metadata':None,'instance':None,'algorithm':None,'bbox':None,'edge':False})
                metadata=RGB/group['dataset_id']/scene/('CAM'+camera)/path.stem/'metadata.json'
                if not metadata.exists():
                    continue
                try:
                    record=json.loads(metadata.read_text(encoding='utf-8'))
                except (OSError,json.JSONDecodeError):
                    continue
                meta_key=asset(metadata,'METADATA')
                segmentations.append({'source':raw_key,'metadata':meta_key,'algorithm':record['algorithm'],
                                      'status':record['status'],'count':len(record['instances']),
                                      'details':{key:record.get(key) for key in ('source_size_wh','source_roi_xyxy','working_size_wh','working_to_source_scale_xy','overlapping_masks','has_vegetation_candidate','physical_identity_verified')}})
                for instance in record['instances']:
                    root=Path(instance['output_directory'])
                    images.append({'asset':asset(root/'rgb.png','RGB_CROP'),'session':key,'kind':'CROP','camera':camera,'frame_index':index,
                                   'source':raw_key,'mask':asset(root/'mask.png','MASK'),'segmented':asset(root/'segmented.png','SEGMENTED_RGB'),
                                   'metadata':meta_key,'instance':instance['instance_local_id'],'algorithm':record['algorithm'],
                                   'bbox':instance['source_bbox_xyxy'],'edge':instance['source_edge_truncated_candidate'],
                                   'quality':'EDGE_REVIEW' if instance['source_edge_truncated_candidate'] else 'CANDIDATE'})
        if len(sessions)%15==0:
            print(json.dumps({'rgb_sessions':len(sessions),'images':len(images)}),flush=True)
    raw_obs=load('ply_from_raw_candidates/observations.json')
    by_source={row['source_raw']:row for row in raw_obs}
    for source,row in by_source.items():
        code=re.search(r'2026-\d\d-\d\d_\d\d-\d\d-\d\d',source).group()
        crop='tomato' if '\\tomato\\' in source.casefold() else 'lettuce'
        batch=('tomato_run1' if code<'2026-10-01' else 'tomato_run2') if crop=='tomato' else ('lettuce_run3' if '\\lettuce 3d\\' in source.casefold() else ('lettuce_run1' if code<'2026-07-01' else 'lettuce_run2'))
        sessions.append({'key':'ply:'+row['source_sha256'],'kind':'PLY','capture_code':code,'crop':crop,'batch':batch,
                         'folder':str(Path(source).parent),'dataset':None,'expected':0,'review_status':'GEOMETRY_CANDIDATE','evidence':{'source_sha256':row['source_sha256']}})
    for kind,name in (('RAW_COMPONENT','ply_from_raw_candidates/observations.json'),('CORRECTION_SELECTION','ply_singleplant_candidates/observations.json')):
        for row in load(name):
            path=Path(row['csv_path']);folder=path.parent
            with path.open(encoding='utf-8-sig',newline='') as file:
                values=list(csv.DictReader(file))
            assert len(values)==1
            values=values[0]
            exports.append({'key':row['observation_id'],'kind':kind,'csv':asset(path,'CSV',hashlib.sha256(path.read_bytes()).hexdigest()),
                            'source_ply':asset(values['source_ply'],'PLY_RAW' if kind=='RAW_COMPONENT' else 'PLY_CORRECTED',row['source_sha256']),
                            'geometry':asset(row['ply_path'],'PLY_COMPONENT'),'indices':asset(folder/'source_vertex_indices.npy','POINT_INDICES'),
                            'metadata':asset(folder/'metadata.json','METADATA'),'values':values})
    with (PIPELINE/'pair_candidates.csv').open(encoding='utf-8-sig',newline='') as file:
        pairs=list(csv.DictReader(file))
    result={'version':1,'source_host':'plant','assets':list(assets.values()),'sessions':sessions,'images':images,
            'segmentations':segmentations,'csv_exports':exports,'raw_observations':raw_obs,
            'strict_review':strict,'local_links':links,'time_candidates':pairs,'policy':policy,
            'batch_rules':load('experiment_batches.json')['plant_counts'],
            'segmentation_status':load('segmentation_batch_status.json'),'tomato_queue_status':load('tomato_queue_status.json')}
    runs=defaultdict(list)
    for path in PIPELINE.glob('segmentation_p*_shard_*_status.json'):
        state=json.loads(path.read_text(encoding='utf-8'))
        runs[state['run_id']].append(state)
    result['processing_runs']=[]
    for run_id,states in runs.items():
        if len(states)!=states[0]['shard_count'] or not all(state['status']=='complete_with_review' for state in states):
            continue
        summary={'run_id':run_id,'status':'complete_with_review','total_images':sum(state['total_images'] for state in states),
                 'done':sum(state['done'] for state in states),'instances':sum(state['instances'] for state in states),
                 'no_detection':sum(state['no_detection'] for state in states),'errors':sum(state['errors'] for state in states)}
        summary['capture_set']='tomato_confirmed' if summary['total_images']==1440 else 'main_109_scenes'
        result['processing_runs'].append(summary)
    result['summary']={'assets':len(assets),'sessions':len(sessions),'raw_images':sum(row['kind']=='RAW' for row in images),
                       'crop_images':sum(row['kind']=='CROP' for row in images),'segmentation_results':len(segmentations),
                       'csv_exports':len(exports),'observations':len(strict['records'])}
    with gzip.open(BASE/'snapshot.json.gz','wt',encoding='utf-8') as file:
        json.dump(result,file,ensure_ascii=False,separators=(',',':'))
    print(json.dumps(result['summary']),flush=True)


if __name__=='__main__':
    main()
