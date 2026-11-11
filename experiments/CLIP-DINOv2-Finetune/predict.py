"""Inference uses RGB views and an adapter only; no target CSV or PLY is read."""
import argparse
import json
from pathlib import Path
import torch
from train import Fusion,load_inputs,write_json,TARGETS


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input-json',type=Path,required=True,help='Object containing views: [{camera: "1" to "4", rgb_crop: path}, ...]')
    ap.add_argument('--adapter',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    record=json.loads(args.input_json.read_text(encoding='utf-8'))
    checkpoint=torch.load(args.adapter,map_location='cpu',weights_only=True)
    if checkpoint.get('variable_views'):
        assert 1 <= len(record['views']) <= 24
        assert all(v['camera'] in ('1','2','3','4') for v in record['views'])
        assert all(sum(v['camera']==c for v in record['views'])<=6 for c in ('1','2','3','4'))
    else:
        assert len(record['views']) in (12,24)
        cameras=('1','2','3','4') if len(record['views'])==24 else ('2','4')
        assert all([v['camera'] for v in record['views']].count(c)==6 for c in cameras)
    for view in record['views']:
        path=Path(view['rgb_crop'])
        if not path.is_absolute():
            path=args.input_json.parent/path
        assert path.is_file(),str(path)
        view['rgb_crop']=str(path)
    assert len({str(Path(v['rgb_crop']).resolve()).casefold() for v in record['views']})==len(record['views'])
    native_targets=['pGH','pTLA','pPLA','pLAA','pCHA','pE','pMW']
    assert checkpoint['target_names'] in (TARGETS,native_targets)
    assert checkpoint['fixed_ensemble_weight']==.5
    model=Fusion(output_dim=len(checkpoint['target_names']))
    expected={name for name,p in model.named_parameters() if p.requires_grad}
    assert set(checkpoint['adapter_state'])==expected,'Incomplete or incompatible adapter'
    loaded=model.load_state_dict(checkpoint['adapter_state'],strict=False)
    assert not loaded.unexpected_keys
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device).eval()
    inputs=[t.to(device) for t in load_inputs([record])[0]]
    with torch.inference_mode():
        prediction=model(*inputs)[0].cpu()*checkpoint['target_scale']+checkpoint['target_mean']
    result={'predictions':dict(zip(checkpoint['target_names'],prediction.tolist())),
            'input_variant':checkpoint.get('input_variant','original_or_legacy_crop'),'input_views':len(record['views']),
            'label_schema':checkpoint.get('label_schema','PLY_PROXY'),'coordinate_unit':checkpoint['coordinate_unit'],
            'calibrated_physical_traits':False,'point_cloud_generated':False,
            'target_csv_or_ply_required_at_inference':False,
            'note':'Exploratory prediction under the adapter label schema; units and physical calibration are unverified.'}
    write_json(args.output,result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
