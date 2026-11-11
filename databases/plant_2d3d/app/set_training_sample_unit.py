"""Use crop/batch/light/plant/date candidate keys; preserve identity uncertainty."""
import hashlib
import json
from pathlib import Path
from database import BASE,connect

ROOT=BASE.parent
MODEL=ROOT/'CLIP-DINOv2-Finetune'
PIPELINE=ROOT.parent/'data_pipeline'


def main():
    path=MODEL/'prepared_manifest.json';raw=path.read_bytes();data=json.loads(raw)
    catalog=json.loads((PIPELINE/'capture_catalog.json').read_text(encoding='utf-8'))
    by_day={}
    for row in catalog:
        if row['dataset_id']=='lettuce_new_202609':
            by_day.setdefault(row['capture_id'][:10],[]).append(row['capture_id'])
    for values in by_day.values():
        values.sort()
    backup=BASE/'review-updates/prepared_manifest_before_sample_unit.json'
    if not backup.exists():
        backup.write_bytes(raw)
    updates=[]
    for row in data['rows']:
        code=row['capture_id'];date=code[:10]
        if code<'2026-07-01':
            batch,light,plant='lettuce_run1','A-1','P11'
            evidence='Late first-run PPT single-pot A1-11 candidate; physical continuity remains unconfirmed.'
        else:
            captures=by_day[date]
            assert len(captures)==4
            batch,light,plant='lettuce_run3','single_light',f'P{captures.index(code)+1:02d}'
            evidence='User stated single-light four-pot chronological sequence; physical numbers not independently verified.'
        key='|'.join(('lettuce',batch,light,plant,date))
        row.update(crop='lettuce',batch=batch,capture_date=date,light_condition_candidate=light,
                   plant_number_candidate=plant,sample_key_candidate=key,sample_key_confirmed=None,
                   sample_identity_evidence=evidence)
        updates.append((key,evidence,row['db_observation_id']))
    main_rows=[r for r in data['rows'] if r['proxy_training_candidate']]
    assert len({r['sample_key_candidate'] for r in main_rows})==len(main_rows)==11
    data['sample_counting_unit']=['crop','batch','light_condition','plant_id','capture_date']
    data['sample_identity_status']='LAYOUT_SEQUENCE_CANDIDATES_NOT_INDEPENDENTLY_VERIFIED_POT_NUMBERS'
    connection=connect()
    try:
        with connection.cursor() as cur:
            cur.executemany("UPDATE p3d_observations SET evidence_json=JSON_SET(evidence_json,'$.round3.sample_key_candidate',%s,'$.round3.sample_identity_evidence',%s,'$.round3.sample_identity_confirmed',FALSE) WHERE id=%s",updates)
            cur.execute("SELECT COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(evidence_json,'$.round3.sample_key_candidate'))) FROM p3d_observations WHERE JSON_UNQUOTE(JSON_EXTRACT(evidence_json,'$.round3.proxy_preparation_candidate'))='true'")
            assert cur.fetchone()[0]==11
            connection.commit()
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        result={'unit':data['sample_counting_unit'],'prepared_unique_candidate_plant_days':11,
                'confirmed_physical_ids':0,'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'note':'Candidate identity keys prevent duplicate counting; this metadata does not independently confirm pot numbers.'}
        (BASE/'review-updates/sample_unit_update.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    except Exception:
        connection.rollback();raise
    finally:
        connection.close()


if __name__=='__main__':
    main()
