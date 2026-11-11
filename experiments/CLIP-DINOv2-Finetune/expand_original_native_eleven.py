"""Extend the original nine-capture pipeline to 11 native-CSV captures only."""
import copy
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
OLD=BASE/'outputs'/'original_nine_reproduction_20261111'
OUT=BASE/'outputs'/'original_method_native11_20261111'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)


def prepare():
    old=read(ROOT/'ResNet18-DepthAnything-Fusion'/'outputs'/'manifest.json')
    chosen=read(BASE/'user_confirmed_samples_manifest.json')
    sources=[r for r in chosen['samples'] if r['sources'].get('native',{}).get('trial_eligible')]
    assert len(sources)==11
    old_groups={r['capture_id']:r for r in old['groups']}
    assert len(old_groups)==9
    previous_audit={r['capture_id']:r for r in read(OLD/'input_audit.private.json')['rows']}
    groups=[];audit=[];new=[]
    targets=old['primary_targets']
    for sample in sorted(sources,key=lambda r:r['capture_id']):
        identity=sample['capture_id'];source=sample['sources']['native'];csv_path=Path(source['path'])
        assert sha(csv_path)==source['sha256']
        with csv_path.open(encoding='utf-8-sig',newline='') as stream:
            labels={r[0].strip():float(r[1]) for r in csv.reader(stream) if len(r)>=2 and r[0].strip() in targets}
        assert set(labels)==set(targets)
        np.testing.assert_array_equal([labels[t] for t in targets],[source['numeric_values'][t] for t in targets])
        if identity in old_groups:
            group=copy.deepcopy(old_groups[identity])
            np.testing.assert_array_equal([labels[t] for t in targets],[group['labels'][t] for t in targets])
            expected={v['path'].casefold():v['sha256'] for v in previous_audit[identity]['selected_images']}
        else:
            new.append(identity);folder=Path(sample['views'][0]['image_path']).parent
            selected={}
            for camera in ('1','2','3','4'):
                files=sorted(p for p in folder.glob('CAM'+camera+'_*') if p.suffix.lower() in ('.jpg','.jpeg','.png'))
                assert len(files)==60,(identity,camera,len(files))
                selected[camera]=[str(files[round(i*(len(files)-1)/5)]) for i in range(6)]
            group={'capture_id':identity,'image_dir':str(folder),'selected_images':selected,'labels':labels,
                   'camera_counts':{c:60 for c in selected},'image_count':240}
            expected=None
        group.update(csv_path=str(csv_path),csv_minus_rgb_seconds=sample['csv_minus_rgb_seconds'],label_schema='VENDOR_NATIVE')
        views=[]
        for camera in ('1','2','3','4'):
            assert len(group['selected_images'][camera])==6
            for p in group['selected_images'][camera]:
                digest=sha(p)
                if expected is not None:assert digest==expected[p.casefold()]
                views.append({'camera':camera,'path':p,'sha256':digest})
        assert len({v['path'].casefold() for v in views})==24
        groups.append(group);audit.append({'capture_id':identity,'added':identity not in old_groups,
            'native_csv':str(csv_path),'native_csv_sha256':source['sha256'],
            'csv_minus_rgb_seconds':sample['csv_minus_rgb_seconds'],'views':views})
    assert new==['2026-06-20_13-03-38','2026-08-12_13-12-16'],new
    full={**old,'groups':groups};subset={**old,'groups':[r for r in groups if r['capture_id'] in new]}
    write(OUT/'baseline11'/'outputs'/'manifest.json',full)
    write(OUT/'new_two'/'outputs'/'manifest.json',subset)
    report={'passed':True,'samples':11,'original_samples':9,'added_samples':new,'selected_original_images':264,
            'views_per_sample':24,'target_names':targets,'native_only':True,'ply_generated_labels':0,
            'old_nine_image_hashes_and_labels_unchanged':True,'selection':'Original round(i*(60-1)/5), six frames per camera, no SAM selection.',
            'rows':audit,'database_modified':False,
            'near_time_note':'June20 RGB13:03:38 uses native CSV13:48:26 (+44m48s); August12 differs by one second. These candidate associations are retained, not promoted to verified identities.'}
    write(OUT/'input_audit.private.json',report)
    return full,subset


def clip_new_two(subset):
    import clip
    import torch
    from PIL import Image
    assert torch.cuda.is_available()
    torch.set_num_threads(4)
    model,preprocess=clip.load('ViT-B/32',device='cuda',jit=False,download_root=str(ROOT/'CLIP-MVP'/'.cache'/'clip'))
    model.eval()
    for p in model.parameters():p.requires_grad_(False)
    rows=[]
    for group in subset['groups']:
        features=[]
        for camera in ('1','2','3','4'):
            images=[]
            for p in group['selected_images'][camera]:
                with Image.open(p) as image:images.append(preprocess(image.convert('RGB')))
            with torch.inference_mode():features.append(model.encode_image(torch.stack(images).cuda()).float().cpu().numpy())
        rows.append(np.concatenate(features).mean(0).astype(np.float32))
    np.savez_compressed(OUT/'new_two_clip.npz',X_clip_full_mean=np.stack(rows),capture_ids=np.asarray([r['capture_id'] for r in subset['groups']]))


def merge_features(full):
    targets=full['primary_targets'];ids=[r['capture_id'] for r in full['groups']]
    y=np.asarray([[r['labels'][t] for t in targets] for r in full['groups']],np.float64)
    with np.load(OLD/'clip_features.npz') as old,np.load(OUT/'new_two_clip.npz') as new:
        lookup={identity:old['X_clip_full_mean'][i].copy() for i,identity in enumerate(old['capture_ids'].astype(str))}
        lookup.update({identity:new['X_clip_full_mean'][i].copy() for i,identity in enumerate(new['capture_ids'].astype(str))})
        np.savez_compressed(OUT/'clip_features.npz',X_clip_full_mean=np.stack([lookup[i] for i in ids]),y=y,capture_ids=np.asarray(ids),target_names=np.asarray(targets))
    with np.load(OLD/'dinov2_view_features.npz') as old,np.load(OUT/'new_two_dino.npz') as new:
        lookup={identity:old['X_views'][i].copy() for i,identity in enumerate(old['capture_ids'].astype(str))}
        paths={identity:old['image_paths'][i].copy() for i,identity in enumerate(old['capture_ids'].astype(str))}
        lookup.update({identity:new['X_views'][i].copy() for i,identity in enumerate(new['capture_ids'].astype(str))})
        paths.update({identity:new['image_paths'][i].copy() for i,identity in enumerate(new['capture_ids'].astype(str))})
        for key in ('camera_ids','role_ids','angle_ids'):np.testing.assert_array_equal(old[key],new[key])
        np.savez_compressed(OUT/'dinov2_view_features.npz',X_views=np.stack([lookup[i] for i in ids]),image_paths=np.stack([paths[i] for i in ids]),
            y=y,capture_ids=np.asarray(ids),target_names=np.asarray(targets),**{k:old[k] for k in ('camera_ids','role_ids','angle_ids')})
    write(OUT/'feature_provenance.json',{'common_nine_features':'Reused without alteration from the fresh original-nine reproduction.',
        'new_two_clip':'Original clip.load preprocessing, per-camera six-image encode batches, full-frame mean; no per-view L2 normalization.',
        'new_two_dino':'Original extract_dinov2_features.py, unchanged, native-only two-group manifest.',
        'old_clip_sha256':sha(OLD/'clip_features.npz'),'old_dino_sha256':sha(OLD/'dinov2_view_features.npz'),
        'new_clip_sha256':sha(OUT/'clip_features.npz'),'new_dino_sha256':sha(OUT/'dinov2_view_features.npz')})


def evaluate_clip():
    script=ROOT/'CLIP-MVP'/'adapter'/'evaluate_clip.py'
    spec=importlib.util.spec_from_file_location('original_clip_evaluation',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with np.load(OUT/'clip_features.npz') as data:
        y=data['y'];ids=data['capture_ids'].astype(str);targets=data['target_names'].astype(str)
        with threadpool_limits(limits=1):pred,baseline=module.cross_validated_predictions(data['X_clip_full_mean'],y)
    folder=OUT/'clip';folder.mkdir(exist_ok=True)
    rows=[]
    for i,identity in enumerate(ids):
        row={'variant':'clip_full_mean','capture_id':identity}
        for j,t in enumerate(targets):row['actual_'+t]=float(y[i,j]);row['predicted_'+t]=float(pred[i,j])
        rows.append(row)
    with (folder/'predictions.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def score(actual,pred,baseline):
    from sklearn.metrics import r2_score
    mae=np.mean(np.abs(actual-pred),0);base=np.mean(np.abs(actual-baseline),0)
    return {'mean_mae_ratio':float(np.mean(mae/base)),'mean_r2':float(np.mean([r2_score(actual[:,i],pred[:,i]) for i in range(actual.shape[1])])),
            'better_targets':int(np.sum(mae<base)),'mae':mae.tolist(),'baseline_mae':base.tolist()}


def finish(full):
    def predictions(path,variant):
        with path.open(encoding='utf-8-sig',newline='') as f:return {r['capture_id']:r for r in csv.DictReader(f) if r['variant']==variant}
    variant='clip_dino_selector_50_50'
    old=predictions(OLD/'ensemble'/'predictions.csv',variant)
    new=predictions(OUT/'ensemble'/'predictions.csv',variant)
    targets=full['primary_targets'];ids=sorted(new);common=sorted(old)
    def arrays(rows,keys):
        return np.asarray([[float(rows[k]['actual_'+t]) for t in targets] for k in keys]),np.asarray([[float(rows[k]['predicted_'+t]) for t in targets] for k in keys])
    oy,op=arrays(old,common);ny,npred=arrays(new,ids);cy,cp=arrays(new,common)
    np.testing.assert_array_equal(oy,cy)
    ob=np.stack([np.delete(oy,i,axis=0).mean(0) for i in range(len(oy))])
    nb=np.stack([np.delete(ny,i,axis=0).mean(0) for i in range(len(ny))])
    results={'original_nine':score(oy,op,ob),'expanded_eleven':score(ny,npred,nb),
             'common_nine_after_adding_two_same_old_baseline':score(cy,cp,ob)}
    result={'status':'completed','samples':11,'selected_images':264,'native_csv_only':True,'ply_generated_labels':0,
            'validation':'Capture LeaveOneOut, 10 train / 1 test, 11 folds; original nine used 8 train / 1 test.',
            'selector_epochs':800,'selector_seeds':5,'fixed_ensemble_weight':.5,'database_modified':False,
            'target_names':targets,'results':results,
            'added_capture_ids':[r['capture_id'] for r in full['groups'] if r['capture_id'] not in old],
            'note':'The whole-11 target population and mean baseline differ from the old nine. The common-nine comparison fixes test cases and old baseline, with new groups added to training. June20 +44m48s remains a candidate pairing; August12 +1s.'}
    write(OUT/'result.json',result)
    lines=['# 原方法擴充至11組原廠CSV','',
        '原九組＋2026-06-20 13:03:38、2026-08-12 13:12:16，共11組。只有原廠七項CSV，沒有PLY生成標籤；各四相機等距選六張，共264張。', '',
        '原九組新抽取特徵直接沿用，避免重新抽取數值漂移；新增兩組用相同原始CLIP／DINO前處理。原版PCA／Ridge、原視角選擇器800 epochs×5 seeds、固定50/50融合，不改演算法。', '',
        '| 比較 | 平均誤差比 | 平均R² | 優於基準目標 |','|---|---:|---:|---:|']
    names={'original_nine':'原9組，9折LOO','expanded_eleven':'擴充11組，11折LOO','common_nine_after_adding_two_same_old_baseline':'加入2組後，只評估原9組（固定舊基準）'}
    for key,r in results.items():lines.append(f"| {names[key]} | {r['mean_mae_ratio']:.6f} | {r['mean_r2']:.6f} | {r['better_targets']}/7 |")
    lines+=['','整體11組與原9組的測試資料和平均值基準不同，不能只用分數差異判斷新資料品質。共同九組比較保持測試病例與分母不變，較能觀察新增兩組作訓練資料的影響。', '',
        '6/20圖片13:03:38對CSV13:48:26，相差44分48秒，仍是近時間候選；8/12差1秒。未宣稱來源身分／單位已校正。', '',
        '這是拍攝組LOO，可能在訓練中保留同批次／同株其他日期，不能代表獨立植株或跨批次驗證。資料庫與公開頁面未更新。']
    (OUT/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result),flush=True)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'status.json').exists():raise RuntimeError('Already launched, inspect status.')
    state={'status':'running','current':'prepare','completed':[],'started_at':datetime.now(timezone.utc).isoformat()}
    def update(name):state['current']=name;write(OUT/'status.json',state)
    update('prepare')
    try:
        full,subset=prepare();state['completed'].append('prepare')
        update('extract_new_clip');clip_new_two(subset);state['completed'].append('extract_new_clip')
        env=os.environ.copy();env.update(PYTHONUTF8='1',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',OPENBLAS_NUM_THREADS='1')
        def run(name,args):
            update(name)
            with (OUT/(name+'.log')).open('w',encoding='utf-8') as log:
                proc=subprocess.Popen([sys.executable,'-u',*[str(a) for a in args]],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                state['child_pid']=proc.pid;write(OUT/'status.json',state);code=proc.wait()
            if code:raise RuntimeError(name+' failed: '+str(code))
            state['completed'].append(name)
        run('extract_new_dino',[ROOT/'ViewSparsifier-DINOv2'/'adapter'/'extract_dinov2_features.py','--baseline-root',OUT/'new_two','--output',OUT/'new_two_dino.npz'])
        update('merge_features');merge_features(full);state['completed'].append('merge_features')
        update('evaluate_clip');evaluate_clip();state['completed'].append('evaluate_clip')
        run('evaluate_dino',[ROOT/'ViewSparsifier-DINOv2'/'adapter'/'evaluate_viewsparsifier.py','--features',OUT/'dinov2_view_features.npz','--epochs','800','--seeds','5','--output-dir',OUT/'dino'])
        run('ensemble',[ROOT/'ViewSparsifier-DINOv2'/'adapter'/'evaluate_clip_dino_ensemble.py','--clip-predictions',OUT/'clip'/'predictions.csv','--dino-predictions',OUT/'dino'/'predictions.csv','--output-dir',OUT/'ensemble'])
        finish(full);state.update(status='completed',current=None,finished_at=datetime.now(timezone.utc).isoformat());write(OUT/'status.json',state)
    except Exception:
        state.update(status='failed',error=traceback.format_exc());write(OUT/'status.json',state);raise


if __name__=='__main__':main()
