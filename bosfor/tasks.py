from __future__ import annotations
from datetime import datetime, timezone, timedelta
import secrets, sqlite3, time
from .migrations import ensure_phase5_schema

class TaskConflict(RuntimeError): pass
def _now(): return int(time.time()*1000)
def _actor_id(a): return str(a.get('id') or a.get('username') or 'system')
def _manager(a):
    if a.get('role') not in {'owner','manager'}: raise TaskConflict('permission denied')

def create_template(con: sqlite3.Connection, name: str, items, actor: dict) -> dict:
    ensure_phase5_schema(con); _manager(actor); name=str(name or '').strip()
    if len(name)<2 or not isinstance(items,list) or not items or len(items)>100: raise TaskConflict('invalid template')
    tid='TPL-'+secrets.token_hex(4).upper(); now=_now(); con.execute('INSERT INTO ops_task_templates(id,name,created_by,created_at) VALUES(?,?,?,?)',(tid,name,_actor_id(actor),now))
    for idx,item in enumerate(items):
        title=str((item or {}).get('title','')).strip()
        try: offset=int((item or {}).get('due_offset_min',0))
        except Exception: raise TaskConflict('invalid due offset')
        if len(title)<2 or len(title)>200 or offset<0 or offset>48*60: raise TaskConflict('invalid template item')
        con.execute('INSERT INTO ops_task_template_items(template_id,title,due_offset_min,sort_order) VALUES(?,?,?,?)',(tid,title,offset,idx))
    out=dict(con.execute('SELECT * FROM ops_task_templates WHERE id=?',(tid,)).fetchone()); return out

def _day_start(date_s: str) -> int:
    try: d=datetime.strptime(str(date_s),'%Y-%m-%d').date()
    except Exception as exc: raise TaskConflict('invalid business date') from exc
    return int(datetime(d.year,d.month,d.day,tzinfo=timezone(timedelta(hours=5))).timestamp()*1000)

def instantiate_checklist(con: sqlite3.Connection, template_id: str, business_date: str, actor: dict, assigned_to: str='') -> dict:
    ensure_phase5_schema(con); _manager(actor); tpl=con.execute('SELECT * FROM ops_task_templates WHERE id=? AND active=1',(template_id,)).fetchone()
    if not tpl: raise TaskConflict('template not found')
    base=_day_start(business_date); cid='CL-'+secrets.token_hex(5).upper(); now=_now(); assigned_to=str(assigned_to or '').strip()
    con.execute('INSERT INTO ops_checklists(id,template_id,business_date,assigned_to,created_by,created_at) VALUES(?,?,?,?,?,?)',(cid,template_id,business_date,assigned_to,_actor_id(actor),now))
    for item in con.execute('SELECT * FROM ops_task_template_items WHERE template_id=? ORDER BY sort_order,id',(template_id,)):
        cur=con.execute("INSERT INTO ops_tasks(checklist_id,title,assigned_to,due_at,status,created_at) VALUES(?,?,?,?, 'pending',?)",(cid,item['title'],assigned_to,base+int(item['due_offset_min'])*60000,now))
        con.execute("INSERT INTO ops_task_events(task_id,event_type,actor_id,created_at) VALUES(?,'created',?,?)",(cur.lastrowid,_actor_id(actor),now))
    return dict(con.execute('SELECT * FROM ops_checklists WHERE id=?',(cid,)).fetchone())

def transition_task(con: sqlite3.Connection, task_id: int, target: str, actor: dict, reason: str='') -> dict:
    ensure_phase5_schema(con)
    began=False
    try:
        if not con.in_transaction: con.execute('BEGIN IMMEDIATE'); began=True
        row=con.execute('SELECT * FROM ops_tasks WHERE id=?',(int(task_id),)).fetchone()
        if not row: raise TaskConflict('task not found')
        if actor.get('role') not in {'owner','manager','waiter','cashier','kitchen'}: raise TaskConflict('permission denied')
        if row['assigned_to'] and actor.get('role') not in {'owner','manager'} and row['assigned_to']!=_actor_id(actor): raise TaskConflict('permission denied')
        graph={'pending':{'in_progress','done','skipped'},'in_progress':{'done','skipped'},'done':set(),'skipped':set()}
        if target not in graph.get(row['status'],set()): raise TaskConflict('invalid task transition')
        reason=str(reason or '').strip()
        if target=='skipped' and len(reason)<2: raise TaskConflict('skip reason required')
        now=_now(); started=now if target=='in_progress' and row['started_at'] is None else row['started_at']; completed=now if target in {'done','skipped'} else row['completed_at']
        con.execute('UPDATE ops_tasks SET status=?,skip_reason=?,started_at=?,completed_at=? WHERE id=?',(target,reason if target=='skipped' else row['skip_reason'],started,completed,row['id']))
        con.execute('INSERT INTO ops_task_events(task_id,event_type,actor_id,reason,created_at) VALUES(?,?,?,?,?)',(row['id'],target,_actor_id(actor),reason,now))
        out=dict(con.execute('SELECT * FROM ops_tasks WHERE id=?',(row['id'],)).fetchone())
        if began: con.commit()
        return out
    except Exception:
        if began and con.in_transaction: con.rollback()
        raise

def overdue_tasks(con: sqlite3.Connection, now_ms: int | None=None) -> list[dict]:
    ensure_phase5_schema(con); now=_now() if now_ms is None else int(now_ms)
    return [dict(r) for r in con.execute("SELECT * FROM ops_tasks WHERE status IN ('pending','in_progress') AND due_at<? ORDER BY due_at,id",(now,))]

def add_logbook_entry(con: sqlite3.Connection, entry: str, actor: dict, *, related_type: str='', related_id: str='') -> dict:
    ensure_phase5_schema(con); _manager(actor); entry=str(entry or '').strip(); related_type=str(related_type or '').strip(); related_id=str(related_id or '').strip()
    if len(entry)<2 or len(entry)>1000 or len(related_type)>40 or len(related_id)>80: raise TaskConflict('invalid logbook entry')
    cur=con.execute('INSERT INTO ops_logbook(entry,actor_id,related_type,related_id,created_at) VALUES(?,?,?,?,?)',(entry,_actor_id(actor),related_type,related_id,_now()))
    return dict(con.execute('SELECT * FROM ops_logbook WHERE id=?',(cur.lastrowid,)).fetchone())
