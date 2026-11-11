"""Register user-confirmed single-pot image sets, including native CSV without a PLY.

Native traits and generated proxies remain distinct sources and label definitions.
"""
import csv,hashlib,json,math
from datetime import datetime
from pathlib import Path
import numpy as np
from database import BASE,connect

ROOT=BASE.parent;PIPELINE=ROOT.parent/'data_pipeline';MODEL=ROOT/'CLIP-DINOv2-Finetune'
NATIVE_TARGETS=['pGH','pTLA','pPLA','pLAA','pCHA','pE','pMW']
PROXY_TARGETS=['pGH_proxy','pMW_proxy']


def norm(path):return str(path).replace('/','\\').casefold()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def js(value):return json.dumps(value,ensure_ascii=False,default=str)
def dt(value):return datetime.strptime(value,'%Y-%m-%d_%H-%M-%S')


def numbers(values):
    numeric={}
    for name,value in values.items():
        try:
            number=float(value)
            if math.isfinite(number):numeric[name]=number
        except (ValueError,TypeError):pass
    return numeric


def read_source(path,kind):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        if kind=='VENDOR_NATIVE':
            values={r[0].strip():','.join(r[1:]).strip() for r in csv.reader(stream) if len(r)>=2}
        else:
            rows=list(csv.DictReader(stream));assert len(rows)==1
            values=rows[0]
    required=NATIVE_TARGETS if kind=='VENDOR_NATIVE' else PROXY_TARGETS
    numeric=numbers(values)
    return {'path':str(path),'kind':kind,'sha256':sha(path),'raw_values':values,'numeric_values':numeric,
            'required_targets':required,'has_required_numeric_targets':all(k in numeric for k in required),
            'coordinate_unit':values.get('coordinate_unit','VENDOR_UNIT_UNVERIFIED')}


def main():
    selection=json.loads((PIPELINE/'user_confirmed_legacy_singles.json').read_text(encoding='utf-8'))
    inventory=json.loads((PIPELINE/'legacy_manual_selection/legacy_csv_inventory.json').read_text(encoding='utf-8'))
    by_source={r['source_capture_id']:r for r in inventory['records']}
    old_manifest=json.loads((MODEL/'prepared_manifest.json').read_text(encoding='utf-8'))
    october=[r for r in old_manifest['rows'] if r['capture_id'].startswith('2026-10-')];assert len(october)==17
    specs=[]
    for code in selection['capture_ids']:
        target_code=selection['explicit_csv_time_candidates'].get(code,code)
        item=by_source[target_code]
        native=read_source(item['native_csvs'][0]['path'],'VENDOR_NATIVE') if item['native_csvs'] else None
        proxy=read_source(item['derived_corrected_csvs'][0]['path'],'PLY_CORRECTION_PROXY') if item['derived_corrected_csvs'] else None
        assert native or proxy,code
        notes=item.get('existing_review_notes','')
        blocked=item.get('existing_review_status')=='HOLD_CORRECTED_GEOMETRY'
        if proxy:
            proxy['trial_eligible']=proxy['has_required_numeric_targets'] and not blocked
            proxy['quality_status']='HOLD_EXISTING_GEOMETRY_ISSUE' if blocked else 'UNVERIFIED_COORDINATE_PROXY'
            proxy['quality_notes']=notes
        if native:
            native['trial_eligible']=native['has_required_numeric_targets']
            native['quality_status']='VENDOR_DEFINITION_AND_UNITS_UNVERIFIED'
            native['quality_notes']=notes
        specs.append({'capture_id':code,'csv_capture_id':target_code,'native':native,'proxy':proxy,
            'all_source_paths':item,'prior_review_notes':notes,'user_confirmation':'USER_LISTED_LEGACY_SINGLE_POT_ALL_FOUR_CAMERAS'})
    for row in october:
        proxy=read_source(row['target_csv_path'],'PLY_CORRECTION_PROXY')
        proxy.update(trial_eligible=True,quality_status='USER_SELECTED_EXPLORATORY_PROXY',quality_notes=row.get('target_review_notes'))
        specs.append({'capture_id':row['capture_id'],'csv_capture_id':row['capture_id'],'native':None,'proxy':proxy,
            'prior_review_notes':row.get('target_review_notes'),'user_confirmation':'USER_CONFIRMED_OCTOBER_SINGLE_POT',
            'all_source_paths':{'derived_corrected_csvs':[{'path':row['target_csv_path']}],'native_csvs':[]}})
    assert len(specs)==len({r['capture_id'] for r in specs})==36
    folder=BASE/'review-updates';folder.mkdir(exist_ok=True)
    connection=connect();output=[]
    try:
        with connection.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS p3d_user_samples (
                id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                sample_key VARCHAR(191) CHARACTER SET ascii NOT NULL UNIQUE,
                rgb_session_id BIGINT UNSIGNED NOT NULL UNIQUE,
                crop VARCHAR(24) NOT NULL,batch_code VARCHAR(64) NOT NULL,capture_code VARCHAR(32) CHARACTER SET ascii NOT NULL,
                capture_date DATE NOT NULL,csv_capture_code VARCHAR(32) CHARACTER SET ascii NOT NULL,
                csv_minus_rgb_seconds DOUBLE NOT NULL,
                confirmation_status VARCHAR(64) NOT NULL,primary_csv_asset_id BIGINT UNSIGNED NOT NULL,
                primary_kind VARCHAR(40) NOT NULL,trial_eligible BOOLEAN NOT NULL,
                native_trial_eligible BOOLEAN NOT NULL,proxy_trial_eligible BOOLEAN NOT NULL,
                target_sources_json JSON NOT NULL,evidence_json JSON NOT NULL,
                FOREIGN KEY(rgb_session_id) REFERENCES p3d_sessions(id),
                FOREIGN KEY(primary_csv_asset_id) REFERENCES p3d_assets(id)
            ) ENGINE=InnoDB''')
            cur.execute('''CREATE TABLE IF NOT EXISTS p3d_user_sample_images (
                sample_id BIGINT UNSIGNED NOT NULL,image_id BIGINT UNSIGNED NOT NULL UNIQUE,
                PRIMARY KEY(sample_id,image_id),FOREIGN KEY(sample_id) REFERENCES p3d_user_samples(id),
                FOREIGN KEY(image_id) REFERENCES p3d_images(id)
            ) ENGINE=InnoDB''')
            backup=folder/'before_user_confirmed_sample_registration.json'
            if not backup.exists():
                cur.execute('SELECT * FROM p3d_user_samples');prior=cur.fetchall()
                cur.execute('SELECT * FROM p3d_user_sample_images')
                backup.write_text(js({'samples':prior,'images':cur.fetchall()}),encoding='utf-8')
            for item in sorted(specs,key=lambda r:r['capture_id']):
                code=item['capture_id']
                cur.execute("SELECT s.id,s.source_host_id,b.batch_code FROM p3d_sessions s LEFT JOIN p3d_batches b ON b.id=s.batch_id WHERE s.session_kind='RGB' AND s.capture_code=%s",(code,))
                session=cur.fetchone();assert session is not None,code
                rid,host,batch=session
                cur.execute("SELECT i.id,i.asset_id,a.file_path,i.camera_code,i.frame_index FROM p3d_images i JOIN p3d_assets a ON a.id=i.asset_id WHERE i.session_id=%s AND i.image_kind='RAW' ORDER BY i.camera_code,i.frame_index",(rid,))
                images=cur.fetchall();assert len(images)==240 and all(Path(i[2]).is_file() for i in images),code
                assert all(sum(i[3]==str(c) for i in images)==60 for c in range(1,5))
                sources={k:item[k] for k in ('native','proxy') if item[k]}
                for source in sources.values():
                    path=Path(source['path']);path_hash=hashlib.sha256(norm(path).encode()).hexdigest()
                    kind='CSV_VENDOR_NATIVE' if source['kind']=='VENDOR_NATIVE' else 'CSV_PLY_PROXY'
                    cur.execute('''INSERT INTO p3d_assets(host_id,path_sha256,file_path,asset_kind,content_sha256,file_size_bytes,exists_on_export)
                        VALUES(%s,%s,%s,%s,%s,%s,TRUE) ON DUPLICATE KEY UPDATE content_sha256=VALUES(content_sha256),file_size_bytes=VALUES(file_size_bytes),exists_on_export=TRUE''',
                        (host,path_hash,str(path),kind,source['sha256'],path.stat().st_size))
                    cur.execute('SELECT id FROM p3d_assets WHERE host_id=%s AND path_sha256=%s',(host,path_hash))
                    source['asset_id']=cur.fetchone()[0]
                primary=sources.get('native',sources.get('proxy'))
                native_ok=bool(sources.get('native',{}).get('trial_eligible'))
                proxy_ok=bool(sources.get('proxy',{}).get('trial_eligible'))
                delta=(dt(item['csv_capture_id'])-dt(code)).total_seconds()
                evidence={'user_confirmation':item['user_confirmation'],'all_cameras_same_plant':True,'sam_required':False,
                    'sample_counting_unit':['crop','batch','light_condition','plant','date'],
                    'light_condition':None,'physical_plant_id':None,'physical_plant_day_dedup_status':'POT_NUMBER_NOT_PROVIDED',
                    'identity_confirmation_scope':'User confirms a single plant across all cameras, not calibration of numeric labels.',
                    'csv_time_status':'EXACT' if delta==0 else 'ONE_SECOND' if abs(delta)==1 else 'APPROXIMATE_TIME_CANDIDATE',
                    'previous_review_notes':item['prior_review_notes'],'source_choices':item['all_source_paths'],
                    'formal_calibrated_training_approved':False}
                key='user-single:'+code
                cur.execute('''INSERT INTO p3d_user_samples(sample_key,rgb_session_id,crop,batch_code,capture_code,capture_date,csv_capture_code,
                    csv_minus_rgb_seconds,confirmation_status,primary_csv_asset_id,primary_kind,trial_eligible,native_trial_eligible,
                    proxy_trial_eligible,target_sources_json,evidence_json) VALUES(%s,%s,'lettuce',%s,%s,%s,%s,%s,'USER_CONFIRMED_SINGLE_POT',%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE primary_csv_asset_id=VALUES(primary_csv_asset_id),primary_kind=VALUES(primary_kind),
                    trial_eligible=VALUES(trial_eligible),native_trial_eligible=VALUES(native_trial_eligible),proxy_trial_eligible=VALUES(proxy_trial_eligible),
                    target_sources_json=VALUES(target_sources_json),evidence_json=VALUES(evidence_json),csv_capture_code=VALUES(csv_capture_code),csv_minus_rgb_seconds=VALUES(csv_minus_rgb_seconds)''',
                    (key,rid,batch,code,code[:10],item['csv_capture_id'],delta,primary['asset_id'],primary['kind'],native_ok or proxy_ok,native_ok,proxy_ok,js(sources),js(evidence)))
                cur.execute('SELECT id FROM p3d_user_samples WHERE sample_key=%s',(key,));sample_id=cur.fetchone()[0]
                cur.executemany('INSERT IGNORE INTO p3d_user_sample_images(sample_id,image_id) VALUES(%s,%s)',[(sample_id,i[0]) for i in images])
                views=[]
                for camera in ('1','2','3','4'):
                    selected=[i for i in images if i[3]==camera]
                    for j in np.linspace(0,59,6,dtype=int):
                        image=selected[int(j)]
                        views.append({'camera':camera,'frame_index':image[4],'image_path':image[2],
                                      'asset_id':image[1],'sha256':sha(image[2]),'image_kind':'RAW'})
                output.append({'sample_id':sample_id,'sample_key':key,'capture_id':code,'crop':'lettuce','batch':batch,
                    'csv_capture_id':item['csv_capture_id'],'csv_minus_rgb_seconds':delta,
                    'trial_eligible':native_ok or proxy_ok,'native_trial_eligible':native_ok,'proxy_trial_eligible':proxy_ok,
                    'sources':sources,'views':views,'original_image_count':len(images),'evidence':evidence,
                    'split_group':batch+'_all_user_confirmed_scenes'})
            cur.execute('SELECT COUNT(*),SUM(trial_eligible),SUM(native_trial_eligible),SUM(proxy_trial_eligible) FROM p3d_user_samples')
            total,trial,native_count,proxy_count=map(int,cur.fetchone());assert total==36
            cur.execute('SELECT COUNT(*) FROM p3d_user_sample_images');image_count=cur.fetchone()[0];assert image_count==8640
            cur.execute('SELECT COUNT(*) FROM p3d_v_training_ready');assert cur.fetchone()[0]==0
            connection.commit()
        report={'user_selected_legacy_scenes':19,'october_scenes':17,'linked_single_pot_samples':total,
                'original_images':image_count,'samples_with_trial_label_source':trial,
                'native_seven_trait_samples':native_count,'proxy_two_trait_samples':proxy_count,
                'target_quality_hold_samples':total-trial,
                'exact_time_samples':sum(r['csv_minus_rgb_seconds']==0 for r in output),
                'one_second_samples':sum(abs(r['csv_minus_rgb_seconds'])==1 for r in output),
                'approximate_time_samples':sum(abs(r['csv_minus_rgb_seconds'])>1 for r in output),
                'formal_calibrated_training_samples':0,
                'note':'Native trait and proxy label sets overlap; do not add their sample counts. Near-time CSV associations and old numeric-quality notes remain explicit.'}
        artifact={'summary':report,'target_definitions':{'native':NATIVE_TARGETS,'proxy':PROXY_TARGETS},'samples':output}
        (MODEL/'user_confirmed_samples_manifest.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'user_confirmed_samples_report.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
        with (folder/'user_confirmed_samples.csv').open('w',encoding='utf-8-sig',newline='') as f:
            fields=['capture_id','csv_capture_id','csv_minus_rgb_seconds','native_csv','proxy_csv','trial_eligible','native_trial_eligible','proxy_trial_eligible','original_image_count']
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            for r in output:
                writer.writerow({**{k:r[k] for k in fields if k not in ('native_csv','proxy_csv')},
                    'native_csv':r['sources'].get('native',{}).get('path',''),'proxy_csv':r['sources'].get('proxy',{}).get('path','')})
        print(json.dumps(report,ensure_ascii=False),flush=True)
    except Exception:
        connection.rollback();raise
    finally:connection.close()


if __name__=='__main__':main()
