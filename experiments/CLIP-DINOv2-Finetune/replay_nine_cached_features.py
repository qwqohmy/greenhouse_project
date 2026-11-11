"""Separate regression reproducibility from small fresh encoder differences."""
import csv
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'CLIP-DINOv2-Finetune'/'outputs'/'original_nine_reproduction_20261111'


def main():
    assert json.loads((OUT/'status.json').read_text(encoding='utf-8'))['status']=='completed'
    script=ROOT/'CLIP-MVP'/'adapter'/'evaluate_clip.py'
    spec=importlib.util.spec_from_file_location('original_clip_evaluation',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with np.load(ROOT/'CLIP-MVP'/'outputs'/'clip_features.npz') as data:
        y=data['y'].copy();ids=data['capture_ids'].astype(str);names=data['target_names'].astype(str)
        with threadpool_limits(limits=1):pred,baseline=module.cross_validated_predictions(data['X_clip_full_mean'],y)
    rows=[]
    for i,identity in enumerate(ids):
        row={'variant':'clip_full_mean','capture_id':identity}
        for j,name in enumerate(names):
            row['actual_'+name]=float(y[i,j]);row['predicted_'+name]=float(pred[i,j])
        rows.append(row)
    out=OUT/'cached_feature_replay';out.mkdir(exist_ok=True)
    path=out/'clip_predictions.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    ratios=[mean_absolute_error(y[:,j],pred[:,j])/mean_absolute_error(y[:,j],baseline[:,j]) for j in range(y.shape[1])]
    command=[sys.executable,'-u',str(ROOT/'ViewSparsifier-DINOv2'/'adapter'/'evaluate_clip_dino_ensemble.py'),
             '--clip-predictions',str(path),'--dino-predictions',str(OUT/'dino'/'predictions.csv'),
             '--output-dir',str(out/'ensemble')]
    with (out/'ensemble.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    result=json.loads((out/'ensemble'/'result.json').read_text(encoding='utf-8'))
    result.update(clip_mean_mae_ratio=float(np.mean(ratios)),clip_mean_r2=float(np.mean([r2_score(y[:,j],pred[:,j]) for j in range(y.shape[1])])),
                  clip_features='Historical cache, regressors refitted now using original code',
                  dino_features='Fresh extraction, identical to historical cache; selector retrained now',
                  database_modified=False)
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    report=OUT/'RESULTS.md'
    report.write_text(report.read_text(encoding='utf-8')+'\n## 歷史特徵快取交叉檢查\n\n'
        +f"固定舊CLIP特徵、重新擬合原始回歸器：{result['clip_mean_mae_ratio']:.6f}。搭配本次重新訓練的DINO選擇器，固定50/50融合：{result['best']['mean_mae_ratio_vs_baseline']:.6f}。\n\n"
        +'這一項不是重新讀取歷史分數，而是重算回歸預測與融合；用來區分新抽CLIP特徵的小幅差異及評估流程是否可重現。\n',encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
