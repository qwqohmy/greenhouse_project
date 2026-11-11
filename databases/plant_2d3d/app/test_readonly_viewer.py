"""Loopback-only ephemeral HTTP tests. No public tunnel or persistent task is started."""
import argparse
import csv
import io
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from http.server import ThreadingHTTPServer
from PIL import Image

import viewer


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-linked-scenes',type=int,required=True)
    parser.add_argument('--expected-linked-views',type=int,required=True)
    parser.add_argument('--expected-proxy-samples',type=int,required=True)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',0),viewer.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    root='http://127.0.0.1:'+str(server.server_port)
    base=root+viewer.PREFIX
    checks={}
    def data(path):
        with urlopen(base+path,timeout=30) as response:
            return json.load(response)
    try:
        with urlopen(base,timeout=30) as response:
            html=response.read().decode('utf-8')
        assert 'PlantView' in html;checks['html_served']=True
        summary=data('api/overview');assert summary['observations']==176
        assert int(summary['linked_views'])==args.expected_linked_views;checks['real_remote_db_counts']=True
        rows=data('api/observations');assert len(rows)==args.expected_linked_scenes;checks['expected_linked_scenes_listed']=True
        assert summary['time_candidate_scenes']==69
        assert summary['proxy_training_scenes']==args.expected_proxy_samples
        candidates=data('api/time-candidates')
        assert len(candidates)==len({r['ply_session_id'] for r in candidates})==69
        assert sum(r['csv_component_candidates'] for r in candidates)==106
        assert all(r['time_link_implies_training_approval'] is False for r in candidates)
        scene=data('api/time-candidates/'+str(candidates[0]['ply_session_id']))
        assert scene['images'] and scene['observations']
        assert scene['candidate_context']['rgb_session_id']==scene['selected_rgb']['rgb_session_id']
        sid=scene['candidate_context']['ply_session_id'];rid=scene['candidate_context']['rgb_session_id']
        aid=scene['images'][0]['asset_id']
        with urlopen(base+f'candidate-asset/{sid}/{rid}/{aid}',timeout=30) as response:
            assert response.status==200
        for path in (f'candidate-asset/999999999/{rid}/{aid}',f'candidate-asset/{sid}/999999999/{aid}',f'time-candidates/{sid}/rgb/999999999'):
            try:
                urlopen(base+('api/' if path.startswith('time-candidates') else '')+path,timeout=30)
            except HTTPError as error:
                assert error.code==404
            else:
                raise AssertionError('Unrelated scene pair granted access')
        checks['all_69_time_scenes_and_106_component_candidates_visible']=True
        checks['candidate_images_scoped_to_actual_scene_edges']=True
        october=[row for row in rows if row['visual_review_status']=='USER_SINGLE_POT_DIRECT']
        assert len(october)==17
        raw_detail=data('api/observations/'+str(october[0]['observation_id']))
        assert len(raw_detail['images'])==240
        assert all(image['image_kind']=='RAW' and image['mask_asset_id'] is None for image in raw_detail['images'])
        with urlopen(base+'asset/'+str(raw_detail['images'][0]['asset_id']),timeout=30) as response:
            assert response.status==200 and response.headers['Content-Type']=='image/jpeg'
        checks['all_17_october_single_scenes_link_original_rgb_without_sam']=True
        assert len(data('api/observations?linked=0'))==176;checks['all_candidate_filter']=True
        detail=data('api/observations/'+str(rows[0]['observation_id']))
        assert len(detail['images'])>0
        for key in ('asset_id','mask_asset_id','segmented_asset_id'):
            with urlopen(base+'asset/'+str(detail['images'][0][key]),timeout=30) as response:
                raw=response.read()
            with Image.open(io.BytesIO(raw)) as image:
                assert image.width>0 and image.height>0
        checks['rgb_mask_and_segmented_images_readable']=True
        with urlopen(base+'api/observations/'+str(rows[0]['observation_id'])+'/csv',timeout=30) as response:
            raw=response.read().decode('utf-8-sig')
        output=list(csv.DictReader(io.StringIO(raw)))
        assert len(output)==1 and output[0]['observation_key']==rows[0]['observation_key']
        checks['one_observation_csv_download']=True
        for path in (root+'/',base+'asset/999999999',base+'.private/credentials.json',base+'asset/../../.private/credentials.json'):
            try:
                urlopen(path,timeout=30)
            except HTTPError as error:
                assert error.code==404
            else:
                raise AssertionError('Unexpected asset or secret path exposed')
        checks['unlinked_assets_and_private_paths_denied']=True
        connection=viewer.connect(readonly=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT i.asset_id FROM p3d_observation_images l JOIN p3d_images i ON i.id=l.image_id WHERE l.link_status='REJECTED' AND NOT EXISTS(SELECT 1 FROM p3d_observation_images active WHERE active.image_id=l.image_id AND active.link_status IN ('LINKED_SCENE','VERIFIED')) LIMIT 1")
                rejected=cursor.fetchone()
            if rejected:
                try:
                    urlopen(base+'asset/'+str(rejected[0]),timeout=30)
                except HTTPError as error:
                    assert error.code==404
                else:
                    raise AssertionError('Rejected scene image is still served')
            checks['rejected_scene_images_not_served']=True
        finally:
            connection.close()
        try:
            urlopen(Request(base+'api/observations',data=b'{}',method='POST'),timeout=30)
        except HTTPError as error:
            assert error.code==405
        else:
            raise AssertionError('Write method accepted')
        checks['write_http_methods_denied']=True
        connection=viewer.connect(readonly=True)
        try:
            with connection.cursor() as cursor:
                try:
                    cursor.execute('UPDATE p3d_observations SET id=id WHERE 1=0')
                except Exception as error:
                    assert error.args[0]==1142
                else:
                    raise AssertionError('Viewer database account has write privilege')
        finally:
            connection.rollback();connection.close()
        checks['viewer_database_account_select_only']=True
        result={'passed':True,'checks':checks,'public_tunnel_started':False,'system_tasks_created':False,'summary':summary}
        (viewer.BASE/'viewer_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False))
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':
    main()
