"""Create a fresh SELECT-only account and local settings; never commit them."""
import json
import os
from pathlib import Path
import secrets
import re
import pymysql

BASE=Path(__file__).resolve().parent


def main():
    private=BASE/'.private';private.mkdir(exist_ok=True);settings=private/'viewer.json'
    if settings.exists() or (BASE/'deployment.json').exists():raise RuntimeError('Local settings already exist; refusing to overwrite.')
    db=os.environ.get('P3D_MYSQL_DATABASE','plant_2d3d');reader='plant_viewer_'+secrets.token_hex(4)
    if not re.fullmatch('[A-Za-z0-9_]+',db):raise ValueError('Invalid database name')
    secret={'viewer_user':reader,'viewer_password':secrets.token_urlsafe(36),'share_token':secrets.token_urlsafe(24)}
    host=os.environ.get('P3D_MYSQL_HOST','127.0.0.1');port=int(os.environ.get('P3D_MYSQL_PORT','3306'))
    connection=pymysql.connect(host=host,port=port,user='root',password=os.environ['MYSQL_ROOT_PASSWORD'])
    try:
        with connection.cursor() as cur:
            cur.execute('CREATE USER %s@localhost IDENTIFIED BY %s',(reader,secret['viewer_password']))
            cur.execute('GRANT SELECT ON `'+db+'`.* TO %s@localhost',(reader,))
        connection.commit()
    finally:connection.close()
    settings.write_text(json.dumps(secret,indent=2),encoding='utf-8')
    deploy={'host':host,'port':port,'database':db,'user':os.environ.get('P3D_MYSQL_USER','greenhouse'),
            'credentials_file':str(settings),'web_port':int(os.environ.get('P3D_WEB_PORT','8077'))}
    (BASE/'deployment.json').write_text(json.dumps(deploy,indent=2),encoding='utf-8')
    print('http://127.0.0.1:'+str(deploy['web_port'])+'/s/'+secret['share_token']+'/')


if __name__=='__main__':main()
