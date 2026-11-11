"""Durable supervisor for disjoint SAM shards, with aggregate progress."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parent


def save(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(100):
        try:
            os.replace(temp,path)
            return
        except PermissionError:
            if attempt==99:
                raise
            time.sleep(.02)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,choices=(2,3),default=2)
    parser.add_argument('--capture-set',choices=('all','tomato_confirmed'),default='all')
    args=parser.parse_args()
    run_id='p'+str(time.time_ns())
    worker_state={'status':'starting','run_id':run_id,'workers':args.workers,'launcher_pid':os.getpid(),
                  'capture_set':args.capture_set,
                  'started_at':time.strftime('%Y-%m-%d %H:%M:%S'),'processes':[]}
    handles=[];workers=[]
    for index in range(args.workers):
        suffix=f'{run_id}_shard_{index}'
        stdout=(BASE/(suffix+'.stdout.log')).open('w',encoding='utf-8')
        stderr=(BASE/(suffix+'.stderr.log')).open('w',encoding='utf-8')
        handles.extend([stdout,stderr])
        process=subprocess.Popen([sys.executable,'-X','utf8','-u',str(BASE/'segment_rgb_batch.py'),
                   '--all-frames','--shard-count',str(args.workers),'--shard-index',str(index),'--run-id',run_id,
                   '--capture-set',args.capture_set],
                   cwd=BASE,stdout=stdout,stderr=stderr)
        status=BASE/('segmentation_'+suffix+'_status.json')
        workers.append((process,status))
        worker_state['processes'].append({'shard_index':index,'pid':process.pid,'status_path':str(status)})
    worker_state['status']='running';save(BASE/'segmentation_worker.json',worker_state)
    try:
        while True:
            states=[]
            for process,path in workers:
                if path.exists():
                    try:
                        states.append(json.loads(path.read_text(encoding='utf-8')))
                    except (OSError,json.JSONDecodeError):
                        pass
            live=[process.poll() is None for process,_ in workers]
            codes=[process.poll() for process,_ in workers]
            failed=any(code not in (None,0) for code in codes)
            complete=not any(live)
            aggregate={'status':('failed' if failed else 'complete_with_review') if complete else ('running_with_failed_shard' if failed else 'running'),
                       'algorithm':'sam31_rgb_roi_v4','execution':'disjoint_shards','workers':args.workers,
                       'run_id':run_id,'all_frames':True,'started_at':worker_state['started_at'],
                       'capture_set':args.capture_set,
                       'updated_at':time.strftime('%Y-%m-%d %H:%M:%S'),'shards_reporting':len(states),
                       'total_images':max((state['global_total_images'] for state in states),default=26160),
                       'held_capture_groups':max((state['held_capture_groups'] for state in states),default=11),
                       'processed_capture_groups':max((state['processed_capture_groups'] for state in states),default=109),
                       'shards':states,'exit_codes':codes}
            for key in ('done','reused','instances','no_detection','errors'):
                aggregate[key]=sum(state.get(key,0) for state in states)
            aggregate['new_images_this_run']=aggregate['done']-aggregate['reused']
            save(BASE/'segmentation_batch_status.json',aggregate)
            if complete:
                worker_state.update(status=aggregate['status'],exit_codes=codes,finished_at=aggregate['updated_at'])
                save(BASE/'segmentation_worker.json',worker_state)
                return
            time.sleep(2)
    finally:
        for handle in handles:
            handle.close()


if __name__=='__main__':
    main()
