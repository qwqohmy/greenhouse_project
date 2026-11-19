"""Whitelisted, read-only reporting gallery; independent of phenotype training approval."""
import io
import json
from pathlib import Path
import re
from urllib.parse import parse_qs
import zipfile


def _data(base):
    root=(Path(base)/'web-runtime/gallery').resolve()
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    return root,manifest


def _file(root,name):
    if not isinstance(name,str) or '\\' in name or not re.fullmatch(r'(?:images/)?[a-zA-Z0-9_-]+\.jpg',name):raise FileNotFoundError()
    file=(root/name).resolve()
    if not file.is_relative_to(root) or not file.is_file():raise FileNotFoundError()
    return file


def handle_gallery(handler,route,query,base):
    static={'':('gallery.html','text/html; charset=utf-8'),'gallery':('gallery.html','text/html; charset=utf-8'),
            'gallery.css':('gallery.css','text/css; charset=utf-8'),'gallery.js':('gallery.js','application/javascript; charset=utf-8')}
    if route in static:
        name,mime=static[route];handler.send((Path(base)/name).read_bytes(),mime);return True
    if route!='api/dataset-gallery' and not route.startswith('gallery/'):return False
    root,manifest=_data(base);params=parse_qs(query)
    crop=params.get('crop',['lettuce'])[0]
    if crop not in ('lettuce','tomato'):
        handler.send(json.dumps({'error':'作物格式不正確'},ensure_ascii=False),'application/json; charset=utf-8',400);return True
    if route=='api/dataset-gallery':
        selected=[r for r in manifest['rows'] if r['crop']==crop]
        rows=[{**{k:v for k,v in row.items() if k!='image_file'},'image_url':'gallery/image/'+row['id']} for row in selected]
        handler.send(json.dumps({'kind':manifest['kind'],'crop':crop,'count':len(rows),'display_slots':12,
                                'sample_unit':'plant-date observation','updated_on':manifest['updated_on'],'rows':rows},ensure_ascii=False),'application/json; charset=utf-8');return True
    match=re.fullmatch(r'gallery/image/([a-z0-9_-]{1,100})',route)
    if match:
        row=next((r for r in manifest['rows'] if r['id']==match.group(1)),None)
        if row is None:handler.send('Not found','text/plain',404);return True
        handler.send(_file(root,row['image_file']).read_bytes(),'image/jpeg');return True
    match=re.fullmatch(r'gallery/sheet/(lettuce|tomato)',route)
    if match:
        selected=match.group(1)
        handler.send(_file(root,manifest['sheets'][selected]).read_bytes(),'image/jpeg',filename=selected+'-'+manifest['kind']+'-examples.jpg');return True
    match=re.fullmatch(r'gallery/download/(lettuce|tomato)\.zip',route)
    if match:
        selected=match.group(1);stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for row in manifest['rows']:
                if row['crop']==selected:archive.writestr(row['id']+'.jpg',_file(root,row['image_file']).read_bytes())
        handler.send(stream.getvalue(),'application/zip',filename=selected+'-'+manifest['kind']+'-jpgs.zip');return True
    handler.send('Not found','text/plain',404);return True
