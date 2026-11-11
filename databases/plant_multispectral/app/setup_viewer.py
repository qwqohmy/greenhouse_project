"""Provision a SELECT-only local viewer; do not publish a tunnel."""
import json
import secrets
from database import BASE,connect
from prepare_dataset import write


def main():
    private=BASE/'.private';private.mkdir(exist_ok=True)
    path=private/'viewer.json'
    existed=path.exists()
    settings=json.loads(path.read_text(encoding='utf-8')) if existed else {
        'reader_user':'spectral_viewer','reader_password':secrets.token_urlsafe(36),
        'share_token':secrets.token_urlsafe(24),'web_port':8078}
    connection=connect(admin=True,database=None)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM mysql.user WHERE User='spectral_viewer' AND Host='localhost'")
            user_exists=bool(cur.fetchone()[0])
            if user_exists and not existed:raise RuntimeError('Existing viewer user without its private configuration; refusing password reset.')
            if not user_exists:cur.execute("CREATE USER 'spectral_viewer'@'localhost' IDENTIFIED BY %s",(settings['reader_password'],))
            cur.execute("GRANT SELECT ON plant_multispectral.* TO 'spectral_viewer'@'localhost'")
        connection.commit()
    finally:connection.close()
    write(path,settings)
    write(BASE/'web-runtime'/'local_preview.json',{
        'url':'http://127.0.0.1:'+str(settings['web_port'])+'/s/'+settings['share_token']+'/',
        'access':'Private localhost preview via SSH forwarding; no public tunnel.',
        'remote_port':settings['web_port'],'public':False})
    print(json.dumps({'configured':True,'port':settings['web_port'],'database_access':'SELECT only','public':False}),flush=True)


if __name__=='__main__':main()
