"""Idempotent metadata import into independent p3d_ tables; no training is run."""
import argparse
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path

from database import BASE,connect


def norm(path):
    return path.replace('/','\\').casefold() if path else None


def js(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def numeric(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (ValueError,TypeError):
        return None


def upsert(cursor,table,columns,rows,preserve=()):
    if not rows:
        return
    assert table.startswith('p3d_') and table.replace('_','').isalnum()
    updates=','.join(f'{column}=VALUES({column})' for column in columns if column not in preserve)
    query=f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s']*len(columns))}) ON DUPLICATE KEY UPDATE {updates}"
    for first in range(0,len(rows),500):
        cursor.executemany(query,rows[first:first+500])
    print(js({'table':table,'input_rows':len(rows)}),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,default=BASE/'snapshot.json.gz');args=parser.parse_args()
    source_hash=hashlib.sha256(args.snapshot.read_bytes()).hexdigest()
    with gzip.open(args.snapshot,'rt',encoding='utf-8') as file:
        data=json.load(file)
    connection=connect()
    try:
        with connection.cursor() as cursor:
            sql='\n'.join(line for line in (BASE/'schema.sql').read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith('--'))
            for statement in sql.split(';'):
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute("SHOW TABLES LIKE 'capture_groups'");has_legacy=cursor.fetchone() is not None
            legacy_before=None
            if has_legacy:
                cursor.execute('SELECT COUNT(*) FROM capture_groups');legacy_before=cursor.fetchone()[0]
            upsert(cursor,'p3d_hosts',['host_code','description'],[('plant','Remote Windows host accessed through ssh plant; paths belong to that host')])
            cursor.execute("SELECT id FROM p3d_hosts WHERE host_code='plant'");host=cursor.fetchone()[0]
            batch_rows=[(row['crop']+'_'+row['batch'],row['crop'],row['plants_per_light'],row['light_count'],'User-confirmed plants per light, not samples per image') for row in data['batch_rules']]
            upsert(cursor,'p3d_batches',['batch_code','crop','plants_per_light','light_count','evidence'],batch_rows)
            cursor.execute('SELECT batch_code,id FROM p3d_batches');batches=dict(cursor.fetchall())
            session_rows=[(row['key'],row['kind'],host,batches.get(row['batch']),row['capture_code'],
                datetime.strptime(row['capture_code'],'%Y-%m-%d_%H-%M-%S'),row['crop'],row['folder'],row['dataset'],row['expected'],row['review_status'],js(row['evidence'])) for row in data['sessions']]
            upsert(cursor,'p3d_sessions',['session_key','session_kind','source_host_id','batch_id','capture_code','captured_at','crop','source_folder','dataset_code','expected_rgb_frames','review_status','evidence_json'],session_rows)
            cursor.execute('SELECT session_key,id FROM p3d_sessions');sessions=dict(cursor.fetchall())
            asset_rows=[(host,hashlib.sha256(norm(row['path']).encode()).hexdigest(),row['path'],row['kind'],row['content_sha256'],row['size'],row['exists']) for row in data['assets']]
            upsert(cursor,'p3d_assets',['host_id','path_sha256','file_path','asset_kind','content_sha256','file_size_bytes','exists_on_export'],asset_rows)
            cursor.execute('SELECT file_path,id FROM p3d_assets WHERE host_id=%s',(host,));assets={norm(path):identity for path,identity in cursor.fetchall()}
            aid=lambda path:assets[norm(path)] if path else None
            held_sessions={row['key'] for row in data['sessions'] if row['review_status'] in ('HOLD','CONFLICT','SUSPECTED_CONFLICT')}
            image_rows=[(aid(row['asset']),sessions[row['session']],aid(row['source']),aid(row['mask']),aid(row['segmented']),aid(row['metadata']),row['kind'],row['camera'],row['frame_index'],row['instance'],row['algorithm'],'HOLD_SOURCE' if row['session'] in held_sessions else row['quality'],js(row['bbox']) if row['bbox'] is not None else None,row['edge']) for row in data['images']]
            upsert(cursor,'p3d_images',['asset_id','session_id','source_image_asset_id','mask_asset_id','segmented_asset_id','metadata_asset_id','image_kind','camera_code','frame_index','instance_local_id','algorithm_version','quality_status','source_bbox_json','source_edge_truncated'],image_rows)
            cursor.execute('SELECT asset_id,id FROM p3d_images');images_by_asset=dict(cursor.fetchall())
            upsert(cursor,'p3d_segmentation_results',['source_image_asset_id','metadata_asset_id','algorithm_version','result_status','instance_count','details_json'],
                [(aid(row['source']),aid(row['metadata']),row['algorithm'],row['status'],row['count'],js(row['details'])) for row in data['segmentations']])
            export_rows=[(row['key'],aid(row['csv']),aid(row['source_ply']),aid(row['geometry']),aid(row['indices']),aid(row['metadata']),row['kind'],row['values']['algorithm_version'],row['values']['coordinate_unit'],row['values'].get('scope_status'),js(row['values'])) for row in data['csv_exports']]
            upsert(cursor,'p3d_csv_exports',['export_key','csv_asset_id','source_ply_asset_id','geometry_asset_id','point_indices_asset_id','metadata_asset_id','export_kind','algorithm_version','coordinate_unit','source_scope_status','raw_values_json'],export_rows)
            cursor.execute('SELECT e.id,a.file_path FROM p3d_csv_exports e JOIN p3d_assets a ON a.id=e.csv_asset_id');exports_by_path={norm(path):identity for identity,path in cursor.fetchall()}
            metrics=['pGH_proxy','pMW_proxy','xy_convex_hull_area','centroid_x','centroid_y','centroid_z','extent_x','extent_y','extent_z','pTLA','pPLA','pLAA','pCHA','pE','normal_tilt_mean_deg']
            measurements=[]
            for row in data['csv_exports']:
                for metric in metrics:
                    value=numeric(row['values'].get(metric))
                    measurements.append((exports_by_path[norm(row['csv'])],metric,value,'degree' if metric=='normal_tilt_mean_deg' else row['values']['coordinate_unit'],'UNAVAILABLE' if value is None else 'PLY_DERIVED_PROXY'))
            upsert(cursor,'p3d_measurements',['csv_export_id','metric_code','metric_value','unit','measurement_kind'],measurements)
            raw_by_key={row['observation_id']:row for row in data['raw_observations']}
            local_by_scene={row['capture_id']:row for row in data['local_links']['observations']}
            observation_rows=[]
            for row in data['strict_review']['records']:
                raw=raw_by_key[row['observation_id']];local=local_by_scene.get(row['scene_id'],{})
                observation_rows.append((row['observation_id'],sessions['ply:'+raw['source_sha256']],exports_by_path[norm(row['target_csv_path'])],raw['component_index'],row.get('scene_local_plant_id'),
                    None,local.get('physical_plant_id_candidate'),row['visual_review_status'],row['geometry_scope_verified'],row['rgb_target_identity_verified'],row['input_crop_complete_verified'],row['coordinate_units_verified'],row['target_definitions_verified'],row['point_and_numeric_provenance_verified'],False,row.get('review_notes'),js({'admission_failures':row['admission_failures'],'source_corrected_reference':raw['source_corrected_reference'],'excluded_raw_csv':row.get('excluded_raw_csv'),'physical_identity_evidence':local.get('physical_identity_evidence')})))
            upsert(cursor,'p3d_observations',['observation_key','ply_session_id','target_csv_export_id','component_index','scene_local_plant_id','physical_plant_id','physical_plant_id_candidate','visual_review_status','geometry_scope_verified','rgb_identity_verified','input_crop_complete_verified','coordinate_units_verified','target_definitions_verified','numeric_provenance_verified','averaged_across_plants','review_notes','evidence_json'],observation_rows,
                preserve=('physical_plant_id','geometry_scope_verified','rgb_identity_verified','input_crop_complete_verified','coordinate_units_verified','target_definitions_verified'))
            cursor.execute('SELECT observation_key,id FROM p3d_observations');observations=dict(cursor.fetchall())
            strict_by_target={norm(row['target_csv_path']):row for row in data['strict_review']['records']}
            linked=[]
            for row in data['local_links']['observations']:
                observation=strict_by_target[norm(row['target_csv_path'])]
                for view in row['rgb_crop_candidates']:
                    key=norm(view['rgb_crop'])
                    if key not in assets:
                        raise ValueError('Link refers to crop outside snapshot: '+view['rgb_crop'])
                    linked.append((observations[observation['observation_id']],images_by_asset[assets[key]],'LINKED_SCENE',js({'scene_local_plant_id':row['scene_local_plant_id'],'basis':row['scene_link_status'],'limit':row['scene_link_limit'],'mask_quality_status':view['mask_quality_status']})))
            upsert(cursor,'p3d_observation_images',['observation_id','image_id','link_status','link_evidence_json'],linked,preserve=('link_status',))
            rgb_by_code={row['capture_code']:row['key'] for row in data['sessions'] if row['kind']=='RGB'}
            raw_by_corrected=defaultdict(list)
            for row in data['raw_observations']:
                raw_by_corrected[norm(row['source_corrected_reference'])].append(row)
            candidate_rows={}
            for row in data['time_candidates']:
                if not row['ply_path'] or row['rgb_capture_id'] not in rgb_by_code:
                    continue
                status=row['match_status'];capture=row['rgb_capture_id']
                if capture in data['policy']['conflict_capture_ids']:
                    status='CONFLICT'
                elif capture in data['policy'].get('suspected_conflict_capture_ids',[]):
                    status='SUSPECTED_CONFLICT'
                for raw in raw_by_corrected[norm(row['ply_path'])]:
                    pair=(observations[raw['observation_id']],sessions[rgb_by_code[capture]])
                    candidate_rows[pair]=(*pair,float(row['delta_seconds']),status,js(row))
            upsert(cursor,'p3d_session_candidates',['observation_id','rgb_session_id','delta_seconds','match_status','evidence_json'],list(candidate_rows.values()))
            components=[('mysql-community','database','GPL',True,False,'OPEN_SOURCE','https://www.mysql.com/products/community/','Existing local MySQL Community Server 8.0.39'),
                ('pymysql','database connector','MIT',True,False,'OPEN_SOURCE','https://github.com/PyMySQL/PyMySQL/blob/main/LICENSE','Installed in project-local .deps'),
                ('dinov2','planned RGB feature encoder','Apache-2.0',True,True,'OPEN_SOURCE','https://github.com/facebookresearch/dinov2','Code and weights explicitly Apache-2.0; no training started'),
                ('xgboost','planned numeric regression baseline','Apache-2.0',True,False,'OPEN_SOURCE','https://github.com/dmlc/xgboost','No fine tuning/training started'),
                ('sam3.1','existing segmentation provenance','SAM License',False,False,'CUSTOM_LICENSE_NOT_MARKED_OSI','https://github.com/facebookresearch/sam3/blob/main/LICENSE','Source-available custom license; exact checkpoint license needs verification; not represented as Apache/MIT or fully OSI-open pipeline')]
            upsert(cursor,'p3d_components',['component_code','purpose','license_name','code_license_verified','weights_license_verified','strict_open_source_status','source_url','notes'],components)
            upsert(cursor,'p3d_import_runs',['snapshot_sha256','source_host','summary_json'],[(source_hash,'plant',js(data['summary']))])
            upsert(cursor,'p3d_processing_runs',['run_key','capture_set','run_status','total_images','processed_images','detected_instances','no_detection_images','error_count'],
                [(row['run_id'],row['capture_set'],row['status'],row['total_images'],row['done'],row['instances'],row['no_detection'],row['errors']) for row in data.get('processing_runs',[])])
            if has_legacy:
                cursor.execute('SELECT COUNT(*) FROM capture_groups');assert cursor.fetchone()[0]==legacy_before
            for table,expected in [('p3d_observations',len(data['strict_review']['records'])),('p3d_csv_exports',len(data['csv_exports']))]:
                cursor.execute('SELECT COUNT(*) FROM '+table);assert cursor.fetchone()[0]==expected
            cursor.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cursor.fetchone()[0]==0
            cursor.execute('SELECT COUNT(*) FROM p3d_observations WHERE averaged_across_plants=TRUE');assert cursor.fetchone()[0]==0
            counts={}
            for table in ('p3d_sessions','p3d_assets','p3d_images','p3d_segmentation_results','p3d_csv_exports','p3d_measurements','p3d_observations','p3d_observation_images','p3d_session_candidates','p3d_processing_runs','p3d_v_training_ready'):
                cursor.execute('SELECT COUNT(*) FROM '+table);counts[table]=cursor.fetchone()[0]
            connection.commit()
            actual_database=connection.db.decode() if isinstance(connection.db,bytes) else connection.db
            report={'database':actual_database,'namespace':'p3d_','snapshot_sha256':source_hash,'counts':counts,
                    'legacy_capture_count_unchanged':legacy_before,'snapshot_status':data['segmentation_status'],'tomato_queue':data['tomato_queue_status']}
            (BASE/'import_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(js({'committed':True,'counts':counts,'legacy_capture_count':legacy_before}))
    except Exception:
        connection.rollback();raise
    finally:
        connection.close()


if __name__=='__main__':
    main()
