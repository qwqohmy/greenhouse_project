import json
import os
from pathlib import Path
import subprocess
import sys
import time

base=Path(__file__).resolve().parent
state={'status':'starting','launcher_pid':os.getpid(),'started_at':time.strftime('%Y-%m-%d %H:%M:%S')}
(base/'segmentation_worker.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
with (base/'segmentation_full.stdout.log').open('w',encoding='utf-8') as out, (base/'segmentation_full.stderr.log').open('w',encoding='utf-8') as err:
    worker=subprocess.Popen([sys.executable,'-X','utf8','-u',str(base/'segment_rgb_batch.py'),'--all-frames'],cwd=base,stdout=out,stderr=err)
    state.update(status='running',worker_pid=worker.pid)
    (base/'segmentation_worker.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    code=worker.wait()
state.update(status='exited',exit_code=code,finished_at=time.strftime('%Y-%m-%d %H:%M:%S'))
(base/'segmentation_worker.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
