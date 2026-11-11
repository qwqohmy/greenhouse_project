"""Read-only SAM inventory for the 31 selected single-pot capture groups."""
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
SAM = BASE.parent.parent / 'plant_seg' / 'rgb_singleplant_dataset'
OUT = BASE / 'outputs' / 'sam_comparison_20261111'


def main():
    data = json.loads((BASE / 'user_confirmed_samples_manifest.json').read_text(encoding='utf-8'))
    results = []
    for row in data['samples']:
        if not any(s.get('trial_eligible') for s in row['sources'].values()):
            continue
        folders = list(SAM.glob('*/' + row['capture_id']))
        assert len(folders) <= 1, row['capture_id']
        selected = {str(Path(v['image_path'])).casefold(): v for v in row['views']}
        frames = []; reasons = Counter(); selected_ok = 0
        for folder in folders:
            for path in sorted(folder.glob('CAM*/*/metadata.json')):
                meta = json.loads(path.read_text(encoding='utf-8'))
                source = Path(meta['source'])
                if not source.is_file():
                    reasons['missing_source'] += 1; continue
                stat = source.stat()
                if meta.get('source_bytes') != stat.st_size or meta.get('source_mtime_ns') != stat.st_mtime_ns:
                    reasons['stale_source'] += 1; continue
                instances = meta['instances']
                valid = []
                for instance in instances:
                    output = Path(instance['output_directory'])
                    if all((output / n).is_file() for n in ('rgb.png', 'mask.png', 'segmented.png')):
                        valid.append(instance)
                is_selected = str(source).casefold() in selected
                if not valid:
                    reasons['no_usable_mask'] += 1
                elif len(valid) > 1:
                    reasons['multiple_instances'] += 1
                if valid and is_selected:
                    selected_ok += 1
                frames.append({'metadata': str(path), 'source': str(source), 'camera': meta['camera'],
                               'selected_original_frame': is_selected, 'valid_instances': len(valid),
                               'source_edge': any(i['source_edge_truncated_candidate'] for i in valid)})
        counts = {str(c): sum(f['camera'] == str(c) and f['valid_instances'] > 0 for f in frames) for c in range(1, 5)}
        results.append({'capture_id': row['capture_id'], 'sam_folder': str(folders[0]) if folders else None,
                        'trial_sources': [k for k, s in row['sources'].items() if s.get('trial_eligible')],
                        'csv_minus_rgb_seconds': row['csv_minus_rgb_seconds'],
                        'metadata_count': len(frames), 'available_mask_frames_by_camera': counts,
                        'selected_24_with_mask': selected_ok, 'reasons': dict(reasons), 'frames': frames})
    report = {'samples': len(results), 'all_original_24_have_sam': sum(r['selected_24_with_mask'] == 24 for r in results),
              'six_masked_views_each_camera': sum(all(n >= 6 for n in r['available_mask_frames_by_camera'].values()) for r in results),
              'rows': results, 'database_modified': False}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'sam_inventory.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}), flush=True)
    for row in results:
        print(json.dumps({k: v for k, v in row.items() if k != 'frames'}), flush=True)


if __name__ == '__main__':
    main()
