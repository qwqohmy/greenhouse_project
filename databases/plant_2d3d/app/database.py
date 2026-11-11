"""MySQL connection helper. Password is supplied only through the environment."""
import os
import json
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parent
if (BASE/'.deps').exists():
    sys.path.insert(0,str(BASE/'.deps'))
import pymysql


def settings(readonly=False):
    deployment=json.loads((BASE/'deployment.json').read_text(encoding='utf-8')) if (BASE/'deployment.json').exists() else {}
    secret=json.loads(Path(deployment['credentials_file']).read_text(encoding='utf-8')) if deployment.get('credentials_file') else {}
    password=secret.get('viewer_password') if readonly else os.environ.get('MYSQL_PWD',secret.get('password'))
    if password is None:
        raise RuntimeError('Set MYSQL_PWD for this process; no password is stored in project files.')
    return {'host':os.environ.get('P3D_MYSQL_HOST',deployment.get('host','127.0.0.1')),
            'port':int(os.environ.get('P3D_MYSQL_PORT',deployment.get('port',3306))),
            'user':secret.get('viewer_user') if readonly else os.environ.get('P3D_MYSQL_USER',deployment.get('user','greenhouse')),
            'password':password,'database':os.environ.get('P3D_MYSQL_DATABASE',deployment.get('database','plant_2d3d'))}


def connect(readonly=False):
    return pymysql.connect(**settings(readonly),
        charset='utf8mb4',autocommit=False,connect_timeout=10,read_timeout=120,write_timeout=120)
