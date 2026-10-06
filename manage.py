#!/usr/bin/env python3
import argparse,os,pathlib,getpass,sqlite3,json,shutil,datetime,sys,hashlib,secrets
from shifttap.db import migrate,connect,row,transaction,uid,now,audit
from shifttap.security import cipher,hash_password
from shifttap.app import issue_email,email

def settings():
    path=os.environ.get('DB_PATH','data/shifttap.sqlite');secret=os.environ.get('APP_SECRET','')
    if len(secret)<32:raise SystemExit('APP_SECRET must contain at least 32 random characters.')
    return path,cipher(secret)

def backup(path,destination,key):
    from cryptography.fernet import Fernet
    out=pathlib.Path(destination);out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+secrets.token_hex(3)
    tmp=out/(stamp+'.tmp');db=connect(path);copy=sqlite3.connect(tmp)
    try:db.backup(copy)
    finally:copy.close();db.close()
    try:
        encrypted=Fernet(key.encode()).encrypt(tmp.read_bytes());target=out/('shifttap-'+stamp+'.sqlite.enc')
        target.write_bytes(encrypted);target.chmod(0o600)
        target.with_suffix(target.suffix+'.sha256').write_text(hashlib.sha256(encrypted).hexdigest()+'  '+target.name+'\n')
        return target
    finally:tmp.unlink(missing_ok=True)

def main():
    p=argparse.ArgumentParser(description='ShiftTap administration. Read README before production use.')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('migrate')
    owner=sub.add_parser('owner');owner.add_argument('--email',required=True);owner.add_argument('--name',required=True)
    boot=sub.add_parser('owner-local');boot.add_argument('--email',required=True);boot.add_argument('--name',required=True)
    back=sub.add_parser('backup');back.add_argument('--destination',default='backups')
    restore=sub.add_parser('restore');restore.add_argument('file');restore.add_argument('--confirm',required=True)
    recover=sub.add_parser('owner-recover');recover.add_argument('--email',required=True)
    sub.add_parser('export-data')
    a=p.parse_args();path,crypt=settings();migrate(path)
    db=connect(path)
    try:
        if a.command=='migrate':print('Migrations applied.')
        elif a.command in ['owner','owner-local']:
            address=email(a.email)
            if row(db,"SELECT 1 FROM users WHERE role='owner'"):raise SystemExit('An owner already exists. No changes made.')
            if a.command=='owner-local' and (os.environ.get('APP_URL','').startswith('https://') or os.environ.get('ALLOW_LOCAL_OWNER')!='yes'):raise SystemExit('Local-only bootstrap requires ALLOW_LOCAL_OWNER=yes and localhost APP_URL.')
            if a.command=='owner-local' and not os.environ.get('APP_URL','').startswith(('http://localhost:','http://127.0.0.1:')):raise SystemExit('Local bootstrap requires a loopback origin.')
            hashed=None
            if a.command=='owner-local':
                password=getpass.getpass('Owner password (12+ characters): ')
                if password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords did not match.')
                hashed=hash_password(password)
            elif not os.environ.get('SMTP_HOST'):raise SystemExit('Configure SMTP before creating the production owner.')
            with transaction(db):
                who=uid();db.execute('INSERT INTO users(id,email,name,role,password_hash,verified,created) VALUES(?,?,?,?,?,?,?)',(who,address,a.name,'owner',hashed,int(a.command=='owner-local'),now()))
                if a.command=='owner':issue_email(db,crypt,(os.environ.get('APP_URL') or os.environ.get('RENDER_EXTERNAL_URL','')).rstrip('/'),row(db,'SELECT * FROM users WHERE id=?',(who,)),'activate')
                audit(db,'console','owner_created',who)
            print('Owner created. Activation email queued.' if a.command=='owner' else 'Local owner created. Do not use this database for production.')
        elif a.command=='backup':
            key=os.environ.get('BACKUP_KEY','')
            if not key:raise SystemExit('Configure BACKUP_KEY first.')
            print(backup(path,a.destination,key))
        elif a.command=='restore':
            if a.confirm!='STOPPED-AND-BACKED-UP':raise SystemExit('Stop web and maintenance services, then confirm STOPPED-AND-BACKED-UP.')
            from cryptography.fernet import Fernet
            key=os.environ.get('BACKUP_KEY','');data=Fernet(key.encode()).decrypt(pathlib.Path(a.file).read_bytes())
            temp=pathlib.Path(path+'.restore');temp.write_bytes(data)
            check=sqlite3.connect(temp)
            try:
                if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Backup integrity check failed.')
                if check.execute("SELECT count(*) FROM sqlite_master WHERE name='users'").fetchone()[0]!=1:raise SystemExit('Invalid backup.')
                check.execute('DELETE FROM sessions');check.execute('DELETE FROM tokens');check.execute('DELETE FROM outbox WHERE sent IS NULL');check.commit()
            finally:check.close()
            db.close();shutil.copy2(path,path+'.pre-restore')
            for suffix in ['-wal','-shm']:pathlib.Path(path+suffix).unlink(missing_ok=True)
            os.replace(temp,path);print('Database restored. Sessions and pending auth emails invalidated. Restart services and check records.')
        elif a.command=='owner-recover':
            u=row(db,"SELECT * FROM users WHERE role='owner' AND email=?",(email(a.email),))
            if not u:raise SystemExit('Owner not found.')
            if input('Type RECOVER-OWNER to disable MFA and revoke sessions: ')!='RECOVER-OWNER':raise SystemExit('Cancelled.')
            with transaction(db):
                db.execute('UPDATE users SET totp_secret=NULL,totp_last_step=-1 WHERE id=?',(u['id'],));db.execute('DELETE FROM recovery_codes WHERE user_id=?',(u['id'],));db.execute('DELETE FROM sessions WHERE user_id=? OR pending_user=?',(u['id'],u['id']));audit(db,'console','owner_mfa_recovery',u['id'],reason='Console operator recovery')
            print('MFA reset. Use verified email password reset if necessary, then enrol MFA again.')
        elif a.command=='export-data':
            # Intentionally excludes passwords, sessions, reset tokens, tag secrets and email bodies.
            tables=['memberships','shifts','breaks','corrections','exceptions','audit','location_events','settings']
            result={t:[dict(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
            result['users']=[dict(r) for r in db.execute('SELECT id,email,name,role,active,verified,created FROM users')]
            result['stores']=[dict(r) for r in db.execute('SELECT id,name,address,timezone,archived,latitude,longitude,radius,max_accuracy,location_required FROM stores')]
            print(json.dumps(result,indent=2))
    finally:
        try:db.close()
        except Exception:pass
if __name__=='__main__':main()
