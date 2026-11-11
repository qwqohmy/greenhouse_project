"""Apply explicit user crop confirmation while retaining original catalog fields."""
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent
policy=json.loads((BASE/'rgb_processing_policy.json').read_text(encoding='utf-8'))
catalog=json.loads((BASE/'capture_catalog.json').read_text(encoding='utf-8'))
ids=set(policy['confirmed_tomato_capture_ids'])
changed=[]
for group in catalog:
    if group['capture_id'] in ids:
        group.setdefault('catalog_crop_before_confirmation',group.get('crop'))
        group.setdefault('catalog_dataset_before_confirmation',group.get('dataset_id'))
        group.update(crop='tomato',dataset_id='tomato_rgb_user_confirmed_202610',
                     crop_identity_source=policy['tomato_confirmation_source'],crop_identity_status='USER_CONFIRMED',
                     crop_batch_candidate='tomato_run2')
        changed.append(group['capture_id'])
assert set(changed)==ids
(BASE/'capture_catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'confirmed_tomato':changed,'count':len(changed)}))
