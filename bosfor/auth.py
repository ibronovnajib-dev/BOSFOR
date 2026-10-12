from __future__ import annotations
import base64,hashlib,hmac,secrets,time
from .migrations import apply_migrations,ROLE_PERMISSIONS

ROLES=set(ROLE_PERMISSIONS)
ITERATIONS=210_000

def _now(): return int(time.time()*1000)
def _hash_password(password: str, salt: bytes|None=None, *, min_length: int=8) -> str:
    password=str(password or '')
    if len(password)<min_length: raise ValueError('password too short')
    salt=salt or secrets.token_bytes(16)
    dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(dk).decode()}'

def _verify(password: str, encoded: str) -> bool:
    try:
        alg,it,salt_b64,digest_b64=encoded.split('$',3)
        if alg!='pbkdf2_sha256': return False
        salt=base64.urlsafe_b64decode(salt_b64.encode());expected=base64.urlsafe_b64decode(digest_b64.encode())
        actual=hashlib.pbkdf2_hmac('sha256',str(password).encode(),salt,int(it))
        return hmac.compare_digest(actual,expected)
    except Exception: return False

def _principal(con,user_id:int):
    r=con.execute('''SELECT u.id,u.username,u.display_name,u.enabled,s.role FROM staff_users u
                     JOIN staff_roles s ON s.user_id=u.id WHERE u.id=?''',(int(user_id),)).fetchone()
    if not r or not int(r['enabled']): return None
    return {'id':str(r['id']),'username':r['username'],'name':r['display_name'],'role':r['role'],'permissions':permissions_for_role(r['role'])}

def permissions_for_role(role:str)->list[str]: return list(ROLE_PERMISSIONS.get(str(role),[]))
def has_permission(principal,permission:str)->bool:
    if not principal:return False
    p=set(principal.get('permissions') or permissions_for_role(principal.get('role','')))
    return '*' in p or permission in p

def require_permission(principal,permission:str):
    if not has_permission(principal,permission): raise PermissionError('permission denied')

def bootstrap_owner(con,password:str):
    apply_migrations(con);now=_now();row=con.execute("SELECT id FROM staff_users WHERE username='owner' COLLATE NOCASE").fetchone()
    if not row:
        cur=con.execute('INSERT INTO staff_users(username,display_name,password_hash,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',('owner','Owner',_hash_password(password,min_length=1),1,now,now));uid=cur.lastrowid
        con.execute("INSERT INTO staff_roles(user_id,role) VALUES(?,'owner')",(uid,))
    else: uid=row['id']
    return _principal(con,uid)

def authenticate(con,username:str,password:str):
    apply_migrations(con);row=con.execute('''SELECT u.id,u.password_hash,u.enabled FROM staff_users u WHERE username=? COLLATE NOCASE''',(str(username or '').strip(),)).fetchone()
    if not row or not int(row['enabled']) or not _verify(password,row['password_hash']): return None
    return _principal(con,row['id'])

def create_staff(con,username,password,display_name,role,actor):
    require_permission(actor,'*'); role=str(role)
    if role not in ROLES or role=='owner': raise ValueError('invalid role')
    username=str(username or '').strip();display_name=str(display_name or '').strip()
    if not username or len(username)>64 or len(display_name)<2 or len(display_name)>80: raise ValueError('invalid staff')
    now=_now();cur=con.execute('INSERT INTO staff_users(username,display_name,password_hash,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',(username,display_name,_hash_password(password),1,now,now));uid=cur.lastrowid
    con.execute('INSERT INTO staff_roles(user_id,role) VALUES(?,?)',(uid,role));return _principal(con,uid)

def set_role(con,user_id,role,actor):
    require_permission(actor,'*');role=str(role)
    if role not in ROLES: raise ValueError('invalid role')
    con.execute('UPDATE staff_roles SET role=? WHERE user_id=?',(role,int(user_id)));return _principal(con,int(user_id))

def set_enabled(con,user_id,enabled,actor):
    require_permission(actor,'*');con.execute('UPDATE staff_users SET enabled=?,updated_at=? WHERE id=?',(1 if enabled else 0,_now(),int(user_id)))
    if not enabled: con.execute('DELETE FROM staff_sessions WHERE user_id=?',(int(user_id),))
    return _principal(con,int(user_id))

def list_staff(con,actor):
    require_permission(actor,'*')
    return [dict(r) for r in con.execute('''SELECT u.id,u.username,u.display_name,u.enabled,s.role,u.created_at,u.updated_at FROM staff_users u JOIN staff_roles s ON s.user_id=u.id ORDER BY u.display_name,u.id''')]

def create_session(con,principal_id:int,ttl_seconds:int=12*60*60):
    apply_migrations(con);principal=_principal(con,int(principal_id))
    if not principal: raise PermissionError('disabled account')
    raw=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);now=_now();exp=now+int(ttl_seconds)*1000
    con.execute('INSERT INTO staff_sessions(token_hash,user_id,csrf,created_at,expires_at) VALUES(?,?,?,?,?)',(hashlib.sha256(raw.encode()).hexdigest(),int(principal_id),csrf,now,exp))
    return {'token':raw,'csrf':csrf,'expires_at':exp}

def resolve_session(con,token:str|None):
    if not token:return None
    apply_migrations(con);h=hashlib.sha256(str(token).encode()).hexdigest();row=con.execute('SELECT user_id,csrf,expires_at FROM staff_sessions WHERE token_hash=?',(h,)).fetchone()
    if not row:return None
    if int(row['expires_at'])<=_now(): con.execute('DELETE FROM staff_sessions WHERE token_hash=?',(h,));return None
    p=_principal(con,row['user_id'])
    if not p:return None
    p['csrf']=row['csrf'];p['expires_at']=int(row['expires_at']);return p

def delete_session(con,token:str|None):
    if token: con.execute('DELETE FROM staff_sessions WHERE token_hash=?',(hashlib.sha256(str(token).encode()).hexdigest(),))
