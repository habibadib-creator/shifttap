import os,time,smtplib,ssl,email.message,pathlib,logging
from shifttap.db import connect,migrate,row,transaction,now,audit
from shifttap.security import cipher
from manage import backup
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')

def tick():
    path=os.environ.get('DB_PATH','data/shifttap.sqlite');db=connect(path);crypt=cipher(os.environ['APP_SECRET'])
    try:
        # One maintenance process only. At-least-once SMTP delivery; expired links remain harmless.
        pending=db.execute('SELECT * FROM outbox WHERE sent IS NULL AND available<=? AND attempts<10 ORDER BY available LIMIT 20',(now(),)).fetchall()
        for m in pending:
            try:
                message=email.message.EmailMessage();message['From']=os.environ['SMTP_FROM'];message['To']=m['to_email'];message['Subject']=m['subject'];message['Message-ID']='<'+m['id']+'@shifttap.local>';message.set_content(crypt.decrypt(m['body_cipher'].encode()).decode())
                host=os.environ['SMTP_HOST'];port=int(os.environ.get('SMTP_PORT','587'));mode=os.environ.get('SMTP_MODE','starttls')
                if mode=='ssl':server=smtplib.SMTP_SSL(host,port,timeout=20,context=ssl.create_default_context())
                elif mode=='starttls':
                    server=smtplib.SMTP(host,port,timeout=20);server.ehlo();server.starttls(context=ssl.create_default_context());server.ehlo()
                else:raise RuntimeError('SMTP_MODE must be ssl or starttls')
                with server:
                    if os.environ.get('SMTP_USERNAME'):server.login(os.environ['SMTP_USERNAME'],os.environ['SMTP_PASSWORD'])
                    server.send_message(message)
                db.execute('UPDATE outbox SET sent=?,body_cipher=\'\',last_error=NULL WHERE id=?',(now(),m['id']))
            except Exception:
                logging.error('Email delivery failed for queue item %s; check SMTP configuration.',m['id'])
                db.execute('UPDATE outbox SET attempts=attempts+1,available=?,last_error=\'SMTP delivery failed\' WHERE id=?',(now()+min(3600,60*2**m['attempts']),m['id']))
        with transaction(db):
            db.execute('DELETE FROM sessions WHERE expires<? OR last_seen<?',(now(),now()-7*86400));db.execute('DELETE FROM tokens WHERE expires<?',(now(),));db.execute('DELETE FROM rate_limits WHERE expires<?',(now(),))
            db.execute('DELETE FROM outbox WHERE sent IS NOT NULL AND sent<?',(now()-7*86400,))
            settings=row(db,'SELECT * FROM settings WHERE id=1')
            db.execute('DELETE FROM location_events WHERE created<?',(now()-settings['location_retention_days']*86400,))
            # Attendance retention is opt-in; exclude open, unapproved or pending-correction shifts.
            if settings['retention_days']:
                cutoff=now()-settings['retention_days']*86400
                stale=db.execute("SELECT id FROM shifts WHERE ended<? AND approval='approved' AND id NOT IN(SELECT shift_id FROM corrections WHERE status='pending')",(cutoff,)).fetchall()
                for s in stale:
                    audit(db,'maintenance','retention_purge',s['id'],reason='Configured attendance retention elapsed')
                    db.execute('DELETE FROM corrections WHERE shift_id=?',(s['id'],));db.execute('DELETE FROM shifts WHERE id=?',(s['id'],))
        folder=pathlib.Path(os.environ.get('BACKUP_DIR','backups'));folder.mkdir(parents=True,exist_ok=True)
        latest=max((p.stat().st_mtime for p in folder.glob('*.sqlite.enc')),default=0)
        if time.time()-latest>86400:
            if not os.environ.get('BACKUP_KEY'):logging.error('BACKUP_KEY missing: automated backup did not run.')
            else:
                backup(path,str(folder),os.environ['BACKUP_KEY']);logging.info('Encrypted database backup completed.')
                cutoff=time.time()-settings['backup_retention_days']*86400
                for p in folder.glob('*.sqlite.enc'):
                    if p.stat().st_mtime<cutoff:p.unlink();p.with_suffix(p.suffix+'.sha256').unlink(missing_ok=True)
    finally:db.close()

if __name__=='__main__':
    migrate(os.environ.get('DB_PATH','data/shifttap.sqlite'))
    while True:
        try:tick()
        except Exception:logging.exception('Maintenance cycle failed; no success assumed.')
        time.sleep(60)
