"""Link reviewed single-plant scenes to one corrected CSV and available RGB crops.

Scene-local linkage, physical identity, crop quality and training admission are separate.
"""
import csv
import argparse
import contextlib
from datetime import datetime
import json
import os
from pathlib import Path
import time

BASE=Path(__file__).resolve().parent
OUT=BASE/'plant_observation_links'
RGB=Path(os.environ.get('RGB_SAM_ROOT','data/rgb_sam'))


def main():
    OUT.mkdir(exist_ok=True)
    decisions=json.loads((BASE/'single_pot_visual_decisions.json').read_text(encoding='utf-8'))
    clean=json.loads((BASE/'single_pot_audit'/'clean_target_review.json').read_text(encoding='utf-8'))
    catalog=json.loads((BASE/'capture_catalog.json').read_text(encoding='utf-8'))
    by_id={group['capture_id']:group for group in catalog}
    by_day={}
    for group in catalog:
        if group['dataset_id']=='lettuce_new_202609':
            by_day.setdefault(group['capture_id'][:10],[]).append(group['capture_id'])
    for values in by_day.values():
        values.sort()
    spectral={}
    if (BASE/'crossmodal_candidates.csv').exists():
        with (BASE/'crossmodal_candidates.csv').open(encoding='utf-8-sig',newline='') as file:
            spectral={row['rgb_capture_id']:row for row in csv.DictReader(file)}
    results=[]
    for selection in clean:
        scene=selection['scene_id']
        if scene not in decisions['clean_single_scene_ids']:
            continue
        group=by_id[scene]
        folder=RGB/group['dataset_id']/scene
        accepted=[];held=[];processed=0
        for path in sorted(folder.glob('CAM*/*/metadata.json')):
            record=json.loads(path.read_text(encoding='utf-8'))
            processed+=1
            reason=None
            if len(record['instances'])!=1:
                reason='NO_DETECTION' if not record['instances'] else 'MULTIPLE_MASKS_IN_SINGLE_PLANT_SCENE'
            elif record['camera'] not in ('2','4'):
                reason='CAM1_CAM3_EXCLUDED_DUE_TO_TRUNCATION_IN_REVIEWED_VIEWS'
            elif record['instances'][0]['source_edge_truncated_candidate']:
                reason='SOURCE_EDGE_TRUNCATED'
            elif record['overlapping_masks']:
                reason='OVERLAPPING_MASKS'
            if reason:
                held.append({'source':record['source'],'metadata':str(path),'reason':reason});continue
            instance=record['instances'][0]
            crop_dir=Path(instance['output_directory'])
            files=[crop_dir/name for name in ('rgb.png','mask.png','segmented.png')]
            if not all(file.is_file() for file in files):
                held.append({'source':record['source'],'metadata':str(path),'reason':'INCOMPLETE_OUTPUT_FILES'});continue
            accepted.append({'source_rgb':record['source'],'camera':record['camera'],
                             'frame_index_in_camera':record['frame_index_in_camera'],
                             'metadata':str(path),'rgb_crop':str(files[0]),'mask':str(files[1]),
                             'segmented_rgb':str(files[2]),'source_bbox_xyxy':instance['source_bbox_xyxy'],
                             'mask_quality_status':'AUTOMATED_SCREEN_ONLY_NOT_MANUAL_SEGMENTATION_TRUTH',
                             'scene_local_plant_id':scene+'__single_01','train_eligible':False})
        with Path(selection['corrected_csv_path']).open(encoding='utf-8-sig',newline='') as file:
            target=list(csv.DictReader(file))
        assert len(target)==1
        local=scene+'__single_01'
        physical=None
        identity_evidence=None
        batch='lettuce_run1' if scene<'2026-07-01' else 'lettuce_run3'
        sequence=None
        if scene in spectral:
            physical='lettuce_run1_A-1_P11'
            identity_evidence='PPT slide4 late first-run single-pot A1-11; verify source marker/physical pot continuity'
        elif batch=='lettuce_run3':
            values=by_day.get(scene[:10],[])
            if len(values)==4:
                sequence=values.index(scene)+1
                physical=f'lettuce_run3_single_light_P{sequence:02d}'
                identity_evidence='User daily chronological ordering rule, four scenes per day; cross-date physical identity not independently checked'
        spectral_link=None
        if scene in spectral:
            candidate=spectral[scene]
            plant_dir=Path(candidate['spectral_plant_directory'])
            source_metadata=plant_dir.parent/'_SUCCESS.json'
            if source_metadata.exists():
                meta=json.loads(source_metadata.read_text(encoding='utf-8'))
                assert meta['batch']==1 and meta['light_condition']=='A-1' and 11 in meta['plant_numbers']
                assert (plant_dir/'L405.png').exists()
                rgb_time=datetime.strptime(scene,'%Y-%m-%d_%H-%M-%S')
                spectral_time=datetime.strptime(candidate['spectral_capture_id'],'%Y-%m-%d_%H-%M-%S')
                spectral_link={'capture_id':candidate['spectral_capture_id'],'plant_directory':str(plant_dir),
                               'l405_path':str(plant_dir/'L405.png'),'metadata':str(source_metadata),
                               'light_code':'A-1','plant_no':11,'seconds_after_rgb':(spectral_time-rgb_time).total_seconds(),
                               'status':'LAYOUT_BASED_SAME_DAY_CANDIDATE_NOT_SIMULTANEOUS',
                               'harvest_link_status':'UNCONFIRMED_HARVEST_PLANT_NUMBER'}
        row={'observation_id':local,'capture_id':scene,'crop':'lettuce','crop_batch':batch,
             'scene_local_plant_id':local,'physical_plant_id':None,'physical_plant_id_candidate':physical,
             'physical_identity_evidence':identity_evidence,'daily_capture_sequence_candidate':sequence,
             'scene_link_status':'LINKED_SINGLE_PLANT_SCENE_BY_EXACT_TIME_AND_VISUAL_REVIEW',
             'scene_link_limit':'Single plant observed in corrected PLY and eight reviewed RGB views; no calibrated camera-to-PLY registration or full-view identity audit.',
             'target_csv_path':selection['corrected_csv_path'],'source_corrected_ply':selection['source_corrected'],
             'excluded_raw_csv':selection['raw_candidate_csv'],'target_values':{key:target[0][key] for key in ('pGH_proxy','pMW_proxy','xy_convex_hull_area','coordinate_unit')},
             'averaged_across_plants':False,'rgb_source_folder':group['folder'],
             'rgb_frames_expected':sum(group['camera_counts'].values()),'sam_metadata_found':processed,
             'rgb_crop_candidates':accepted,'held_rgb_frames':held,'spectral_candidate':spectral_link,
             'train_eligible':False,'remaining_training_checks':['coordinate_units_and_target_definitions','full_plant_geometry_completeness','per_input_mask_quality_and_identity'],
             'harvest_measurements_attached':False}
        assert Path(row['target_csv_path']).is_file()
        results.append(row)
    assert len({row['target_csv_path'] for row in results})==len(results)
    summary={'scene_observations_linked':len(results),'unique_target_csvs':len(results),
             'rgb_crop_candidates':sum(len(row['rgb_crop_candidates']) for row in results),
             'held_rgb_frames':sum(len(row['held_rgb_frames']) for row in results),
             'spectral_layout_candidates':sum(row['spectral_candidate'] is not None for row in results),
             'confirmed_cross_date_physical_ids':0,'train_eligible':0,
             'note':'Local scene linkage is separate from physical pot identity and formal training admission.'}
    (OUT/'observations.json').write_text(json.dumps({'summary':summary,'observations':results},ensure_ascii=False,indent=2),encoding='utf-8')
    fields=['observation_id','capture_id','crop_batch','physical_plant_id_candidate','daily_capture_sequence_candidate','target_csv_path','rgb_frames_expected','sam_metadata_found','scene_link_status','train_eligible']
    with (OUT/'observations.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields+['rgb_crop_candidates','held_rgb_frames','spectral_l405_candidate'])
        writer.writeheader()
        for row in results:
            writer.writerow({**{key:row[key] for key in fields},'rgb_crop_candidates':len(row['rgb_crop_candidates']),
                             'held_rgb_frames':len(row['held_rgb_frames']),
                             'spectral_l405_candidate':(row['spectral_candidate'] or {}).get('l405_path')})
    view_fields=['observation_id','capture_id','physical_plant_id_candidate','camera','frame_index_in_camera',
                 'source_rgb','rgb_crop','mask','segmented_rgb','target_csv_path','train_eligible']
    with (OUT/'image_to_csv.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=view_fields);writer.writeheader()
        for row in results:
            for view in row['rgb_crop_candidates']:
                writer.writerow({**{key:row[key] for key in ('observation_id','capture_id','physical_plant_id_candidate','target_csv_path','train_eligible')},
                                 **{key:view[key] for key in ('camera','frame_index_in_camera','source_rgb','rgb_crop','mask','segmented_rgb')}})
    print(json.dumps({'summary':summary,'scenes':[{'capture_id':row['capture_id'],'rgb_candidates':len(row['rgb_crop_candidates']),
                       'sam_metadata_found':row['sam_metadata_found'],'physical_id_candidate':row['physical_plant_id_candidate']} for row in results]},ensure_ascii=False))
    return all(row['sam_metadata_found']==row['rgb_frames_expected'] for row in results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    if args.watch:
        OUT.mkdir(exist_ok=True)
        with (OUT/'refresh.log').open('a',encoding='utf-8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            while True:
                complete=main()
                (OUT/'refresh_status.json').write_text(json.dumps({'status':'complete' if complete else 'watching_sam',
                            'pid':os.getpid(),'updated_at':time.strftime('%Y-%m-%d %H:%M:%S')},indent=2),encoding='utf-8')
                if complete:
                    break
                time.sleep(30)
    else:
        main()
