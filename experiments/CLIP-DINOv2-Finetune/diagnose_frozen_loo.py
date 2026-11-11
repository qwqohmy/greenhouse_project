"""Supplementary capture-LOO diagnosis; primary results remain batch-held-out."""
import json
import numpy as np
from threadpoolctl import threadpool_limits
from frozen_views_experiment import OUT, ridge, metrics
from train import write_json


def main():
    manifest=json.loads((OUT/'manifest.private.json').read_text(encoding='utf-8'))
    results=[]
    with threadpool_limits(limits=1):
        for scope in ('selected553','all_sam_detected'):
            for variant in ('original','sam'):
                for label in ('proxy','native'):
                    rows=[];cf=[];df=[]
                    for i,row in enumerate(manifest['samples']):
                        if not row['sources'].get(label,{}).get('trial_eligible'):continue
                        with np.load(OUT/'features'/f'{i:02d}_{variant}.npz') as features:
                            take=[j for j,idx in enumerate(features['indices']) if scope!='selected553' or row['views'][int(idx)]['selected_553']]
                            cf.append(features['clip'][take].mean(0));df.append(features['dino'][take].mean(0))
                        rows.append(row)
                    cf=np.stack(cf);df=np.stack(df)
                    targets=manifest['target_definitions'][label]
                    y=np.asarray([[r['sources'][label]['numeric_values'][t] for t in targets] for r in rows])
                    cp=np.zeros_like(y);dp=np.zeros_like(y);baseline=np.zeros_like(y)
                    for test in range(len(rows)):
                        train=[i for i in range(len(rows)) if i!=test]
                        cp[[test]]=ridge(cf[train],cf[[test]],y[train])
                        dp[[test]]=ridge(df[train],df[[test]],y[train])
                        baseline[test]=y[train].mean(0)
                    values={'clip_mean_ridge':metrics(y,cp,baseline),'dino_mean_ridge':metrics(y,dp,baseline),
                            'clip_dino_mean_fusion':metrics(y,(cp+dp)*.5,baseline)}
                    result={'scope':scope,'variant':variant,'labels':label,'samples':len(rows),'target_names':targets,'metrics':values}
                    results.append(result)
    report={'validation':'Leave one capture group out; training can contain other captures from the same batch/physical plant.',
            'diagnostic_only':True,'selector_not_tested_in_loo':True,'backbone_updates':0,'database_modified':False,'results':results,
            'note':'Not an independent-plant or independent-batch score. Earlier 0.5837 also used a selector and different inputs/transforms/data; this is not its exact reproduction.'}
    write_json(OUT/'loo_diagnostic.json',report)
    lines=['# 補充診斷：留一拍攝組（LOO）','',
           '此評估允許同批次、甚至同一實體植株其他日期出現在訓練集；僅用來檢查驗證方式的影響，不能取代主要的整批留出結果。骨幹仍完全凍結，沒有重跑視角選擇器。','',
           '| 視角 | 輸入 | 標籤 | 組數 | CLIP＋Ridge | DINO＋Ridge | 固定平均融合 |','|---|---|---|---:|---:|---:|---:|']
    for r in results:
        m=r['metrics']
        lines.append(f"| {r['scope']} | {r['variant']} | {r['labels']} | {r['samples']} | {m['clip_mean_ridge']['mean_target_mae_ratio']:.4f} | {m['dino_mean_ridge']['mean_target_mae_ratio']:.4f} | {m['clip_dino_mean_fusion']['mean_target_mae_ratio']:.4f} |")
    lines+=['','各列基準依各自訓練折計算，LOO與整批留出的基準並不相同；不能只用誤差比差異計算模型提升百分比。', '',
            '沒有測LOO視角選擇器；舊九組的0.5837仍不可作直接比較，這裡是固定平均融合。']
    (OUT/'LOO_DIAGNOSTIC.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k!='metrics'}|{'fusion_ratio':r['metrics']['clip_dino_mean_fusion']['mean_target_mae_ratio']} for r in results]),flush=True)


if __name__=='__main__':main()
