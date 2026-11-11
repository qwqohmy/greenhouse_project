"""Record user's scene-time linkage request without asserting individual-pot identity."""
import json
from pathlib import Path
from datetime import datetime
from database import connect,BASE


def main():
    folder=BASE/'review-updates';folder.mkdir(exist_ok=True)
    connection=connect()
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT observation_id,rgb_session_id,delta_seconds,match_status,evidence_json FROM p3d_session_candidates')
            before=cur.fetchall()
            backup=folder/'before_time_scene_link.json'
            if not backup.exists():
                backup.write_text(json.dumps(before,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
            cur.execute("""UPDATE p3d_session_candidates SET evidence_json=JSON_SET(COALESCE(evidence_json,JSON_OBJECT()),
                '$.user_requested_time_scene_link',TRUE,'$.link_scope','SCENE_TIME_ONLY_POT_UNCONFIRMED',
                '$.training_approval_from_time',FALSE)""")
            cur.execute('SELECT COUNT(DISTINCT o.ply_session_id),COUNT(*) FROM p3d_session_candidates c JOIN p3d_observations o ON o.id=c.observation_id')
            scenes,edges=cur.fetchone();assert scenes==69
            cur.execute("""SELECT s.crop,b.batch_code,COUNT(DISTINCT s.id) AS ply_scenes,
                COUNT(o.id) AS geometric_component_candidates,
                COUNT(DISTINCT CASE WHEN EXISTS(SELECT 1 FROM p3d_session_candidates c WHERE c.observation_id=o.id) THEN s.id END) AS time_linked_ply_scenes,
                SUM(EXISTS(SELECT 1 FROM p3d_session_candidates c WHERE c.observation_id=o.id)) AS components_with_time_candidate
                FROM p3d_observations o JOIN p3d_sessions s ON s.id=o.ply_session_id
                LEFT JOIN p3d_batches b ON b.id=s.batch_id GROUP BY s.crop,b.batch_code ORDER BY b.batch_code""")
            names=[c[0] for c in cur.description];coverage=[dict(zip(names,r)) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(DISTINCT observation_id),COUNT(*) FROM p3d_observation_images WHERE link_status IN ('LINKED_SCENE','VERIFIED')")
            single_scenes,single_views=cur.fetchone();assert(single_scenes,single_views)==(12,771)
            cur.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cur.fetchone()[0]==0
            connection.commit()
        unit={'sample_unit':['crop','batch','light_condition','plant_id','capture_date'],
              'multiple_angles_are_one_sample':True,'multiple_csv_versions_are_one_sample':True,
              'same_plant_same_day_repeat_scenes_are_one_sample':True,
              'multiple_plants_in_one_scene_require_individual_csv_and_image_mapping':True,
              'time_candidate_is_not_automatically_a_training_sample':True,
              'multispectral_plant_days_are_not_automatically_3d_labeled_samples':True}
        report={'updated_at':datetime.now().isoformat(),'time_linked_scenes':scenes,'candidate_edges':edges,
                'single_scene_links':single_scenes,'single_scene_views':single_views,
                'sample_definition':unit,'coverage_by_batch':coverage,
                'note':'Counts are acquisition scenes and unverified geometric components, not confirmed individual plant-day training samples.'}
        (folder/'time_scene_link_report.json').write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
        (folder/'training_sample_definition.json').write_text(json.dumps(unit,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,default=str),flush=True)
    except Exception:
        connection.rollback();raise
    finally:
        connection.close()


if __name__=='__main__':
    main()
