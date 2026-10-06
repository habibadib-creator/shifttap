"""Loopback-only disposable integration fixture. Never a production entrypoint."""
import pathlib,tempfile,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
from shifttap.app import create_app
from shifttap.db import connect,now
from shifttap.security import cipher,digest,hash_password
from werkzeug.serving import make_server,WSGIRequestHandler
class Quiet(WSGIRequestHandler):
 def log_request(self,*args,**kwargs):pass
 def log_error(self,*args,**kwargs):pass
with tempfile.TemporaryDirectory() as tmp:
 path=str(pathlib.Path(tmp)/'test.sqlite');secret='test-fixture-secret-'+'x'*64
 app=create_app({'TESTING':True,'APP_SECRET':secret,'DB_PATH':path,'APP_URL':'http://localhost:8901','COOKIE_SECURE':False,'SMTP_HOST':'mail.test'})
 db=connect(path);hashed=hash_password('FixturePassword123!')
 for uid,email,name,role in [('owner','owner@test.com','Test Owner','owner'),('staff','staff@test.com','Test Staff','staff')]:db.execute('INSERT INTO users(id,email,name,role,password_hash,verified,created) VALUES(?,?,?,?,?,1,?)',(uid,email,name,role,hashed,now()))
 db.execute('INSERT INTO stores(id,name,address,tag_hash,tag_cipher) VALUES(?,?,?,?,?)',('store','Test Location','Sydney',digest('fixture-tag'),cipher(secret).encrypt(b'fixture-tag').decode()))
 db.execute('INSERT INTO memberships VALUES(?,?)',('staff','store'));db.close()
 server=make_server('127.0.0.1',8901,app,request_handler=Quiet);print('FIXTURE_READY',flush=True)
 try:server.serve_forever()
 finally:server.server_close()
