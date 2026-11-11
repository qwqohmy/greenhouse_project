import os
"""Read-only shared viewer. Only DB-linked image assets can be served."""
import csv
import io
import json
import logging
from pathlib import Path
import re
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit

from database import BASE,connect

DEPLOY=json.loads((BASE/'deployment.json').read_text(encoding='utf-8'))
PRIVATE=json.loads(Path(DEPLOY['credentials_file']).read_text(encoding='utf-8'))
PREFIX='/s/'+PRIVATE['share_token']+'/'
LOG=BASE/'web-runtime';LOG.mkdir(exist_ok=True)
logging.basicConfig(filename=LOG/'viewer.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')


def select(sql,params=(),one=False):
    connection=connect(readonly=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql,params)
            names=[column[0] for column in cursor.description]
            rows=[dict(zip(names,row)) for row in cursor.fetchall()]
            return (rows[0] if rows else None) if one else rows
    finally:
        connection.close()


def time_candidates(crop='',date='',ply_session_id=None):
    where=[];params=[]
    if crop in ('lettuce','tomato'):
        where.append('p.crop=%s');params.append(crop)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):
        where.append('DATE(p.captured_at)=%s');params.append(date)
    if ply_session_id is not None:
        where.append('p.id=%s');params.append(ply_session_id)
    sql='''SELECT DISTINCT p.id AS ply_session_id,p.capture_code AS ply_capture_code,
        p.captured_at,p.crop,r.id AS rgb_session_id,r.capture_code AS rgb_capture_code,
        c.delta_seconds,r.review_status AS rgb_review_status
        FROM p3d_session_candidates c JOIN p3d_observations o ON o.id=c.observation_id
        JOIN p3d_sessions p ON p.id=o.ply_session_id JOIN p3d_sessions r ON r.id=c.rgb_session_id'''
    if where:
        sql+=' WHERE '+' AND '.join(where)
    pairs=select(sql+' ORDER BY p.captured_at,p.id,ABS(c.delta_seconds),r.capture_code',params)
    thumbs={r['session_id']:r['thumbnail_asset_id'] for r in select("SELECT session_id,MIN(asset_id) AS thumbnail_asset_id FROM p3d_images WHERE image_kind='CROP' GROUP BY session_id")}
    observations={r['ply_session_id']:r['count'] for r in select('SELECT ply_session_id,COUNT(*) AS count FROM p3d_observations GROUP BY ply_session_id')}
    grouped={}
    for pair in pairs:
        sid=pair['ply_session_id']
        if sid not in grouped:
            grouped[sid]={'ply_session_id':sid,'ply_capture_code':pair['ply_capture_code'],
                'captured_at':pair['captured_at'],'crop':pair['crop'],
                'csv_component_candidates':observations.get(sid,0),'rgb_candidates':[],
                'nearest_rgb_session_id':pair['rgb_session_id'],'nearest_rgb_capture_code':pair['rgb_capture_code'],
                'nearest_delta_seconds':pair['delta_seconds'],'thumbnail_asset_id':thumbs.get(pair['rgb_session_id']),
                'link_scope':'TIME_CANDIDATE_SCENE_NOT_INDIVIDUAL_POT',
                'time_link_implies_training_approval':False}
        grouped[sid]['rgb_candidates'].append({k:pair[k] for k in ('rgb_session_id','rgb_capture_code','delta_seconds','rgb_review_status')})
    return list(grouped.values())


class Handler(BaseHTTPRequestHandler):
    server_version='PlantViewer'

    def log_message(self,format,*args):
        # Do not persist bearer share URL tokens in access logs.
        logging.info('request from %s status=%s',self.client_address[0],args[1] if len(args)>1 else '-')

    def send(self,body,content_type='application/json; charset=utf-8',status=200,filename=None):
        if not isinstance(body,bytes):
            body=body.encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','private, no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        if filename:
            self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(body)

    def data(self,value,status=200):
        self.send(json.dumps(value,ensure_ascii=False,default=str),status=status)

    def do_GET(self):
        try:
            self.route()
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            logging.exception('Read-only request failed')
            self.data({'error':'資料暫時無法讀取，請稍後重試。'},500)

    def route(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/healthz':
            self.data({'ok':bool(select('SELECT 1 AS ok',one=True))});return
        if not parsed.path.startswith(PREFIX):
            self.send('Not found','text/plain; charset=utf-8',404);return
        route=parsed.path[len(PREFIX):]
        if route=='':
            self.send((BASE/'viewer.html').read_bytes(),'text/html; charset=utf-8');return
        if route=='time-candidates.js':
            self.send((BASE/'time-candidates.js').read_bytes(),'application/javascript; charset=utf-8');return
        if route=='user-samples.js':
            self.send((BASE/'user-samples.js').read_bytes(),'application/javascript; charset=utf-8');return
        if route=='api/overview':
            counts=select('''SELECT
                (SELECT COUNT(*) FROM p3d_observations) AS observations,
                (SELECT COUNT(*) FROM p3d_csv_exports) AS csv_versions,
                (SELECT COUNT(DISTINCT observation_id) FROM p3d_observation_images WHERE link_status IN ('LINKED_SCENE','VERIFIED')) AS linked_observations,
                (SELECT COUNT(*) FROM p3d_observation_images WHERE link_status IN ('LINKED_SCENE','VERIFIED')) AS linked_views,
                (SELECT COUNT(*) FROM p3d_v_training_ready) AS training_ready,
                (SELECT COUNT(*) FROM p3d_user_samples) AS user_confirmed_samples,
                (SELECT COUNT(*) FROM p3d_user_sample_images) AS user_confirmed_images,
                (SELECT COUNT(*) FROM p3d_user_samples WHERE trial_eligible=TRUE) AS user_trial_samples,
                (SELECT COUNT(*) FROM p3d_user_samples WHERE native_trial_eligible=TRUE) AS user_native_trial_samples,
                (SELECT COUNT(*) FROM p3d_user_samples WHERE proxy_trial_eligible=TRUE) AS user_proxy_trial_samples,
                (SELECT COUNT(DISTINCT o.ply_session_id) FROM p3d_session_candidates c JOIN p3d_observations o ON o.id=c.observation_id) AS time_candidate_scenes,
                (SELECT COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(o.evidence_json,'$.round3.sample_key_candidate'))) FROM p3d_observations o WHERE o.visual_review_status IN ('LINKED_SCENE_SCREENED_EXACT','USER_SINGLE_POT_DIRECT')
                 AND JSON_UNQUOTE(JSON_EXTRACT(o.evidence_json,'$.round3.proxy_preparation_candidate'))='true'
                 AND EXISTS(SELECT 1 FROM p3d_observation_images l WHERE l.observation_id=o.id AND l.link_status IN ('LINKED_SCENE','VERIFIED'))) AS proxy_training_scenes,
                (SELECT SUM(processed_images) FROM p3d_processing_runs) AS processed_images,
                (SELECT SUM(no_detection_images) FROM p3d_processing_runs) AS no_detection_images,
                (SELECT SUM(error_count) FROM p3d_processing_runs) AS errors''',one=True)
            self.data(counts);return
        if route=='api/user-samples':
            query=parse_qs(parsed.query);where=[];params=[]
            crop=query.get('crop',[''])[0];date=query.get('date',[''])[0]
            if crop in ('lettuce','tomato'):where.append('s.crop=%s');params.append(crop)
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):where.append('s.capture_date=%s');params.append(date)
            sql='''SELECT s.id AS sample_id,s.sample_key,s.capture_code,s.capture_date,s.csv_capture_code,
                s.csv_minus_rgb_seconds,s.crop,s.batch_code,s.primary_kind,s.trial_eligible,
                s.native_trial_eligible,s.proxy_trial_eligible,s.target_sources_json,s.evidence_json,
                COUNT(l.image_id) AS image_count,MIN(i.asset_id) AS thumbnail_asset_id
                FROM p3d_user_samples s JOIN p3d_user_sample_images l ON l.sample_id=s.id
                JOIN p3d_images i ON i.id=l.image_id'''
            if where:sql+=' WHERE '+' AND '.join(where)
            rows=select(sql+' GROUP BY s.id ORDER BY s.capture_code',params)
            for row in rows:
                row['sources']=json.loads(row.pop('target_sources_json'));row['evidence']=json.loads(row.pop('evidence_json'))
            self.data(rows);return
        match=re.fullmatch(r'api/user-samples/(\d+)(/csv)?',route)
        if match:
            sid=int(match[1]);row=select('SELECT * FROM p3d_user_samples WHERE id=%s',(sid,),one=True)
            if row is None:self.data({'error':'找不到人工確認的單株資料'},404);return
            sources=json.loads(row.pop('target_sources_json'));row['evidence']=json.loads(row.pop('evidence_json'))
            if match[2]:
                query=parse_qs(parsed.query);kind=query.get('source',['primary'])[0]
                if kind=='primary':kind='native' if row['primary_kind']=='VENDOR_NATIVE' else 'proxy'
                source=sources.get(kind) if kind in ('native','proxy') else None
                if not source:self.send('Not found','text/plain',404);return
                file=Path(source['path']).resolve()
                allowed=[Path(os.environ.get('PLY_ROOT','data/ply')).resolve(),Path(os.environ.get('OCTOBER_RGB_ROOT','data/october_rgb')).resolve(),Path(os.environ.get('PIPELINE_ROOT','data/pipeline')).resolve()]
                if file.suffix.lower()!='.csv' or not any(file.is_relative_to(root) for root in allowed):
                    self.send('Not found','text/plain',404);return
                self.send(file.read_bytes(),'text/csv; charset=utf-8',filename=f'user-single-{sid}-{kind}.csv');return
            images=select('''SELECT i.asset_id,i.camera_code,i.frame_index,i.image_kind FROM p3d_user_sample_images l
                JOIN p3d_images i ON i.id=l.image_id WHERE l.sample_id=%s ORDER BY i.camera_code,i.frame_index''',(sid,))
            row.update(sample_id=sid,sources=sources,images=images);self.data(row);return
        match=re.fullmatch(r'user-asset/(\d+)/(\d+)',route)
        if match:
            sid,aid=map(int,match.groups())
            asset=select('''SELECT a.file_path FROM p3d_user_sample_images l JOIN p3d_images i ON i.id=l.image_id
                JOIN p3d_assets a ON a.id=i.asset_id WHERE l.sample_id=%s AND a.id=%s AND i.image_kind='RAW'
                AND a.asset_kind='RGB_RAW' LIMIT 1''',(sid,aid),one=True)
            if asset is None:self.send('Not found','text/plain',404);return
            file=Path(asset['file_path']).resolve()
            allowed=[Path(os.environ.get('RGB_ROOT','data/rgb')).resolve(),Path(os.environ.get('OCTOBER_RGB_ROOT','data/october_rgb')).resolve()]
            if file.suffix.lower() not in ('.jpg','.jpeg','.png') or not any(file.is_relative_to(root) for root in allowed):
                self.send('Not found','text/plain',404);return
            self.send(file.read_bytes(),'image/png' if file.suffix.lower()=='.png' else 'image/jpeg');return
        if route=='api/time-candidates':
            query=parse_qs(parsed.query)
            self.data(time_candidates(query.get('crop',[''])[0],query.get('date',[''])[0]));return
        match=re.fullmatch(r'api/time-candidates/(\d+)(?:/rgb/(\d+))?',route)
        if match:
            sid=int(match[1]);scenes=time_candidates(ply_session_id=sid)
            if not scenes:
                self.data({'error':'找不到時間候選場次'},404);return
            scene=scenes[0]
            rid=int(match[2]) if match[2] else scene['nearest_rgb_session_id']
            candidates={r['rgb_session_id']:r for r in scene['rgb_candidates']}
            if rid not in candidates:
                self.data({'error':'這兩個場次沒有候選連結'},404);return
            images=select("SELECT asset_id,mask_asset_id,segmented_asset_id,camera_code,frame_index,quality_status,instance_local_id FROM p3d_images WHERE session_id=%s AND image_kind='CROP' ORDER BY camera_code,frame_index,instance_local_id",(rid,))
            observations=select('''SELECT v.observation_id,v.observation_key,v.visual_review_status,
                v.review_notes,v.pGH_proxy,v.pMW_proxy,v.coordinate_unit FROM p3d_v_observations v
                JOIN p3d_observations o ON o.id=v.observation_id WHERE o.ply_session_id=%s ORDER BY v.observation_id''',(sid,))
            scene.update(selected_rgb=candidates[rid],candidate_context={'ply_session_id':sid,'rgb_session_id':rid},images=images,observations=observations)
            self.data(scene);return
        if route=='api/observations':
            query=parse_qs(parsed.query);linked=query.get('linked',['1'])[0]=='1'
            crop=query.get('crop',[''])[0];date=query.get('date',[''])[0]
            where=[];params=[]
            if linked:
                where.append('v.linked_image_count>0')
            if crop in ('lettuce','tomato'):
                where.append('v.crop=%s');params.append(crop)
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):
                where.append('DATE(v.captured_at)=%s');params.append(date)
            sql='''SELECT v.observation_id,v.observation_key,v.captured_at,v.crop,v.batch_code,
                v.scene_local_plant_id,v.physical_plant_id_candidate,v.visual_review_status,
                v.linked_image_count,v.pGH_proxy,v.pMW_proxy,v.coordinate_unit,
                (SELECT MIN(i.asset_id) FROM p3d_observation_images l JOIN p3d_images i ON i.id=l.image_id
                 WHERE l.observation_id=v.observation_id AND l.link_status IN ('LINKED_SCENE','VERIFIED')) AS thumbnail_asset_id
                FROM p3d_v_observations v'''
            if where:
                sql+=' WHERE '+' AND '.join(where)
            self.data(select(sql+' ORDER BY v.captured_at,v.observation_key LIMIT 300',params));return
        match=re.fullmatch(r'api/observations/(\d+)(/csv)?',route)
        if match:
            identity=int(match[1])
            observation=select('''SELECT v.observation_id,v.observation_key,v.captured_at,v.crop,v.batch_code,
                v.scene_local_plant_id,v.physical_plant_id_candidate,v.visual_review_status,v.review_notes,
                v.coordinate_unit,v.linked_image_count,e.export_kind,e.algorithm_version,
                e.id AS csv_export_id FROM p3d_v_observations v
                JOIN p3d_observations o ON o.id=v.observation_id
                JOIN p3d_csv_exports e ON e.id=o.target_csv_export_id WHERE v.observation_id=%s''',(identity,),one=True)
            if observation is None:
                self.data({'error':'找不到此觀測'},404);return
            metrics=select('SELECT metric_code,metric_value,unit,measurement_kind FROM p3d_measurements WHERE csv_export_id=%s ORDER BY metric_code',(observation['csv_export_id'],))
            if match[2]:
                row={key:observation[key] for key in ('observation_key','captured_at','crop','scene_local_plant_id','physical_plant_id_candidate','coordinate_unit','visual_review_status')}
                row.update({metric['metric_code']:metric['metric_value'] for metric in metrics})
                file=io.StringIO();writer=csv.DictWriter(file,fieldnames=list(row));writer.writeheader();writer.writerow(row)
                self.send(('\ufeff'+file.getvalue()).encode('utf-8'),'text/csv; charset=utf-8',filename='plant-observation-'+str(identity)+'.csv');return
            images=select('''SELECT i.asset_id,i.mask_asset_id,i.segmented_asset_id,i.camera_code,
                i.frame_index,i.image_kind,i.quality_status,l.link_status FROM p3d_observation_images l
                JOIN p3d_images i ON i.id=l.image_id WHERE l.observation_id=%s
                AND l.link_status IN ('LINKED_SCENE','VERIFIED') ORDER BY i.camera_code,i.frame_index''',(identity,))
            observation.update(metrics=metrics,images=images)
            self.data(observation);return
        match=re.fullmatch(r'candidate-asset/(\d+)/(\d+)/(\d+)',route)
        if match:
            sid,rid,identity=map(int,match.groups())
            asset=select('''SELECT DISTINCT a.file_path,a.asset_kind FROM p3d_assets a
                JOIN p3d_images i ON a.id IN (i.asset_id,i.mask_asset_id,i.segmented_asset_id)
                WHERE a.id=%s AND i.session_id=%s AND i.image_kind='CROP'
                AND a.asset_kind IN ('RGB_CROP','MASK','SEGMENTED_RGB')
                AND EXISTS(SELECT 1 FROM p3d_session_candidates c JOIN p3d_observations o ON o.id=c.observation_id
                    WHERE o.ply_session_id=%s AND c.rgb_session_id=i.session_id) LIMIT 1''',(identity,rid,sid),one=True)
            if asset is None:
                self.send('Not found','text/plain',404);return
            file=Path(asset['file_path']);allowed=Path(os.environ.get('RGB_SAM_ROOT','data/rgb_sam')).resolve()
            if not file.resolve().is_relative_to(allowed) or file.suffix.lower() not in ('.png','.jpg','.jpeg'):
                self.send('Not found','text/plain',404);return
            self.send(file.read_bytes(),'image/png' if file.suffix.lower()=='.png' else 'image/jpeg');return
        match=re.fullmatch(r'asset/(\d+)',route)
        if match:
            identity=int(match[1])
            asset=select('''SELECT DISTINCT a.file_path,a.asset_kind FROM p3d_assets a
                JOIN p3d_images i ON a.id IN (i.asset_id,i.mask_asset_id,i.segmented_asset_id)
                JOIN p3d_observation_images l ON l.image_id=i.id
                WHERE a.id=%s AND l.link_status IN ('LINKED_SCENE','VERIFIED')
                AND (a.asset_kind IN ('RGB_CROP','MASK','SEGMENTED_RGB') OR
                    (a.asset_kind='RGB_RAW' AND JSON_UNQUOTE(JSON_EXTRACT(l.link_evidence_json,'$.link_method'))='USER_CONFIRMED_SINGLE_POT_DIRECT')) LIMIT 1''',(identity,),one=True)
            if asset is None:
                self.send('Not found','text/plain',404);return
            file=Path(asset['file_path'])
            allowed=(Path(os.environ.get('OCTOBER_RGB_ROOT','data/october_rgb')) if asset['asset_kind']=='RGB_RAW' else Path(os.environ.get('RGB_SAM_ROOT','data/rgb_sam'))).resolve()
            if not file.resolve().is_relative_to(allowed) or file.suffix.lower() not in ('.png','.jpg','.jpeg'):
                self.send('Not found','text/plain',404);return
            self.send(file.read_bytes(),'image/png' if file.suffix.lower()=='.png' else 'image/jpeg');return
        self.send('Not found','text/plain',404)

    def do_POST(self):
        self.send('Read only','text/plain',405)

    do_PUT=do_POST
    do_DELETE=do_POST
    do_PATCH=do_POST


if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',DEPLOY['web_port']),Handler)
    logging.info('Read-only viewer listening on loopback port %s',DEPLOY['web_port'])
    server.serve_forever()
