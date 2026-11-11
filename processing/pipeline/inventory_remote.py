import collections
import json
import re
from pathlib import Path

BASE = Path('D:/user_chao/greenhouse/data_pipeline')
BASE.mkdir(parents=True, exist_ok=True)
roots = [Path('E:/Lettuce 2D-3D'), Path('E:/lettuce 3D'), Path('E:/tomato')]
rows = []
captures = []
ply_files = []
csv_files = []
notes = []
for root in roots:
    if not root.exists():
        continue
    for branch in sorted(root.iterdir()):
        if branch.is_file():
            continue
        counts = collections.Counter()
        total = 0
        examples = []
        dates = set()
        for p in branch.rglob('*'):
            if not p.is_file():
                continue
            counts[p.suffix.lower()] += 1
            total += p.stat().st_size
            if len(examples) < 4:
                examples.append(str(p))
            hit = re.search(r'(20\d{2}-\d{2}-\d{2})[_ ](\d{2}[-:]\d{2}[-:]\d{2})', str(p))
            if hit:
                dates.add(hit[1])
            if p.suffix.lower() == '.ply':
                ply_files.append(str(p))
            elif p.suffix.lower() == '.csv':
                csv_files.append(str(p))
            elif p.suffix.lower() in ('.txt', '.xlsx', '.pptx', '.log'):
                notes.append(str(p))
            if re.match(r'CAM\d+_', p.name, re.I) and p.suffix.lower() in ('.jpg','.png','.jpeg') and '_originals' not in p.parts:
                captures.append(str(p))
        rows.append({'folder':str(branch),'files':sum(counts.values()),'GiB':round(total/2**30,3),
                     'extensions':dict(counts),'examples':examples,'dates':sorted(dates)})
result = {'branches':rows,'camera_images':captures,'ply_files':ply_files,'csv_files':csv_files,'notes':notes}
(BASE/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'branches':rows,'camera_images':len(captures),'ply_files':len(ply_files),'csv_files':len(csv_files),'notes':notes},ensure_ascii=False,indent=2))
for p in Path('E:/').glob('*.txt'):
    print('ROOT_NOTE', p.name)
    for encoding in ('utf-8-sig','cp950','utf-16'):
        try:
            print(p.read_text(encoding=encoding)[:12000])
            break
        except UnicodeError:
            pass
