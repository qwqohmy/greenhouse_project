"""Train native traits and PLY proxies separately on user-confirmed four-camera singles."""
import argparse,csv,json,sys
from pathlib import Path
import numpy as np
import torch
from train import BASE,ROOT,digest,load_inputs,train_one,write_json


def prepare(args):
    data=json.loads(args.manifest.read_text(encoding='utf-8'))
    targets=data['target_definitions'][args.labels]
    rows=[];near=[];held=[]
    for sample in data['samples']:
        source=sample['sources'].get(args.labels)
        if not source or not source['trial_eligible']:
            held.append(sample['capture_id']);continue
        if abs(sample['csv_minus_rgb_seconds'])>1 and not args.include_near_time:
            near.append(sample['capture_id']);continue
        assert digest(source['path'])==source['sha256']
        assert all(t in source['numeric_values'] for t in targets)
        views=[]
        for view in sample['views']:
            assert digest(view['image_path'])==view['sha256']
            views.append({**view,'rgb_crop':view['image_path']})
        assert len(views)==24 and all(sum(v['camera']==str(c) for v in views)==6 for c in range(1,5))
        assert len({v['sha256'] for v in views})==24
        rows.append({**sample,'views':views,'values':{t:source['numeric_values'][t] for t in targets},'source':source})
    assert len({r['sample_key'] for r in rows})==len(rows)>=3
    sys.path.insert(0,str(ROOT/'database'));from database import connect
    connection=connect(readonly=True)
    try:
        with connection.cursor() as cur:
            for row in rows:
                cur.execute('SELECT native_trial_eligible,proxy_trial_eligible,target_sources_json FROM p3d_user_samples WHERE id=%s',(row['sample_id'],))
                native_ok,proxy_ok,current=cur.fetchone()
                assert (native_ok if args.labels=='native' else proxy_ok)
                source=json.loads(current)[args.labels]
                assert source['sha256']==row['source']['sha256']
                cur.execute('SELECT a.file_path FROM p3d_user_sample_images l JOIN p3d_images i ON i.id=l.image_id JOIN p3d_assets a ON a.id=i.asset_id WHERE l.sample_id=%s',(row['sample_id'],))
                active={p.casefold() for p, in cur.fetchall()}
                assert all(v['image_path'].casefold() in active for v in row['views'])
    finally:connection.close()
    report={'samples':len(rows),'selected_original_images':len(rows)*24,'cameras':['1','2','3','4'],
        'source_schema':args.labels,'target_names':targets,'target_count':len(targets),
        'near_time_samples_included':sum(abs(r['csv_minus_rgb_seconds'])>1 for r in rows),
        'near_time_samples_excluded':near,'missing_or_held_label_source':held,
        'groups':{g:sum(r['split_group']==g for r in rows) for g in sorted({r['split_group'] for r in rows})},
        'manifest_sha256':digest(args.manifest),'formal_calibrated_training_samples':0,
        'note':'User confirms one plant per image folder across all cameras; labels retain separate native/proxy definitions, unverified units and explicit quality/time notes.'}
    return rows,targets,report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',type=Path,default=BASE/'user_confirmed_samples_manifest.json')
    ap.add_argument('--labels',choices=['native','proxy'],required=True)
    ap.add_argument('--mode',choices=['check','smoke','cv','fit'],default='check')
    ap.add_argument('--include-near-time',action='store_true')
    ap.add_argument('--allow-unverified-labels',action='store_true')
    ap.add_argument('--epochs',type=int,default=20);ap.add_argument('--seed',type=int,default=20261111)
    ap.add_argument('--output',type=Path)
    args=ap.parse_args();rows,targets,report=prepare(args)
    out=args.output or BASE/'outputs'/('user_'+args.labels)/args.mode
    write_json(out/'preflight.json',report);print(json.dumps(report),flush=True)
    if args.mode=='check':return
    if not args.allow_unverified_labels:raise SystemExit('Exploratory labels require --allow-unverified-labels; this does not open formal calibrated DB gates.')
    assert args.epochs>0 and torch.cuda.is_available()
    torch.set_num_threads(4);inputs=load_inputs(rows)
    schema='VENDOR_NATIVE' if args.labels=='native' else 'PLY_PROXY'
    if args.mode in ('smoke','fit'):
        indices=[0,len(rows)-1] if args.mode=='smoke' else list(range(len(rows)))
        model,mean,scale,y,changes=train_one(rows,inputs,indices,1 if args.mode=='smoke' else args.epochs,args.seed,out,report,targets,schema)
        result={'status':args.mode+'_completed','source_schema':schema,'target_names':targets,
                'optimized_scenes':len(indices),'backbone_updates':changes,'full_set_fit':args.mode=='fit',
                'formal_calibrated_model':False}
        if args.mode=='smoke':
            model.eval()
            with torch.no_grad():
                batch=[t.cuda() for t in inputs[0]];before=model(*batch)[0].cpu()
                saved=torch.load(out/'adapter.pt',map_location='cpu',weights_only=True)
                assert saved['target_names']==targets and saved['label_schema']==schema
                model.clip_head.bias.add_(1.)
                model.load_state_dict(saved['adapter_state'],strict=False)
                torch.testing.assert_close(model(*batch)[0].cpu(),before,rtol=1e-5,atol=1e-6)
            result['checkpoint_reload_match']=True
        write_json(out/'result.json',result);print(json.dumps(result),flush=True);return
    groups=sorted({r['split_group'] for r in rows});assert len(groups)>=2
    predictions=[]
    for fold,group in enumerate(groups):
        train=[i for i,r in enumerate(rows) if r['split_group']!=group]
        test=[i for i,r in enumerate(rows) if r['split_group']==group]
        assert not {rows[i]['split_group'] for i in train}&{rows[i]['split_group'] for i in test}
        model,mean,scale,y,_=train_one(rows,inputs,train,args.epochs,args.seed,out/f'fold_{fold}',report,targets,schema)
        model.eval()
        with torch.no_grad():
            for i in test:
                value=model(*[t.cuda() for t in inputs[i]])[0].cpu().numpy()*scale+mean
                predictions.append({'sample_key':rows[i]['sample_key'],'capture_id':rows[i]['capture_id'],
                    'held_out_group':group,'actual':y[i].tolist(),'predicted':value.tolist(),'train_mean_baseline':mean.tolist()})
        del model;torch.cuda.empty_cache()
    actual=np.asarray([r['actual'] for r in predictions]);pred=np.asarray([r['predicted'] for r in predictions]);baseline=np.asarray([r['train_mean_baseline'] for r in predictions])
    metrics={t:{'mae':float(np.mean(np.abs(actual[:,i]-pred[:,i]))),'baseline_mae':float(np.mean(np.abs(actual[:,i]-baseline[:,i])))} for i,t in enumerate(targets)}
    write_json(out/'result.json',{'status':'cv_completed','label_schema':schema,'metrics':metrics,'predictions':predictions,
        'note':'Entire crop batches held out; only two or three groups. Cohort effects and unresolved calibration limit interpretation. Not comparable to old 0.5837.'})


if __name__=='__main__':main()
