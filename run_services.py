"""Single-instance hosting entrypoint. Supervises web + maintenance on one disk."""
import os,sys,time,signal,subprocess,pathlib
from shifttap.db import migrate

def main():
    path=os.environ.get('DB_PATH','data/shifttap.sqlite');folder=os.environ.get('BACKUP_DIR','backups')
    pathlib.Path(folder).mkdir(parents=True,exist_ok=True);migrate(path)
    commands=[
        [sys.executable,'-m','gunicorn','--bind','0.0.0.0:'+os.environ.get('PORT','8000'),'--workers','2','--threads','2','--timeout','30','wsgi:app'],
        [sys.executable,'maintenance.py']
    ]
    children=[subprocess.Popen(c) for c in commands];stopping=False
    def stop(_signal=None,_frame=None):
        nonlocal stopping
        stopping=True
        for p in children:
            if p.poll() is None:p.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while not stopping:
            if any(p.poll() is not None for p in children):
                print('A service stopped; shutting down so the host can restart both.',file=sys.stderr);stop();return 1
            time.sleep(1)
        return 0
    finally:
        stop()
        for p in children:
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:p.kill();p.wait()
if __name__=='__main__':raise SystemExit(main())
