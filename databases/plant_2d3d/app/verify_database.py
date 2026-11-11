"""Integration checks against real imported MySQL data; temporary edits roll back."""
import json
import argparse
from database import BASE,connect


def main(standalone=False):
    connection=connect();checks={}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM p3d_observations');checks['observation_count']=cursor.fetchone()[0]
            assert checks['observation_count']==176
            cursor.execute('SELECT COUNT(*) FROM p3d_csv_exports');assert cursor.fetchone()[0]==264
            cursor.execute("SELECT COUNT(*),COUNT(DISTINCT content_sha256) FROM p3d_assets WHERE asset_kind IN ('PLY_RAW','PLY_CORRECTED')")
            assert cursor.fetchone()==(244,176);checks['all_244_ply_paths_and_176_unique_contents']=True
            cursor.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cursor.fetchone()[0]==0
            cursor.execute("SELECT COUNT(*) FROM p3d_measurements WHERE metric_code='pTLA' AND metric_value IS NULL")
            assert cursor.fetchone()[0]==264;checks['unavailable_traits_preserved_as_null']=True
            if not standalone:
                cursor.execute('SELECT COUNT(*) FROM capture_groups');assert cursor.fetchone()[0]==1159;checks['legacy_data_unchanged']=True
            else:
                checks['standalone_remote_database']=True
            cursor.execute("SELECT COUNT(*) FROM p3d_sessions WHERE review_status='HOLD' AND crop='unknown' AND batch_id IS NULL")
            assert cursor.fetchone()[0]==5;checks['five_unknown_oct10_scenes_held']=True
            cursor.execute('SELECT l.observation_id,l.image_id,o.target_csv_export_id FROM p3d_observation_images l JOIN p3d_observations o ON o.id=l.observation_id LIMIT 1')
            observation,image,target=cursor.fetchone()
            try:
                cursor.execute('UPDATE p3d_observations SET averaged_across_plants=TRUE WHERE id=%s',(observation,))
            except Exception as error:
                assert error.args[0]==3819
                checks['cross_plant_average_rejected']=True
            else:
                raise AssertionError('Database accepted cross-plant average')
            finally:
                connection.rollback()
            try:
                cursor.execute("INSERT INTO p3d_observations (observation_key,ply_session_id,target_csv_export_id,component_index,visual_review_status,evidence_json) SELECT 'verification_only_do_not_persist',ply_session_id,target_csv_export_id,component_index,'TEST',JSON_OBJECT() FROM p3d_observations WHERE id=%s",(observation,))
            except Exception as error:
                assert error.args[0]==1062
                checks['same_csv_cannot_label_two_observations']=True
            else:
                raise AssertionError('Database accepted one target for two observations')
            finally:
                connection.rollback()
            try:
                cursor.execute('UPDATE p3d_observations SET geometry_scope_verified=TRUE,rgb_identity_verified=TRUE,input_crop_complete_verified=TRUE,coordinate_units_verified=TRUE,target_definitions_verified=TRUE,numeric_provenance_verified=TRUE WHERE id=%s',(observation,))
                cursor.execute("UPDATE p3d_observation_images SET link_status='VERIFIED' WHERE observation_id=%s AND image_id=%s",(observation,image))
                cursor.execute("UPDATE p3d_images SET quality_status='VERIFIED' WHERE id=%s",(image,))
                cursor.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cursor.fetchone()[0]==0
                checks['unknown_units_still_block_training']=True
                cursor.execute("UPDATE p3d_csv_exports SET coordinate_unit='TEMPORARY_TEST_UNIT' WHERE id=%s",(target,))
                cursor.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cursor.fetchone()[0]==1
                checks['training_view_opens_only_when_all_requirements_met']=True
            finally:
                connection.rollback()
            cursor.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cursor.fetchone()[0]==0
            checks['all_test_changes_rolled_back']=True
            cursor.execute('SELECT observation_key,captured_at,crop,physical_plant_id_candidate,linked_image_count,pGH_proxy,pMW_proxy,coordinate_unit,csv_path,visual_review_status FROM p3d_v_observations WHERE linked_image_count>0 ORDER BY captured_at LIMIT 5')
            columns=[description[0] for description in cursor.description]
            examples=[dict(zip(columns,row)) for row in cursor.fetchall()]
            report={'passed':True,'checks':checks,'sample_observations':examples}
            (BASE/'verification_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False))
    finally:
        connection.rollback();connection.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--standalone',action='store_true');args=parser.parse_args()
    main(args.standalone)
