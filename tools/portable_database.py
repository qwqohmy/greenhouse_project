"""Read-only MySQL export and restore into an EMPTY database. Never embeds passwords."""
import argparse
import base64
import datetime
import decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import pymysql


def ident(name):
    return '`'+name.replace('`','``')+'`'


class PortablePaths:
    def __init__(self, roots=None):
        self.roots=sorted((roots or {}).items(),key=lambda x:-len(x[0]))
    def clean(self, value):
        if isinstance(value,dict):
            return {k:('[REDACTED]' if re.search(r'password|secret|share_token|access_token',k,re.I) else self.clean(v)) for k,v in value.items()}
        if isinstance(value,list):return [self.clean(v) for v in value]
        if not isinstance(value,str):return value
        if value[:1] in ('{','['):
            try:return json.dumps(self.clean(json.loads(value)),ensure_ascii=False,separators=(',',':'))
            except (ValueError,TypeError):pass
        for root,placeholder in self.roots:
            pattern=re.escape(root.replace('\\','/')).replace('/',r'[/\\]')
            value=re.sub(pattern,lambda m:placeholder,value,flags=re.I)
        value=re.sub(r'[A-Za-z]:[/\\]Users[/\\][^/\\"\s]+','${USER_HOME}',value,flags=re.I)
        value=re.sub(r'https?://[^\s"<>]*trycloudflare\.com[^\s"<>]*','[TEMPORARY_LINK_REMOVED]',value)
        return value


def encode(value,clean):
    if isinstance(value,bytes):return {'__bytes__':base64.b64encode(value).decode('ascii')}
    if isinstance(value,(datetime.datetime,datetime.date,datetime.time,decimal.Decimal)):return str(value)
    if isinstance(value,datetime.timedelta):return str(value)
    return clean(value)


def decode(value,paths):
    if isinstance(value,dict) and set(value)=={'__bytes__'}:return base64.b64decode(value['__bytes__'])
    if isinstance(value,str):
        for key,replacement in paths.items():value=value.replace('${'+key+'}',replacement)
    return value


def export_database(connection,destination,roots=None,exclude_prefixes=()):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    cleaner=PortablePaths(roots);manifest={'format_version':1,'source_data_modified':False,'paths_are_placeholders':True,'tables':[],'views':[]}
    with connection.cursor() as cur:
        cur.execute('SELECT DATABASE()');db=cur.fetchone()[0]
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        cur.execute('SHOW FULL TABLES');objects=cur.fetchall()
        for name,kind in objects:
            if any(name.startswith(p) for p in exclude_prefixes):continue
            cur.execute('SHOW CREATE '+('VIEW ' if kind=='VIEW' else 'TABLE ')+ident(name));ddl=cur.fetchone()[1]
            ddl=re.sub(r'DEFINER=`[^`]*`@`[^`]*`\s*','',ddl)
            ddl=ddl.replace('SQL SECURITY DEFINER','SQL SECURITY INVOKER').replace(ident(db)+'.','')
            if kind=='VIEW':manifest['views'].append({'name':name,'ddl':ddl});continue
            cur.execute('SELECT * FROM '+ident(name));columns=[d[0] for d in cur.description]
            file=destination/(name+'.jsonl.gz');count=0
            with gzip.open(file,'wt',encoding='utf-8',newline='\n') as stream:
                while True:
                    rows=cur.fetchmany(1000)
                    if not rows:break
                    for row in rows:
                        stream.write(json.dumps([encode(v,cleaner.clean) for v in row],ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n');count+=1
            manifest['tables'].append({'name':name,'columns':columns,'ddl':ddl,'rows':count,'file':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    connection.rollback()
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (destination/'schema.sql').write_text('SET FOREIGN_KEY_CHECKS=0;\n'+';\n'.join(x['ddl'] for x in manifest['tables']+manifest['views'])+';\nSET FOREIGN_KEY_CHECKS=1;\n',encoding='utf-8')
    return {t['name']:t['rows'] for t in manifest['tables']}


def restore_database(connection,source,paths=None):
    source=Path(source);manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    for t in manifest['tables']:
        if hashlib.sha256((source/t['file']).read_bytes()).hexdigest()!=t['sha256']:raise ValueError('Checksum mismatch: '+t['name'])
    with connection.cursor() as cur:
        cur.execute('SHOW TABLES')
        if cur.fetchone():raise RuntimeError('Restore requires an EMPTY database; existing data will never be overwritten.')
        cur.execute('SET FOREIGN_KEY_CHECKS=0')
        for t in manifest['tables']:cur.execute(t['ddl'])
        for t in manifest['tables']:
            sql='INSERT INTO '+ident(t['name'])+' ('+','.join(map(ident,t['columns']))+') VALUES ('+','.join(['%s']*len(t['columns']))+')'
            batch=[]
            with gzip.open(source/t['file'],'rt',encoding='utf-8') as stream:
                for line in stream:
                    batch.append([decode(v,paths or {}) for v in json.loads(line)])
                    if len(batch)==1000:cur.executemany(sql,batch);batch=[]
                if batch:cur.executemany(sql,batch)
            cur.execute('SELECT COUNT(*) FROM '+ident(t['name']))
            if cur.fetchone()[0]!=t['rows']:raise AssertionError('Count mismatch: '+t['name'])
        remaining=list(manifest['views'])
        while remaining:
            failed=[]
            for view in remaining:
                try:cur.execute(view['ddl'])
                except pymysql.MySQLError:failed.append(view)
            if len(failed)==len(remaining):raise RuntimeError('Could not restore dependent views')
            remaining=failed
        cur.execute('SET FOREIGN_KEY_CHECKS=1')
    connection.commit()
    return {t['name']:t['rows'] for t in manifest['tables']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['export','restore'])
    p.add_argument('--database',required=True);p.add_argument('--directory',required=True,type=Path)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',default=3306,type=int);p.add_argument('--user',required=True)
    p.add_argument('--password-env',default='MYSQL_PWD');p.add_argument('--path-map',type=Path)
    p.add_argument('--exclude-prefix',action='append',default=[]);args=p.parse_args()
    password=os.environ.get(args.password_env)
    if password is None:raise RuntimeError('Supply the password using '+args.password_env)
    paths=json.loads(args.path_map.read_text(encoding='utf-8')) if args.path_map else {}
    c=pymysql.connect(host=args.host,port=args.port,user=args.user,password=password,database=args.database,charset='utf8mb4',autocommit=False)
    try:
        result=export_database(c,args.directory,paths,args.exclude_prefix) if args.action=='export' else restore_database(c,args.directory,paths)
        print(json.dumps(result,ensure_ascii=False))
    finally:c.close()


if __name__=='__main__':main()
