import secrets,hashlib,hmac,base64,struct,time,math
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash,check_password_hash
from .db import now,row

class Problem(Exception):
    def __init__(self,message,status=400,code=None):self.message=message;self.status=status;self.code=code

def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def token():return secrets.token_urlsafe(32)
def cipher(secret):return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
def hash_password(password):
    if not isinstance(password,str) or len(password)<12 or len(password)>128:raise Problem('Use a password between 12 and 128 characters.')
    return generate_password_hash(password,method='scrypt:32768:8:1')
def verify_password(saved,password):
    try:return check_password_hash(saved,password)
    except (ValueError,TypeError):return False

def rate(db,key,limit,seconds=900):
    # Atomic UPSERT across workers. Every attempt counts, including rejected ones.
    window=now()//seconds
    r=db.execute('INSERT INTO rate_limits(key,window,count,expires) VALUES(?,?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END,window=excluded.window,expires=excluded.expires RETURNING count',(digest(key),window,(window+1)*seconds)).fetchone()
    if r['count']>limit:raise Problem('Too many attempts. Try again later.',429)

def base32_secret():return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
def totp(secret,step):
    raw=base64.b32decode(secret+'='*((8-len(secret)%8)%8))
    value=hmac.new(raw,struct.pack('>Q',step),hashlib.sha1).digest();offset=value[-1]&15
    return str((struct.unpack('>I',value[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)
def match_totp(secret,code,last_step=-1,at=None):
    if not isinstance(code,str) or len(code)!=6 or not code.isdigit():return None
    step=int((time.time() if at is None else at)//30)
    for candidate in [step-1,step,step+1]:
        if candidate>last_step and hmac.compare_digest(totp(secret,candidate),code):return candidate
    return None

def distance(lat1,lon1,lat2,lon2):
    p1,p2=math.radians(lat1),math.radians(lat2)
    a=math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371000*2*math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))

def location_result(store,value):
    if value is None:return {'status':'missing','latitude':None,'longitude':None,'accuracy':None,'distance':None}
    if not isinstance(value,dict):raise Problem('Invalid location reading.')
    try:
        lat,lon,accuracy=[float(value[k]) for k in ['latitude','longitude','accuracy']]
        if not all(math.isfinite(x) for x in [lat,lon,accuracy]) or not -90<=lat<=90 or not -180<=lon<=180 or accuracy<0 or accuracy>100000:raise ValueError()
    except (ValueError,TypeError,KeyError):raise Problem('Invalid location reading.')
    if store['latitude'] is None or store['longitude'] is None:raise Problem('This store has no configured location.')
    d=distance(lat,lon,store['latitude'],store['longitude'])
    status='verified' if accuracy<=store['max_accuracy'] and d+accuracy<=store['radius'] else 'uncertain' if d-accuracy<=store['radius'] else 'outside'
    return {'status':status,'latitude':lat,'longitude':lon,'accuracy':accuracy,'distance':d}
