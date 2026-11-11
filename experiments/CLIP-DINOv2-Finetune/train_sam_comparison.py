"""Matched-frame RGB vs existing SAM experiment, with variable view counts."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
import torch
from train import BASE, digest, load_inputs, train_one, write_json

RUN = BASE / 'outputs' / 'sam_comparison_20261111'


def metric_table(predictions, targets):
    if not predictions: return None
    actual = np.asarray([p['actual'] for p in predictions])
    pred = np.asarray([p['predicted'] for p in predictions])
    baseline = np.asarray([p['train_mean_baseline'] for p in predictions])
    values = {}
    for i, target in enumerate(targets):
        mae = float(np.mean(np.abs(actual[:,i]-pred[:,i])))
        base = float(np.mean(np.abs(actual[:,i]-baseline[:,i])))
        values[target] = {'mae': mae, 'baseline_mae': base, 'mae_ratio': mae/base if base else None}
    ratios = [v['mae_ratio'] for v in values.values() if v['mae_ratio'] is not None]
    return {'samples':len(predictions), 'metrics':values, 'mean_target_mae_ratio':float(np.mean(ratios))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--labels',choices=['native','proxy'],required=True)
    parser.add_argument('--variant',choices=['original','crop','sam'],required=True)
    parser.add_argument('--mode',choices=['cv','fit'],required=True)
    parser.add_argument('--epochs',type=int,default=20)
    parser.add_argument('--seed',type=int,default=20261111)
    args = parser.parse_args()
    path = RUN / 'paired_manifest.private.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    targets = manifest['target_definitions'][args.labels]
    rows = []
    for sample in manifest['samples']:
        source = sample['sources'].get(args.labels)
        if not source or not source['trial_eligible']: continue
        assert digest(source['path']) == source['sha256']
        assert all(np.isfinite(source['numeric_values'][t]) for t in targets)
        views = []
        for v in sample['views']:
            assert digest(v[args.variant]) == v['sha256'][args.variant]
            views.append({**v, 'rgb_crop': v[args.variant]})
        assert 1 <= len(views) <= 24 and len({v['original'] for v in views}) == len(views)
        rows.append({**sample, 'views':views, 'values':{t:source['numeric_values'][t] for t in targets}})
    assert len({r['sample_key'] for r in rows}) == len(rows)
    out = RUN / (args.labels+'_'+args.variant+'_'+args.mode)
    report = {'samples':len(rows), 'variant':args.variant, 'labels':args.labels, 'target_names':targets,
              'selected_images':sum(len(r['views']) for r in rows), 'manifest_sha256':digest(path),
              'near_time_samples_included':sum(abs(r['csv_minus_rgb_seconds']) > 1 for r in rows),
              'group_sizes':{g:sum(r['split_group']==g for r in rows) for g in sorted({r['split_group'] for r in rows})},
              'variable_views':True, 'database_modified':False, 'formal_calibrated_training_samples':0}
    write_json(out/'preflight.json',report); print(json.dumps(report),flush=True)
    assert torch.cuda.is_available() and args.epochs > 0
    torch.set_num_threads(4)
    inputs = load_inputs(rows)
    schema = 'VENDOR_NATIVE' if args.labels == 'native' else 'PLY_PROXY'
    if args.mode == 'fit':
        train_one(rows,inputs,list(range(len(rows))),args.epochs,args.seed,out,report,targets,schema)
        checkpoint = torch.load(out/'adapter.pt',map_location='cpu',weights_only=True)
        checkpoint.update(input_variant=args.variant,variable_views=True,max_views_per_camera=6,
                          near_time_candidates_included=report['near_time_samples_included'])
        torch.save(checkpoint,out/'adapter.pt')
        write_json(out/'result.json',{'status':'fit_completed','samples':len(rows),'input_variant':args.variant,
                                     'formal_calibrated_model':False,'note':'All-sample fit; no held-out score.'})
        return
    predictions = []
    for fold, group in enumerate(sorted({r['split_group'] for r in rows})):
        training = [i for i,r in enumerate(rows) if r['split_group'] != group]
        testing = [i for i,r in enumerate(rows) if r['split_group'] == group]
        assert not {rows[i]['split_group'] for i in training} & {rows[i]['split_group'] for i in testing}
        model, mean, scale, y, _ = train_one(rows,inputs,training,args.epochs,args.seed,out/f'fold_{fold}',report,targets,schema)
        model.eval()
        with torch.inference_mode():
            for i in testing:
                pred = model(*[t.cuda() for t in inputs[i]])[0].cpu().numpy()*scale+mean
                predictions.append({'sample_key':rows[i]['sample_key'],'capture_id':rows[i]['capture_id'],
                                    'held_out_group':group,'view_count':len(rows[i]['views']),
                                    'csv_minus_rgb_seconds':rows[i]['csv_minus_rgb_seconds'],
                                    'both_top_and_side':rows[i]['both_top_and_side'],
                                    'actual':y[i].tolist(),'predicted':pred.tolist(),'train_mean_baseline':mean.tolist()})
        del model; torch.cuda.empty_cache()
    result = {'status':'cv_completed','label_schema':schema,'variant':args.variant,
              'all_samples':metric_table(predictions,targets),
              'exact_or_one_second_subset':metric_table([p for p in predictions if abs(p['csv_minus_rgb_seconds'])<=1],targets),
              'both_top_and_side_subset':metric_table([p for p in predictions if p['both_top_and_side']],targets),
              'predictions':predictions,
              'note':'Identical frames, labels, seed, batches and epochs across input variants. Near-time candidates included and separately reported; exact subset still trained with near-time candidates in other folds. SAM presence does not certify mask quality or target calibration.'}
    write_json(out/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='predictions'}),flush=True)


if __name__ == '__main__': main()
