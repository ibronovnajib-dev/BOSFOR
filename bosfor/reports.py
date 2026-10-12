from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .finance import daily_close
from .inventory import low_stock_items
from .migrations import ensure_phase2_schema, ensure_phase3_schema, ensure_phase4_schema, ensure_phase5_schema
from .staff import hours_summary
from .tasks import overdue_tasks

TZ = ZoneInfo('Asia/Dushanbe')


def _as_local(now: datetime | None) -> datetime:
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=TZ)
    return now.astimezone(TZ)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except Exception as exc:
        raise ValueError('invalid date') from exc


def live_dashboard(con, now: datetime | None = None) -> dict:
    ensure_phase2_schema(con); ensure_phase3_schema(con); ensure_phase4_schema(con); ensure_phase5_schema(con)
    local = _as_local(now); now_ms = int(local.timestamp() * 1000); business_date = local.date().isoformat()
    finance = daily_close(con, business_date)
    open_orders = int(con.execute("SELECT COUNT(*) c FROM os_orders WHERE state NOT IN ('closed','cancelled')").fetchone()['c'])
    active_tables = int(con.execute("SELECT COUNT(*) c FROM os_table_state WHERE state NOT IN ('free','cleaning','out_of_service')").fetchone()['c'])
    waiting = int(con.execute("SELECT COUNT(*) c FROM os_waitlist WHERE status IN ('waiting','notified')").fetchone()['c'])
    kt = con.execute("""SELECT COUNT(*) active,
                     COALESCE(SUM(CASE WHEN state IN ('queued','preparing') AND (? - sent_at) > target_minutes*60000 THEN 1 ELSE 0 END),0) overdue
                     FROM os_kitchen_tickets WHERE state IN ('queued','preparing')""", (now_ms,)).fetchone()
    lows = low_stock_items(con)
    out_stock = sum(1 for x in lows if float(x['available']) <= 0)
    sold_out = int(con.execute('SELECT COUNT(*) c FROM os_dish_availability WHERE available=0').fetchone()['c'])
    open_po = int(con.execute("SELECT COUNT(*) c FROM purchase_orders WHERE status IN ('draft','approved','partial')").fetchone()['c'])
    staff_ids = [r['staff_id'] for r in con.execute('SELECT DISTINCT staff_id FROM os_clock_events')]
    clocked = 0
    for sid in staff_ids:
        try:
            if hours_summary(con, sid, 0, now_ms + 1)['open_clock_in'] is not None:
                clocked += 1
        except Exception:
            continue
    overdue = overdue_tasks(con, now_ms)
    variance = int(finance.get('cash_variance_total') or 0)
    alerts = []
    if int(kt['overdue'] or 0): alerts.append({'severity':'critical','code':'kitchen_overdue','count':int(kt['overdue'])})
    if out_stock: alerts.append({'severity':'critical','code':'out_of_stock','count':out_stock})
    if waiting: alerts.append({'severity':'warning','code':'waiting_parties','count':waiting})
    if variance: alerts.append({'severity':'warning','code':'cash_variance','amount':variance})
    if len(lows) - out_stock: alerts.append({'severity':'warning','code':'low_stock','count':len(lows)-out_stock})
    if sold_out: alerts.append({'severity':'warning','code':'sold_out_dishes','count':sold_out})
    if open_po: alerts.append({'severity':'warning','code':'open_purchase_orders','count':open_po})
    if overdue: alerts.append({'severity':'warning','code':'overdue_tasks','count':len(overdue)})
    return {
        'business_date': business_date,
        'open_orders': open_orders,
        'active_tables': active_tables,
        'waiting_parties': waiting,
        'kitchen_active': int(kt['active'] or 0),
        'kitchen_overdue': int(kt['overdue'] or 0),
        'sales_today': int(finance.get('net_sales') or 0),
        'average_check': finance.get('average_check') or 0,
        'refunds_today': int(finance.get('refunds') or 0),
        'cash_variance': variance,
        'low_stock_count': len(lows),
        'out_of_stock_count': out_stock,
        'sold_out_dishes': sold_out,
        'open_purchase_orders': open_po,
        'staff_clocked_in': clocked,
        'overdue_tasks': len(overdue),
        'cogs_complete': bool(finance.get('cogs_complete')),
        'alerts': alerts,
    }


def historical_report(con, date_from: str, date_to: str) -> dict:
    start = _parse_date(date_from); end = _parse_date(date_to)
    if end < start or (end - start).days > 366:
        raise ValueError('invalid date range')
    days=[]; cur=start
    while cur <= end:
        days.append(daily_close(con, cur.isoformat()))
        cur += timedelta(days=1)
    totals = {
        'orders_count': sum(int(x['orders_count']) for x in days),
        'gross_sales': sum(int(x['gross_sales']) for x in days),
        'discounts': sum(int(x['discounts']) for x in days),
        'net_sales': sum(int(x['net_sales']) for x in days),
        'refunds': sum(int(x['refunds']) for x in days),
        'expenses': sum(int(x['expenses']) for x in days),
        'cash_variance_total': sum(int(x['cash_variance_total']) for x in days),
        'cogs_complete': all(bool(x['cogs_complete']) for x in days),
    }
    totals['average_check'] = 0 if not totals['orders_count'] else round(totals['net_sales']/totals['orders_count'],2)
    return {'date_from':start.isoformat(),'date_to':end.isoformat(),'days':days,'totals':totals}


def _csv_safe(value) -> str:
    s = '' if value is None else str(value)
    if s.lstrip().startswith(('=','+','-','@')):
        return "'" + s
    return s


def export_csv(report_type: str, rows: list[dict]) -> str:
    report_type = str(report_type or '').strip()
    if not report_type or not isinstance(rows, list):
        raise ValueError('invalid report')
    keys=[]
    for row in rows:
        if not isinstance(row, dict): raise ValueError('invalid row')
        for key in row:
            if key not in keys: keys.append(key)
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=keys,extrasaction='ignore'); w.writeheader()
    for row in rows:
        w.writerow({k:_csv_safe(row.get(k,'')) for k in keys})
    return out.getvalue()
