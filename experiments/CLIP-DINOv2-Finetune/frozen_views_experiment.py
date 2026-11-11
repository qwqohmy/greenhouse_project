"""Frozen pretrained visual features, fold-local regressors and masked selectors.

Never updates CLIP/DINOv2, writes the DB or creates depth/point-cloud outputs.
"""
import hashlib
import json
import random
from pathlib import Path
import numpy as np
import torch
from torch import nn
from sklearn.decomposition import PCA
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score
from threadpoolctl import threadpool_limits
from train import BASE, ROOT, Fusion, digest, load_inputs, write_json

PAIRED = BASE/'outputs'/'sam_comparison_20261111'
OUT = BASE/'outputs'/'frozen_views_20261111'
SEEDS = 5
EPOCHS = 800


def progress(phase, **kwargs):
    write_json(OUT/'status.json', {'status':'running','phase':phase,**kwargs})
    print(json.dumps({'phase':phase,**kwargs}),flush=True)


def prepare():
    import sys
    sys.path.insert(0,str(ROOT/'database'))
    from database import connect
    data=json.loads((PAIRED/'paired_manifest.private.json').read_text(encoding='utf-8'))
    inventory=json.loads((PAIRED/'sam_inventory.json').read_text(encoding='utf-8'))
    by_capture={r['capture_id']:r for r in data['samples']}
    db=connect(readonly=True)
    rows=[]
    try:
        for item in inventory['rows']:
            row=by_capture[item['capture_id']]
            selected={v['original'].casefold() for v in row['views']}
            with db.cursor() as cur:
                cur.execute('SELECT a.file_path FROM p3d_user_sample_images l JOIN p3d_images i ON i.id=l.image_id JOIN p3d_assets a ON a.id=i.asset_id WHERE l.sample_id=%s',(row['sample_id'],))
                allowed={p.casefold() for p, in cur.fetchall()}
            views=[]
            for frame in item['frames']:
                if frame['valid_instances'] != 1: continue
                metadata=Path(frame['metadata'])
                meta=json.loads(metadata.read_text(encoding='utf-8'))
                source=Path(frame['source']);stat=source.stat()
                assert str(source).casefold() in allowed
                assert stat.st_size==meta['source_bytes'] and stat.st_mtime_ns==meta['source_mtime_ns']
                folder=Path(meta['instances'][0]['output_directory'])
                paths={'original':str(source),'crop':str(folder/'rgb.png'),'sam':str(folder/'segmented.png')}
                views.append({'camera':frame['camera'],'phase_bin':min(5,int((meta['frame_index_in_camera']-1)*6/60)),
                              'frame_index':meta['frame_index_in_camera'],'selected_553':str(source).casefold() in selected,
                              **paths,'sha256':{k:digest(p) for k,p in paths.items()}})
            assert len(views)>0 and len({v['original'] for v in views})==len(views)
            assert sum(v['selected_553'] for v in views)==len(selected)
            for source in row['sources'].values():
                if source['trial_eligible']: assert digest(source['path'])==source['sha256']
            rows.append({**row,'views':views})
    finally: db.close()
    data['samples']=rows
    data['all_available_sam_frames']=sum(len(r['views']) for r in rows)
    write_json(OUT/'manifest.private.json',data)
    return data


def param_hash(module):
    value=hashlib.sha256()
    for name,param in module.named_parameters():
        value.update(name.encode());value.update(param.detach().cpu().numpy().tobytes())
    return value.hexdigest()


def extract(data):
    torch.set_num_threads(4)
    assert torch.cuda.is_available()
    model=Fusion().cuda().eval()
    for p in model.parameters(): p.requires_grad_(False)
    before={k:param_hash(getattr(model,k)) for k in ('clip','dino')}
    records=[]
    for index,row in enumerate(data['samples']):
        variants={}
        for variant in ('original','sam','crop'):
            # Crop control is needed only for the previously matched 553 views.
            indices=[i for i,v in enumerate(row['views']) if variant!='crop' or v['selected_553']]
            views=[row['views'][i] for i in indices]
            signature=hashlib.sha256(json.dumps({'paths':[(v[variant],v['sha256'][variant]) for v in views],
                'preprocessing':'224-letterbox-v1','weights':before},sort_keys=True).encode()).hexdigest()
            cache=OUT/'features'/f'{index:02d}_{variant}.npz'
            if cache.is_file():
                with np.load(cache) as saved:
                    assert saved['signature'].item()==signature
                    cf=saved['clip'].copy();df=saved['dino'].copy()
            else:
                clip_chunks=[];dino_chunks=[]
                for start in range(0,len(views),24):
                    batch=[{**v,'rgb_crop':v[variant]} for v in views[start:start+24]]
                    clip_rgb,dino_rgb,_=load_inputs([{'views':batch}])[0]
                    with torch.inference_mode():
                        clip_chunks.append(model.clip(clip_rgb.cuda()).float().cpu().numpy())
                        dino_chunks.append(torch.nn.functional.normalize(model.dino(dino_rgb.cuda()).float(),dim=-1).cpu().numpy())
                cf=np.concatenate(clip_chunks);df=np.concatenate(dino_chunks)
                cache.parent.mkdir(parents=True,exist_ok=True)
                np.savez_compressed(cache,clip=cf,dino=df,indices=np.asarray(indices),signature=np.asarray(signature))
            assert np.isfinite(cf).all() and np.isfinite(df).all()
            variants[variant]={'clip':cf,'dino':df,'indices':indices}
            progress('extract',sample=index+1,samples=len(data['samples']),variant=variant,views=len(views))
        records.append(variants)
    after={k:param_hash(getattr(model,k)) for k in ('clip','dino')}
    assert before==after and not any(p.requires_grad for p in model.parameters())
    write_json(OUT/'frozen_backbone_verification.json',{'passed':True,'before':before,'after':after,'optimizer_updates':0})
    del model;torch.cuda.empty_cache()
    return records


def ridge(train_x, test_x, y):
    mean=y.mean(0);scale=y.std(0);scale[scale==0]=1
    model=Pipeline([('scale',StandardScaler()),('pca',PCA(n_components=min(5,len(y)-1),svd_solver='full')),
                    ('ridge',RidgeCV(alphas=np.logspace(-3,3,13),alpha_per_target=True))])
    model.fit(train_x,(y-mean)/scale)
    return model.predict(test_x)*scale+mean


class Selector(nn.Module):
    def __init__(self,k,targets):
        super().__init__()
        self.camera=nn.Embedding(4,3);self.role=nn.Embedding(2,2);self.angle=nn.Embedding(6,3)
        self.score=nn.Sequential(nn.Linear(k+8,12),nn.Tanh(),nn.Linear(12,1))
        self.head=nn.Linear(k*3+2,targets)

    def forward(self,x,camera,role,angle,valid,drop=None):
        metadata=torch.cat([self.camera(camera),self.role(role),self.angle(angle)],-1)
        usable=valid if drop is None else valid & drop
        score=self.score(torch.cat([x,metadata],-1)).squeeze(-1).masked_fill(~usable,-1e4)
        weights=torch.softmax(score,1)
        selected=(weights[...,None]*x).sum(1)
        pools=[];presence=[]
        for category in (0,1):
            mask=valid & (role==category)
            pools.append((x*mask[...,None]).sum(1)/mask.sum(1,keepdim=True).clamp_min(1))
            presence.append(mask.any(1).float()[:,None])
        return self.head(torch.cat([selected,*pools,*presence],-1))


def learned_prediction(features, metadata, y, train, test):
    k=min(12,len(train)-1,features[0].shape[1])
    pca=PCA(n_components=k,whiten=True,random_state=0)
    pca.fit(np.concatenate([features[i] for i in train]))
    count=max(len(f) for f in features)
    shape=(len(features),count)
    x=np.zeros((*shape,k),np.float32);valid=np.zeros(shape,bool)
    camera=np.zeros(shape,np.int64);role=np.zeros(shape,np.int64);angle=np.zeros(shape,np.int64)
    for i,f in enumerate(features):
        n=len(f);x[i,:n]=pca.transform(f);valid[i,:n]=True
        camera[i,:n]=[int(v['camera'])-1 for v in metadata[i]]
        role[i,:n]=(camera[i,:n]>=2).astype(np.int64)
        angle[i,:n]=[v['phase_bin'] for v in metadata[i]]
    tensors=[torch.from_numpy(a) for a in (x,camera,role,angle,valid)]
    train_tensors=[t[train] for t in tensors];test_tensors=[t[test] for t in tensors]
    mean=y[train].mean(0);scale=y[train].std(0);scale[scale==0]=1
    target=torch.tensor((y[train]-mean)/scale,dtype=torch.float32)
    predictions=[]
    for seed in range(SEEDS):
        random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
        model=Selector(k,y.shape[1]);optimizer=torch.optim.AdamW(model.parameters(),lr=.01,weight_decay=.05)
        for epoch in range(EPOCHS):
            generator=torch.Generator().manual_seed(seed*EPOCHS+epoch)
            keep=torch.rand(train_tensors[4].shape,generator=generator)>.20
            keep[:,0]=True
            noise=torch.randn(train_tensors[0].shape,generator=generator)*.015
            pred=model(train_tensors[0]+noise,*train_tensors[1:],drop=keep)
            loss=nn.functional.smooth_l1_loss(pred,target)
            assert torch.isfinite(loss)
            optimizer.zero_grad(set_to_none=True);loss.backward();optimizer.step()
        model.eval()
        with torch.inference_mode():pred=model(*test_tensors).numpy()*scale+mean
        predictions.append(pred)
    return np.mean(predictions,axis=0)


def metrics(y,pred,baseline):
    result=[]
    for i in range(y.shape[1]):
        mae=float(np.mean(np.abs(y[:,i]-pred[:,i])))
        base=float(np.mean(np.abs(y[:,i]-baseline[:,i])))
        result.append({'mae':mae,'baseline_mae':base,'mae_ratio':mae/base if base else None,
                       'r2':float(r2_score(y[:,i],pred[:,i]))})
    return {'mean_target_mae_ratio':float(np.mean([r['mae_ratio'] for r in result if r['mae_ratio'] is not None])),
            'mean_r2':float(np.mean([r['r2'] for r in result])), 'better_than_baseline':sum(r['mae']<r['baseline_mae'] for r in result),
            'targets':result}


def evaluate(data,records):
    torch.set_num_threads(1)
    configurations=[('selected553',v) for v in ('original','crop','sam')]+[('all_sam_detected',v) for v in ('original','sam')]
    results=[]
    for scope,variant in configurations:
        for label in ('proxy','native'):
            rows=[];clip=[];dino=[];metadata=[]
            for i,row in enumerate(data['samples']):
                if not row['sources'].get(label,{}).get('trial_eligible'):continue
                record=records[i][variant]
                take=[j for j,idx in enumerate(record['indices']) if scope!='selected553' or row['views'][idx]['selected_553']]
                rows.append(row);clip.append(record['clip'][take]);dino.append(record['dino'][take])
                metadata.append([row['views'][record['indices'][j]] for j in take])
            targets=data['target_definitions'][label]
            y=np.asarray([[r['sources'][label]['numeric_values'][t] for t in targets] for r in rows],np.float64)
            cp=np.zeros_like(y);cn=np.zeros_like(y);dp=np.zeros_like(y);sp=np.zeros_like(y);baseline=np.zeros_like(y)
            cmean=np.stack([v.mean(0) for v in clip])
            cnmean=np.stack([(v/np.maximum(np.linalg.norm(v,axis=1,keepdims=True),1e-12)).mean(0) for v in clip])
            dmean=np.stack([v.mean(0) for v in dino])
            for group in sorted({r['split_group'] for r in rows}):
                training=[i for i,r in enumerate(rows) if r['split_group']!=group]
                testing=[i for i,r in enumerate(rows) if r['split_group']==group]
                assert not {rows[i]['split_group'] for i in training} & {rows[i]['split_group'] for i in testing}
                cp[testing]=ridge(cmean[training],cmean[testing],y[training])
                cn[testing]=ridge(cnmean[training],cnmean[testing],y[training])
                dp[testing]=ridge(dmean[training],dmean[testing],y[training])
                sp[testing]=learned_prediction(dino,metadata,y,training,testing)
                baseline[testing]=y[training].mean(0)
                progress('evaluate',scope=scope,variant=variant,labels=label,held_out_group=group)
            predictions={'clip_mean_ridge':cp,'clip_l2mean_ridge':cn,'dino_mean_ridge':dp,
                         'dino_selector':sp,'clip_dino_mean_fusion':(cp+dp)*.5,'clip_dino_selector_fusion':(cp+sp)*.5}
            summary={name:metrics(y,p,baseline) for name,p in predictions.items()}
            ids=[r['capture_id'] for r in rows]
            # Ensure the matched 553-frame comparison really uses the previous labels/folds.
            if scope=='selected553':
                previous=json.loads((PAIRED/f'{label}_{variant}_cv'/'result.json').read_text(encoding='utf-8'))
                lookup={p['capture_id']:p for p in previous['predictions']}
                for i,row in enumerate(rows):
                    assert row['split_group']==lookup[ids[i]]['held_out_group']
                    np.testing.assert_allclose(y[i],lookup[ids[i]]['actual'],rtol=1e-6)
                    np.testing.assert_allclose(baseline[i],lookup[ids[i]]['train_mean_baseline'],rtol=1e-6)
            result={'scope':scope,'variant':variant,'labels':label,'samples':len(rows),'frames':sum(map(len,clip)),
                    'target_names':targets,'metrics':summary,
                    'predictions':{'capture_ids':ids,'actual':y.tolist(),'baseline':baseline.tolist(),**{k:v.tolist() for k,v in predictions.items()}}}
            write_json(OUT/f'{scope}_{variant}_{label}.private.json',result)
            results.append({k:v for k,v in result.items() if k!='predictions'})
            write_json(OUT/'partial_summary.json',results)
    report={'frozen_backbones':True,'backbone_updates':0,'regressors_and_selector_trained':True,'selector_epochs':EPOCHS,'selector_seeds':SEEDS,
            'samples_union':len(data['samples']),'raw_image_count':len(data['samples'])*4*60,
            'all_sam_detected_views':data['all_available_sam_frames'],'previous_selected_views':553,
            'validation':'Leave one entire crop batch out; PCA, feature/target scaling and selector fit on training batches only.',
            'preprocessing':'224 letterbox and CLIP/ImageNet normalization; unlike historical official center-crop transforms.',
            'selector_adaptation':'Variable-view masks; same 4 camera/2 role/6 acquisition-phase embeddings, with explicit missing-role presence. Phase bins derive from frame order, not calibrated geometry.',
            'near_time_candidates_included':True,'database_modified':False,'results':results}
    write_json(OUT/'summary.json',report)
    lines=['# 不微調骨幹：31組單株多視角實驗','',
           f"完整原圖7,440張；全部可用SAM視角{data['all_available_sam_frames']}張。上一輪每相機最多6張的553張版本另作配對對照。",'',
           'CLIP與DINOv2全部參數凍結、推論前後參數雜湊一致；仍以訓練折的CSV建立PCA／Ridge與小型視角選擇器。不是零樣本直接輸出CSV。', '',
           '誤差比越低越好，1代表猜訓練集平均值；驗證按整個植物批次留出。原廠11組與代理值30組重疊，不能加成41組。', '',
           '| 視角範圍 | 圖片 | 標籤 | 組數 | CLIP＋Ridge | DINO＋Ridge | 各50%平均融合 | CLIP＋DINO選擇器融合 |',
           '|---|---|---|---:|---:|---:|---:|---:|']
    for r in results:
        m=r['metrics']
        lines.append(f"| {r['scope']} | {r['variant']} | {r['labels']} | {r['samples']} | {m['clip_mean_ridge']['mean_target_mae_ratio']:.4f} | {m['dino_mean_ridge']['mean_target_mae_ratio']:.4f} | {m['clip_dino_mean_fusion']['mean_target_mae_ratio']:.4f} | {m['clip_dino_selector_fusion']['mean_target_mae_ratio']:.4f} |")
    lines+=['','注意：全部可用SAM視角指有既有單實例遮罩的原圖影格，不包含SAM未檢出影格；無黑圖、複製視角或補造影像。', '',
            '保留兩個近時間候選與僅俯視／單張場次。遮罩品質、實體盆號、PLY方向與物理單位仍有先前限制。', '',
            '此輪骨幹固定，但前處理是與新微調對照相同的letterbox，與歷史九組的官方center-crop流程不同；視角選擇器為缺視角做了遮罩／缺少俯側視註記適配。不能把這些分數直接與0.5837比較。', '',
            '有監督的小型回歸／選擇器不等於骨幹Fine-tune。相同553張版本可與上一輪微調對照，CLIP L2特徵版本亦保留在JSON；兩者回歸器／損失不同，因此比較的是整套方法。', '',
            '這是方法對照，沒有新增RGB-D重建、深度圖、資料庫寫入或公開頁面更新。']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write_json(OUT/'status.json',{'status':'completed','backbone_updates':0,'experiments':len(results),'database_modified':False})


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    progress('prepare')
    try:
        data=prepare();progress('prepared',samples=len(data['samples']),all_sam_views=data['all_available_sam_frames'])
        features=extract(data)
        with threadpool_limits(limits=1):evaluate(data,features)
    except Exception:
        import traceback
        write_json(OUT/'status.json',{'status':'failed','error':traceback.format_exc()});raise


if __name__=='__main__':main()
