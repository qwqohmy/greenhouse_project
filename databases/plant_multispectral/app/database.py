"""MySQL configuration supplied by environment; no workstation credentials."""
import os
from pathlib import Path
import pymysql

BASE=Path(__file__).resolve().parent
DB_NAME=os.environ.get('SPECTRAL_DB_NAME','plant_multispectral')


def private_settings():
    return {'host':os.environ.get('MYSQL_HOST','127.0.0.1'),'port':int(os.environ.get('MYSQL_PORT','3306'))}, {
        'password':os.environ.get('MYSQL_PWD'),'root_password':os.environ.get('MYSQL_ROOT_PASSWORD')}


def connect(admin=False,read_only=False,database=DB_NAME):
    deployment,secret=private_settings();password=secret['root_password' if admin else 'password']
    if password is None:raise RuntimeError('Set MYSQL_ROOT_PASSWORD (admin) or MYSQL_PWD (application) in this process.')
    connection=pymysql.connect(**deployment,user='root' if admin else os.environ.get('MYSQL_USER','greenhouse'),
        password=password,database=database,charset='utf8mb4',autocommit=False,connect_timeout=15,read_timeout=180,write_timeout=180)
    if read_only:
        with connection.cursor() as cur:cur.execute('SET SESSION TRANSACTION READ ONLY')
    return connection
