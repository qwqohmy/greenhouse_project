"""Create/import the independent SAM multispectral DB; leave legacy apps alone."""
import hashlib
import json
from pathlib import Path
import time
from database import BASE, DB_NAME, connect
from prepare_dataset import BANDS, VERSION, write


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def encode(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def existing_2d3d_snapshot(cur):
    tables=['p3d_observations','p3d_user_samples','p3d_user_sample_images']
    result={}
    for table in tables:
        cur.execute('SELECT COUNT(*) FROM plant_2d3d.'+table);result[table]=cur.fetchone()[0]
    return result


def provision():
    conn=connect(admin=True,database=None)
    try:
        with conn.cursor() as cur:
            before=existing_2d3d_snapshot(cur)
            cur.execute('SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s',(DB_NAME,))
            exists=cur.fetchone()[0]>0
            if exists and not (BASE/'deployment.json').is_file():
                cur.execute('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s',(DB_NAME,))
                if cur.fetchone()[0]>0:raise RuntimeError('Existing nonempty database without this deployment marker; refusing to overwrite.')
            cur.execute('CREATE DATABASE IF NOT EXISTS plant_multispectral CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
            cur.execute("SELECT Host FROM mysql.user WHERE User='greenhouse'")
            hosts=[row[0] for row in cur.fetchall() if row[0] in ('localhost','127.0.0.1')]
            assert hosts
            for host in hosts:
                cur.execute("GRANT ALL PRIVILEGES ON plant_multispectral.* TO 'greenhouse'@'"+host+"'")
        conn.commit()
    finally:conn.close()
    write(BASE/'deployment.json',{'database':DB_NAME,'host':'127.0.0.1','port':3306,
        'settings_source':'environment variables',
        'sam_source_root':str(__import__('prepare_dataset').SAM),'algorithm_version':VERSION,
        'public_web_enabled':False,'public_web_requested_later':True})
    return before


def upsert(cur,table,values,update=None):
    columns=list(values)
    updates=update if update is not None else columns
    sql='INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join(['%s']*len(columns))+') ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)'
    if updates:sql+=','+','.join(f'{c}=VALUES({c})' for c in updates)
    cur.execute(sql,tuple(values[c] for c in columns))
    return cur.lastrowid


def main():
    stage=BASE/'staging'/'captures.jsonl'
    prep=json.loads((BASE/'reports'/'preparation_report.json').read_text(encoding='utf-8'))
    assert prep['status']=='prepared' and prep['snapshot_sha256']==sha(stage)
    assert prep['observations']>0 and prep['band_images']==prep['observations']*16
    before=provision();started=time.time();conn=connect()
    try:
        with conn.cursor() as cur:
            schema=(BASE/'schema.sql').read_text(encoding='utf-8')
            for statement in schema.split(';'):
                if statement.strip():cur.execute(statement)
            conn.commit()
            run_id=upsert(cur,'import_runs',{'snapshot_sha256':prep['snapshot_sha256'],'algorithm_version':VERSION,'summary_json':encode(prep)})
            batches={}
            for key,b in prep['by_batch'].items():
                number=int(key)
                batches[number]=upsert(cur,'crop_batches',{'crop_code':'lettuce','batch_no':number,
                    'batch_code':f'lettuce-run{number}','display_name':f'萵苣第{number}批',
                    'first_captured_on':b['first_captured_on'],'last_captured_on':b['last_captured_on'],
                    'plants_per_light':12 if number==1 else 21,'source_basis':'SAM _SUCCESS.json batch field + user plant counts'})
            lights={};bands={}
            for order,code in enumerate([f'{r}-{l}' for r in 'ABCD' for l in (1,2,3)],1):
                lights[code]=upsert(cur,'light_conditions',{'code':code,'rack_code':code[0],'level_no':int(code[2]),'display_order':order})
            for order,nm in enumerate(BANDS,1):
                bands[nm]=upsert(cur,'spectral_bands',{'code':f'L{nm}','wavelength_nm':nm,'display_order':order})
            definition=upsert(cur,'index_definitions',{'code':'NDVI','algorithm_version':VERSION,
                'formula_text':'(R800-R680)/(R800+R680)',
                'pixel_aggregation':'Masked per-pixel ratio, then mean/median/std/quantiles; no ratio of band averages.',
                'value_basis':'RAW_DN_UNCALIBRATED','calibration_status':'NOT_VERIFIED',
                'alignment_status':'SHARED_SAM_CROP_REGISTRATION_NOT_VERIFIED',
                'reference_url':'https://science.data.nasa.gov/disasters/data-gallery/landsat-ndvi'})
            conn.commit()
            source_cache={};plant_cache={};captures=observations=images=0
            with stage.open(encoding='utf-8') as stream:
                for line in stream:
                    record=json.loads(line);batch_id=batches[record['batch_no']];light_id=lights[record['light_code']]
                    if record['source_path_hash'] not in source_cache:
                        source_cache[record['source_path_hash']]=upsert(cur,'source_folders',{
                            'batch_id':batch_id,'folder_name':record['source_folder'],'folder_path':record['source_path'],
                            'source_path_hash':record['source_path_hash'],'original_source_exists':record['source_exists']})
                    meta=record['metadata'];overview=Path(record['metadata_path']).parent/'overview_overlay.jpg'
                    capture_id=upsert(cur,'capture_groups',{'source_folder_id':source_cache[record['source_path_hash']],
                        'light_condition_id':light_id,'captured_at':record['captured_at'],'capture_code':record['capture_code'],
                        'shoot_no':meta.get('shoot'),'photo_no':meta.get('photo_no'),'layout_code':meta.get('layout_code'),
                        'segmentation_channel':meta.get('source_channel_for_segmentation'),
                        'sam_metadata_path':record['metadata_path'],'overview_image_path':str(overview) if overview.is_file() else None,
                        'sam_metadata_sha256':record['metadata_sha256'],'metadata_json':encode(meta),'import_run_id':run_id})
                    for o in record['observations']:
                        key=(batch_id,light_id,o['plant_number'])
                        if key not in plant_cache:
                            plant_cache[key]=upsert(cur,'plants',{'batch_id':batch_id,'light_condition_id':light_id,
                                'position_no':o['plant_number'],'identity_status':'SAM_LAYOUT_NUMBER'})
                        oid=upsert(cur,'plant_observations',{'capture_group_id':capture_id,'plant_id':plant_cache[key],
                            'output_directory':o['directory'],'directory_hash':o['directory_hash'],'quality_status':o['quality'],
                            'mask_source':o['mask_source'],'mask_area_pixels':o['mask_area'],'crop_box_json':encode(o['crop_box']),
                            'band_count':o['band_count'],'import_run_id':run_id})
                        assets=[]
                        for a in o['images']:
                            assets.append((oid,bands.get(a['wavelength_nm']),a['channel'],a['kind'],a['path'],a['path_hash'],a['size_bytes'],
                                a['mtime_ns'],a['sha256'],a['original_path'],a['width'],a['height'],a['mode']))
                        cur.executemany('''INSERT INTO singleplant_images
                          (observation_id,band_id,channel_code,image_kind,file_path,file_path_hash,file_size_bytes,file_modified_ns,
                           content_sha256,original_file_path,width_px,height_px,pixel_mode)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                          ON DUPLICATE KEY UPDATE file_size_bytes=VALUES(file_size_bytes),file_modified_ns=VALUES(file_modified_ns),
                          content_sha256=VALUES(content_sha256),original_file_path=VALUES(original_file_path),
                          width_px=VALUES(width_px),height_px=VALUES(height_px),pixel_mode=VALUES(pixel_mode)''',assets)
                        m=o['ndvi']
                        upsert(cur,'index_measurements',{'observation_id':oid,'definition_id':definition,'calculation_status':m['status'],
                            'index_mean':m['mean'],'index_median':m['median'],'index_std':m['std'],'index_min':m['min'],'index_max':m['max'],
                            'index_p10':m['p10'],'index_p90':m['p90'],'red_mean_dn':m['red_mean_dn'],'nir_mean_dn':m['nir_mean_dn'],
                            'valid_pixel_count':m['valid_pixel_count'],'mask_pixel_count':m['mask_pixel_count'],
                            'zero_denominator_count':m['zero_denominator_count'],'saturated_pixel_count':m['saturated_pixel_count'],
                            'input_sha256_json':encode(m['input_sha256']),'import_run_id':run_id})
                        observations+=1;images+=len(assets)
                    captures+=1
                    if captures%25==0:
                        conn.commit();write(BASE/'reports'/'import_status.json',{'status':'running','captures':captures,
                            'observations':observations,'images':images,'elapsed_seconds':time.time()-started})
            conn.commit()
            assert (captures,observations,images)==(prep['captures'],prep['observations'],prep['images'])
            current=existing_2d3d_snapshot(cur);assert current==before,'Existing 2D3D counts changed during import'
            cur.execute('SELECT COUNT(*) FROM plant_observations');assert cur.fetchone()[0]==prep['observations']
            cur.execute("SELECT COUNT(*) FROM singleplant_images WHERE image_kind='SPECTRAL'");assert cur.fetchone()[0]==prep['band_images']
            report={'status':'imported','database':DB_NAME,'import_run_id':run_id,'captures':captures,'observations':observations,
                'images':images,'band_images':prep['band_images'],'elapsed_seconds':time.time()-started,
                'snapshot_sha256':prep['snapshot_sha256'],'existing_2d3d_unchanged':before,
                'public_web_enabled':False,'website_modified':False,'ndvi_value_basis':'RAW_DN_UNCALIBRATED'}
            cur.execute('UPDATE import_runs SET summary_json=%s WHERE id=%s',(encode({**prep,'database_import':report}),run_id));conn.commit()
            write(BASE/'reports'/'import_report.json',report);write(BASE/'reports'/'import_status.json',report)
            print(encode(report),flush=True)
    except Exception:
        conn.rollback();raise
    finally:conn.close()


if __name__=='__main__':main()
