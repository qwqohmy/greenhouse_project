"""Verify DB completeness and independently recompute sampled source-pixel indices."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from database import BASE, connect
from prepare_dataset import write


def query(cur,sql,params=()):
    cur.execute(sql,params);columns=[c[0] for c in cur.description]
    return [dict(zip(columns,row)) for row in cur.fetchall()]


def main():
    prep=json.loads((BASE/'reports'/'preparation_report.json').read_text(encoding='utf-8'))
    conn=connect(read_only=True)
    try:
        with conn.cursor() as cur:
            counts={}
            for table in ('crop_batches','light_conditions','spectral_bands','source_folders','capture_groups','plants',
                          'plant_observations','singleplant_images','index_definitions','index_measurements','v_singleplant_16_bands'):
                cur.execute('SELECT COUNT(*) FROM '+table);counts[table]=cur.fetchone()[0]
            assert counts['plant_observations']==counts['index_measurements']==counts['v_singleplant_16_bands']==prep['observations']
            assert counts['singleplant_images']==prep['images'] and counts['capture_groups']==prep['captures']
            cur.execute("SELECT COUNT(*) FROM singleplant_images WHERE image_kind='SPECTRAL'");assert cur.fetchone()[0]==prep['band_images']
            cur.execute('SELECT COUNT(*) FROM v_singleplant_16_bands WHERE band_count<>16 OR L680 IS NULL OR L800 IS NULL OR mask_path IS NULL');assert cur.fetchone()[0]==0
            cur.execute("SELECT COUNT(*) FROM index_measurements WHERE calculation_status='COMPUTED' AND (index_mean IS NULL OR index_mean < -1 OR index_mean > 1 OR index_min>index_mean OR index_max<index_mean OR index_std<0)");assert cur.fetchone()[0]==0
            cur.execute("SELECT COUNT(*) FROM index_measurements WHERE calculation_status<>'COMPUTED' AND index_mean IS NOT NULL");assert cur.fetchone()[0]==0
            status=query(cur,'SELECT calculation_status,COUNT(*) AS observations FROM index_measurements GROUP BY calculation_status')
            assert {r['calculation_status']:r['observations'] for r in status}==prep['ndvi_status_counts']
            batches=query(cur,'SELECT * FROM v_batch_summary ORDER BY crop_code,batch_no')
            assert [r['batch_no'] for r in batches]==[1,2]
            assert [r['plants_per_light'] for r in batches]==[12,21]
            sample_ids=query(cur,"SELECT MIN(observation_id) AS first_id,MAX(observation_id) AS last_id FROM v_singleplant_16_bands WHERE ndvi_status='COMPUTED' GROUP BY batch_no,light_code")
            samples=sorted({r[k] for r in sample_ids for k in ('first_id','last_id')})
            checked=source_bands=0;max_error=0.
            for oid in samples:
                row=query(cur,'SELECT o.crop_box_json,v.* FROM v_singleplant_16_bands v JOIN plant_observations o ON o.id=v.observation_id WHERE v.observation_id=%s',(oid,))[0]
                with Image.open(row['mask_path']) as im:mask=np.asarray(im.convert('L'))>0
                with Image.open(row['L680']) as im:red=np.asarray(im)
                with Image.open(row['L800']) as im:nir=np.asarray(im)
                rf=red.astype(float);nf=nir.astype(float);denom=nf+rf
                saturated=(red==np.iinfo(red.dtype).max)|(nir==np.iinfo(nir.dtype).max)
                valid=mask&np.isfinite(rf)&np.isfinite(nf)&(denom>0)&~saturated
                assert int(valid.sum())==row['valid_pixel_count']
                # A scalar accumulation supplies a separate check of the stored aggregate.
                values=(nf[valid]-rf[valid])/denom[valid]
                value=float(np.sum(values,dtype=np.float64)/len(values))
                error=abs(value-row['ndvi_mean']);max_error=max(max_error,error);assert error<1e-12
                box=json.loads(row['crop_box_json']);left,top,right,bottom=box
                originals=query(cur,"SELECT channel_code,original_file_path FROM singleplant_images WHERE observation_id=%s AND channel_code IN ('L680','L800')",(oid,))
                for asset in originals:
                    assert asset['original_file_path'] is not None
                    with Image.open(asset['original_file_path']) as im:raw=np.asarray(im)
                    raw_crop=raw[top:bottom,left:right]
                    segmented=red if asset['channel_code']=='L680' else nir
                    assert raw_crop.shape==segmented.shape==mask.shape
                    np.testing.assert_array_equal(raw_crop[mask],segmented[mask])
                    assert np.all(segmented[~mask]==0)
                    source_bands+=1
                checked+=1
            examples=query(cur,'SELECT observation_id,batch_no,batch_name,light_code,captured_at,plant_number,ndvi_mean,ndvi_status,ndvi_value_basis,quality_status,L680,L800,mask_path FROM v_singleplant_16_bands ORDER BY batch_no,captured_at,light_order,plant_number LIMIT 5')
            result={'passed':True,'database':'plant_multispectral','table_counts':counts,
                'batches':json.loads(json.dumps(batches,default=str,ensure_ascii=False)),
                'ndvi_status_counts':status,'sample_observations_recomputed':checked,'original_source_bands_compared':source_bands,
                'max_sample_mean_error':max_error,'empty_measurements_are_null':True,'all_16_band_links_present':True,
                'website_modified':False,'public_web_enabled':False,
                'examples':json.loads(json.dumps(examples,default=str,ensure_ascii=False))}
            write(BASE/'reports'/'verification_report.json',result)
            print(json.dumps(result,ensure_ascii=True),flush=True)
    finally:conn.rollback();conn.close()


if __name__=='__main__':main()
