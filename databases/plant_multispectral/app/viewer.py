import os
"""Read-only, DB-scoped multispectral preview bound only to remote localhost."""
import csv
import io
import json
import logging
from pathlib import Path
import re
from functools import lru_cache
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit
import numpy as np
from PIL import Image
from database import BASE,pymysql

SETTINGS=json.loads((BASE/'.private'/'viewer.json').read_text(encoding='utf-8'))
PREFIX='/s/'+SETTINGS['share_token']+'/'
SAM=Path(os.environ.get('SAM_ROOT','data/multispectral_sam')).resolve()
RUNTIME=BASE/'web-runtime';RUNTIME.mkdir(exist_ok=True)
logging.basicConfig(filename=RUNTIME/'viewer.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
JSON_DEFAULT=str


def connect_readonly():
    connection=pymysql.connect(host=os.environ.get('MYSQL_HOST','127.0.0.1'),port=int(os.environ.get('MYSQL_PORT','3306')),
        user=SETTINGS['reader_user'],password=SETTINGS['reader_password'],database='plant_multispectral',
        charset='utf8mb4',autocommit=False,connect_timeout=10,read_timeout=60)
    with connection.cursor() as cur:cur.execute('SET SESSION TRANSACTION READ ONLY')
    return connection


def select(sql,params=(),one=False):
    connection=connect_readonly()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql,params);names=[c[0] for c in cursor.description]
            rows=[dict(zip(names,row)) for row in cursor.fetchall()]
        return (rows[0] if rows else None) if one else rows
    finally:connection.rollback();connection.close()


def filters(query):
    where=[];params=[]
    values={k:v[0] for k,v in query.items()}
    if values.get('batch'):
        if values['batch'] not in ('1','2'):raise ValueError('批次格式不正確')
        where.append('b.batch_no=%s');params.append(int(values['batch']))
    if values.get('light'):
        if not re.fullmatch('[ABCD]-[123]',values['light']):raise ValueError('光照格式不正確')
        where.append('l.code=%s');params.append(values['light'])
    if values.get('date'):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',values['date']):raise ValueError('日期格式不正確')
        from datetime import date
        date.fromisoformat(values['date'])
        where.append('DATE(c.captured_at)=%s');params.append(values['date'])
    if values.get('plant'):
        if not re.fullmatch(r'[1-9]\d?',values['plant']) or int(values['plant'])>21:raise ValueError('單株編號格式不正確')
        where.append('p.position_no=%s');params.append(int(values['plant']))
    if values.get('quality'):
        if values['quality'] not in ('ok','tiny_or_sparse_plant','no_visible_plant'):raise ValueError('品質格式不正確')
        where.append('o.quality_status=%s');params.append(values['quality'])
    if values.get('computed')=='1':where.append("m.calculation_status='COMPUTED'")
    return (' WHERE '+' AND '.join(where) if where else ''),params


FROM=''' FROM plant_observations o JOIN plants p ON p.id=o.plant_id
 JOIN crop_batches b ON b.id=p.batch_id JOIN light_conditions l ON l.id=p.light_condition_id
 JOIN capture_groups c ON c.id=o.capture_group_id
 LEFT JOIN index_definitions d ON d.code='NDVI' AND d.algorithm_version='ndvi800680_dn_v1'
 LEFT JOIN index_measurements m ON m.observation_id=o.id AND m.definition_id=d.id'''
FIELDS='''o.id AS observation_id,b.batch_no,b.display_name AS batch_name,l.code AS light_code,
 c.captured_at,c.capture_code,p.position_no AS plant_number,o.quality_status,o.mask_source,o.band_count,
 m.index_mean AS ndvi_mean,m.index_median AS ndvi_median,m.index_std AS ndvi_std,
 m.calculation_status AS ndvi_status,d.value_basis AS ndvi_value_basis,
 COALESCE((SELECT i.id FROM singleplant_images i WHERE i.observation_id=o.id AND i.channel_code='Color'),
 (SELECT i.id FROM singleplant_images i WHERE i.observation_id=o.id AND i.channel_code='L540'),
 (SELECT i.id FROM singleplant_images i WHERE i.observation_id=o.id AND i.channel_code='L800')) AS thumbnail_id'''
SORT={'time':'b.batch_no,c.captured_at,l.display_order,p.position_no',
      'ndvi_desc':'m.index_mean IS NULL,m.index_mean DESC,b.batch_no,c.captured_at,l.display_order,p.position_no',
      'ndvi_asc':'m.index_mean IS NULL,m.index_mean ASC,b.batch_no,c.captured_at,l.display_order,p.position_no'}


@lru_cache(maxsize=256)
def preview(asset_id,size,mtime):
    row=select('SELECT i.*,o.output_directory FROM singleplant_images i JOIN plant_observations o ON o.id=i.observation_id WHERE i.id=%s',(asset_id,),one=True)
    if row is None:raise FileNotFoundError()
    path=allowed_path(row['file_path']);folder=allowed_path(row['output_directory'],directory=True)
    with Image.open(path) as source:
        array=np.asarray(source)
        if array.ndim==2 and row['image_kind'] not in ('MASK','VENDOR_INDEX'):
            with Image.open(folder/'mask.png') as im:mask=np.asarray(im.convert('L'))>0
            valid=array[mask] if mask.any() else array.ravel()
            low,high=np.percentile(valid,(1,99)) if len(valid) else (0,1)
            scaled=np.clip((array.astype(float)-low)/max(float(high-low),1.),0,1)
            gray=(scaled*255).astype(np.uint8)
            rgba=np.dstack([gray,gray,gray,mask.astype(np.uint8)*255])
            image=Image.fromarray(rgba,'RGBA')
        else:image=source.convert('RGBA')
        image.thumbnail((size,size),Image.Resampling.LANCZOS)
        data=io.BytesIO();image.save(data,format='PNG');return data.getvalue()


def allowed_path(value,directory=False):
    path=Path(value).resolve()
    if not path.is_relative_to(SAM):raise FileNotFoundError()
    if directory:
        if not path.is_dir():raise FileNotFoundError()
    elif not path.is_file() or path.suffix.lower()!='.png':raise FileNotFoundError()
    return path


class Handler(BaseHTTPRequestHandler):
    server_version='SpectralViewer'
    def log_message(self,format,*args):logging.info('request status=%s',args[1] if len(args)>1 else '-')
    def send(self,body,mime='application/json; charset=utf-8',status=200,filename=None,cache=False):
        if not isinstance(body,bytes):body=body.encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','private, max-age=120' if cache else 'private, no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(body)
    def data(self,value,status=200):self.send(json.dumps(value,ensure_ascii=False,default=JSON_DEFAULT),status=status)
    def do_POST(self):self.send('Read only','text/plain',405)
    do_PUT=do_POST;do_PATCH=do_POST;do_DELETE=do_POST
    def do_GET(self):
        try:self.route()
        except (BrokenPipeError,ConnectionResetError):pass
        except ValueError as error:self.data({'error':str(error)},400)
        except FileNotFoundError:self.data({'error':'找不到指定資料'},404)
        except Exception:
            logging.exception('Request failed');self.data({'error':'資料讀取失敗，請稍後再試。'},500)
    def route(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/healthz':self.data({'ok':bool(select('SELECT 1 AS ok',one=True))});return
        if not parsed.path.startswith(PREFIX):self.send('Not found','text/plain',404);return
        route=parsed.path[len(PREFIX):];query=parse_qs(parsed.query)
        static={'':('viewer.html','text/html; charset=utf-8'),'viewer.css':('viewer.css','text/css; charset=utf-8'),'viewer.js':('viewer.js','application/javascript; charset=utf-8')}
        if route in static:
            name,mime=static[route];self.send((BASE/name).read_bytes(),mime);return
        if route=='api/overview':
            summary=select('''SELECT (SELECT COUNT(*) FROM plant_observations) AS observations,
             (SELECT COUNT(*) FROM singleplant_images WHERE image_kind='SPECTRAL') AS band_images,
             (SELECT COUNT(*) FROM index_measurements WHERE calculation_status='COMPUTED') AS computed,
             (SELECT COUNT(*) FROM index_measurements WHERE calculation_status='EMPTY_MASK') AS empty_masks''',one=True)
            summary['batches']=select('SELECT * FROM v_batch_summary ORDER BY batch_no')
            summary['lights']=select('SELECT code FROM light_conditions ORDER BY display_order')
            summary['dates']=select('''SELECT DISTINCT b.batch_no,DATE(c.captured_at) AS date FROM capture_groups c
             JOIN source_folders s ON s.id=c.source_folder_id JOIN crop_batches b ON b.id=s.batch_id ORDER BY b.batch_no,date''')
            summary['ndvi_basis']='RAW_DN_UNCALIBRATED';self.data(summary);return
        if route=='api/observations':
            where,params=filters(query)
            page=int(query.get('page',['1'])[0]);size=int(query.get('size',['24'])[0]);sort=query.get('sort',['time'])[0]
            if not 1<=page<=1000 or not 1<=size<=48 or sort not in SORT:raise ValueError('分頁或排序格式不正確')
            total=select('SELECT COUNT(*) AS n'+FROM+where,params,one=True)['n']
            rows=select('SELECT '+FIELDS+FROM+where+' ORDER BY '+SORT[sort]+' LIMIT %s OFFSET %s',[*params,size,(page-1)*size])
            self.data({'total':total,'page':page,'size':size,'rows':rows});return
        match=re.fullmatch(r'api/observations/(\d+)',route)
        if match:
            oid=int(match[1]);row=select('SELECT '+FIELDS+FROM+' WHERE o.id=%s',(oid,),one=True)
            if row is None:raise FileNotFoundError()
            row['images']=select('''SELECT id,channel_code,image_kind,file_path,width_px,height_px,pixel_mode
             FROM singleplant_images WHERE observation_id=%s ORDER BY image_kind='COLOR' DESC,image_kind='SPECTRAL' DESC,band_id,channel_code''',(oid,))
            row['measurement']=select('''SELECT m.*,d.formula_text,d.value_basis,d.calibration_status,d.alignment_status
             FROM index_measurements m JOIN index_definitions d ON d.id=m.definition_id
             WHERE m.observation_id=%s AND d.code='NDVI' AND d.algorithm_version='ndvi800680_dn_v1' ''',(oid,),one=True)
            self.data(row);return
        match=re.fullmatch(r'(preview|asset)/(\d+)',route)
        if match:
            asset_id=int(match[2]);row=select('SELECT * FROM singleplant_images WHERE id=%s',(asset_id,),one=True)
            if row is None:raise FileNotFoundError()
            path=allowed_path(row['file_path'])
            if match[1]=='asset':self.send(path.read_bytes(),'image/png',filename=row['channel_code']+'.png');return
            size=int(query.get('size',['180'])[0])
            if size not in (120,180,320,640):raise ValueError('預覽尺寸不正確')
            self.send(preview(asset_id,size,path.stat().st_mtime_ns),'image/png',cache=True);return
        if route=='api/export.csv':
            where,params=filters(query)
            rows=select('SELECT o.id AS observation_id,b.batch_no,b.display_name AS batch_name,l.code AS light_code,c.captured_at,p.position_no AS plant_number,o.quality_status,m.index_mean AS ndvi_mean,m.index_median AS ndvi_median,m.calculation_status AS ndvi_status,d.value_basis AS ndvi_value_basis'+FROM+where+' ORDER BY '+SORT['time'],params)
            fields=['observation_id','batch_no','batch_name','light_code','captured_at','plant_number','quality_status','ndvi_mean','ndvi_median','ndvi_status','ndvi_value_basis']
            stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            self.send(stream.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8',filename='multispectral_observations.csv');return
        raise FileNotFoundError()


if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',int(SETTINGS['web_port'])),Handler)
    logging.info('Private read-only viewer listening on loopback port %s',SETTINGS['web_port'])
    server.serve_forever()
