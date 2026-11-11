"""Serial paired-image ablation and final SAM fits; all artifacts remain private."""
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN = BASE / 'outputs' / 'sam_comparison_20261111'


def save(data):
    tmp = RUN/'status.tmp'
    tmp.write_text(json.dumps(data,indent=2),encoding='utf-8')
    tmp.replace(RUN/'status.json')


def main():
    RUN.mkdir(parents=True,exist_ok=True)
    if (RUN/'status.json').exists(): raise RuntimeError('Run already started; inspect existing status instead of overwriting.')
    jobs = [(label,variant,'cv') for label in ('proxy','native') for variant in ('original','sam','crop')]
    jobs += [(label,'sam','fit') for label in ('proxy','native')]
    state = {'status':'running','started_at':datetime.now(timezone.utc).isoformat(),
             'completed':[],'current':None,'epochs':20,'database_modified':False,'planned_jobs':len(jobs)}
    try:
        for label,variant,mode in jobs:
            name = '_'.join((label,variant,mode))
            state.update(current=name,current_started_at=datetime.now(timezone.utc).isoformat())
            save(state)
            command = [sys.executable,'-u',str(BASE/'train_sam_comparison.py'),
                       '--labels',label,'--variant',variant,'--mode',mode,'--epochs','20']
            with (RUN/(name+'.log')).open('w',encoding='utf-8') as log:
                proc = subprocess.Popen(command,cwd=BASE,stdout=log,stderr=subprocess.STDOUT)
                state['child_pid']=proc.pid;save(state)
                code = proc.wait()
            if code: raise RuntimeError(name+' failed; inspect its log. Exit='+str(code))
            result = json.loads((RUN/name/'result.json').read_text(encoding='utf-8'))
            assert result['status']==mode+'_completed'
            state['completed'].append(name);save(state)
        state.update(status='completed',current=None,finished_at=datetime.now(timezone.utc).isoformat())
        save(state)
    except Exception:
        state.update(status='failed',error=traceback.format_exc());save(state);raise


if __name__=='__main__':main()
