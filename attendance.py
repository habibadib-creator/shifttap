import json,hashlib,datetime,zoneinfo
from .db import row,rows,uid,now,audit,transaction
from .security import Problem,digest,location_result

def manages(db,user,store_id):
    live=row(db,'SELECT role,active,verified FROM users WHERE id=?',(user['id'],))
    if not live or not live['active'] or not live['verified']:return False
    return live['role']=='owner' or live['role']=='manager' and bool(row(db,'SELECT 1 FROM memberships WHERE user_id=? AND store_id=?',(user['id'],store_id)))
def assigned(db,user,store_id):return bool(row(db,'SELECT 1 FROM memberships WHERE user_id=? AND store_id=?',(user['id'],store_id)))
def can_read(db,user,shift):return shift['user_id']==user['id'] or manages(db,user,shift['store_id'])

def clock(db,user,body,at=None):
    action=body.get('action');key=body.get('key');store_id=body.get('store_id')
    if action not in ['in','out','break','resume']:raise Problem('Invalid clock action.')
    if not isinstance(key,str) or not 16<=len(key)<=100:raise Problem('A valid retry key is required.')
    fingerprint=digest(json.dumps(body,sort_keys=True,separators=(',',':')))
    stamp=now() if at is None else at
    with transaction(db):
        old=row(db,'SELECT * FROM idempotency WHERE user_id=? AND key=?',(user['id'],key))
        if old:
            if old['payload_hash']!=fingerprint:raise Problem('Retry key was used for another action.',409)
            return json.loads(old['result'])
        # Recheck active state inside the write transaction to close deactivation races.
        live=row(db,'SELECT active,verified FROM users WHERE id=?',(user['id'],))
        if not live or not live['active'] or not live['verified']:raise Problem('Account is inactive.',403)
        store=row(db,'SELECT * FROM stores WHERE id=?',(store_id,))
        if not store or store['archived']:raise Problem('Store is unavailable.',404)
        if not assigned(db,user,store_id):raise Problem('You are not assigned to this store.',403)
        if not isinstance(body.get('tag'),str) or digest(body['tag'])!=store['tag_hash']:raise Problem('This NFC link has been revoked or is invalid.',403)
        reading=location_result(store,body.get('location')) if store['location_required'] else {'status':'not_required','latitude':None,'longitude':None,'accuracy':None,'distance':None}
        if store['location_required'] and reading['status']!='verified':
            # Rejected action does not create a punch. Exception endpoint stores requested reading.
            raise Problem('Location could not be verified. Request a manager-reviewed exception.',422,'location_exception')
        current=row(db,'SELECT * FROM shifts WHERE user_id=? AND ended IS NULL',(user['id'],))
        if action=='in':
            if current:raise Problem('You already have an open shift. Clock out first.',409)
            if row(db,'SELECT 1 FROM shifts WHERE user_id=? AND ended>?',(user['id'],stamp)):raise Problem('This action overlaps a recorded shift.',409)
            shift_id=uid()
            db.execute('INSERT INTO shifts(id,user_id,store_id,started,source) VALUES(?,?,?,?,?)',(shift_id,user['id'],store_id,stamp,'staff_nfc'))
        else:
            if not current or current['store_id']!=store_id:raise Problem('No open shift at this store.',409)
            shift_id=current['id']
            b=row(db,'SELECT * FROM breaks WHERE shift_id=? AND ended IS NULL',(shift_id,))
            if action=='break':
                if b:raise Problem('A break is already running.',409)
                if body.get('paid') not in [True,False,0,1]:raise Problem('Choose paid or unpaid break.')
                db.execute('INSERT INTO breaks(id,shift_id,started,paid) VALUES(?,?,?,?)',(uid(),shift_id,stamp,int(bool(body['paid']))))
            elif action=='resume':
                if not b:raise Problem('No break is running.',409)
                db.execute('UPDATE breaks SET ended=? WHERE id=?',(stamp,b['id']))
            elif action=='out':
                if b:db.execute('UPDATE breaks SET ended=? WHERE id=?',(stamp,b['id']))
                db.execute('UPDATE shifts SET ended=?,version=version+1 WHERE id=?',(stamp,shift_id))
        if action in ['break','resume']:db.execute('UPDATE shifts SET version=version+1 WHERE id=?',(shift_id,))
        db.execute('INSERT INTO location_events(user_id,store_id,action,latitude,longitude,accuracy,distance,status,created) VALUES(?,?,?,?,?,?,?,?,?)',(user['id'],store_id,action,reading['latitude'],reading['longitude'],reading['accuracy'],reading['distance'],reading['status'],stamp))
        audit(db,user['id'],'clock_'+action,shift_id,after={'timestamp':stamp,'paid':body.get('paid')})
        result={'ok':True,'timestamp':stamp,'shift_id':shift_id,'action':action}
        db.execute('INSERT INTO idempotency VALUES(?,?,?,?,?)',(user['id'],key,fingerprint,json.dumps(result),stamp))
        return result

def normalize_breaks(value,start,end):
    if not isinstance(value,list) or len(value)>100:raise Problem('Provide a valid break list.')
    result=[]
    for b in value:
        try:
            a,z=b['started'],b['ended']
            if isinstance(a,bool) or isinstance(z,bool) or not isinstance(a,int) or not isinstance(z,int) or a<start or z<a or z>end or b['paid'] not in [True,False,0,1]:raise ValueError()
            result.append({'started':a,'ended':z,'paid':int(bool(b['paid']))})
        except (KeyError,TypeError,ValueError):raise Problem('Breaks must be valid and fall within the completed shift.')
    result.sort(key=lambda b:b['started'])
    if any(a['ended']>b['started'] for a,b in zip(result,result[1:])):raise Problem('Breaks cannot overlap.')
    return result

def correct(db,user,body):
    reason=body.get('reason','').strip()
    if len(reason)<5 or len(reason)>1000:raise Problem('Give a correction reason (5–1,000 characters).')
    with transaction(db):
        s=row(db,'SELECT * FROM shifts WHERE id=?',(body.get('shift_id'),))
        if not s:raise Problem('Shift not found.',404)
        if not manages(db,user,s['store_id']):raise Problem('Manager permission required.',403)
        if s['version']!=body.get('version'):raise Problem('Shift has changed. Refresh before correcting.',409)
        a,z=body.get('started'),body.get('ended')
        if isinstance(a,bool) or isinstance(z,bool) or not isinstance(a,int) or not isinstance(z,int) or a<=0 or z<a or z>now()+60:raise Problem('Enter a valid completed shift time range.')
        if row(db,'SELECT 1 FROM shifts WHERE user_id=? AND id<>? AND started<? AND COALESCE(ended,9223372036854775807)>?',(s['user_id'],s['id'],z,a)):raise Problem('This correction would overlap another shift.',409)
        bs=normalize_breaks(body.get('breaks',[]),a,z)
        before={**s,'breaks':rows(db,'SELECT * FROM breaks WHERE shift_id=?',(s['id'],))}
        db.execute('UPDATE shifts SET started=?,ended=?,approval=\'pending\',version=version+1 WHERE id=?',(a,z,s['id']))
        db.execute('DELETE FROM breaks WHERE shift_id=?',(s['id'],))
        for b in bs:db.execute('INSERT INTO breaks VALUES(?,?,?,?,?)',(uid(),s['id'],b['started'],b['ended'],b['paid']))
        audit(db,user['id'],'shift_correction',s['id'],before=before,after={'started':a,'ended':z,'breaks':bs},reason=reason)
    return {'ok':True}

def bounds(date,tz,end=False):
    d=datetime.date.fromisoformat(date)
    if end:d+=datetime.timedelta(days=1)
    return int(datetime.datetime.combine(d,datetime.time(),zoneinfo.ZoneInfo(tz)).timestamp())

def worked(s,bs,at,start=None,end=None):
    lo=max(s['started'],start if start is not None else s['started'])
    hi=min(s['ended'] if s['ended'] is not None else at,end if end is not None else at)
    total=max(0,hi-lo)
    unpaid=sum(max(0,min(b['ended'] if b['ended'] is not None else at,hi)-max(b['started'],lo)) for b in bs if not b['paid'])
    return max(0,total-unpaid)

def shift_records(db,user,filters,at=None):
    stamp=now() if at is None else at
    args=[];where=[]
    if user['role']=='staff':where.append('s.user_id=?');args.append(user['id'])
    elif user['role']=='manager':where.append('s.store_id IN(SELECT store_id FROM memberships WHERE user_id=?)');args.append(user['id'])
    if filters.get('store_id'):where.append('s.store_id=?');args.append(filters['store_id'])
    if filters.get('user_id'):where.append('s.user_id=?');args.append(filters['user_id'])
    result=rows(db,'SELECT s.*,u.name AS employee_name,t.name AS store_name,t.timezone FROM shifts s JOIN users u ON u.id=s.user_id JOIN stores t ON t.id=s.store_id'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY s.started DESC',args)
    # Entire selected range, including cross-midnight shifts; totals clipped to range.
    for f in ['from','to']:
        if filters.get(f):
            try:datetime.date.fromisoformat(filters[f])
            except ValueError:raise Problem('Invalid date filter.')
    if filters.get('from') and filters.get('to') and filters['from']>filters['to']:raise Problem('Start date must precede end date.')
    output=[]
    for s in result:
        lo=bounds(filters['from'],s['timezone']) if filters.get('from') else None
        hi=bounds(filters['to'],s['timezone'],True) if filters.get('to') else None
        if lo is not None and (s['ended'] if s['ended'] is not None else stamp)<=lo:continue
        if hi is not None and s['started']>=hi:continue
        bs=rows(db,'SELECT * FROM breaks WHERE shift_id=? ORDER BY started',(s['id'],))
        s['breaks']=bs;s['worked_seconds']=worked(s,bs,stamp);s['range_worked_seconds']=worked(s,bs,stamp,lo,hi)
        s['unpaid_seconds']=sum(max(0,(b['ended'] if b['ended'] is not None else stamp)-b['started']) for b in bs if not b['paid'])
        s['on_break']=any(b['ended'] is None for b in bs)
        setting=row(db,'SELECT long_shift_hours FROM settings WHERE id=1')
        s['exception']= 'Long shift / missing clock-out' if s['ended'] is None and stamp-s['started']>setting['long_shift_hours']*3600 else ''
        output.append(s)
    return output
