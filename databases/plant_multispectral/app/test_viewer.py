"""Exercise the running private viewer without changing research data."""
import csv
import hashlib
import io
import json
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from PIL import Image
import viewer
from prepare_dataset import write


def main():
    base='http://127.0.0.1:'+str(viewer.SETTINGS['web_port'])+viewer.PREFIX
    def get(path):
        with urlopen(base+path,timeout=60) as response:return json.load(response)
    overview=get('api/overview')
    assert (overview['observations'],overview['band_images'],overview['computed'],overview['empty_masks'])==(5940,95040,5933,7)
    assert [b['batch_no'] for b in overview['batches']]==[1,2]
    page=get('api/observations');assert page['total']==5940 and len(page['rows'])==24
    filtered=get('api/observations?batch=2&light=A-1&date=2026-07-15&plant=21')
    assert filtered['total']==1 and filtered['rows'][0]['plant_number']==21
    assert get('api/observations?computed=1')['total']==5933
    empty=get('api/observations?quality=no_visible_plant')
    assert empty['total']==7 and all(r['ndvi_mean'] is None for r in empty['rows'])
    detail=get('api/observations/'+str(page['rows'][0]['observation_id']))
    assert sum(i['image_kind']=='SPECTRAL' for i in detail['images'])==16
    band=next(i for i in detail['images'] if i['channel_code']=='L680')
    for aid,size in [(page['rows'][0]['thumbnail_id'],120),(band['id'],640)]:
        with urlopen(base+f'preview/{aid}?size={size}',timeout=30) as response:
            assert response.headers['Content-Type']=='image/png'
            with Image.open(io.BytesIO(response.read())) as image:assert max(image.size)<=size
    with urlopen(base+'asset/'+str(band['id']),timeout=30) as response:raw=response.read()
    assert hashlib.sha256(raw).hexdigest()==hashlib.sha256(viewer.allowed_path(band['file_path']).read_bytes()).hexdigest()
    with urlopen(base+'api/export.csv?batch=2&light=A-1&date=2026-07-15&plant=21',timeout=30) as response:
        rows=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
    assert len(rows)==1 and rows[0]['batch_no']=='2' and rows[0]['ndvi_value_basis']=='RAW_DN_UNCALIBRATED'
    for path,status in [('api/observations?batch=2%20OR%201=1',400),('api/observations?light=../../.private',400),
                        ('asset/999999999',404),('preview/999999999',404),('.private/viewer.json',404),('api/observations/999999999',404)]:
        try:urlopen(base+path,timeout=30)
        except HTTPError as error:assert error.code==status
        else:raise AssertionError('Unexpected access: '+path)
    try:urlopen(Request(base+'api/observations',data=b'{}',method='POST'),timeout=30)
    except HTTPError as error:assert error.code==405
    else:raise AssertionError('Write method was accepted')
    connection=viewer.connect_readonly()
    try:
        with connection.cursor() as cur:
            cur.execute('SHOW GRANTS');grants=[r[0] for r in cur.fetchall()]
            assert any('GRANT SELECT ON `plant_multispectral`.*' in g for g in grants)
            assert not any('ALL PRIVILEGES' in g or 'INSERT' in g or 'UPDATE' in g for g in grants)
            try:cur.execute('UPDATE crop_batches SET display_name=display_name WHERE id=0')
            except viewer.pymysql.MySQLError:pass
            else:raise AssertionError('Viewer write was not rejected')
    finally:connection.rollback();connection.close()
    report={'passed':True,'observations':5940,'band_images':95040,'computed':5933,'empty_masks':7,
            'batch2_plant21_filter_verified':True,'previews_and_unchanged_raw_download_verified':True,
            'filtered_csv_verified':True,'readonly_role_verified':True,'private_files_not_served':True,'public':False}
    write(viewer.BASE/'reports'/'viewer_verification.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':main()
