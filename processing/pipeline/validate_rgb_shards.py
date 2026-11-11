"""Verify actual source partition before replacing the production worker."""
import json
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parent


def manifest(count,index):
    command=[sys.executable,str(BASE/'segment_rgb_batch.py'),'--all-frames','--dry-run',
             '--shard-count',str(count),'--shard-index',str(index),'--run-id','validation','--capture-set',capture_set]
    return json.loads(subprocess.check_output(command,encoding='utf-8'))


count=int(sys.argv[1]) if len(sys.argv)>1 else 2
capture_set=sys.argv[2] if len(sys.argv)>2 else 'all'
assert count in (2,3)
full=manifest(1,0)
parts=[manifest(count,index) for index in range(count)]
sets=[set(part['jobs']) for part in parts]
policy=json.loads((BASE/'rgb_processing_policy.json').read_text(encoding='utf-8'))
catalog=json.loads((BASE/'capture_catalog.json').read_text(encoding='utf-8'))
selected=[group for group in catalog if group['capture_id'] not in policy['hold_capture_ids'] and
          (capture_set=='all' or group['capture_id'] in policy['confirmed_tomato_capture_ids'])]
assert len(full['jobs'])==sum(sum(group['camera_counts'].values()) for group in selected)
assert all(len(values)==len(part['jobs']) for values,part in zip(sets,parts))
assert sum(map(len,sets))==len(set.union(*sets))
assert set.union(*sets)==set(full['jobs'])
held=set(json.loads((BASE/'rgb_processing_policy.json').read_text(encoding='utf-8'))['hold_capture_ids'])
assert not any(capture in source for source in set.union(*sets) for capture in held)
result={'passed':True,'workers':count,'capture_set':capture_set,'capture_groups':len(selected),'total':len(full['jobs']),'shard_sizes':list(map(len,sets)),'overlap':0,'held_capture_groups':len(held)}
(BASE/'rgb_shard_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
