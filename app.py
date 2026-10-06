import os,secrets,json,sqlite3,pathlib,datetime,zoneinfo,io,csv,urllib.parse,logging
from flask import Flask,request,g,jsonify,make_response,send_from_directory,Response
from .db import connect,migrate,row,rows,transaction,uid,now,audit
from .security import Problem,digest,token,cipher,hash_password,verify_password,rate,base32_secret,match_totp,location_result
from .attendance import manages,assigned,clock,correct,shift_records,bounds,worked

ROOT=pathlib.Path(__file__).resolve().parent.parent

def text(value,name,maxlen=150,required=True):
    if not isinstance(value,str):raise Problem(f'Invalid {name}.')
    value=value.strip()
    if len(value)>maxlen or required and not value:raise Problem(f'Enter a valid {name}.')
    return value

def email(value):
    value=text(value,'email',254).lower()
    if len(value.split('@'))!=2 or any(c.isspace() for c in value) or '.' not in value.split('@')[1]:raise Problem('Enter a valid email address.')
    return value

def safe_user(u):return {k:u[k] for k in ['id','email','name','role','active','verified']}

def issue_email(db,crypt,base,user,kind):
    t=token();expires=now()+(86400 if kind=='activate' else 3600)
    db.execute('DELETE FROM tokens WHERE user_id=? AND kind=?',(user['id'],kind))
    db.execute('INSERT INTO tokens VALUES(?,?,?,?)',(digest(t),user['id'],kind,expires))
    link=base+'/?flow='+kind+'&token='+urllib.parse.quote(t)
    subject='Set up your ShiftTap account' if kind=='activate' else 'Reset your ShiftTap password'
    body=f"Hello {user['name']},\n\n{subject}:\n{link}\n\nThis link expires in {'24 hours' if kind=='activate' else '1 hour'}. If you did not request this, ignore this email.\n"
    db.execute('INSERT INTO outbox(id,to_email,subject,body_cipher,available) VALUES(?,?,?,?,?)',(uid(),user['email'],subject,crypt.encrypt(body.encode()).decode(),now()))

def create_app(overrides=None):
    app=Flask(__name__,static_folder=None)
    if os.environ.get('TRUST_PROXY')=='true':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
    app.config.update(DB_PATH=os.environ.get('DB_PATH',str(ROOT/'data/shifttap.sqlite')),APP_URL=os.environ.get('APP_URL') or os.environ.get('RENDER_EXTERNAL_URL','http://localhost:8000'),APP_SECRET=os.environ.get('APP_SECRET',''),COOKIE_SECURE=os.environ.get('COOKIE_SECURE','true')=='true',TESTING=False,MAX_CONTENT_LENGTH=65536,SMTP_HOST=os.environ.get('SMTP_HOST',''))
    if overrides:app.config.update(overrides)
    if len(app.config['APP_SECRET'])<32 or 'REPLACE_WITH' in app.config['APP_SECRET']:raise RuntimeError('Set APP_SECRET to at least 32 random characters before starting.')
    origin=app.config['APP_URL'].rstrip('/')
    url=urllib.parse.urlsplit(origin)
    if url.path or url.query or url.fragment or url.username or url.scheme not in ['http','https']:raise RuntimeError('APP_URL must be an origin only, without a path.')
    if not app.config['TESTING'] and url.hostname not in ['localhost','127.0.0.1'] and (url.scheme!='https' or not app.config['COOKIE_SECURE']):raise RuntimeError('Production requires HTTPS and secure cookies.')
    app.extensions['crypt']=cipher(app.config['APP_SECRET']);migrate(app.config['DB_PATH'])
    dummy=hash_password(secrets.token_urlsafe(24))
    cookie_name='__Host-shifttap' if app.config['COOKIE_SECURE'] else 'shifttap_dev'

    @app.before_request
    def before():
        if request.path=='/health':return
        g.db=connect(app.config['DB_PATH']);g.user=None;g.session=None;g.cookie=None
        presented=request.cookies.get(cookie_name,'')
        session=row(g.db,'SELECT * FROM sessions WHERE token_hash=?',(digest(presented),)) if presented else None
        if session and (session['expires']<now() or session['last_seen']<now()-7*86400):
            g.db.execute('DELETE FROM sessions WHERE token_hash=?',(session['token_hash'],));session=None
        if session:
            g.session=session
            if session['user_id']:
                user=row(g.db,'SELECT * FROM users WHERE id=?',(session['user_id'],))
                if user and user['active'] and user['verified'] and (not user['totp_secret'] or session['mfa']):g.user=user
                else:
                    g.db.execute('DELETE FROM sessions WHERE token_hash=?',(session['token_hash'],));g.session=None
            if g.session:g.db.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(now(),session['token_hash']))
        if request.path=='/api/session' and not g.session:
            rate(g.db,'anon:'+request.remote_addr,100,60);new_session()
        if request.method in ['POST','PUT','PATCH','DELETE']:
            if request.headers.get('Origin')!=origin:raise Problem('Invalid request origin.',403)
            if not request.is_json:raise Problem('Use a JSON request.',415)
            if not g.session or not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),g.session['csrf']):raise Problem('Session expired. Refresh and try again.',403)
            rate(g.db,'write:'+g.session['token_hash'],120,60)

    @app.after_request
    def after(response):
        response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",'Permissions-Policy':'geolocation=(self), camera=(), microphone=()'})
        if app.config['COOKIE_SECURE']:response.headers['Strict-Transport-Security']='max-age=31536000'
        if request.path.startswith('/api/') or request.path=='/':response.headers['Cache-Control']='no-store'
        if getattr(g,'cookie',None):response.set_cookie(cookie_name,g.cookie,max_age=30*86400,httponly=True,secure=app.config['COOKIE_SECURE'],samesite='Lax',path='/')
        if getattr(g,'delete_cookie',False):response.delete_cookie(cookie_name,path='/',secure=app.config['COOKIE_SECURE'],httponly=True,samesite='Lax')
        return response

    @app.teardown_request
    def teardown(_):
        if getattr(g,'db',None):g.db.close()

    @app.errorhandler(Problem)
    def problem(e):return jsonify(error=e.message,code=e.code),e.status
    @app.errorhandler(sqlite3.IntegrityError)
    def integrity(_):return jsonify(error='This change conflicts with an existing record. Refresh and retry.'),409
    @app.errorhandler(413)
    def large(_):return jsonify(error='Request is too large.'),413
    @app.errorhandler(500)
    def unexpected(_):return jsonify(error='Unable to complete this request. Please retry.'),500

    def new_session(user=None,pending=None,mfa=False):
        if getattr(g,'session',None):g.db.execute('DELETE FROM sessions WHERE token_hash=?',(g.session['token_hash'],))
        value=token();g.cookie=value
        g.db.execute('INSERT INTO sessions(token_hash,user_id,csrf,pending_user,expires,last_seen,mfa) VALUES(?,?,?,?,?,?,?)',(digest(value),user['id'] if user else None,token(),pending,now()+30*86400,now(),int(mfa)))
        g.session=row(g.db,'SELECT * FROM sessions WHERE token_hash=?',(digest(value),));g.user=user

    def body():
        value=request.get_json()
        if not isinstance(value,dict):raise Problem('Invalid request body.')
        for key in ['id','store_id','user_id','shift_id']:
            if value.get(key) is not None and (not isinstance(value[key],str) or not 1<=len(value[key])<=100):raise Problem('Invalid identifier: '+key)
        if 'version' in value and (isinstance(value['version'],bool) or not isinstance(value['version'],int)):raise Problem('Invalid record version.')
        return value
    def auth(roles=None):
        if not g.user:raise Problem('Sign in to continue.',401)
        if roles and g.user['role'] not in roles:raise Problem('Permission denied.',403)
        return g.user
    def manager(store_id):
        auth(['owner','manager'])
        if not manages(g.db,g.user,store_id):raise Problem('This store is not assigned to you.',403)
    def store_public(s,include_link=False):
        result={k:v for k,v in s.items() if k not in ['tag_cipher','tag_hash']}
        if include_link:result['clock_url']=origin+'/tap/'+app.extensions['crypt'].decrypt(s['tag_cipher'].encode()).decode();result['qr_url']='/api/stores/'+s['id']+'/qr'
        return result

    @app.get('/health')
    def health():return jsonify(ok=True)
    @app.get('/')
    @app.get('/tap/<tag>')
    def index(tag=None):return send_from_directory(ROOT/'public','index.html')
    @app.get('/assets/<path:file>')
    def assets(file):return send_from_directory(ROOT/'public',file)

    @app.get('/api/session')
    def session_state():return jsonify(user=safe_user(g.user) if g.user else None,csrf=g.session['csrf'],mfa_required=bool(g.session['pending_user']),mfa_enabled=bool(g.user and g.user['totp_secret']),now=now())

    @app.post('/api/login')
    def login():
        b=body();address=email(b.get('email'));password=b.get('password','')
        if not isinstance(password,str) or len(password)>128:raise Problem('Invalid email or password.',401)
        rate(g.db,'login-ip:'+request.remote_addr,30);rate(g.db,'login-account:'+address,10)
        u=row(g.db,'SELECT * FROM users WHERE email=?',(address,))
        valid=verify_password(u['password_hash'] if u and u['password_hash'] else dummy,password)
        if not valid or not u or not u['active'] or not u['verified']:raise Problem('Invalid email or password, or account is not activated.',401)
        if u['totp_secret']:new_session(pending=u['id']);return jsonify(mfa_required=True)
        new_session(u);return jsonify(ok=True)

    @app.post('/api/login/mfa')
    def login_mfa():
        rate(g.db,'mfa:'+g.session['token_hash'],8)
        u=row(g.db,'SELECT * FROM users WHERE id=?',(g.session['pending_user'],))
        if not u or not u['active'] or not u['totp_secret']:raise Problem('Restart sign-in.',401)
        code=text(body().get('code'),'verification code',100)
        with transaction(g.db):
            u=row(g.db,'SELECT * FROM users WHERE id=?',(u['id'],))
            if not u['active']:raise Problem('Account is inactive.',403)
            secret=app.extensions['crypt'].decrypt(u['totp_secret'].encode()).decode()
            step=match_totp(secret,code,u['totp_last_step'])
            recovery=row(g.db,'SELECT 1 FROM recovery_codes WHERE user_id=? AND code_hash=?',(u['id'],digest(code)))
            if step is None and not recovery:raise Problem('Invalid or already-used verification code.',401)
            if recovery:g.db.execute('DELETE FROM recovery_codes WHERE user_id=? AND code_hash=?',(u['id'],digest(code)))
            else:g.db.execute('UPDATE users SET totp_last_step=? WHERE id=?',(step,u['id']))
            new_session(u,mfa=True)
        return jsonify(ok=True)

    @app.post('/api/logout')
    def logout():
        g.db.execute('DELETE FROM sessions WHERE token_hash=?',(g.session['token_hash'],));g.delete_cookie=True;g.cookie=None
        return jsonify(ok=True)

    @app.post('/api/password/request')
    def request_password():
        b=body();address=email(b.get('email'));rate(g.db,'reset-ip:'+request.remote_addr,10,3600);rate(g.db,'reset-email:'+address,3,3600)
        u=row(g.db,'SELECT * FROM users WHERE email=?',(address,))
        if u and u['active'] and app.config['SMTP_HOST']:
            with transaction(g.db):issue_email(g.db,app.extensions['crypt'],origin,u,'reset' if u['verified'] else 'activate')
        return jsonify(ok=True,message='If an active account exists, an email will arrive shortly.')

    @app.post('/api/password/complete')
    def complete_password():
        b=body();rate(g.db,'token:'+request.remote_addr,12)
        value=text(b.get('token'),'account link',100);hashed=hash_password(b.get('password'))
        with transaction(g.db):
            t=row(g.db,'SELECT * FROM tokens WHERE token_hash=? AND expires>=?',(digest(value),now()))
            if not t or t['kind'] not in ['activate','reset']:raise Problem('This link has expired or was already used.')
            u=row(g.db,'SELECT * FROM users WHERE id=?',(t['user_id'],))
            if not u['active']:raise Problem('Account is inactive.',403)
            g.db.execute('UPDATE users SET password_hash=?,verified=1 WHERE id=?',(hashed,u['id']))
            g.db.execute('DELETE FROM tokens WHERE user_id=?',(u['id'],));g.db.execute('DELETE FROM sessions WHERE user_id=? OR pending_user=?',(u['id'],u['id']))
            audit(g.db,u['id'],'password_changed',u['id'])
        g.delete_cookie=True;g.cookie=None
        return jsonify(ok=True)

    @app.post('/api/mfa/start')
    def mfa_start():
        u=auth();b=body();rate(g.db,'mfa-setup:'+u['id'],5)
        if u['totp_secret']:raise Problem('MFA is already enabled.')
        if not verify_password(u['password_hash'],b.get('password','')):raise Problem('Incorrect password.',401)
        secret=base32_secret();g.db.execute('UPDATE sessions SET pending_totp=? WHERE token_hash=?',(app.extensions['crypt'].encrypt(secret.encode()).decode(),g.session['token_hash']))
        uri='otpauth://totp/'+urllib.parse.quote('ShiftTap:'+u['email'])+'?secret='+secret+'&issuer=ShiftTap&algorithm=SHA1&digits=6&period=30'
        return jsonify(secret=secret,uri=uri)

    @app.post('/api/mfa/confirm')
    def mfa_confirm():
        u=auth();rate(g.db,'mfa-confirm:'+u['id'],8)
        with transaction(g.db):
            s=row(g.db,'SELECT * FROM sessions WHERE token_hash=?',(g.session['token_hash'],))
            if not s['pending_totp']:raise Problem('Start MFA setup first.')
            secret=app.extensions['crypt'].decrypt(s['pending_totp'].encode()).decode();step=match_totp(secret,body().get('code',''))
            if step is None:raise Problem('Invalid verification code.')
            codes=[secrets.token_hex(8) for _ in range(10)]
            g.db.execute('UPDATE users SET totp_secret=?,totp_last_step=? WHERE id=?',(s['pending_totp'],step,u['id']))
            g.db.execute('DELETE FROM recovery_codes WHERE user_id=?',(u['id'],))
            g.db.executemany('INSERT INTO recovery_codes VALUES(?,?)',[(u['id'],digest(c)) for c in codes])
            g.db.execute('DELETE FROM sessions WHERE (user_id=? OR pending_user=?) AND token_hash<>?',(u['id'],u['id'],s['token_hash']))
            g.db.execute('UPDATE sessions SET mfa=1,pending_totp=NULL WHERE token_hash=?',(s['token_hash'],))
            audit(g.db,u['id'],'mfa_enabled',u['id'])
        return jsonify(ok=True,recovery_codes=codes)

    @app.get('/api/tap/<tag>')
    def tap(tag):
        u=auth();s=row(g.db,'SELECT * FROM stores WHERE tag_hash=? AND archived=0',(digest(tag),))
        if not s:raise Problem('This store link has been revoked or archived.',404)
        if not assigned(g.db,u,s['id']):raise Problem('You are not assigned to this store.',403)
        return jsonify(store=store_public(s),tag=tag)

    @app.post('/api/clock')
    def punch():auth();return jsonify(clock(g.db,g.user,body()))

    @app.get('/api/data')
    def data():
        u=auth();args=() if u['role']=='owner' else (u['id'],)
        ss=rows(g.db,'SELECT * FROM stores'+('' if u['role']=='owner' else ' WHERE id IN(SELECT store_id FROM memberships WHERE user_id=?)')+' ORDER BY archived,name',args)
        if u['role']=='owner':us=rows(g.db,'SELECT * FROM users ORDER BY name')
        elif u['role']=='manager':us=rows(g.db,'SELECT DISTINCT u.* FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.store_id IN(SELECT store_id FROM memberships WHERE user_id=?) ORDER BY u.name',(u['id'],))
        else:us=[u]
        for person in us:person['stores']=[r['store_id'] for r in rows(g.db,'SELECT store_id FROM memberships WHERE user_id=?',(person['id'],))]
        users=[{**safe_user(person),'stores':person.get('stores',[])} for person in us]
        sh=shift_records(g.db,u,request.args)
        query='';qargs=[]
        if u['role']=='staff':query=' WHERE user_id=?';qargs=[u['id']]
        elif u['role']=='manager':query=' WHERE store_id IN(SELECT store_id FROM memberships WHERE user_id=?)';qargs=[u['id']]
        ex=rows(g.db,'SELECT * FROM exceptions'+query+' ORDER BY created DESC',qargs)
        corr_query='' if u['role']=='owner' else ' WHERE c.user_id=?' if u['role']=='staff' else ' WHERE s.store_id IN(SELECT store_id FROM memberships WHERE user_id=?)'
        cs=rows(g.db,'SELECT c.*,s.store_id FROM corrections c JOIN shifts s ON s.id=c.shift_id'+corr_query+' ORDER BY c.created DESC',[] if u['role']=='owner' else [u['id']])
        settings=row(g.db,'SELECT * FROM settings WHERE id=1')
        stamp=now();summary={'daily_seconds':0,'weekly_seconds':0}
        # Summary uses unfiltered shifts apart from location/person; calculated per-store day/week.
        for s in shift_records(g.db,u,{k:request.args[k] for k in ['store_id','user_id'] if k in request.args},stamp):
            local=datetime.datetime.fromtimestamp(stamp,zoneinfo.ZoneInfo(s['timezone']));today=local.date();monday=today-datetime.timedelta(days=today.weekday())
            summary['daily_seconds']+=worked(s,s['breaks'],stamp,bounds(today.isoformat(),s['timezone']),bounds(today.isoformat(),s['timezone'],True))
            summary['weekly_seconds']+=worked(s,s['breaks'],stamp,bounds(monday.isoformat(),s['timezone']),stamp)
        return jsonify(stores=[store_public(s,u['role']!='staff') for s in ss],users=users,shifts=sh,exceptions=ex,corrections=cs,settings=settings,summary=summary,now=stamp)

    @app.post('/api/stores')
    def save_store():
        u=auth(['owner','manager']);b=body();sid=b.get('id');previous=row(g.db,'SELECT * FROM stores WHERE id=?',(sid,)) if sid else None
        if sid and not previous:raise Problem('Store not found.',404)
        if previous:manager(sid)
        elif u['role']!='owner':raise Problem('Only the owner can create stores.',403)
        name=text(b.get('name'),'store name');address=text(b.get('address',''),'address',300,False);tz=text(b.get('timezone','Australia/Sydney'),'timezone',60)
        try:zoneinfo.ZoneInfo(tz)
        except zoneinfo.ZoneInfoNotFoundError:raise Problem('Choose a valid IANA timezone.')
        try:
            lat=float(b['latitude']) if b.get('latitude') not in [None,''] else None;lon=float(b['longitude']) if b.get('longitude') not in [None,''] else None
            radius=float(b.get('radius',150));accuracy=float(b.get('max_accuracy',100))
            if (lat is None)!=(lon is None) or lat is not None and not (-90<=lat<=90 and -180<=lon<=180) or not 10<=radius<=10000 or not 1<=accuracy<=1000:raise ValueError()
            required=int(b.get('location_required',False) is True or b.get('location_required')==1)
            if required and lat is None:raise ValueError()
        except (TypeError,ValueError):raise Problem('Enter valid location coordinates, radius and accuracy.')
        with transaction(g.db):
            if previous:
                g.db.execute('UPDATE stores SET name=?,address=?,timezone=?,latitude=?,longitude=?,radius=?,max_accuracy=?,location_required=? WHERE id=?',(name,address,tz,lat,lon,radius,accuracy,required,sid))
            else:
                sid=uid();tag=token();g.db.execute('INSERT INTO stores(id,name,address,timezone,tag_hash,tag_cipher,latitude,longitude,radius,max_accuracy,location_required) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,name,address,tz,digest(tag),app.extensions['crypt'].encrypt(tag.encode()).decode(),lat,lon,radius,accuracy,required))
            audit(g.db,u['id'],'store_saved',sid,before=store_public(previous) if previous else None,after={'name':name,'address':address,'timezone':tz,'location_required':required,'latitude':lat,'longitude':lon,'radius':radius,'max_accuracy':accuracy})
        return jsonify(ok=True,id=sid)

    @app.post('/api/stores/<sid>/state')
    def store_state(sid):
        u=auth(['owner']);b=body();s=row(g.db,'SELECT * FROM stores WHERE id=?',(sid,))
        if not s:raise Problem('Store not found.',404)
        with transaction(g.db):
            if b.get('action')=='rotate':
                t=token();g.db.execute('UPDATE stores SET tag_hash=?,tag_cipher=? WHERE id=?',(digest(t),app.extensions['crypt'].encrypt(t.encode()).decode(),sid))
            elif b.get('action') in ['archive','restore']:
                if b['action']=='archive' and row(g.db,'SELECT 1 FROM shifts WHERE store_id=? AND ended IS NULL',(sid,)):raise Problem('Close open shifts before archiving.',409)
                g.db.execute('UPDATE stores SET archived=? WHERE id=?',(int(b['action']=='archive'),sid))
            else:raise Problem('Invalid store action.')
            audit(g.db,u['id'],'store_'+b['action'],sid,reason=text(b.get('reason','Store configuration change'),'reason',1000))
        return jsonify(ok=True)

    @app.get('/api/stores/<sid>/qr')
    def qr(sid):
        manager(sid);s=row(g.db,'SELECT * FROM stores WHERE id=?',(sid,))
        if not s:raise Problem('Store not found.',404)
        import qrcode,qrcode.image.svg
        img=qrcode.make(store_public(s,True)['clock_url'],image_factory=qrcode.image.svg.SvgPathImage);buf=io.BytesIO();img.save(buf)
        return Response(buf.getvalue(),mimetype='image/svg+xml',headers={'Cache-Control':'no-store'})

    @app.post('/api/users')
    def save_user():
        u=auth(['owner','manager']);b=body();who=b.get('id');old=row(g.db,'SELECT * FROM users WHERE id=?',(who,)) if who else None
        if who and not old:raise Problem('Staff member not found.',404)
        role=b.get('role','staff');name=text(b.get('name'),'staff name');address=email(b.get('email'))
        if role not in ['manager','staff']:raise Problem('Choose manager or staff.')
        store_ids=b.get('stores')
        if not isinstance(store_ids,list) or not store_ids or len(store_ids)>100 or any(not isinstance(x,str) for x in store_ids):raise Problem('Assign at least one store.')
        if old and old['role']=='owner':raise Problem('Owner identity cannot be edited here.')
        if u['role']=='manager' and (old or role!='staff'):raise Problem('Managers can invite new staff; only the owner can edit existing accounts.',403)
        for sid in set(store_ids):
            if not row(g.db,'SELECT 1 FROM stores WHERE id=? AND archived=0',(sid,)):raise Problem('Choose active stores.')
            manager(sid)
        if old and old['email']!=address:raise Problem('Email changes require a new verified invitation; deactivate this account and invite the new email.')
        if not old and not app.config['SMTP_HOST']:raise Problem('Configure SMTP before inviting staff.',503)
        with transaction(g.db):
            who=who or uid()
            if old:g.db.execute('UPDATE users SET name=?,role=? WHERE id=?',(name,role,who))
            else:g.db.execute('INSERT INTO users(id,email,name,role,created) VALUES(?,?,?,?,?)',(who,address,name,role,now()))
            g.db.execute('DELETE FROM memberships WHERE user_id=?',(who,))
            g.db.executemany('INSERT INTO memberships VALUES(?,?)',[(who,sid) for sid in set(store_ids)])
            if not old:issue_email(g.db,app.extensions['crypt'],origin,row(g.db,'SELECT * FROM users WHERE id=?',(who,)),'activate')
            audit(g.db,u['id'],'staff_saved',who,before=safe_user(old) if old else None,after={'name':name,'email':address,'role':role,'stores':store_ids})
        return jsonify(ok=True)

    @app.post('/api/users/<who>/state')
    def user_state(who):
        u=auth(['owner']);b=body();old=row(g.db,'SELECT * FROM users WHERE id=?',(who,))
        if not old or old['role']=='owner':raise Problem('This account cannot be changed.')
        with transaction(g.db):
            if b.get('action')=='resend':
                if not app.config['SMTP_HOST']:raise Problem('Configure SMTP first.',503)
                rate(g.db,'invite:'+who,3,3600);issue_email(g.db,app.extensions['crypt'],origin,old,'reset' if old['verified'] else 'activate')
            elif b.get('action') in ['deactivate','activate']:
                g.db.execute('UPDATE users SET active=? WHERE id=?',(int(b['action']=='activate'),who))
                g.db.execute('DELETE FROM sessions WHERE user_id=? OR pending_user=?',(who,who));g.db.execute('DELETE FROM tokens WHERE user_id=?',(who,))
            else:raise Problem('Invalid staff action.')
            audit(g.db,u['id'],'staff_'+b['action'],who,reason=text(b.get('reason','Account management'),'reason',1000))
        return jsonify(ok=True)

    @app.post('/api/corrections')
    def request_correction():
        u=auth();b=body();s=row(g.db,'SELECT * FROM shifts WHERE id=?',(b.get('shift_id'),))
        if not s or s['user_id']!=u['id']:raise Problem('Select your own shift.',403)
        reason=text(b.get('reason'),'correction details',1000)
        g.db.execute('INSERT INTO corrections(id,user_id,shift_id,reason,created) VALUES(?,?,?,?,?)',(uid(),u['id'],s['id'],reason,now()))
        return jsonify(ok=True)
    @app.post('/api/shifts/correct')
    def correct_shift():auth(['owner','manager']);return jsonify(correct(g.db,g.user,body()))

    @app.post('/api/shifts/<sid>/approve')
    def approve(sid):
        u=auth(['owner','manager']);b=body()
        with transaction(g.db):
            s=row(g.db,'SELECT * FROM shifts WHERE id=?',(sid,))
            if not s:raise Problem('Shift not found.',404)
            manager(s['store_id'])
            if s['ended'] is None:raise Problem('Complete the shift before approving.')
            if s['version']!=b.get('version'):raise Problem('Shift changed. Refresh.',409)
            if row(g.db,'SELECT 1 FROM corrections WHERE shift_id=? AND status=\'pending\'',(sid,)):raise Problem('Resolve pending correction requests first.')
            g.db.execute('UPDATE shifts SET approval=\'approved\',version=version+1 WHERE id=?',(sid,));audit(g.db,u['id'],'shift_approved',sid,before={'approval':s['approval']},after={'approval':'approved'})
        return jsonify(ok=True)

    @app.post('/api/exceptions')
    def request_exception():
        u=auth();b=body();sid=b.get('store_id');s=row(g.db,'SELECT * FROM stores WHERE id=? AND archived=0',(sid,))
        if not s or not assigned(g.db,u,sid) or not isinstance(b.get('tag'),str) or digest(b['tag'])!=s['tag_hash']:raise Problem('Use the link for an assigned active store.',403)
        action=b.get('action')
        if action not in ['in','out','break','resume']:raise Problem('Invalid action.')
        reason=text(b.get('reason'),'exception reason',1000);reading=location_result(s,b.get('location')) if s['location_required'] else {'status':'not_required','latitude':None,'longitude':None,'accuracy':None,'distance':None}
        with transaction(g.db):
            if row(g.db,'SELECT 1 FROM exceptions WHERE user_id=? AND store_id=? AND action=? AND status=\'pending\'',(u['id'],sid,action)):raise Problem('This exception request is already pending.',409)
            g.db.execute('INSERT INTO exceptions(id,user_id,store_id,action,reason,created) VALUES(?,?,?,?,?,?)',(uid(),u['id'],sid,action,reason,now()))
            g.db.execute('INSERT INTO location_events(user_id,store_id,action,latitude,longitude,accuracy,distance,status,created) VALUES(?,?,?,?,?,?,?,?,?)',(u['id'],sid,action,reading['latitude'],reading['longitude'],reading['accuracy'],reading['distance'],reading['status'],now()))
        return jsonify(ok=True,message='Exception submitted. No clock action has been recorded.')

    @app.post('/api/review')
    def review():
        u=auth(['owner','manager']);b=body();kind=b.get('kind');resolution=text(b.get('resolution'),'resolution',1000);status=b.get('status')
        if kind not in ['exceptions','corrections'] or status not in ['resolved','rejected']:raise Problem('Invalid review.')
        with transaction(g.db):
            item=row(g.db,'SELECT * FROM '+kind+' WHERE id=?',(b.get('id'),))
            if not item:raise Problem('Request not found.',404)
            sid=item.get('store_id') or row(g.db,'SELECT store_id FROM shifts WHERE id=?',(item['shift_id'],))['store_id'];manager(sid)
            if item['status']!='pending':raise Problem('Already reviewed.',409)
            g.db.execute('UPDATE '+kind+' SET status=?,resolution=?,resolved=? WHERE id=?',(status,resolution,now(),item['id']))
            audit(g.db,u['id'],kind+'_reviewed',item['id'],before=item,after={'status':status},reason=resolution)
        return jsonify(ok=True)

    @app.post('/api/shifts/manual')
    def manual():
        u=auth(['owner','manager']);b=body();sid=b.get('store_id');manager(sid)
        who=b.get('user_id');person=row(g.db,'SELECT * FROM users WHERE id=?',(who,));store=row(g.db,'SELECT * FROM stores WHERE id=?',(sid,))
        if not person or not store or not assigned(g.db,person,sid):raise Problem('Choose staff assigned to the store.')
        reason=text(b.get('reason'),'manual entry reason',1000)
        a,z=b.get('started'),b.get('ended')
        if isinstance(a,bool) or isinstance(z,bool) or not isinstance(a,int) or not isinstance(z,int) or a<=0 or z<a or z>now()+60:raise Problem('Enter a valid completed shift.')
        from .attendance import normalize_breaks
        bs=normalize_breaks(b.get('breaks',[]),a,z)
        with transaction(g.db):
            if row(g.db,'SELECT 1 FROM shifts WHERE user_id=? AND started<? AND COALESCE(ended,9223372036854775807)>?',(who,z,a)):raise Problem('Shift overlaps an existing shift.',409)
            shift_id=uid();g.db.execute('INSERT INTO shifts(id,user_id,store_id,started,ended,source) VALUES(?,?,?,?,?,?)',(shift_id,who,sid,a,z,'manager_manual'))
            for br in bs:g.db.execute('INSERT INTO breaks VALUES(?,?,?,?,?)',(uid(),shift_id,br['started'],br['ended'],br['paid']))
            audit(g.db,u['id'],'manual_shift',shift_id,after={'user_id':who,'store_id':sid,'started':a,'ended':z,'breaks':bs},reason=reason)
        return jsonify(ok=True)

    @app.get('/api/shifts/<sid>/audit')
    def shift_audit(sid):
        auth(['owner','manager']);s=row(g.db,'SELECT * FROM shifts WHERE id=?',(sid,))
        if not s:raise Problem('Shift not found.',404)
        manager(s['store_id']);return jsonify(records=rows(g.db,'SELECT * FROM audit WHERE entity_id=? ORDER BY id',(sid,)))

    @app.get('/api/export.csv')
    def export():
        auth(['owner','manager']);sh=shift_records(g.db,g.user,request.args);buf=io.StringIO(newline='');writer=csv.writer(buf)
        writer.writerow(['Employee','Store','Timezone','Clock in (ISO)','Clock out (ISO)','Status','Unpaid break seconds','Shift worked seconds','Worked seconds within filter','Approval','Source'])
        def cell(v):
            value=str(v)
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
        for s in sh:
            tz=zoneinfo.ZoneInfo(s['timezone']);iso=lambda n:datetime.datetime.fromtimestamp(n,tz).isoformat()
            writer.writerow([cell(s['employee_name']),cell(s['store_name']),s['timezone'],iso(s['started']),iso(s['ended']) if s['ended'] is not None else '', 'Completed' if s['ended'] is not None else 'Provisional',s['unpaid_seconds'],s['worked_seconds'],s['range_worked_seconds'],s['approval'],s['source']])
        return Response('\ufeff'+buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="shifttap-timesheets.csv"','Cache-Control':'no-store'})

    @app.post('/api/settings')
    def settings():
        u=auth(['owner']);b=body()
        ranges={'long_shift_hours':(4,72),'retention_days':(0,36500),'location_retention_days':(1,3650),'backup_retention_days':(7,3650)};values=[]
        for k,(lo,hi) in ranges.items():
            v=b.get(k)
            if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi:raise Problem('Invalid setting: '+k)
            if k=='retention_days' and v and v<365:raise Problem('Attendance retention must be disabled (0) or at least 365 days.')
            values.append(v)
        with transaction(g.db):
            old=row(g.db,'SELECT * FROM settings WHERE id=1');g.db.execute('UPDATE settings SET long_shift_hours=?,retention_days=?,location_retention_days=?,backup_retention_days=? WHERE id=1',values);audit(g.db,u['id'],'settings_changed','1',before=old,after=b)
        return jsonify(ok=True)

    return app
