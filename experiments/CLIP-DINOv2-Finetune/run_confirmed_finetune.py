"""Run grouped evaluation and final fits serially, preserving logs and status."""
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN = BASE / 'outputs' / 'confirmed_finetune_20261111'


def status(data):
    RUN.mkdir(parents=True, exist_ok=True)
    tmp = RUN / 'status.tmp'
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(RUN / 'status.json')


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    state = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
             'epochs': 20, 'near_time_included': False, 'completed': [], 'current': None}
    try:
        for labels, mode in [('proxy', 'cv'), ('native', 'cv'), ('proxy', 'fit'), ('native', 'fit')]:
            name = labels + '_' + mode
            output = RUN / name
            if (output / 'result.json').exists():
                raise RuntimeError('Existing result requires a new run directory: ' + name)
            command = [sys.executable, '-u', str(BASE / 'train_user_confirmed.py'),
                       '--labels', labels, '--mode', mode, '--epochs', '20',
                       '--allow-unverified-labels', '--output', str(output)]
            state.update(current=name, current_started_at=datetime.now(timezone.utc).isoformat())
            status(state)
            with (RUN / (name + '.log')).open('w', encoding='utf-8') as log:
                proc = subprocess.Popen(command, cwd=BASE, stdout=log, stderr=subprocess.STDOUT)
                state['child_pid'] = proc.pid
                status(state)
                code = proc.wait()
            if code:
                raise RuntimeError(name + ' failed with exit code ' + str(code))
            result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            if result['status'] != mode + '_completed':
                raise RuntimeError('Unexpected result: ' + name)
            state['completed'].append({'job': name, 'result': str(output / 'result.json')})
        state.update(status='completed', current=None, finished_at=datetime.now(timezone.utc).isoformat())
        status(state)
    except Exception:
        state.update(status='failed', error=traceback.format_exc())
        status(state)
        raise


if __name__ == '__main__':
    main()
