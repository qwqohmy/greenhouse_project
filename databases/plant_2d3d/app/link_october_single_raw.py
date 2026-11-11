"""User-confirmed October lettuce single-pot scenes: original RGB -> unique scene CSV."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from database import BASE,connect

ROOT=BASE.parent;PIPELINE=ROOT.parent/'data_pipeline';MODEL=ROOT/'CLIP-DINOv2-Finetune'
BAD_TARGETS={'2026-10-17_17-00-19':'CORRECTION_NEAR_PLANAR_GEOMETRY',
             '2026-10-15_11-16-42':'CORRECTION_UP_AXIS_MISMATCH_REQUIRES_REVIEW'}


def norm(path):return str(path).replace('/','\\').casefold()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--include-noted-targets',action='store_true',help='User-selected exploratory inclusion; keep unresolved target quality notes.')
    args=parser.parse_args()
    folder=BASE/'review-updates';folder.mkdir(exist_ok=True)
    catalog=json.loads((PIPELINE/'capture_catalog.json').read_text(encoding='utf-8'))
    clean=json.loads((PIPELINE/'ply_singleplant_candidates/observations.json').read_text(encoding='utf-8'))
    scenes=json.loads((PIPELINE/'single_pot_audit/scenes.json').read_text(encoding='utf-8'))
    raw=json.loads((PIPELINE/'ply_from_raw_candidates/observations.json').read_text(encoding='utf-8'))
    selected=[s for s in scenes if s['scene_id'].startswith('2026-10-')]
    assert len(selected)==17
    by_day={}
    for r in catalog:
        if r['dataset_id']=='lettuce_new_202609':by_day.setdefault(r['capture_id'][:10],[]).append(r['capture_id'])
    for values in by_day.values():values.sort()
    path=MODEL/'prepared_manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'))
    backup=folder/'prepared_manifest_before_october_raw.json'
    if not backup.exists():backup.write_bytes(path.read_bytes())
    kept=[r for r in manifest['rows'] if not r['capture_id'].startswith('2026-10-')]
    connection=connect();report_rows=[]
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT o.id,o.observation_key,s.capture_code,o.target_csv_export_id,o.evidence_json,o.visual_review_status,o.review_notes FROM p3d_observations o JOIN p3d_sessions s ON s.id=o.ply_session_id WHERE s.capture_code LIKE '2026-10-%'")
            records={r[2]:r for r in cur.fetchall()};assert len(records)==17
            before=folder/'before_october_raw_links.json'
            if not before.exists():
                cur.execute("SELECT l.observation_id,l.image_id,l.link_status,l.link_evidence_json FROM p3d_observation_images l JOIN p3d_observations o ON o.id=l.observation_id JOIN p3d_sessions s ON s.id=o.ply_session_id WHERE s.capture_code LIKE '2026-10-%'")
                before.write_text(json.dumps({'observations':list(records.values()),'links':cur.fetchall()},ensure_ascii=False,default=str),encoding='utf-8')
            cur.execute('SELECT e.id,a.file_path FROM p3d_csv_exports e JOIN p3d_assets a ON a.id=e.csv_asset_id');exports={norm(p):i for i,p in cur.fetchall()}
            for scene in selected:
                code=scene['scene_id'];oid,key,_,_,evidence,previous_status,previous_notes=records[code]
                original=[r for r in raw if r['source_raw']==scene['source_raw']];assert len(original)==1
                target=[r for r in clean if r['source_ply']==original[0]['source_corrected_reference']];assert len(target)==1
                target_path=target[0]['csv_path']
                with Path(target_path).open(encoding='utf-8-sig',newline='') as f:values=list(csv.DictReader(f))
                assert len(values)==1
                cur.execute("SELECT i.id,i.asset_id,a.file_path,i.camera_code,i.frame_index,i.session_id FROM p3d_images i JOIN p3d_assets a ON a.id=i.asset_id JOIN p3d_sessions s ON s.id=i.session_id WHERE i.image_kind='RAW' AND s.capture_code=%s ORDER BY i.camera_code,i.frame_index",(code,))
                images=cur.fetchall();assert len(images)==240 and len({r[5] for r in images})==1
                assert all(Path(r[2]).is_file() for r in images)
                data=json.loads(evidence) if isinstance(evidence,str) else evidence
                seq=by_day[code[:10]].index(code)+1;assert len(by_day[code[:10]])==4
                sample_key='|'.join(['lettuce','lettuce_run3','single_light',f'P{seq:02d}',code[:10]])
                usable=code not in BAD_TARGETS or args.include_noted_targets
                data['october_direct']={'link_method':'USER_CONFIRMED_SINGLE_POT_DIRECT','sam_required':False,
                    'identity_basis':'User confirms October lettuce scenes are single pot; exact RGB/PLY timestamp',
                    'original_views':240,'target_hold':None if usable else BAD_TARGETS.get(code),
                    'target_review_notes':BAD_TARGETS.get(code),
                    'user_requested_all_october_for_proxy_trial':args.include_noted_targets,
                    'prior_review_status':previous_status,'prior_review_notes':previous_notes}
                data.setdefault('round3',{}).update(sample_key_candidate=sample_key,proxy_preparation_candidate=usable,
                    sample_identity_confirmed=False,disposition='USER_SINGLE_POT_DIRECT',rgb_capture_id=code,delta_seconds=0)
                notes='使用者確認10月份萵苣各場為單盆；同時刻原始多角度RGB直接連唯一Correction CSV，不依賴SAM。'
                if code in BAD_TARGETS:
                    notes+=(' CSV方向疑點保留備註，依使用者要求納入代理值試訓：' if usable else ' CSV幾何疑點另行擱置：')+BAD_TARGETS[code]
                cur.execute("UPDATE p3d_observations SET target_csv_export_id=%s,scene_local_plant_id=%s,physical_plant_id_candidate=%s,visual_review_status='USER_SINGLE_POT_DIRECT',rgb_identity_verified=TRUE,review_notes=%s,evidence_json=%s WHERE id=%s",(exports[norm(target_path)],code+'__single_01',f'lettuce_run3_single_light_P{seq:02d}',notes,json.dumps(data,ensure_ascii=False),oid))
                cur.execute("UPDATE p3d_observation_images SET link_status='REJECTED' WHERE observation_id=%s",(oid,))
                link_evidence=json.dumps({'link_method':'USER_CONFIRMED_SINGLE_POT_DIRECT','sam_required':False,'rgb_capture_id':code,'sample_key_candidate':sample_key})
                cur.executemany("INSERT INTO p3d_observation_images(observation_id,image_id,link_status,link_evidence_json) VALUES(%s,%s,'LINKED_SCENE',%s) ON DUPLICATE KEY UPDATE link_status=VALUES(link_status),link_evidence_json=VALUES(link_evidence_json)",[(oid,r[0],link_evidence) for r in images])
                selected_views=[]
                for cam in ('2','4'):
                    camera_images=[r for r in images if r[3]==cam];assert len(camera_images)==60
                    for j in np.linspace(0,59,6,dtype=int):
                        r=camera_images[int(j)]
                        selected_views.append({'camera':cam,'frame_index':r[4],'rgb_crop':r[2],
                            'image_path':r[2],'image_kind':'RAW','mask':None,'metadata':None,'sha256':sha(r[2])})
                kept.append({'capture_id':code,'rgb_capture_id':code,'proxy_training_candidate':usable,
                    'physical_plant_id':None,'split_group':'lettuce_run3_conservative_all_plants',
                    'split_group_reason':'Entire batch held together because cross-date physical identities remain sequence candidates.',
                    'target_csv_path':target_path,'target_csv_sha256':sha(target_path),
                    'values':{n:float(values[0][n]) for n in ('pGH_proxy','pMW_proxy')},
                    'coordinate_unit':values[0]['coordinate_unit'],'vertical_axis':values[0]['vertical_axis'],
                    'delta_seconds':0.,'views':selected_views,'formal_train_eligible':False,
                    'db_observation_id':oid,'db_observation_key':key,'crop':'lettuce','batch':'lettuce_run3',
                    'capture_date':code[:10],'light_condition_candidate':'single_light','plant_number_candidate':f'P{seq:02d}',
                    'sample_key_candidate':sample_key,'sample_key_confirmed':None,'target_hold':None if usable else BAD_TARGETS.get(code),
                    'target_review_notes':BAD_TARGETS.get(code),
                    'input_policy':'Original single-pot RGB, no SAM crop required.'})
                report_rows.append({'capture_id':code,'original_images':240,'csv_path':target_path,'proxy_trial_candidate':usable,'target_hold':None if usable else BAD_TARGETS.get(code),'target_review_notes':BAD_TARGETS.get(code)})
            cur.execute("SELECT COUNT(DISTINCT observation_id),COUNT(*) FROM p3d_observation_images WHERE link_status IN ('LINKED_SCENE','VERIFIED')")
            count,views=cur.fetchone();assert(count,views)==(23,4549)
            cur.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cur.fetchone()[0]==0
            connection.commit()
        kept.sort(key=lambda r:r['capture_id']);manifest['rows']=kept
        manifest['input']='Per scene: six CAM2 and six CAM4. October uses original single-pot RGB directly, no SAM required; legacy scenes retain existing crops.'
        expected_trials=22 if args.include_noted_targets else 20
        assert sum(r['proxy_training_candidate'] for r in kept)==expected_trials
        path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        report={'user_confirmed_october_single_scenes':17,'october_original_images':4080,
                'direct_scene_links_total':count,'linked_views_total':views,
                'proxy_trial_samples':expected_trials,'approximate_time_held':1,
                'october_csv_geometry_held':0 if args.include_noted_targets else 2,
                'october_target_quality_notes_retained':2,
                'manifest_sha256':sha(path),'rows':report_rows,'formal_calibrated_training_ready':0}
        (folder/'october_direct_raw_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
    except Exception:
        connection.rollback();raise
    finally:connection.close()


if __name__=='__main__':main()
