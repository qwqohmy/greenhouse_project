"""Check SAM-trained adapters using RGB inputs alone, including variable views."""
import csv
import json
import math
import subprocess
import sys
from train import BASE, write_json

RUN = BASE/'outputs'/'sam_comparison_20261111'


def main():
    assert json.loads((RUN/'status.json').read_text(encoding='utf-8'))['status']=='completed'
    manifest=json.loads((RUN/'paired_manifest.private.json').read_text(encoding='utf-8'))
    results={}
    for labels in ('proxy','native'):
        row=min((r for r in manifest['samples'] if r['sources'].get(labels,{}).get('trial_eligible')),key=lambda r:len(r['views']))
        path=RUN/(labels+'_inference_input.private.json')
        output=RUN/(labels+'_inference_prediction.private.json')
        write_json(path,{'views':[{'camera':v['camera'],'rgb_crop':v['sam']} for v in row['views']]})
        command=[sys.executable,'-X','utf8',str(BASE/'predict.py'),'--input-json',str(path),'--adapter',str(RUN/(labels+'_sam_fit')/'adapter.pt'),'--output',str(output)]
        with (RUN/(labels+'_inference.log')).open('w',encoding='utf-8') as log:
            subprocess.run(command,cwd=BASE,stdout=log,stderr=subprocess.STDOUT,check=True)
        pred=json.loads(output.read_text(encoding='utf-8'))
        assert pred['input_variant']=='sam' and pred['input_views']==len(row['views'])
        assert set(pred['predictions'])==set(manifest['target_definitions'][labels])
        assert all(math.isfinite(v) for v in pred['predictions'].values())
        assert not pred['target_csv_or_ply_required_at_inference'] and not pred['point_cloud_generated']
        with (RUN/(labels+'_inference_prediction.private.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(pred['predictions']))
            writer.writeheader();writer.writerow(pred['predictions'])
        training=json.loads((RUN/(labels+'_sam_fit')/'training_log.json').read_text(encoding='utf-8'))
        assert len(training['epochs'])==20 and training['frozen_conv_unchanged']
        assert all(v>0 for v in training['backbone_max_abs_updates'].values())
        results[labels]={'passed':True,'rgb_only':True,'sam_input':True,'input_views':len(row['views']),
                         'output_count':len(pred['predictions']),'csv_prediction_written':True,
                         'note':'Artifact check on a training example, not performance evaluation.'}
    write_json(RUN/'adapter_verification.json',results);print(json.dumps(results),flush=True)


if __name__=='__main__':main()
