import csv
import json
from pathlib import Path

base = Path(__file__).resolve().parent
summary = json.loads((base/'catalog_summary.json').read_text(encoding='utf-8'))
captures = json.loads((base/'capture_catalog.json').read_text(encoding='utf-8'))
traits = json.loads((base/'ply_derived_traits.json').read_text(encoding='utf-8'))
assert summary['capture_groups'] == len(captures)
assert len({g['folder'] for g in captures}) == len(captures)
assert sum(sum(map(len,g['selected_images'].values())) for g in captures) == summary['selected_images']
assert all(not r['train_eligible'] for r in traits)
assert all(r['label_source']=='PLY_DERIVED' for r in traits)
assert all(r['pTLA'] is None and r['pCHA'] is None for r in traits if r['status']=='COMPUTED_NEEDS_REVIEW')
assert {g['capture_id'] for g in captures if g['match_status']=='MATCH_CONFLICT'} == {'2026-07-21_14-51-25','2026-07-21_15-14-20'}
with (base/'pair_candidates.csv').open(encoding='utf-8-sig') as f:
    pairs = list(csv.DictReader(f))
assert all(r['match_status']!='MATCH_CONFIRMED' for r in pairs)
counts = json.loads((base/'spectral_counts.json').read_text(encoding='utf-8'))
assert counts['lettuce_raw']['spectral_band_images']==16*counts['lettuce_raw']['complete_16_band_groups']
assert counts['tomato_raw']['spectral_band_images']==16*counts['tomato_raw']['complete_16_band_groups']+1
print('PASS: source catalog, derived provenance, null unavailable targets, conflict quarantine, candidate-only joins and spectral counts')
