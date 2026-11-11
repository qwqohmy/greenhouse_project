import os
"""Stage existing single-plant images and masked NDVI DN statistics; no DB writes."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image

BASE=Path(__file__).resolve().parent
SAM=Path(os.environ.get('SAM_ROOT','data/multispectral_sam'))
RAW=Path(os.environ.get('LEGACY_SPECTRAL_ROOT','data/multispectral_raw'))
BANDS=[405,430,450,475,500,540,600,630,680,700,730,770,800,850,900,980]
VERSION='ndvi800680_dn_v1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def path_hash(path):return hashlib.sha256(str(path).replace('\\','/').casefold().encode()).hexdigest()
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    for i in range(20):
        try:tmp.replace(path);return
        except PermissionError:
            if i==19:raise
            time.sleep(.1)


def ndvi(folder,quality):
    result={'status':'PENDING','mean':None,'median':None,'std':None,'min':None,'max':None,'p10':None,'p90':None,
            'red_mean_dn':None,'nir_mean_dn':None,'valid_pixel_count':0,'mask_pixel_count':0,
            'zero_denominator_count':0,'saturated_pixel_count':0,'input_sha256':{}}
    paths={k:folder/(k+'.png') for k in ('L680','L800','mask')}
    if not all(p.is_file() for p in paths.values()):result['status']='MISSING_BAND_OR_MASK';return result
    result['input_sha256']={k:sha(p) for k,p in paths.items()}
    with Image.open(paths['mask']) as im:mask=np.asarray(im.convert('L'))>0
    result['mask_pixel_count']=int(mask.sum())
    if not mask.any():result['status']='EMPTY_MASK';return result
    if quality=='no_visible_plant':result['status']='NO_VISIBLE_PLANT';return result
    arrays=[]
    for name in ('L680','L800'):
        with Image.open(paths[name]) as im:a=np.asarray(im)
        if a.ndim!=2:result['status']='NON_SCALAR_BAND';return result
        if a.shape!=mask.shape:result['status']='SHAPE_MISMATCH';return result
        arrays.append(a)
    red,nir=[a.astype(np.float64) for a in arrays]
    denominator=nir+red
    saturated=np.zeros(mask.shape,bool)
    for a in arrays:
        if np.issubdtype(a.dtype,np.integer):saturated|=a==np.iinfo(a.dtype).max
    finite=np.isfinite(red)&np.isfinite(nir)
    result['zero_denominator_count']=int((mask&finite&(denominator==0)).sum())
    result['saturated_pixel_count']=int((mask&saturated).sum())
    valid=mask&finite&(denominator>0)&~saturated
    result['valid_pixel_count']=int(valid.sum())
    if not valid.any():result['status']='NO_VALID_PIXELS';return result
    values=(nir[valid]-red[valid])/denominator[valid]
    assert np.isfinite(values).all() and values.min()>=-1 and values.max()<=1
    result.update(status='COMPUTED',mean=float(values.mean()),median=float(np.median(values)),std=float(values.std()),
                  min=float(values.min()),max=float(values.max()),p10=float(np.percentile(values,10)),p90=float(np.percentile(values,90)),
                  red_mean_dn=float(red[valid].mean()),nir_mean_dn=float(nir[valid].mean()))
    return result


def capture(path_text):
    path=Path(path_text);meta=json.loads(path.read_text(encoding='utf-8'))
    assert meta['status']=='complete'
    assert path.parent.name==meta['captured_at'] and path.parent.parent.name==meta['light_condition']
    batch=int(meta['batch']);assert batch in (1,2)
    light=meta['light_condition'];assert light in [f'{r}-{l}' for r in 'ABCD' for l in (1,2,3)]
    timestamp=datetime.strptime(meta['captured_at'],'%Y-%m-%d_%H-%M-%S').isoformat(sep=' ')
    raw_folder=RAW/meta['source_folder']
    prompt={int(p['plant_number']):p for p in meta['prompts']}
    observations=[]
    actual_dirs={p.name for p in path.parent.glob('plant-*') if p.is_dir()}
    expected_dirs={f"plant-{int(p['plant_number']):02d}" for p in meta['plants']}
    assert actual_dirs==expected_dirs
    assert {int(p['plant_number']) for p in meta['plants']}==set(map(int,meta['plant_numbers']))
    for plant in meta['plants']:
        number=int(plant['plant_number']);assert 1<=number<=(12 if batch==1 else 21)
        folder=path.parent/f'plant-{number:02d}'
        assert Path(plant['output_directory']).resolve()==folder.resolve()
        index=ndvi(folder,plant['quality'])
        assert index['mask_pixel_count']==plant['mask_area_pixels']
        assets=[]
        for image_path in sorted(folder.glob('*.png')):
            stat=image_path.stat();channel=image_path.stem
            wavelength=int(channel[1:]) if channel.startswith('L') and channel[1:].isdigit() else None
            kind='SPECTRAL' if wavelength in BANDS else ('MASK' if channel=='mask' else ('COLOR' if channel=='Color' else ('VENDOR_INDEX' if channel in ('LNDVI','LNDRE') else 'OTHER')))
            with Image.open(image_path) as im:width,height=im.size;mode=im.mode
            raw_path=raw_folder/f"{meta['captured_at']}__{channel}.png"
            assets.append({'channel':channel,'kind':kind,'wavelength_nm':wavelength if kind=='SPECTRAL' else None,
                'path':str(image_path),'path_hash':path_hash(image_path),'size_bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,
                'sha256':index['input_sha256'].get(channel),'width':width,'height':height,'mode':mode,
                'original_path':str(raw_path) if channel!='mask' and raw_path.is_file() else None})
        band_count=sum(a['kind']=='SPECTRAL' for a in assets)
        assert band_count==16,(str(folder),band_count)
        mask=next(a for a in assets if a['kind']=='MASK')
        assert all((a['width'],a['height'])==(mask['width'],mask['height']) for a in assets if a['kind']=='SPECTRAL')
        observations.append({'plant_number':number,'directory':str(folder),'directory_hash':path_hash(folder),
            'quality':plant['quality'],'mask_source':prompt[number].get('mask_source'),'mask_area':plant['mask_area_pixels'],
            'crop_box':plant['crop_box_xyxy'],'band_count':band_count,'images':assets,'ndvi':index})
    return {'batch_no':batch,'light_code':light,'source_folder':meta['source_folder'],'source_path':str(raw_folder),
        'source_exists':raw_folder.is_dir(),'source_path_hash':path_hash(raw_folder),'capture_code':meta['captured_at'],
        'captured_at':timestamp,'metadata_path':str(path),'metadata_sha256':sha(path),'metadata':meta,'observations':observations}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    stage=BASE/'staging';stage.mkdir(parents=True,exist_ok=True)
    paths=sorted(str(p) for p in SAM.glob('*/*/_SUCCESS.json'))
    assert len(paths)>0
    counts=Counter();quality=Counter();statuses=Counter();batches=defaultdict(lambda:{'captures':0,'observations':0,'dates':set(),'plant_keys':set(),'ndvi_values':[]})
    first=[];seen=set();started=time.time()
    partial=stage/'captures.jsonl.partial'
    with partial.open('w',encoding='utf-8',newline='\n') as stream,ProcessPoolExecutor(max_workers=args.workers) as pool:
        for record in pool.map(capture,paths,chunksize=4):
            key=(record['batch_no'],record['light_code'],record['capture_code']);assert key not in seen;seen.add(key)
            stream.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
            counts['captures']+=1;batch=batches[record['batch_no']];batch['captures']+=1;batch['dates'].add(record['captured_at'][:10])
            for o in record['observations']:
                counts['observations']+=1;counts['images']+=len(o['images']);counts['band_images']+=o['band_count']
                quality[o['quality']]+=1;statuses[o['ndvi']['status']]+=1
                batch['observations']+=1;batch['plant_keys'].add((record['light_code'],o['plant_number']))
                if o['ndvi']['mean'] is not None:batch['ndvi_values'].append(o['ndvi']['mean'])
                if len(first)<3:first.append({'batch_no':record['batch_no'],'light':record['light_code'],'capture':record['capture_code'],'plant':o['plant_number'],'ndvi':o['ndvi']['mean']})
            if counts['captures']%25==0:
                write(BASE/'reports'/'preparation_status.json',{'status':'running','total_captures':len(paths),**counts,'elapsed_seconds':time.time()-started})
    target=stage/'captures.jsonl';partial.replace(target)
    by_batch={str(k):{'batch_no':k,'display_name':f'萵苣第{k}批','captures':b['captures'],'observations':b['observations'],
        'first_captured_on':min(b['dates']),'last_captured_on':max(b['dates']),'plant_numbers_recorded':len(b['plant_keys']),
        'ndvi_mean_range':[min(b['ndvi_values']),max(b['ndvi_values'])] if b['ndvi_values'] else None} for k,b in batches.items()}
    report={'status':'prepared','algorithm_version':VERSION,**counts,'by_batch':by_batch,'quality_counts':dict(quality),
        'ndvi_status_counts':dict(statuses),'snapshot_sha256':sha(target),'elapsed_seconds':time.time()-started,
        'ndvi_basis':'RAW_DN_UNCALIBRATED','ndvi_formula':'(L800-L680)/(L800+L680)',
        'aggregation':'Mean of per-pixel ratios inside mask, finite positive denominator, saturated uint16 maximum excluded.',
        'alignment':'Shared SAM crop/mask; spectral registration unverified.','source_root':str(SAM),'examples':first,
        'database_modified':False,'website_modified':False}
    write(BASE/'reports'/'preparation_report.json',report);write(BASE/'reports'/'preparation_status.json',report)
    print(json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
