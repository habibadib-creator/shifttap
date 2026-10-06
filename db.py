import sqlite3, pathlib, time, json, uuid, fcntl, os
from contextlib import contextmanager

def connect(path):
    db=sqlite3.connect(path,timeout=15,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=15000')
    return db

def migrate(path):
    pathlib.Path(path).parent.mkdir(parents=True,exist_ok=True)
    with open(path+'.migration-lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        db=connect(path)
        try:
            os.chmod(path,0o600)
            db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY,applied INTEGER NOT NULL)')
            for file in sorted((pathlib.Path(__file__).resolve().parent.parent/'migrations').glob('*.sql')):
                if not db.execute('SELECT 1 FROM schema_migrations WHERE name=?',(file.name,)).fetchone():
                    name=file.name.replace("'","''")
                    db.executescript('BEGIN IMMEDIATE;\n'+file.read_text()+f"\nINSERT INTO schema_migrations VALUES('{name}',{int(time.time())});\nCOMMIT;")
        finally:db.close()

@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:yield;db.execute('COMMIT')
    except BaseException:db.execute('ROLLBACK');raise

def uid():return str(uuid.uuid4())
def now():return int(time.time())
def row(db,sql,args=()):
    r=db.execute(sql,args).fetchone();return dict(r) if r else None

def rows(db,sql,args=()):return [dict(r) for r in db.execute(sql,args).fetchall()]
def audit(db,actor,kind,entity,before=None,after=None,reason=''):
    db.execute('INSERT INTO audit(actor_id,kind,entity_id,before_json,after_json,reason,created) VALUES(?,?,?,?,?,?,?)',(actor,kind,entity,json.dumps(before) if before is not None else None,json.dumps(after) if after is not None else None,reason,now()))
