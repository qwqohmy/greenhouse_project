"""Reproduce the historical nine captures with unchanged original scripts."""
import csv
import hashlib
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
OUT=BASE/'outputs'/'original_nine_reproduction_20261111'
EXPECTED=['2026-06-18_13-28-13','2026-06-22_13-29-44','2026-06-24_09-41-11',
          '2026-06-26_08-49-30','2026-06-30_11-07-59','2026-07-21_14-51-25',
          '2026-07-21_15-14-20','2026-08-06_17-15-47','2026-08-10_14-24-58']


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8');temp.replace(path)


def audit():
    manifest_path=ROOT/'ResNet18-DepthAnything-Fusion'/'outputs'/'manifest.json'
    manifest=read(manifest_path)
    assert [r['capture_id'] for r in manifest['groups']]==EXPECTED
    clip=ROOT/'CLIP-MVP'/'outputs'/'clip_features.npz'
    dino=ROOT/'ViewSparsifier-DINOv2'/'outputs'/'dinov2_view_features.npz'
    targets=manifest['primary_targets']
    labels=np.asarray([[r['labels'][t] for t in targets] for r in manifest['groups']])
    with np.load(clip) as c,np.load(dino) as d:
        assert list(c['capture_ids'].astype(str))==list(d['capture_ids'].astype(str))==EXPECTED
        assert list(c['target_names'].astype(str))==list(d['target_names'].astype(str))==targets
        np.testing.assert_array_equal(c['y'],d['y']);np.testing.assert_array_equal(c['y'],labels)
        assert d['X_views'].shape==(9,24,384)
        assert np.isfinite(c['X_clip_full_mean']).all() and np.isfinite(d['X_views']).all()
        stored_paths=d['image_paths'].astype(str).tolist()
    rows=[]
    for i,group in enumerate(manifest['groups']):
        paths=[Path(p) for camera in ('1','2','3','4') for p in group['selected_images'][camera]]
        assert len(paths)==24 and len({str(p).casefold() for p in paths})==24
        assert [[str(p).casefold() for p in paths]][0]==[p.casefold() for p in stored_paths[i]]
        assert all(len(group['selected_images'][c])==6 for c in ('1','2','3','4'))
        csv_path=Path(group['csv_path'])
        with csv_path.open(encoding='utf-8-sig',newline='') as stream:
            native={r[0].strip():float(r[1]) for r in csv.reader(stream) if len(r)>=2 and r[0].strip() in targets}
        np.testing.assert_array_equal([native[t] for t in targets],labels[i])
        rows.append({'capture_id':group['capture_id'],'csv':str(csv_path),'csv_sha256':sha(csv_path),
                     'selected_images':[{'path':str(p),'sha256':sha(p)} for p in paths]})
    script_paths=[ROOT/'CLIP-MVP'/'adapter'/f for f in ('extract_clip_features.py','evaluate_clip.py')]
    script_paths += [ROOT/'ViewSparsifier-DINOv2'/'adapter'/f for f in ('extract_dinov2_features.py','evaluate_viewsparsifier.py','evaluate_clip_dino_ensemble.py')]
    report={'passed':True,'samples':9,'views_per_sample':24,'selected_original_images':216,'target_names':targets,
            'current_native_csv_matches_historical_labels':True,'historical_features_sha256':{'clip':sha(clip),'dino':sha(dino)},
            'manifest_sha256':sha(manifest_path),'scripts':{str(p):sha(p) for p in script_paths},'rows':rows,
            'note':'Current files hashed for this reproduction. Historical image hashes were not recorded, so fresh feature comparison supplies additional evidence.'}
    write(OUT/'input_audit.private.json',report)
    return report


def compare_features():
    result={}
    for name,old,new,keys in [
        ('clip',ROOT/'CLIP-MVP'/'outputs'/'clip_features.npz',OUT/'clip_features.npz',['X_clip_full_mean','y']),
        ('dino',ROOT/'ViewSparsifier-DINOv2'/'outputs'/'dinov2_view_features.npz',OUT/'dinov2_view_features.npz',['X_views','y'])]:
        with np.load(old) as a,np.load(new) as b:
            assert np.array_equal(a['capture_ids'],b['capture_ids'])
            np.testing.assert_array_equal(a['y'],b['y'])
            result[name]={k:{'max_abs_difference':float(np.max(np.abs(a[k].astype(float)-b[k].astype(float)))),
                             'allclose_rtol1e_4_atol1e_5':bool(np.allclose(a[k],b[k],rtol=1e-4,atol=1e-5))} for k in keys}
    write(OUT/'fresh_feature_comparison.json',result)


def finish():
    old_clip=read(ROOT/'CLIP-MVP'/'outputs'/'comparison'/'result.json')['best_clip']
    old_dino=read(ROOT/'ViewSparsifier-DINOv2'/'outputs'/'comparison'/'result.json')['best']
    old_ensemble=read(ROOT/'ViewSparsifier-DINOv2'/'outputs'/'ensemble'/'result.json')['best']
    def summary_row(path,variant):
        with path.open(encoding='utf-8-sig',newline='') as stream:
            row=next(r for r in csv.DictReader(stream) if r['variant']==variant)
        return {**row,'mean_mae_ratio_vs_baseline':float(row['mean_mae_ratio_vs_baseline']),
                'mean_r2':float(row['mean_r2']),'targets_better_than_baseline':int(row['targets_better_than_baseline'])}
    pairs=[('CLIP full mean',old_clip,summary_row(OUT/'clip'/'summary.csv','clip_full_mean')),
           ('DINO all-view mean',old_dino,summary_row(OUT/'dino'/'summary.csv','dino_all_mean')),
           ('CLIP + DINO selector 50/50',old_ensemble,summary_row(OUT/'ensemble'/'summary.csv','clip_dino_selector_50_50'))]
    rows=[{'method':name,'historical':old,'rerun':new,
           'ratio_difference':new['mean_mae_ratio_vs_baseline']-old['mean_mae_ratio_vs_baseline'],
           'same_rounded_4dp':round(new['mean_mae_ratio_vs_baseline'],4)==round(old['mean_mae_ratio_vs_baseline'],4)} for name,old,new in pairs]
    result={'status':'completed','samples':9,'selected_original_images':216,'targets':7,'validation':'Capture-group LeaveOneOut: 8 train, 1 held out, 9 folds.',
            'selector_epochs':800,'selector_seeds':5,'database_modified':False,'fresh_feature_extraction':True,'results':rows,
            'note':'Original extraction/evaluation scripts, original official preprocessing and original 9 native-label captures; no SAM resampling, new data, partial-backbone fine-tuning or batch-holdout substitution.'}
    write(OUT/'result.json',result)
    lines=['# 原始九組基準重現','',
           '九個原始拍攝組，各四相機×六張＝24張，共216張。七項原廠CSV標籤。使用當時原始程式與影像前處理，重新抽特徵及建立小型回歸／視角選擇器；CLIP與DINO骨幹不微調。', '',
           '每折8組訓練、1組測試，共9折；視角選擇器800 epochs、5個種子，最後固定50/50融合。歷史結果與特徵檔未覆蓋。', '',
           '| 方法 | 歷史誤差比 | 本次誤差比 | 本次平均R² | 優於平均值基準 |', '|---|---:|---:|---:|---:|']
    for row in rows:
        new=row['rerun'];old=row['historical']
        lines.append(f"| {row['method']} | {old['mean_mae_ratio_vs_baseline']:.6f} | {new['mean_mae_ratio_vs_baseline']:.6f} | {new['mean_r2']:.6f} | {new['targets_better_than_baseline']}/7 |")
    lines+=['','## 九組清單','']+['- '+capture for capture in EXPECTED]
    lines+=['','本次圖片／原CSV雜湊、原程式雜湊及標籤一致性見input_audit.private.json；重新抽特徵與歷史快取差異見fresh_feature_comparison.json。', '',
            '這只驗證舊九組基準能否重現，不證明單株身分、物理單位或跨批次泛化已驗證。LOO可在訓練中包含同批次／可能同株其他日期，不能與整批留出混為同種評分。']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result),flush=True)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'status.json').exists():raise RuntimeError('Reproduction already launched; inspect status before starting another run.')
    state={'status':'running','started_at':datetime.now(timezone.utc).isoformat(),'completed':[],'current':'input_audit'}
    write(OUT/'status.json',state)
    try:
        audit();state['completed'].append('input_audit')
        jobs=[('extract_clip',[ROOT/'CLIP-MVP'/'adapter'/'extract_clip_features.py','--output',OUT/'clip_features.npz']),
              ('extract_dino',[ROOT/'ViewSparsifier-DINOv2'/'adapter'/'extract_dinov2_features.py','--output',OUT/'dinov2_view_features.npz']),
              ('evaluate_clip',[ROOT/'CLIP-MVP'/'adapter'/'evaluate_clip.py','--features',OUT/'clip_features.npz','--output-dir',OUT/'clip']),
              ('evaluate_dino',[ROOT/'ViewSparsifier-DINOv2'/'adapter'/'evaluate_viewsparsifier.py','--features',OUT/'dinov2_view_features.npz','--epochs','800','--seeds','5','--output-dir',OUT/'dino']),
              ('ensemble',[ROOT/'ViewSparsifier-DINOv2'/'adapter'/'evaluate_clip_dino_ensemble.py','--clip-predictions',OUT/'clip'/'predictions.csv','--dino-predictions',OUT/'dino'/'predictions.csv','--output-dir',OUT/'ensemble'])]
        env=os.environ.copy();env.update(PYTHONUTF8='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1')
        for name,args in jobs:
            state['current']=name;write(OUT/'status.json',state)
            with (OUT/(name+'.log')).open('w',encoding='utf-8') as log:
                proc=subprocess.Popen([sys.executable,'-u',*[str(a) for a in args]],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                state['child_pid']=proc.pid;write(OUT/'status.json',state)
                code=proc.wait()
            if code:raise RuntimeError(name+' failed, see its log: '+str(code))
            state['completed'].append(name);write(OUT/'status.json',state)
            if name=='extract_dino':compare_features()
        finish();state.update(status='completed',current=None,finished_at=datetime.now(timezone.utc).isoformat());write(OUT/'status.json',state)
    except Exception:
        state.update(status='failed',error=traceback.format_exc());write(OUT/'status.json',state);raise


if __name__=='__main__':main()
