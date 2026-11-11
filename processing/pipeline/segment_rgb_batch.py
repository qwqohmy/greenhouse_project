"""Resumable SAM3.1 instance proposals; identity and label joins stay unverified."""
import argparse
import contextlib
import hashlib
import inspect
import json
import os
from pathlib import Path
import time
import traceback

import cv2
import numpy as np
from PIL import Image, ImageDraw
import torch
from sam3.model_builder import build_sam3_multiplex_video_predictor

BASE = Path(__file__).resolve().parent
OUT = Path(os.environ.get('RGB_SAM_ROOT','data/rgb_sam'))
VERSION = 'sam31_rgb_roi_v4'


def save_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(100):
        try:
            os.replace(temp,path)
            return
        except PermissionError:
            if attempt==99:
                raise
            time.sleep(.02)


def roi_for(rgb):
    # Low-resolution component filtering avoids allocating full-resolution label maps.
    height,width=rgb.shape[:2]
    scale=min(1.,1200/max(width,height))
    small=cv2.resize(rgb,(round(width*scale),round(height*scale))) if scale<1 else rgb
    r,g,b=[small[:,:,i].astype(np.float32) for i in range(3)]
    vegetation=((r>45)&(g>45)&(b<.82*np.maximum(r,g))&(g>.68*r)).astype(np.uint8)
    vegetation=cv2.morphologyEx(vegetation,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats(vegetation,8)
    if n<=1:
        return (0,0,width,height),False
    minimum=max(15,int(stats[1:,cv2.CC_STAT_AREA].max()*.01))
    keep=[i for i in range(1,n) if stats[i,cv2.CC_STAT_AREA]>=minimum
          and stats[i,cv2.CC_STAT_WIDTH]>2 and stats[i,cv2.CC_STAT_HEIGHT]>2
          and stats[i,cv2.CC_STAT_AREA]/max(1,stats[i,cv2.CC_STAT_WIDTH]*stats[i,cv2.CC_STAT_HEIGHT])>.08]
    yy,xx=np.nonzero(np.isin(labels,keep))
    if not len(xx):
        return (0,0,width,height),False
    pad=32
    return (max(0,int(xx.min()/scale)-pad),max(0,int(yy.min()/scale)-pad),
            min(width,int((xx.max()+1)/scale)+pad),min(height,int((yy.max()+1)/scale)+pad)),True


def segment_one(predictor, source, target, group, camera, frame_index, work):
    stat=source.stat()
    meta=target/'metadata.json'
    if meta.exists():
        record=json.loads(meta.read_text(encoding='utf-8'))
        if record.get('algorithm')==VERSION and record.get('source_bytes')==stat.st_size and record.get('source_mtime_ns')==stat.st_mtime_ns:
            record['plant_sequence_candidate']=group.get('plant_sequence_candidate')
            record['crop_batch_candidate']=group.get('crop_batch_candidate')
            record['frame_index_in_camera']=frame_index
            save_json(meta,record)
            return record,True
    target.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as image:
        original=np.asarray(image.convert('RGB')).copy()
    height,width=original.shape[:2]
    roi,has_vegetation=roi_for(original)
    x0,y0,x1,y1=roi
    image=Image.fromarray(original[y0:y1,x0:x1])
    image.thumbnail((1600,1600))
    rgb=np.asarray(image).copy()
    frame=work/'00000.jpg'
    Image.fromarray(rgb).save(frame,quality=97)
    response=predictor.handle_request({'type':'start_session','resource_path':str(work),
                                     'offload_video_to_cpu':True,'offload_state_to_cpu':False})
    sid=response['session_id']
    try:
        proposals=[]
        with torch.inference_mode():
            for prompt in ('plant','seedling','tomato plant'):
                result=predictor.handle_request({'type':'add_prompt','session_id':sid,'frame_index':0,
                            'text':prompt,'output_prob_thresh':.25})['outputs']
                masks=result['out_binary_masks']
                if hasattr(masks,'cpu'):
                    masks=masks.cpu().numpy()
                probs=result['out_probs']
                if hasattr(probs,'cpu'):
                    probs=probs.cpu().numpy()
                for m,p in zip(np.asarray(masks),np.asarray(probs)):
                    mask=np.asarray(m,dtype=bool).squeeze()
                    if mask.shape != rgb.shape[:2] or mask.sum()<20:
                        continue
                    duplicate=any((mask&old[0]).sum()/max(1,(mask|old[0]).sum())>.90 for old in proposals)
                    if not duplicate:
                        proposals.append((mask,float(p),prompt))
                if proposals:
                    break
        proposals.sort(key=lambda item:(np.nonzero(item[0])[1].mean(),np.nonzero(item[0])[0].mean()))
        overlay=Image.fromarray(rgb)
        draw=ImageDraw.Draw(overlay)
        instances=[]
        sx=(x1-x0)/rgb.shape[1]
        sy=(y1-y0)/rgb.shape[0]
        for index,(mask,prob,prompt) in enumerate(proposals,1):
            yy,xx=np.nonzero(mask)
            left,top=max(0,int(xx.min())-12),max(0,int(yy.min())-12)
            right,bottom=min(rgb.shape[1],int(xx.max())+13),min(rgb.shape[0],int(yy.max())+13)
            box=[max(0,int(x0+left*sx)),max(0,int(y0+top*sy)),min(width,int(np.ceil(x0+right*sx))),min(height,int(np.ceil(y0+bottom*sy)))]
            sub=target/f'instance-{index:02d}'
            sub.mkdir(exist_ok=True)
            Image.fromarray(rgb[top:bottom,left:right]).save(sub/'rgb.png')
            cropped_mask=mask[top:bottom,left:right]
            Image.fromarray(cropped_mask.astype(np.uint8)*255).save(sub/'mask.png')
            black=rgb[top:bottom,left:right].copy()
            black[~cropped_mask]=0
            Image.fromarray(black).save(sub/'segmented.png')
            source_edge=bool((box[0]==0 and mask[:,0].any()) or (box[1]==0 and mask[0].any())
                             or (box[2]==width and mask[:,-1].any()) or (box[3]==height and mask[-1].any()))
            instances.append({'instance_local_id':index,'plant_id':None,'prompt':prompt,'probability':prob,
                              'source_bbox_xyxy':box,'working_bbox_xyxy':[left,top,right,bottom],
                              'mask_pixels':int(mask.sum()),'source_edge_truncated_candidate':source_edge,
                              'physical_identity_verified':False,'train_eligible':False,'output_directory':str(sub)})
            draw.rectangle((left,top,right-1,bottom-1),outline=(255,80,80),width=3)
            draw.text((left,top),str(index),fill='white',stroke_width=1,stroke_fill='black')
        overlap=[]
        for i in range(len(proposals)):
            for j in range(i+1,len(proposals)):
                a,b=proposals[i][0],proposals[j][0]
                ratio=float((a&b).sum()/max(1,min(a.sum(),b.sum())))
                if ratio>.25:
                    overlap.append([i+1,j+1,ratio])
        overlay.thumbnail((1000,1000))
        overlay.save(target/'overview.jpg',quality=88)
        record={'algorithm':VERSION,'source':str(source),'source_bytes':stat.st_size,'source_mtime_ns':stat.st_mtime_ns,
                'capture_id':group['capture_id'],'dataset_id':group['dataset_id'],'camera':camera,
                'frame_index_in_camera':frame_index,'source_frame_name':source.stem,'source_size_wh':[width,height],
                'source_roi_xyxy':list(roi),'working_size_wh':[rgb.shape[1],rgb.shape[0]],
                'working_to_source_scale_xy':[sx,sy],'instances':instances,'overlapping_masks':overlap,
                'has_vegetation_candidate':has_vegetation,'status':'NO_DETECTION_REVIEW' if not instances else 'INSTANCE_CANDIDATES_REVIEW',
                'physical_identity_verified':False,'match_status':group['match_status']}
        record['plant_sequence_candidate']=group.get('plant_sequence_candidate')
        record['crop_batch_candidate']=group.get('crop_batch_candidate')
        record['crop']=group.get('crop')
        record['crop_identity_source']=group.get('crop_identity_source')
        save_json(meta,record)
        return record,False
    finally:
        predictor.handle_request({'type':'close_session','session_id':sid})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--max-images',type=int)
    parser.add_argument('--all-frames',action='store_true')
    parser.add_argument('--shard-count',type=int,default=1)
    parser.add_argument('--shard-index',type=int,default=0)
    parser.add_argument('--run-id',default='')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--capture-set',choices=('all','tomato_confirmed'),default='all')
    args=parser.parse_args()
    if args.shard_count<1 or not 0<=args.shard_index<args.shard_count:
        parser.error('Invalid shard index/count')
    if args.shard_count>1 and (not args.run_id or not args.run_id.replace('_','').isalnum()):
        parser.error('Multiple shards require an alphanumeric run ID')
    captures=json.loads((BASE/'capture_catalog.json').read_text(encoding='utf-8'))
    policy=json.loads((BASE/'rgb_processing_policy.json').read_text(encoding='utf-8'))
    held=set(policy['hold_capture_ids'])
    captures=[g for g in captures if g['capture_id'] not in held]
    confirmed_tomato=set(policy.get('confirmed_tomato_capture_ids',[]))
    for group in captures:
        if group['capture_id'] in confirmed_tomato:
            group.update(crop='tomato',dataset_id='tomato_rgb_user_confirmed_202610',
                         crop_identity_source=policy['tomato_confirmation_source'],crop_batch_candidate='tomato_run2')
    if args.capture_set=='tomato_confirmed':
        captures=[group for group in captures if group['capture_id'] in confirmed_tomato]
    daily_counts={}
    for g in captures:
        if g['dataset_id']=='lettuce_new_202609':
            day=g['capture_id'][:10]
            daily_counts[day]=daily_counts.get(day,0)+1
    for g in captures:
        if g['dataset_id']=='lettuce_new_202609' and daily_counts[g['capture_id'][:10]]!=4:
            g['dataset_id']='mixed_new_source_species_review'
            g['crop']='unknown'
    ordered={}
    for g in captures:
        if g['dataset_id']=='lettuce_new_202609':
            day=g['capture_id'][:10]
            ordered.setdefault(day,[]).append(g)
    for values in ordered.values():
        for index,g in enumerate(sorted(values,key=lambda x:x['capture_id']),1):
            g['plant_sequence_candidate']=index
            g['crop_batch_candidate']='lettuce_run3'
    for g in captures:
        if g['dataset_id']=='lettuce_legacy_202606_08':
            g['crop_batch_candidate']='lettuce_run1' if g['capture_id']<'2026-07-01' else 'lettuce_run2'
    jobs=[]
    for group in captures:
        for camera in sorted(group['camera_counts']):
            all_names=sorted(Path(group['folder']).glob('CAM'+camera+'_*'))
            positions={p:i+1 for i,p in enumerate(all_names)}
            paths=all_names if args.all_frames else [Path(p) for p in group['selected_images'][camera]]
            for index,source in enumerate(paths,1):
                if source.suffix.lower() in ('.jpg','.jpeg','.png'):
                    actual_index=positions[source]
                    jobs.append((group,camera,actual_index,source))
    if args.max_images:
        # Spread the smoke test over early/late and single/multi-plant captures.
        indices=np.linspace(0,len(jobs)-1,min(args.max_images,len(jobs)),dtype=int)
        jobs=[jobs[i] for i in indices]
    total_jobs=len(jobs)
    jobs=jobs[args.shard_index::args.shard_count]
    suffix=f'{args.run_id}_shard_{args.shard_index}' if args.shard_count>1 else ('smoke' if args.max_images else 'batch')
    if args.dry_run:
        print(json.dumps({'total_jobs':total_jobs,'jobs':[str(item[3]) for item in jobs],
                          'held_capture_groups':len(held),'shard_count':args.shard_count,'shard_index':args.shard_index}))
        return
    OUT.mkdir(parents=True,exist_ok=True)
    work=BASE/('sam_rgb_work_'+suffix)
    work.mkdir(exist_ok=True)
    state={'status':'loading','algorithm':VERSION,'all_frames':args.all_frames,'total_images':len(jobs),
           'global_total_images':total_jobs,'shard_count':args.shard_count,'shard_index':args.shard_index,'run_id':args.run_id,
           'held_capture_groups':len(held),'processed_capture_groups':len(captures),
           'done':0,'reused':0,'instances':0,'no_detection':0,'errors':0,'started_at':time.strftime('%Y-%m-%d %H:%M:%S')}
    status_path=BASE/('segmentation_'+suffix+'_status.json')
    save_json(status_path,state)
    with (BASE/('sam_model_load_'+suffix+'.log')).open('w',encoding='utf-8') as log, contextlib.redirect_stdout(log):
        predictor=build_sam3_multiplex_video_predictor(checkpoint_path='D:/user_chao/greenhouse/plant_seg/models/sam3.1/sam3.1_multiplex.pt',use_fa3=False,compile=False,warm_up=False)
    init=predictor.model.init_state
    accepted=set(inspect.signature(init).parameters)
    predictor.model.init_state=lambda **kw:init(**{k:v for k,v in kw.items() if k in accepted})
    state['status']='running'
    with (BASE/('segmentation_'+suffix+'_records.jsonl')).open('a',encoding='utf-8') as ledger:
        for group,camera,index,source in jobs:
            target=OUT/group['dataset_id']/group['capture_id']/('CAM'+camera)/source.stem
            try:
                record,reused=segment_one(predictor,source,target,group,camera,index,work)
                state['reused']+=int(reused)
                state['instances']+=len(record['instances'])
                state['no_detection']+=int(not record['instances'])
                ledger.write(json.dumps({'source':str(source),'metadata':str(target/'metadata.json'),'status':record['status'],'instances':len(record['instances'])})+'\n')
                ledger.flush()
            except Exception:
                state['errors']+=1
                save_json(target/'error.json',{'source':str(source),'error':traceback.format_exc()})
            state['done']+=1
            state['current_source']=str(source)
            state['updated_at']=time.strftime('%Y-%m-%d %H:%M:%S')
            save_json(status_path,state)
            if state['done']%24==0:
                print(json.dumps(state),flush=True)
    state['status']='complete_with_review'
    save_json(status_path,state)
    print(json.dumps(state),flush=True)


if __name__=='__main__':
    main()
