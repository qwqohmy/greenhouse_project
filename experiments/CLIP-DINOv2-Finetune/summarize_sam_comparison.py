"""Summarize paired ablations only after checking identical held-out targets."""
import json
from pathlib import Path
from train import BASE, write_json

RUN = BASE/'outputs'/'sam_comparison_20261111'


def main():
    state = json.loads((RUN/'status.json').read_text(encoding='utf-8'))
    assert state['status']=='completed',state['status']
    report = {'database_modified':False,'epochs':20,'comparison':'Identical SAM-selected frames, labels, batch folds and seed; only image representation differs.',
              'near_time_candidates_included':True,'models':{}}
    lines = ['# 既有SAM圖片配對微調對照', '',
             '31個單株拍攝組，共553個不同來源視角。每組1～24張，缺少視角不補黑圖、不複製。19組四相機皆有、28組俯側皆有、3組只有俯視。', '',
             '原廠七項11組、PLY兩項代理值30組（兩者重疊）。本次納入兩個近時間候選，未改資料庫或公開頁面。', '',
             '同一模型、相同來源影格、20 epochs、固定seed，按整個批次留出。誤差比為各指標「模型MAE／訓練集平均值基準MAE」的平均；越低越好，1表示與猜平均值相同。', '',
             '| 標籤 | 組數 | 完整原圖 | 同範圍裁切 | SAM裁切去背景 |', '|---|---:|---:|---:|---:|']
    for label in ('proxy','native'):
        results = {v:json.loads((RUN/f'{label}_{v}_cv'/'result.json').read_text(encoding='utf-8')) for v in ('original','crop','sam')}
        reference = results['original']['predictions']
        for variant in ('crop','sam'):
            pairs = results[variant]['predictions']
            assert len(pairs)==len(reference)
            for a,b in zip(reference,pairs):
                assert all(a[k]==b[k] for k in ('capture_id','held_out_group','view_count','actual','train_mean_baseline'))
        report['models'][label] = {v:{k:r[k] for k in ('all_samples','exact_or_one_second_subset','both_top_and_side_subset')} for v,r in results.items()}
        score = {v:r['all_samples']['mean_target_mae_ratio'] for v,r in results.items()}
        n = len(reference)
        lines.append(f"| {label} | {n} | {score['original']:.4f} | {score['crop']:.4f} | {score['sam']:.4f} |")
    for label in ('proxy','native'):
        lines += ['', '## '+('PLY兩項代理值' if label=='proxy' else '原廠七項表型'), '',
                  '| 指標 | 原圖MAE | 裁切MAE | SAM去背景MAE |', '|---|---:|---:|---:|']
        values = report['models'][label]
        for target, metric in values['original']['all_samples']['metrics'].items():
            lines.append(f"| {target} | {metric['mae']:.4f} | {values['crop']['all_samples']['metrics'][target]['mae']:.4f} | {values['sam']['all_samples']['metrics'][target]['mae']:.4f} |")
        lines += ['', '評估子集（相同模型的測試列子集，未重新訓練）：', '', '| 評估資料 | 組數 | 原圖誤差比 | 裁切誤差比 | SAM誤差比 |', '|---|---:|---:|---:|---:|']
        for subset,name in [('exact_or_one_second_subset','時間相同或差1秒'),('both_top_and_side_subset','同時具俯視與側視')]:
            n=values['original'][subset]['samples']
            ratios=[values[v][subset]['mean_target_mae_ratio'] for v in ('original','crop','sam')]
            lines.append(f'| {name} | {n} | {ratios[0]:.4f} | {ratios[1]:.4f} | {ratios[2]:.4f} |')
    lines += ['', '## 限制與權重', '',
              'SAM有偵測不保證遮罩完整；抽查可見部分側視只有半株、部分遮罩有破洞。3組只有俯視，其中1組只保留1張，已保留視角數。', '',
              '近時間候選可能有標籤配對誤差；時間相符測試子集的模型仍可能在其他批次用到近時間資料，不等於完全排除近時間的實驗。俯側子集亦僅為測試列篩選。', '',
              '兩至三個批次的結果不穩定，來源單位、PLY方向及物理校正仍未驗證。不能直接與之前九組0.5837或前一次不同視角／樣本的分數比較。', '',
              '本次SAM完整fit權重：`proxy_sam_fit/adapter.pt`與`native_sam_fit/adapter.pt`。全資料fit沒有留出分數；上表全部取自分批CV。']
    write_json(RUN/'summary.json',report)
    (RUN/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'completed':True,'models':{k:{v:d['all_samples']['mean_target_mae_ratio'] for v,d in values.items()} for k,values in report['models'].items()}}),flush=True)


if __name__=='__main__': main()
