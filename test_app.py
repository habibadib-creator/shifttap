import unittest,tempfile,pathlib,json,sqlite3,datetime,concurrent.futures
from shifttap.app import create_app
from shifttap.db import connect,row,rows,now
from shifttap.security import cipher,digest,hash_password,totp,match_totp,location_result,Problem
from shifttap.attendance import clock,correct,worked,bounds
class ShiftTapTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(pathlib.Path(self.tmp.name)/'test.sqlite');self.secret='a'*64
  self.app=create_app({'TESTING':True,'DB_PATH':self.path,'APP_URL':'http://localhost:8000','COOKIE_SECURE':False,'APP_SECRET':self.secret,'SMTP_HOST':'mail.test'})
  self.db=connect(self.path);hashed=hash_password('VeryGoodPassword123!')
  for uid,role in [('owner','owner'),('manager','manager'),('alice','staff'),('bob','staff')]:self.db.execute('INSERT INTO users(id,email,name,role,password_hash,verified,created) VALUES(?,?,?,?,?,1,?)',(uid,uid+'@test.com',uid,role,hashed,now()))
  crypt=cipher(self.secret)
  for sid,tag in [('store1','tag-one'),('store2','tag-two')]:self.db.execute('INSERT INTO stores(id,name,address,tag_hash,tag_cipher) VALUES(?,?,?,?,?)',(sid,sid,'Sydney',digest(tag),crypt.encrypt(tag.encode()).decode()))
  for who,sid in [('alice','store1'),('alice','store2'),('bob','store2'),('manager','store1')]:self.db.execute('INSERT INTO memberships VALUES(?,?)',(who,sid))
  self.client=self.app.test_client();self.csrf=None
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def login(self,who='alice',client=None):
  c=client or self.client;csrf=c.get('/api/session').json['csrf'];r=c.post('/api/login',json={'email':who+'@test.com','password':'VeryGoodPassword123!'},headers={'Origin':'http://localhost:8000','X-CSRF-Token':csrf});self.assertEqual(r.status_code,200,r.json);s=c.get('/api/session').json
  if not client:self.csrf=s['csrf']
  return s['csrf']
 def post(self,path,payload,client=None,csrf=None):return (client or self.client).post(path,json=payload,headers={'Origin':'http://localhost:8000','X-CSRF-Token':csrf or self.csrf or ''})
 def alice(self):return row(self.db,"SELECT * FROM users WHERE id='alice'")
 def punch(self,action,sid='store1',key=None,at=1000,**kwargs):return clock(self.db,self.alice(),{'action':action,'key':key or action+'-1234567890123456-'+str(at),'store_id':sid,'tag':'tag-one' if sid=='store1' else 'tag-two',**kwargs},at=at)
 def test_no_arbitrary_admin_bootstrap(self):
  self.assertIsNone(self.client.get('/api/session').json['user']);self.assertEqual(self.client.get('/api/data').status_code,401);self.assertEqual(self.db.execute("SELECT count(*) FROM users WHERE role='owner'").fetchone()[0],1)
 def test_cookie_headers(self):
  r=self.client.get('/api/session');self.assertIn('HttpOnly',r.headers['Set-Cookie']);self.assertIn('SameSite=Lax',r.headers['Set-Cookie']);self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy']);self.assertEqual(r.headers['Cache-Control'],'no-store')
 def test_csrf_origin(self):
  self.login();self.assertEqual(self.client.post('/api/clock',json={},headers={'Origin':'http://evil.test','X-CSRF-Token':self.csrf}).status_code,403);self.assertEqual(self.client.post('/api/clock',json={},headers={'Origin':'http://localhost:8000'}).status_code,403)
 def test_staff_data_scope(self):
  self.punch('in');self.db.execute("INSERT INTO shifts VALUES('bob-shift','bob','store2',200,300,'pending','staff_nfc',1)");self.login();d=self.client.get('/api/data').json;self.assertEqual([u['id'] for u in d['users']],['alice']);self.assertEqual([s['user_id'] for s in d['shifts']],['alice']);self.assertEqual(self.client.get('/api/data?user_id=bob').json['shifts'],[])
 def test_staff_manager_api_forbidden(self):
  self.login();self.assertEqual(self.post('/api/stores',{'name':'x'}).status_code,403);self.assertEqual(self.client.get('/api/export.csv').status_code,403)
 def test_manager_store_scope(self):
  self.login('manager');self.assertEqual([s['id'] for s in self.client.get('/api/data').json['stores']],['store1']);self.assertEqual(self.client.get('/api/stores/store2/qr').status_code,403);self.assertEqual(self.post('/api/stores',{'id':'store2','name':'x'}).status_code,403)
 def test_cross_store_tag_and_identity(self):
  self.login('bob');self.assertEqual(self.client.get('/api/tap/tag-one').status_code,403);self.assertEqual(self.post('/api/clock',{'action':'in','key':'this-is-a-long-unique-key','store_id':'store1','tag':'tag-one','user_id':'alice'}).status_code,403)
 def test_cannot_select_other_identity(self):
  self.login();self.assertEqual(self.post('/api/clock',{'action':'in','key':'this-is-a-long-unique-key','store_id':'store1','tag':'tag-one','user_id':'bob'}).status_code,200);self.assertEqual(row(self.db,'SELECT user_id FROM shifts')['user_id'],'alice')
 def test_deactivation_immediate(self):
  self.login();c=self.app.test_client();csrf=self.login('owner',c);self.assertEqual(self.post('/api/users/alice/state',{'action':'deactivate'},c,csrf).status_code,200);self.assertEqual(self.client.get('/api/data').status_code,401)
  with self.assertRaises(Problem):self.punch('in')
 def test_idempotency_and_mismatch(self):
  a=self.punch('in',key='same-retry-key-123456');self.assertEqual(a,self.punch('in',key='same-retry-key-123456',at=1002));self.assertEqual(self.db.execute('SELECT count(*) FROM shifts').fetchone()[0],1)
  with self.assertRaises(Problem):self.punch('out',key='same-retry-key-123456',at=1200)
 def test_concurrent_punches(self):
  user=self.alice()
  def run(i):
   db=connect(self.path)
   try:return clock(db,user,{'action':'in','key':'concurrent-unique-key-'+str(i),'store_id':'store1','tag':'tag-one'},at=1000)
   except Problem as e:return e.status
   finally:db.close()
  with concurrent.futures.ThreadPoolExecutor(4) as p:results=list(p.map(run,range(4)))
  self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertEqual(results.count(409),3)
 def test_concurrent_same_key(self):
  user=self.alice()
  def run(i):
   db=connect(self.path)
   try:return clock(db,user,{'action':'in','key':'concurrent-same-key-123','store_id':'store1','tag':'tag-one'},at=1000+i)
   finally:db.close()
  with concurrent.futures.ThreadPoolExecutor(4) as p:results=list(p.map(run,range(4)))
  self.assertTrue(all(r==results[0] for r in results));self.assertEqual(self.db.execute('SELECT count(*) FROM shifts').fetchone()[0],1)
 def test_paid_unpaid_and_clockout_closes_break(self):
  a=self.punch('in');self.punch('break',at=1100,paid=True);self.punch('resume',at=1200);self.punch('break',at=1300,paid=False);self.punch('out',at=1400);s=row(self.db,'SELECT * FROM shifts WHERE id=?',(a['shift_id'],));bs=rows(self.db,'SELECT * FROM breaks');self.assertEqual(worked(s,bs,1400),300);self.assertTrue(all(b['ended'] is not None for b in bs))
 def test_invalid_sequence(self):
  with self.assertRaises(Problem):self.punch('out')
  self.punch('in')
  with self.assertRaises(Problem):self.punch('resume',at=1100)
  with self.assertRaises(Problem):self.punch('in',sid='store2',at=1100)
 def test_database_overlap_and_immutable_audit(self):
  self.punch('in');self.punch('out',at=1200)
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute("INSERT INTO shifts VALUES('overlap','alice','store2',1100,1300,'pending','manual',1)")
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute("UPDATE audit SET reason='tamper'")
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM audit')
 def test_database_break_boundaries(self):
  s=self.punch('in');self.punch('break',at=1100,paid=False)
  with self.assertRaises(sqlite3.IntegrityError):self.db.execute('INSERT INTO breaks VALUES(?,?,?,?,?)',('bad',s['shift_id'],900,1050,0))
 def test_correction_reason_history_and_version(self):
  s=self.punch('in');self.punch('out',at=1300);owner=row(self.db,"SELECT * FROM users WHERE id='owner'");b={'shift_id':s['shift_id'],'version':2,'started':1001,'ended':1299,'breaks':[],'reason':'Verified with manager'};correct(self.db,owner,b);a=row(self.db,"SELECT * FROM audit WHERE kind='shift_correction'");self.assertEqual(json.loads(a['before_json'])['started'],1000)
  with self.assertRaises(Problem):correct(self.db,owner,b)
 def test_cross_store_correction_blocked(self):
  self.db.execute("INSERT INTO shifts VALUES('b','bob','store2',1000,1300,'pending','manual',1)");manager=row(self.db,"SELECT * FROM users WHERE id='manager'")
  with self.assertRaises(Problem):correct(self.db,manager,{'shift_id':'b','version':1,'started':1001,'ended':1299,'breaks':[],'reason':'Verified test'})
 def test_location_invalid_missing_valid(self):
  self.db.execute("UPDATE stores SET latitude=-33.9,longitude=151,location_required=1 WHERE id='store1'")
  with self.assertRaises(Problem) as cm:self.punch('in')
  self.assertEqual(cm.exception.code,'location_exception');self.assertEqual(self.db.execute('SELECT count(*) FROM shifts').fetchone()[0],0)
  with self.assertRaises(Problem):self.punch('in',location={'latitude':float('nan'),'longitude':151,'accuracy':10})
  self.punch('in',location={'latitude':-33.9,'longitude':151,'accuracy':10})
 def test_uncertain_location(self):
  s=row(self.db,"SELECT * FROM stores WHERE id='store1'");s.update(latitude=-33.9,longitude=151,max_accuracy=50,radius=150);self.assertEqual(location_result(s,{'latitude':-33.9,'longitude':151,'accuracy':100})['status'],'uncertain')
 def test_exception_and_get_do_not_punch(self):
  self.login();self.assertEqual(self.client.get('/api/tap/tag-one').status_code,200);self.assertEqual(self.post('/api/exceptions',{'store_id':'store1','tag':'tag-one','action':'in','reason':'Location denied'}).status_code,200);self.assertEqual(self.db.execute('SELECT count(*) FROM shifts').fetchone()[0],0)
 def test_rotate_archive_preserve_records(self):
  self.punch('in');self.punch('out',at=1300);self.login('owner');self.assertEqual(self.post('/api/stores/store1/state',{'action':'rotate'}).status_code,200);self.assertEqual(self.client.get('/api/tap/tag-one').status_code,404);self.assertEqual(self.post('/api/stores/store1/state',{'action':'archive'}).status_code,200);self.assertEqual(self.db.execute('SELECT count(*) FROM shifts').fetchone()[0],1)
 def test_activation_single_use(self):
  self.login('owner');r=self.post('/api/users',{'name':'New staff','email':'new@test.com','role':'staff','stores':['store1']});self.assertEqual(r.status_code,200,r.json);u=row(self.db,"SELECT * FROM users WHERE email='new@test.com'");self.assertEqual(u['verified'],0);raw='activation-test-secret';self.db.execute("INSERT OR REPLACE INTO tokens VALUES(?,?,'activate',?)",(digest(raw),u['id'],now()+1000));self.assertEqual(self.post('/api/password/complete',{'token':raw,'password':'NewSecurePassword123!'}).status_code,200);self.csrf=self.client.get('/api/session').json['csrf'];self.assertEqual(self.post('/api/password/complete',{'token':raw,'password':'AnotherSecurePassword123!'}).status_code,400)
 def test_overnight_dst_day_clipping(self):
  a=int(datetime.datetime.fromisoformat('2026-10-04T01:00:00+10:00').timestamp());b=int(datetime.datetime.fromisoformat('2026-10-04T04:00:00+11:00').timestamp());self.assertEqual(worked({'started':a,'ended':b},[],b),7200)
  a=int(datetime.datetime.fromisoformat('2026-10-02T22:00:00+10:00').timestamp());b=int(datetime.datetime.fromisoformat('2026-10-03T06:00:00+10:00').timestamp());self.assertEqual(worked({'started':a,'ended':b},[],b,bounds('2026-10-03','Australia/Sydney'),bounds('2026-10-03','Australia/Sydney',True)),21600)
 def test_full_csv_and_formula_injection(self):
  self.db.execute("UPDATE users SET name='=HYPERLINK(\"bad\")' WHERE id='alice'");self.db.executemany("INSERT INTO shifts VALUES(?,?,?, ?,?,'pending','manual',1)",[(str(i),'alice','store1',1000+i*100,1050+i*100) for i in range(120)]);self.login('owner');r=self.client.get('/api/export.csv');self.assertEqual(r.status_code,200);text=r.data.decode();self.assertIn("'=HYPERLINK",text);self.assertEqual(len(text.splitlines()),121)
 def test_totp_replay(self):
  secret='JBSWY3DPEHPK3PXP';step=now()//30;code=totp(secret,step);self.assertEqual(match_totp(secret,code,at=step*30),step);self.assertIsNone(match_totp(secret,code,last_step=step,at=step*30))
 def test_mfa_and_recovery_code(self):
  self.db.execute("UPDATE users SET totp_secret=? WHERE id='alice'",(cipher(self.secret).encrypt(b'JBSWY3DPEHPK3PXP').decode(),));self.db.execute('INSERT INTO recovery_codes VALUES(?,?)',('alice',digest('recovery-one')));self.login();self.assertIsNone(self.client.get('/api/session').json['user']);self.assertEqual(self.post('/api/login/mfa',{'code':'recovery-one'}).status_code,200);self.assertEqual(self.client.get('/api/session').json['user']['id'],'alice');self.assertFalse(row(self.db,'SELECT 1 FROM recovery_codes'))
 def test_approval_pending_request(self):
  s=self.punch('in');self.punch('out',at=1300);self.db.execute("INSERT INTO corrections(id,user_id,shift_id,reason,created) VALUES('c','alice',?,'wrong time',?)",(s['shift_id'],now()));self.login('owner');self.assertEqual(self.post('/api/shifts/'+s['shift_id']+'/approve',{'version':2}).status_code,400)
 def test_backup_integrity(self):
  from manage import backup
  from cryptography.fernet import Fernet
  key=Fernet.generate_key();self.punch('in');path=backup(self.path,self.tmp.name,key.decode());target=pathlib.Path(self.tmp.name)/'restore.sqlite';target.write_bytes(Fernet(key).decrypt(path.read_bytes()));db=connect(str(target));self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok');self.assertEqual(db.execute('SELECT count(*) FROM shifts').fetchone()[0],1);db.close()
 def test_static_and_qr(self):
  r=self.client.get('/');self.assertEqual(r.status_code,200);r.close();r=self.client.get('/assets/app.js');self.assertEqual(r.status_code,200);r.close();self.login('owner');r=self.client.get('/api/stores/store1/qr');self.assertEqual(r.status_code,200);self.assertIn(b'<svg',r.data)

 def test_mfa_enrollment(self):
  self.login('owner');r=self.post('/api/mfa/start',{'password':'VeryGoodPassword123!'});self.assertEqual(r.status_code,200);secret=r.json['secret'];code=totp(secret,now()//30);r=self.post('/api/mfa/confirm',{'code':code});self.assertEqual(r.status_code,200);self.assertEqual(len(r.json['recovery_codes']),10);self.assertTrue(self.client.get('/api/session').json['mfa_enabled'])
 def test_expired_session(self):
  self.login();self.db.execute('UPDATE sessions SET expires=?',(now()-1,));self.assertEqual(self.client.get('/api/data').status_code,401)
 def test_clock_version_changes_on_break(self):
  s=self.punch('in');self.punch('break',at=1100,paid=False);self.assertEqual(row(self.db,'SELECT version FROM shifts')['version'],2)
  with self.assertRaises(Problem):correct(self.db,row(self.db,"SELECT * FROM users WHERE id='owner'"),{'shift_id':s['shift_id'],'version':1,'started':1000,'ended':1200,'breaks':[],'reason':'Verified review'})
 def test_bad_identifier_is_validation_error(self):
  self.login('owner');self.assertEqual(self.post('/api/stores',{'id':{'bad':'input'},'name':'Store'}).status_code,400)
 def test_rate_limit_login(self):
  self.csrf=self.client.get('/api/session').json['csrf']
  for i in range(10):self.assertEqual(self.post('/api/login',{'email':'alice@test.com','password':'wrong'}).status_code,401)
  self.assertEqual(self.post('/api/login',{'email':'alice@test.com','password':'wrong'}).status_code,429)
 def test_schema_migration_parallel_start(self):
  from shifttap.db import migrate
  path=str(pathlib.Path(self.tmp.name)/'parallel.sqlite')
  with concurrent.futures.ThreadPoolExecutor(3) as p:list(p.map(lambda _:migrate(path),range(3)))
  db=connect(path);self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],1);db.close()
 def test_maintenance_backup_and_retention(self):
  import os
  from unittest.mock import patch
  from cryptography.fernet import Fernet
  from maintenance import tick
  backup_dir=str(pathlib.Path(self.tmp.name)/'scheduled')
  with patch.dict(os.environ,{'DB_PATH':self.path,'APP_SECRET':self.secret,'BACKUP_DIR':backup_dir,'BACKUP_KEY':Fernet.generate_key().decode()}):tick()
  self.assertEqual(len(list(pathlib.Path(backup_dir).glob('*.sqlite.enc'))),1)
 def test_manual_overlap_and_approval(self):
  self.login('owner');a=now()-3600;z=now()-1800;b={'store_id':'store1','user_id':'alice','started':a,'ended':z,'breaks':[],'reason':'Verified missed shift'}
  self.assertEqual(self.post('/api/shifts/manual',b).status_code,200);self.assertEqual(self.post('/api/shifts/manual',b).status_code,409);s=row(self.db,'SELECT * FROM shifts');self.assertEqual(self.post('/api/shifts/'+s['id']+'/approve',{'version':1}).status_code,200)

if __name__=='__main__':unittest.main()
