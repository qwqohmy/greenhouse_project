"""Check final adapters via the RGB-only command line inference path."""
import json
import math
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN = BASE / 'outputs' / 'confirmed_finetune_20261111'


def main():
    assert json.loads((RUN / 'status.json').read_text(encoding='utf-8'))['status'] == 'completed'
    manifest = json.loads((BASE / 'user_confirmed_samples_manifest.json').read_text(encoding='utf-8'))
    results = {}
    for labels in ('proxy', 'native'):
        row = next(r for r in manifest['samples'] if r['sources'].get(labels, {}).get('trial_eligible')
                   and abs(r['csv_minus_rgb_seconds']) <= 1)
        record = {'views': [{'camera': v['camera'], 'rgb_crop': v['image_path']} for v in row['views']]}
        input_path = RUN / (labels + '_inference_input.private.json')
        output_path = RUN / (labels + '_inference_result.private.json')
        input_path.write_text(json.dumps(record), encoding='utf-8')
        command = [sys.executable, '-X', 'utf8', str(BASE / 'predict.py'), '--input-json', str(input_path),
                   '--adapter', str(RUN / (labels + '_fit') / 'adapter.pt'), '--output', str(output_path)]
        with (RUN / (labels + '_inference.log')).open('w', encoding='utf-8') as log:
            subprocess.run(command, cwd=BASE, stdout=log, stderr=subprocess.STDOUT, check=True)
        pred = json.loads(output_path.read_text(encoding='utf-8'))
        assert set(pred['predictions']) == set(manifest['target_definitions'][labels])
        assert all(math.isfinite(v) for v in pred['predictions'].values())
        assert not pred['target_csv_or_ply_required_at_inference'] and not pred['point_cloud_generated']
        training = json.loads((RUN / (labels + '_fit') / 'training_log.json').read_text(encoding='utf-8'))
        assert len(training['epochs']) == 20 and training['frozen_conv_unchanged']
        assert all(v > 0 for v in training['backbone_max_abs_updates'].values())
        results[labels] = {'passed': True, 'output_count': len(pred['predictions']), 'rgb_only': True,
                           'trained_epochs': 20, 'backbone_updates_verified': True,
                           'frozen_parameters_unchanged': True,
                           'note': 'Artifact validation only; this inference example is not a held-out evaluation.'}
    (RUN / 'adapter_verification.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results), flush=True)


if __name__ == '__main__':
    main()
