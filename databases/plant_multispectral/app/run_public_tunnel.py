"""Supervise the explicitly authorized public read-only multispectral tunnel."""
import json
from pathlib import Path
import re
import subprocess
import time
from database import BASE
from prepare_dataset import write


def main():
    settings=json.loads((BASE/'.private'/'viewer.json').read_text(encoding='utf-8'))
    permission=json.loads((BASE/'web-runtime'/'public_access.json').read_text(encoding='utf-8-sig'))
    if not permission.get('enabled'):raise RuntimeError('Public access has not been enabled by the operator.')
    binary=Path(permission['cloudflared_binary'])
    runtime=BASE/'web-runtime'
    while True:
        with (runtime/'public-tunnel.log').open('a',encoding='utf-8') as log:
            process=subprocess.Popen([str(binary),'tunnel','--no-autoupdate','--protocol','http2',
                '--url','http://127.0.0.1:'+str(settings['web_port'])],stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
            for line in process.stdout:
                log.write(line);log.flush()
                match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
                if match:
                    write(runtime/'public_share_link.json',{'url':match.group()+'/s/'+settings['share_token']+'/',
                        'tunnel_origin':match.group(),'pid':process.pid,'public':True,'temporary':True,
                        'authorized_scope':'SAM single-plant multispectral viewer, images, NDVI and CSV export.',
                        'updated_at':time.strftime('%Y-%m-%d %H:%M:%S')})
            log.write('Tunnel exited '+str(process.wait())+'; retrying in 10 seconds.\n');log.flush()
        time.sleep(10)


if __name__=='__main__':main()
