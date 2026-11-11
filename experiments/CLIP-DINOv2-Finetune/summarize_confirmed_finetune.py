"""Summarize held-out results; never present an all-sample fit as evaluation."""
import json
import math
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN = BASE / 'outputs' / 'confirmed_finetune_20261111'


def main():
    state = json.loads((RUN / 'status.json').read_text(encoding='utf-8'))
    assert state['status'] == 'completed', state['status']
    summary = {'run': RUN.name, 'epochs': 20, 'near_time_included': False,
               'evaluation': 'Leave one entire crop batch out; target normalization fitted on each training fold only.',
               'old_05837_comparable': False, 'models': {}}
    lines = ['# 四相機單株微調結果', '',
             'CLIP ViT-B/32 + DINOv2 ViT-S/14，各50%融合。每株24張原始RGB（四相機各六張），每個訓練20 epochs。', '',
             '驗證按整個批次留出；沒有將同一拍攝組的不同角度分到訓練與測試。相近時間候選不納入本次。', '',
             '誤差比 = 模型MAE / 僅預測訓練集平均值的MAE；越低越好，1代表與平均值基準相同。它不是準確率。', '']
    for labels in ('proxy', 'native'):
        cv = json.loads((RUN / (labels + '_cv') / 'result.json').read_text(encoding='utf-8'))
        preflight = json.loads((RUN / (labels + '_fit') / 'preflight.json').read_text(encoding='utf-8'))
        fit = json.loads((RUN / (labels + '_fit') / 'result.json').read_text(encoding='utf-8'))
        assert fit['status'] == 'fit_completed' and cv['status'] == 'cv_completed'
        metrics = {}
        for target, values in cv['metrics'].items():
            assert all(math.isfinite(v) for v in values.values())
            metrics[target] = {**values, 'mae_ratio': values['mae'] / values['baseline_mae'] if values['baseline_mae'] else None}
        ratios = [m['mae_ratio'] for m in metrics.values() if m['mae_ratio'] is not None]
        ratio = sum(ratios) / len(ratios)
        summary['models'][labels] = {'samples': preflight['samples'], 'batch_groups': preflight['groups'],
                                    'metrics': metrics, 'mean_target_mae_ratio': ratio,
                                    'checkpoint': str(Path(labels + '_fit') / 'adapter.pt')}
        lines.extend(['## ' + ('PLY兩項代理值' if labels == 'proxy' else '原廠七項表型'), '',
                      f"樣本：{preflight['samples']}組；批次：{len(preflight['groups'])}；各指標誤差比平均：**{ratio:.4f}**。", '',
                      '| 指標 | 模型MAE | 平均值基準MAE | 誤差比 |', '|---|---:|---:|---:|'])
        for target, m in metrics.items():
            ratio_text = f"{m['mae_ratio']:.4f}" if m['mae_ratio'] is not None else 'NA'
            lines.append(f"| {target} | {m['mae']:.4f} | {m['baseline_mae']:.4f} | {ratio_text} |")
        lines.extend(['', '權重：`' + labels + '_fit/adapter.pt`。全資料fit只用於產出推論權重，不作驗證分數。', ''])
    lines.extend(['## 解讀限制', '',
                  '原廠七項與PLY兩項代理值的定義與來源分開，不能混為同一標籤。數值單位及PLY方向／物理校正仍未驗證。', '',
                  '本次樣本、標籤及批次留出方式與早期九組實驗不同，不能直接與0.5837比較。只有兩至三個批次，無法視為穩定的外部泛化估計。', '',
                  '微調最後一個Transformer區塊、正規化層及回歸／視角選擇頭；不是重建點雲。原圖或CSV版本不額外算成獨立樣本。'])
    (RUN / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (RUN / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
