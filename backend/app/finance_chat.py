"""Bounded report questions resolved by code; no SQL or actions supplied by a model."""
import re
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select
from .models import Account
from .reporting import today, month_bounds, period_summary, transaction_report
from fastapi import HTTPException
from .ledger import account_balances

MONTHS=['มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน','กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม']

def resolve_period(text,previous_texts=()):
    now=today()
    has_period=lambda t: bool(re.search(r'\d{4}-\d{2}|เดือนนี้|เดือนที่แล้ว|เดือนก่อน|วันนี้|เมื่อวาน|ปี|\d+\s*เดือน',t) or any(m in t for m in MONTHS))
    source=text
    if not has_period(text) and any(w in text for w in ('แล้ว','ล่ะ','ละ','บัญชีไหน','มีอะไรบ้าง')):
        source=next((t for t in previous_texts if has_period(t)),text)
    dates=re.findall(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)',source)
    if dates:
        if len(dates)>2: raise ValueError('กรุณาระบุช่วงวันเริ่มต้นและสิ้นสุดเพียงช่วงเดียว')
        start,end=date.fromisoformat(dates[0]),date.fromisoformat(dates[-1])
        if start>end: raise ValueError('วันเริ่มต้นต้องไม่เกินวันสิ้นสุด')
        return start,end
    months=re.findall(r'(?<!\d)\d{4}-\d{2}(?![\d-])',source)
    if months:
        if len(set(months))!=1: raise ValueError('รุ่นนี้ถามรายงานได้ทีละเดือน หรือระบุช่วง YYYY-MM-DD ถึง YYYY-MM-DD')
        return month_bounds(months[0])
    for index,name in enumerate(MONTHS,1):
        if name in source:
            match=re.search(r'(?<!\d)(20\d{2}|25\d{2})(?!\d)',source)
            year=int(match[0]) if match else now.year
            if year>2400: year-=543
            return month_bounds(f'{year:04}-{index:02}')
    if 'เมื่อวาน' in source: return now-timedelta(days=1),now-timedelta(days=1)
    if 'วันนี้' in source: return now,now
    if 'เดือนที่แล้ว' in source or 'เดือนก่อน' in source:
        end=now.replace(day=1)-timedelta(days=1)
        return end.replace(day=1),end
    if re.search(r'ปี|\d+\s*เดือน|สัปดาห์',source):
        raise ValueError('กรุณาระบุเดือน เช่น 2026-09 หรือช่วงวัน YYYY-MM-DD ถึง YYYY-MM-DD เพื่อให้รายงานตรงช่วงที่ต้องการ')
    return month_bounds(now.strftime('%Y-%m'))

def money(n): return f'฿{Decimal(n)/100:,.2f}'

def answer_report(db,job,history):
    text=job.payload.get('text','')
    if not any(w in text for w in ('งบ','เท่าไร','เท่าไหร่','เดือน','วันนี้','เมื่อวาน','รายการ','บัญชีไหน','มีอะไรบ้าง','ใช้ไป','จ่ายไป','ยอดเงิน','ยอดบัญชี','ย้อนหลัง')):
        return None
    earlier=[m.content for m in history if m.role=='user' and m.content!=text]
    try: start,end=resolve_period(text,earlier)
    except (ValueError, HTTPException) as exc:
        # Never echo DB/provider errors. Only period parsing happens in this try.
        if isinstance(exc,HTTPException): detail=str(exc.detail)
        elif isinstance(exc,ValueError): detail='ช่วงวันไม่ถูกต้อง กรุณาระบุ YYYY-MM หรือ YYYY-MM-DD ถึง YYYY-MM-DD'
        else: raise
        return detail+' รายงานนี้ไม่ได้เปลี่ยนยอดเงิน'
    if (end-start).days>366: return 'กรุณาเลือกช่วงไม่เกิน 366 วันต่อครั้ง เพื่อให้ตรวจสอบรายการได้ครบ'
    accounts=db.scalars(select(Account).where(Account.workspace_id==job.workspace_id)).all()
    scope=text
    if any(w in text for w in ('แล้ว','ล่ะ')) and not any(a.name.casefold() in text.casefold() for a in accounts):
        scope=text+' '+next(iter(earlier),'')
    wallets=[a for a in accounts if a.kind in ('asset','liability') and a.name.casefold() in scope.casefold()]
    categories=[a for a in accounts if a.kind in ('income','expense') and a.name.casefold() in scope.casefold()]
    if len(wallets)>1 or len(categories)>1:
        return 'กรุณาถามทีละบัญชี/หมวดหมู่ หรือถามภาพรวมโดยไม่ระบุชื่อบัญชี เพื่อไม่ให้รวมยอดผิดขอบเขต'
    if not wallets and 'ยอดบัญชี' not in text and re.search(r'บัญชี\s*(?!ไหน|ใด|อะไร|ทั้งหมด|ทุก|ของ|ล่าสุด|ที่|มี|ใน|:|：|$)[A-Za-zก-๙]',text):
        return 'ยังจับคู่ชื่อบัญชีไม่ได้ กรุณาใช้ชื่อตามหน้าบัญชี: '+', '.join(a.name for a in accounts if a.kind in ('asset','liability'))
    aid=wallets[0].id if wallets else None
    category=categories[0].id if categories else None
    if 'งบ' in text:
        from .budgets import budget_report
        if wallets: return 'งบประมาณแบ่งตามหมวดรายจ่าย ไม่แยกตามบัญชี กรุณาถามชื่อหมวดหรือภาพรวมเดือนที่ต้องการ'
        if (start,end)!=month_bounds(start.strftime('%Y-%m')): return 'งบประมาณเป็นรายเดือน กรุณาระบุเดือน เช่น งบเดือนนี้ หรือ งบ 2026-10'
        if categories and categories[0].kind!='expense': return 'งบประมาณรองรับหมวดรายจ่ายเท่านั้น'
        budget=budget_report(db,job.workspace_id,start.strftime('%Y-%m'))
        rows=[r for r in budget['items'] if not category or r['category_id']==category]
        planned=sum(r['amount'] for r in rows);spent=sum(r['spent'] for r in rows)
        lines=[f'งบประมาณจากระบบโดยตรง · {start.isoformat()} ถึง {end.isoformat()}', 'ขอบเขต: '+(categories[0].name if categories else 'ทุกหมวดที่ตั้งงบใน workspace'), f'วงเงิน {money(planned)} · ใช้จริง {money(spent)} · คงเหลือ {money(planned-spent)}']
        if not rows: lines.append('ยังไม่ได้ตั้งงบในช่วง/หมวดนี้ เพิ่มได้ที่หน้าบริการทั้งหมด → งบประมาณ')
        for row in rows:
            state='เกินงบ '+money(-row['remaining']) if row['remaining']<0 else 'ใช้ครบงบ' if row['remaining']==0 else 'เหลือ '+money(row['remaining'])
            lines.append(f'• {row["name"]}: ใช้ {money(row["spent"])} / {money(row["amount"])} · {state}')
        if not category: lines.append('รายจ่ายในหมวดที่ยังไม่ได้ตั้งงบ '+money(budget['unbudgeted_expense']))
        lines.append('อ่านข้อมูลเท่านั้น ยังไม่ได้สร้างหรือเปลี่ยนงบ หากต้องการตั้งวงเงินให้ใช้หน้างบประมาณ')
        return '\n'.join(lines)
    report=period_summary(db,job.workspace_id,start,end,aid,category)
    kind='income' if 'รายรับ' in text and not any(w in text for w in ('จ่าย','ใช้')) else None if 'รายการทั้งหมด' in text else 'expense'
    details=transaction_report(db,job.workspace_id,start,end,kind,aid,category,page_size=20)
    lines=[f'รายงานจากระบบโดยตรง · {start.isoformat()} ถึง {end.isoformat()}', 'ขอบเขต: '+(' / '.join(a.name for a in wallets+categories) or 'ทุกบัญชีใน workspace'),f'รายจ่าย {money(report["expense"])} · รายรับ {money(report["income"])}', 'การโอนเงินและจ่ายบัตรเครดิตไม่นับเป็นรายจ่ายซ้ำ']
    if report['spending_accounts']:
        lines.append('\nใช้จ่ายจากบัญชี:')
        lines.extend(f'• {a["name"]}: {money(a["expense"])} ({a["count"]} รายการ)' for a in report['spending_accounts'][:20])
    if report['categories']:
        lines.append('\nหมวดใช้จ่าย:')
        lines.extend(f'• {a["name"]}: {money(a["amount"])}' for a in report['categories'][:20])
    lines.append(f'\nรายการ{"รายรับ" if kind=="income" else "ทั้งหมด" if kind is None else "รายจ่าย"}: {details["total"]} รายการ')
    for item in details['items']:
        names=' → '.join(a['name'] for a in item['accounts'])
        lines.append(f'• {item["occurred_on"]} · {item["description"]} · {money(item["amount"])} · {names}')
    if details['total']>20: lines.append('แสดง 20 รายการแรก ยอดรวมด้านบนคำนวณจากทุกรายการในช่วงที่เลือก ดูรายการที่เหลือในหน้ารายการ')
    if any(w in text for w in ('ยอด','มีเงิน')):
        balances=account_balances(db,job.workspace_id)
        lines.append('\nยอดบัญชีล่าสุด (สะสมถึงปัจจุบัน ไม่ใช่ยอดสิ้นช่วงที่เลือก):')
        lines.extend(f'• {a["name"]}: {money(a["balance"])}' for a in balances if a['kind'] in ('asset','liability') and (not aid or a['id']==aid))
    lines.append('\nตัวเลขคำนวณจากบัญชีจริงบนเซิร์ฟเวอร์ ไม่ใช้โมเดลคำนวณหรือบันทึกเงิน')
    return '\n'.join(lines)
