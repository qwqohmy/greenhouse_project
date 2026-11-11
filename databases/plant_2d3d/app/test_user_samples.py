"""Validate typed source labels and scoped original-image access, using an ephemeral server."""
import hashlib,json,threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
import viewer


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),viewer.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)+viewer.PREFIX
    def get(path):
        with urlopen(base+path,timeout=30) as r:return json.load(r)
    try:
        summary=get('api/overview')
        assert (summary['user_confirmed_samples'],summary['user_confirmed_images'],summary['user_trial_samples'])==(36,8640,31)
        assert summary['user_native_trial_samples']==11 and summary['user_proxy_trial_samples']==30
        rows=get('api/user-samples');assert len(rows)==36
        assert len({r['sample_id'] for r in rows})==len({r['capture_code'] for r in rows})==36
        assert sum(r['image_count'] for r in rows)==8640
        assert sum(bool(r['trial_eligible']) for r in rows)==31
        held={r['capture_code'] for r in rows if not r['trial_eligible']}
        assert held=={'2026-07-25_13-21-38','2026-07-27_14-30-56','2026-07-31_15-01-11','2026-08-02_13-59-25','2026-08-08_19-08-02'}
        august=next(r for r in rows if r['capture_code']=='2026-08-12_13-12-16')
        assert august['csv_minus_rgb_seconds']==1
        assert set(august['sources'])=={'native'}
        detail=get('api/user-samples/'+str(august['sample_id']))
        assert len(detail['images'])==240
        assert all(sum(v['camera_code']==str(c) for v in detail['images'])==60 for c in range(1,5))
        sid=august['sample_id'];aid=detail['images'][0]['asset_id']
        with urlopen(base+f'user-asset/{sid}/{aid}',timeout=30) as response:assert response.status==200
        with urlopen(base+f'api/user-samples/{sid}/csv?source=native',timeout=30) as response:
            content=response.read()
        assert hashlib.sha256(content).hexdigest()==detail['sources']['native']['sha256']
        assert 'pGH' in detail['sources']['native']['numeric_values']
        assert 'pGH_proxy' not in detail['sources']['native']['numeric_values']
        for path in (f'user-asset/99999999/{aid}',f'user-asset/{sid}/99999999',f'api/user-samples/{sid}/csv?source=proxy',f'api/user-samples/{sid}/csv?source=../../.private/credentials.json'):
            try:urlopen(base+path,timeout=30)
            except HTTPError as error:assert error.code==404
            else:raise AssertionError('Unrelated or missing asset source was served')
        assert len(get('api/user-samples?date=2026-08-12'))==1
        result={'passed':True,'confirmed_samples':36,'original_views':8640,'trial_source_samples':31,
                'native_samples':11,'proxy_samples':30,'held_target_samples':5,
                'native_csv_without_ply_supported':True,'original_native_values_preserved':True,
                'all_four_cameras_same_sample':True,'scoped_image_and_csv_access_verified':True}
        (viewer.BASE/'review-updates/user_samples_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()
