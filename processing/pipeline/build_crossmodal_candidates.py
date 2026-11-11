import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
manifest = json.loads((ROOT/'plant-project-staging/manifest.json').read_text(encoding='utf-8'))
spectral = json.loads((ROOT/'remote_snapshot/segmentation_manifest_latest.json').read_text(encoding='utf-8'))
rows = []
for group in manifest['groups']:
    cid = group['capture_id']
    if not ('2026-06-18' <= cid[:10] <= '2026-06-30'):
        continue
    for folder in spectral['folders']:
        for capture in folder.get('captures',[]):
            stamp = capture.get('timestamp','')
            if stamp[:10] != cid[:10] or capture.get('light_condition') != 'A-1' or 11 not in capture.get('plant_numbers',[]):
                continue
            out = 'D:/user_chao/greenhouse/plant_seg/segmented_dataset/A-1/'+stamp+'/plant-11'
            rows.append({'crop':'lettuce','batch':'legacy_run1','rgb_capture_id':cid,
                         'vendor_csv':group['csv_path'],'spectral_capture_id':stamp,'spectral_plant_directory':out,
                         'light_condition_candidate':'A-1','plant_number_candidate':11,
                         'evidence':'PPT slide4 late first-run single-pot A1-11 + same-day spectral layout snapshot',
                         'match_status':'MATCH_CANDIDATE','train_eligible':False,
                         'remaining_check':'Verify actual RGB/PLY identity, layout reading, source CSV scope and live spectral metadata'})
path = ROOT/'greenhouse_pipeline/crossmodal_candidates.csv'
with path.open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print('Crossmodal candidates:',len(rows))
