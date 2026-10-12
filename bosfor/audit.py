from __future__ import annotations
import json,time
from .migrations import apply_migrations

def record_event(con,*,actor_id,action,entity_type,entity_id=None,reason='',metadata=None)->int:
    apply_migrations(con);action=str(action or '').strip();entity_type=str(entity_type or '').strip();reason=str(reason or '')
    if not action or not entity_type or len(action)>80 or len(entity_type)>80 or len(reason)>500: raise ValueError('invalid audit event')
    payload=json.dumps(metadata or {},ensure_ascii=False,separators=(',',':'),sort_keys=True)
    
    try: actor_db_id=None if actor_id in (None,'') else int(actor_id)
    except (TypeError,ValueError): actor_db_id=None
    cur=con.execute('INSERT INTO audit_events(actor_id,action,entity_type,entity_id,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)',(actor_db_id,action,entity_type,None if entity_id is None else str(entity_id),reason,payload,int(time.time()*1000)))
    return int(cur.lastrowid)

def list_events(con,*,limit=200,actor_id=None,action=None):
    apply_migrations(con);where=[];args=[]
    if actor_id is not None:where.append('actor_id=?');args.append(int(actor_id))
    if action:where.append('action=?');args.append(str(action))
    q='SELECT * FROM audit_events'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY created_at DESC,id DESC LIMIT ?';args.append(min(1000,max(1,int(limit))))
    out=[]
    for r in con.execute(q,args):
        d=dict(r)
        try:d['metadata']=json.loads(d.pop('metadata_json'))
        except Exception:d['metadata']={};d.pop('metadata_json',None)
        out.append(d)
    return out
