"""Partial backbone fine-tuning for screened single-plant, multi-view proxy targets.

This is an exploratory two-proxy adapter, not a calibrated seven-trait model.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from PIL import Image,ImageOps

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
TARGETS=['pGH_proxy','pMW_proxy']


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(100):
        try:
            os.replace(temp,path);return
        except PermissionError:
            time.sleep(.02)
    raise RuntimeError('Could not atomically write '+str(path))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight(path):
    document=json.loads(path.read_text(encoding='utf-8'))
    assert document['target_names']==TARGETS
    assert document['formal_training_gate_bypassed'] is False
    rows=[r for r in document['rows'] if r['proxy_training_candidate']]
    assert len(rows)>=3
    assert len({r['capture_id'] for r in rows})==len(rows)
    assert len({r['target_csv_path'].casefold() for r in rows})==len(rows)
    keys=[r['sample_key_candidate'] for r in rows]
    assert all(keys) and len(set(keys))==len(rows),'Repeated crop/batch/light/plant/day candidate sample'
    seen_paths=set();seen_digests=set()
    for row in rows:
        assert row['delta_seconds']==0,'Approximate-time candidates stay outside the main set'
        assert row['formal_train_eligible'] is False
        assert digest(row['target_csv_path'])==row['target_csv_sha256']
        with Path(row['target_csv_path']).open(encoding='utf-8-sig',newline='') as stream:
            csv_rows=list(csv.DictReader(stream))
        assert len(csv_rows)==1,'A CSV must contain exactly one plant observation'
        for name in TARGETS:
            assert np.isclose(float(csv_rows[0][name]),row['values'][name])
            assert np.isfinite(row['values'][name]) and row['values'][name]>0
        assert len(row['views'])==12
        assert [v['camera'] for v in row['views']].count('2')==6
        assert [v['camera'] for v in row['views']].count('4')==6
        for view in row['views']:
            key=view['rgb_crop'].casefold()
            assert key not in seen_paths,'Image path shared across observations'
            assert view['sha256'] not in seen_digests,'Image content shared across observations'
            assert digest(view['rgb_crop'])==view['sha256']
            seen_paths.add(key);seen_digests.add(view['sha256'])
    # Re-check active database links so an old manifest cannot silently use rejected pairs.
    sys.path.insert(0,str(ROOT/'database'))
    from database import connect
    connection=connect(readonly=True)
    try:
        with connection.cursor() as cur:
            for row in rows:
                cur.execute('SELECT o.averaged_across_plants,a.file_path FROM p3d_observations o JOIN p3d_csv_exports e ON e.id=o.target_csv_export_id JOIN p3d_assets a ON a.id=e.csv_asset_id WHERE o.id=%s',(row['db_observation_id'],))
                averaged,csv_path=cur.fetchone()
                assert not averaged and csv_path.casefold()==row['target_csv_path'].casefold()
                cur.execute("SELECT a.file_path FROM p3d_observation_images l JOIN p3d_images i ON i.id=l.image_id JOIN p3d_assets a ON a.id=i.asset_id WHERE l.observation_id=%s AND l.link_status IN ('LINKED_SCENE','VERIFIED')",(row['db_observation_id'],))
                active={p.casefold() for p, in cur.fetchall()}
                assert all(v['rgb_crop'].casefold() in active for v in row['views']),'Database link rejected after manifest export'
    finally:
        connection.close()
    groups=sorted({r['split_group'] for r in rows})
    assert len(groups)>=2,'Need at least two conservative groups for held-out evaluation'
    report={'samples':len(rows),'images':len(seen_paths),'target_names':TARGETS,
            'sample_counting_unit':document['sample_counting_unit'],
            'sample_identity_status':document['sample_identity_status'],
            'group_sizes':{g:sum(r['split_group']==g for r in rows) for g in groups},
            'manifest_sha256':digest(path),'formal_calibrated_training_samples':0,
            'approximate_time_samples_excluded':sum(not r['proxy_training_candidate'] and r['delta_seconds']!=0 for r in document['rows']),
            'other_target_samples_held':sum(not r['proxy_training_candidate'] and r['delta_seconds']==0 for r in document['rows']),
            'note':'Prepared exploratory proxy set; source units/up-axis and metric-trait calibration remain unverified.'}
    return rows,report


def load_inputs(rows):
    """Letterbox preserves the entire crop; no random scale/center cropping."""
    result=[]
    means=((.48145466,.4578275,.40821073),(.485,.456,.406))
    stds=((.26862954,.26130258,.27577711),(.229,.224,.225))
    for row in rows:
        images=[]
        for view in row['views']:
            with Image.open(view['rgb_crop']) as source:
                im=ImageOps.contain(source.convert('RGB'),(224,224),method=Image.Resampling.BICUBIC)
                canvas=Image.new('RGB',(224,224),'black')
                canvas.paste(im,((224-im.width)//2,(224-im.height)//2))
                images.append(torch.from_numpy(np.asarray(canvas).copy()).permute(2,0,1).float()/255)
        raw=torch.stack(images)
        transformed=[(raw-torch.tensor(m)[None,:,None,None])/torch.tensor(s)[None,:,None,None] for m,s in zip(means,stds)]
        result.append((*transformed,torch.tensor([[1.,0.] if v['camera'] in ('1','2') else [0.,1.] for v in row['views']])))
    return result


class Fusion(nn.Module):
    def __init__(self,output_dim=2):
        super().__init__()
        import clip
        whole,_=clip.load('ViT-B/32',device='cpu',jit=False,download_root=os.environ.get('CLIP_CACHE'))
        self.clip=whole.visual.float()
        del whole
        if os.environ.get('DINO_REPO'):
            self.dino=torch.hub.load(os.environ['DINO_REPO'],'dinov2_vits14',source='local',pretrained=False)
            self.dino.load_state_dict(torch.load(os.environ['DINO_WEIGHTS'],map_location='cpu',weights_only=True),strict=True)
        else:
            self.dino=torch.hub.load('facebookresearch/dinov2','dinov2_vits14',pretrained=True,trust_repo=True)
        for param in self.parameters():
            param.requires_grad_(False)
        for module in (self.clip.transformer.resblocks[-1],self.clip.ln_post,self.dino.blocks[-1],self.dino.norm):
            for param in module.parameters():
                param.requires_grad_(True)
        self.clip.proj.requires_grad_(True)
        self.clip_head=nn.Linear(512,output_dim)
        self.selector=nn.Sequential(nn.Linear(386,64),nn.Tanh(),nn.Linear(64,1))
        self.dino_head=nn.Linear(384,output_dim)

    def train(self,mode=True):
        super().train(mode)
        # Gradients still flow through the last blocks; deterministic backbone behavior
        # avoids stochastic depth in the mostly-frozen encoders on this tiny dataset.
        self.clip.eval();self.dino.eval()
        return self

    def forward(self,clip_rgb,dino_rgb,cameras):
        clip_features=F.normalize(self.clip(clip_rgb).float(),dim=-1)
        dino_features=F.normalize(self.dino(dino_rgb).float(),dim=-1)
        weights=self.selector(torch.cat([dino_features,cameras],dim=1)).softmax(dim=0)
        cp=self.clip_head(clip_features.mean(dim=0))
        dp=self.dino_head((weights*dino_features).sum(dim=0))
        return .5*cp+.5*dp,cp,dp

    def adapter_state(self):
        return {name:param.detach().cpu().clone() for name,param in self.named_parameters() if param.requires_grad}


def train_one(rows,inputs,indices,epochs,seed,out,report,target_names=None,label_schema='PLY_PROXY'):
    targets=target_names or TARGETS
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
    model=Fusion(output_dim=len(targets)).cuda()
    y=np.asarray([[r['values'][name] for name in targets] for r in rows],np.float32)
    mean=y[indices].mean(axis=0);scale=np.maximum(y[indices].std(axis=0),1e-3)
    normalized=torch.tensor((y-mean)/scale,device='cuda')
    named=dict(model.named_parameters())
    probes=['clip.transformer.resblocks.11.attn.in_proj_weight','dino.blocks.11.attn.qkv.weight']
    before={name:named[name].detach().cpu().clone() for name in probes}
    frozen_probe=model.clip.conv1.weight.detach().cpu().clone()
    heads=[];backbones=[]
    for name,param in named.items():
        if param.requires_grad:
            (backbones if name.startswith(('clip.','dino.')) else heads).append(param)
    optimizer=torch.optim.AdamW([{'params':backbones,'lr':1e-6},{'params':heads,'lr':1e-3}],weight_decay=.01)
    log=[];start=time.time()
    for epoch in range(epochs):
        model.train();order=list(indices);random.shuffle(order);losses=[]
        for index in order:
            data=[t.cuda() for t in inputs[index]]
            optimizer.zero_grad(set_to_none=True)
            ensemble,cp,dp=model(*data)
            target=normalized[index]
            loss=F.smooth_l1_loss(ensemble,target)+.5*(F.smooth_l1_loss(cp,target)+F.smooth_l1_loss(dp,target))
            if not torch.isfinite(loss):
                raise RuntimeError('Non-finite loss')
            loss.backward()
            grad=torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.)
            if not torch.isfinite(grad):
                raise RuntimeError('Non-finite gradients')
            optimizer.step();losses.append(float(loss.detach()))
        log.append({'epoch':epoch+1,'training_loss':float(np.mean(losses))})
        write_json(out/'progress.json',{'status':'running','epoch':epoch+1,'epochs':epochs,'training_scenes':len(indices),'last_loss':log[-1]['training_loss'],'elapsed_seconds':time.time()-start})
        print(f"epoch={epoch+1}/{epochs} training_scenes={len(indices)} loss={log[-1]['training_loss']:.6f}",flush=True)
    changes={name:float((named[name].detach().cpu()-before[name]).abs().max()) for name in probes}
    assert all(value>0 for value in changes.values()),'Backbone parameters did not update'
    assert torch.equal(frozen_probe,model.clip.conv1.weight.detach().cpu()),'Frozen backbone changed'
    checkpoint={'adapter_state':model.adapter_state(),'target_mean':torch.tensor(mean),'target_scale':torch.tensor(scale),
                'target_names':targets,'label_schema':label_schema,'coordinate_unit':'VENDOR_UNIT_UNVERIFIED' if label_schema=='VENDOR_NATIVE' else 'UNVERIFIED','formal_calibrated_model':False,
                'manifest_sha256':report['manifest_sha256'],'training_capture_ids':[rows[i]['capture_id'] for i in indices],
                'training_groups':sorted({rows[i]['split_group'] for i in indices}),'seed':seed,'epochs':epochs,'preprocessing':'224-letterbox-clip-and-imagenet-normalizations','fixed_ensemble_weight':.5}
    out.mkdir(parents=True,exist_ok=True);torch.save(checkpoint,out/'adapter.pt')
    write_json(out/'training_log.json',{'epochs':log,'backbone_max_abs_updates':changes,'frozen_conv_unchanged':True,'elapsed_seconds':time.time()-start,'data_report':report})
    return model,mean,scale,y,changes


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',type=Path,default=BASE/'prepared_manifest.json')
    ap.add_argument('--mode',choices=['check','smoke','cv','fit'],default='check')
    ap.add_argument('--allow-proxy-coordinate-targets',action='store_true')
    ap.add_argument('--epochs',type=int,default=20);ap.add_argument('--seed',type=int,default=20261111)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    rows,report=preflight(args.manifest)
    out=args.output or BASE/'outputs'/args.mode
    write_json(out/'preflight.json',report);print(json.dumps(report),flush=True)
    if args.mode=='check':
        return
    if not args.allow_proxy_coordinate_targets:
        raise SystemExit('Targets are UNVERIFIED coordinate proxies. Explicit --allow-proxy-coordinate-targets is required for exploratory work; this does not open formal DB admission gates.')
    assert args.epochs>0
    if not torch.cuda.is_available():
        raise SystemExit('CUDA GPU required; do not silently run this training on CPU')
    torch.set_num_threads(4);inputs=load_inputs(rows)
    if args.mode=='smoke':
        model,mean,scale,y,changes=train_one(rows,inputs,[0,len(rows)-1],1,args.seed,out,report)
        model.eval()
        with torch.no_grad():
            data=[t.cuda() for t in inputs[0]];expected=model(*data)[0].cpu()
            checkpoint=torch.load(out/'adapter.pt',map_location='cpu',weights_only=True)
            # Reload the entire adapter after deliberate corruption, then compare predictions.
            with torch.no_grad():
                model.clip_head.bias.add_(1.)
            loaded=model.load_state_dict(checkpoint['adapter_state'],strict=False)
            assert not loaded.unexpected_keys
            actual=model(*data)[0].cpu();torch.testing.assert_close(actual,expected,rtol=1e-5,atol=1e-6)
        write_json(out/'result.json',{'status':'smoke_passed','backbone_updates_verified':changes,'adapter_reload_prediction_match':True,
                                     'training_scenes_in_smoke':2,'formal_training_completed':False,'all_sample_finetuning_started':False})
        print('SMOKE PASSED: finite loss, both backbone updates, frozen parameters unchanged, adapter reload predictions match.',flush=True)
        return
    if args.mode=='fit':
        train_one(rows,inputs,list(range(len(rows))),args.epochs,args.seed,out,report)
        write_json(out/'result.json',{'status':'fit_completed','samples':len(rows),'formal_calibrated_model':False,'note':'All-sample fit has no held-out score. Evaluate grouped CV separately.'});return
    groups=sorted({r['split_group'] for r in rows});predictions=[]
    for fold,group in enumerate(groups):
        train=[i for i,r in enumerate(rows) if r['split_group']!=group]
        test=[i for i,r in enumerate(rows) if r['split_group']==group]
        assert set(train).isdisjoint(test)
        assert not {rows[i]['split_group'] for i in train}&{rows[i]['split_group'] for i in test}
        model,mean,scale,y,_=train_one(rows,inputs,train,args.epochs,args.seed,out/f'fold_{fold}',report)
        model.eval()
        with torch.no_grad():
            for i in test:
                pred=model(*[t.cuda() for t in inputs[i]])[0].cpu().numpy()*scale+mean
                predictions.append({'capture_id':rows[i]['capture_id'],'held_out_group':group,
                                    'actual':y[i].tolist(),'predicted':pred.tolist(),'train_mean_baseline':mean.tolist()})
        del model;torch.cuda.empty_cache()
    actual=np.asarray([p['actual'] for p in predictions]);pred=np.asarray([p['predicted'] for p in predictions]);baseline=np.asarray([p['train_mean_baseline'] for p in predictions])
    metrics={name:{'mae':float(np.mean(np.abs(actual[:,i]-pred[:,i]))),'train_mean_baseline_mae':float(np.mean(np.abs(actual[:,i]-baseline[:,i]))),'unit':'UNVERIFIED_SOURCE_COORDINATES'} for i,name in enumerate(TARGETS)}
    write_json(out/'result.json',{'status':'cv_completed','metrics':metrics,'predictions':predictions,'held_out_groups':groups,
                                 'note':'Two-batch held-out proxy experiment, confounded by cohort shift and uncertain physical IDs. Not comparable to the old 9-scene seven-target 0.5837 score.'})


if __name__=='__main__':
    main()
