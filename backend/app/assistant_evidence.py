"""Fail-closed answer boundary. Model prose is never a financial execution receipt."""
import json,re
from dataclasses import dataclass
from sqlalchemy import select,literal,func
from .models import Account,now
from .reporting import today,month_bounds,period_summary
from .assistant_summary import Summary,render

UNVERIFIED='ฉันยังไม่มีข้อมูลที่ตรวจสอบได้พอสำหรับคำตอบนี้ค่ะ ช่วยระบุบัญชี หมวด หรือช่วงวันที่ต้องการได้ไหมคะ? ยังไม่ได้บันทึกหรือแก้ข้อมูล'
NO_WRITE='ยังไม่ได้บันทึกหรือแก้ข้อมูลค่ะ ต้องมีร่างให้ตรวจและให้คุณยืนยันก่อน'

def success_claim(text):
    return bool(re.search(r'(?:บันทึก|แก้ไข|เปลี่ยน|ลบ|เพิ่ม|สร้าง|โอน|จ่าย|ปรับ).{0,65}(?:สำเร็จ|เรียบร้อย|แล้ว)|(?:saved|updated|deleted|recorded|transferred|added|done|completed)\b|เสร็จแล้ว|ดำเนินการ.{0,30}แล้ว|จัดให้แล้ว',text,re.I|re.S))

def financial_claim(text):
    return bool(re.search(r'เงิน|หนี้|ออม|งบประมาณ|วงเงิน|กำไร|ขาดทุน|บาท|สตางค์|฿|ยอด(?:เงิน|คงเหลือ|ใช้|ราย|รวม)|รายจ่าย|รายรับ|balance|spent|income|expense|money|debt',text,re.I))

@dataclass
class Scope:
    kind:str
    text:str
    start:object=None
    end:object=None
    account:object=None
    category:object=None
    error:bool=False


def scope(db,room,text):
    mutation=bool(re.search(r'จด|บันทึก|แก้|เพิ่ม|สร้าง|ตั้งงบ|ปรับงบ|เปลี่ยน|ลบ|record|save|update|delete',text,re.I))
    if mutation:return Scope('mutation',text)
    balance=bool(re.search(r'มีเงิน|ยอด(?:เงิน|บัญชี|คงเหลือ)|เงิน.*เหลือ|balance|how much money',text,re.I))
    period=bool(re.search(r'รายจ่าย|รายรับ|ใช้(?:ไป|เงิน)|จ่าย(?:ไป|อะไร)|เดือน|spent|income|expense',text,re.I) or (re.search(r'วันนี้|เมื่อวาน|ย้อนหลัง',text) and re.search(r'เท่าไร|เท่าไหร่|กี่บาท|กิน|ซื้อ',text)))
    kind='balance' if balance and not period else 'period' if period else 'query' if re.search(r'บัญชี|หมวด|งบ|รายการ|เป้าหมาย|ต่อ|ที่เหลือ',text) else 'conversation'
    result=Scope(kind,text)
    if kind in ('balance','period') and re.search(r'เปรียบเทียบ|เทียบกับ|แนวโน้ม|เฉลี่ย|สูงสุด|ต่ำสุด|มากที่สุด|น้อยที่สุด|คาดการณ์|งบประมาณ|งบเดือน|เกินงบ',text):
        result.error=True;return result
    if balance and (period or re.search(r'เมื่อวาน|ย้อนหลัง|สิ้น|ณ |\d{4}-\d{2}',text)):
        result.error=True;return result
    prior=(room.capture_context or {}).get('verified_scope',{})
    followup=bool(re.fullmatch(r'(?:ต่อ|ดูต่อ|แล้ว.*ล่ะ|.*เดือน.*ล่ะ)[?？\s]*',text.strip()))
    if followup and prior.get('expires',0)>now() and prior.get('kind') in ('balance','period'):
        result.kind=kind=prior['kind']
    if kind not in ('balance','period'):return result
    match=(func.instr(literal(text),Account.name) if db.bind.dialect.name=='sqlite' else func.strpos(literal(text),Account.name))>0
    rows=db.scalars(select(Account).where(Account.workspace_id==room.workspace_id,match).limit(4)).all()
    wallets=[a for a in rows if a.kind in ('asset','liability')];categories=[a for a in rows if a.kind in ('income','expense')]
    if len(wallets)>1 or len(categories)>1:result.error=True;return result
    if followup and prior.get('expires',0)>now() and not rows:
        ids=[prior.get('account_id'),prior.get('category_id')]
        rows=db.scalars(select(Account).where(Account.workspace_id==room.workspace_id,Account.id.in_([v for v in ids if v]))).all()
        wallets=[a for a in rows if a.kind in ('asset','liability')];categories=[a for a in rows if a.kind in ('income','expense')]
        if len(rows)!=len([v for v in ids if v]):result.error=True
    result.account=wallets[0] if wallets else None;result.category=categories[0] if categories else None
    if re.search(r'เฉพาะ|หมวด|บัญชี(?!ไหน|อะไร|ทั้งหมด|ทุก)',text) and not rows:result.error=True
    if kind=='balance' and categories:result.error=True
    if kind=='period':
        from .finance_chat import resolve_period
        try:
            if followup and text.strip() in ('ต่อ','ดูต่อ') and prior.get('start') and prior.get('end'):
                from datetime import date
                result.start,result.end=date.fromisoformat(prior['start']),date.fromisoformat(prior['end'])
            else:result.start,result.end=resolve_period(text,[])
            if (result.end-result.start).days>366:result.error=True
        except Exception:result.error=True
    return result


def clean(text):return re.sub(r'[\\`*_{}\[\]()<>#!|~]','',str(text)).replace('\n',' ')[:300]
def money(n):return ('-' if n<0 else '')+f'{abs(n)//100:,}.{abs(n)%100:02d}'


def grounded(db,room,job,task,cache):
    if task.error:return UNVERIFIED
    if task.kind in ('balance','period'):
        room.capture_context={**(room.capture_context or {}),'verified_scope':dict(kind=task.kind,account_id=task.account.id if task.account else None,category_id=task.category.id if task.category else None,start=str(task.start) if task.start else None,end=str(task.end) if task.end else None,expires=now()+900)}
    if task.kind=='balance':
        from .assistant_lookup import read
        query={'resource':'balances'}
        if task.account:query['q']=task.account.name
        data=read(db,room,json.dumps({'queries':[query]}))
        # Name substring matching must not broaden an exact account scope.
        if task.account and data.get('results',[{}])[0].get('summary',{}).get('account_count')!=1:return UNVERIFIED
        return render(Summary(report='balances'),data)
    if task.kind=='period':
        aid=task.account.id if task.account else None;cat=task.category.id if task.category else None
        result=period_summary(db,room.workspace_id,task.start,task.end,aid,cat)
        from .finance_references import collect
        collect(job,dict(source='ledger_backend',account_id=aid,category_id=cat,**result))
        label=' / '.join(clean(a.name) for a in (task.account,task.category) if a) or 'ทุกบัญชีและทุกหมวดในพื้นที่นี้'
        return f"ช่วง **{task.start.isoformat()} ถึง {task.end.isoformat()}** · {label}\n\n- รายจ่าย: **{money(result['expense'])} บาท**\n- รายรับ: **{money(result['income'])} บาท**\n- รายรับหักรายจ่าย: **{money(result['income']-result['expense'])} บาท**\n\nจากรายการที่บันทึกแล้ว ไม่ใช่ยอดคงเหลือสะสมค่ะ"
    if task.kind=='mutation':return NO_WRITE
    # Read-only lists are rendered, never free model totals from a partial page.
    results=list(cache.values())
    if not results:return UNVERIFIED
    result=results[-1];lines=['ข้อมูลจากการค้น (เฉพาะขอบเขตและหน้าที่เรียก):']
    if result.get('source')=='ledger_backend' and 'month' in result and 'income' in result:return render(Summary(report='monthly'),result)
    for row in result.get('results',[result]):
        for item in row.get('items',[])[:20]:
            label=clean(item.get('name') or item.get('description') or '')
            fields={'amount':'จำนวนเงิน','balance_satang':'ยอดคงเหลือ','target':'เป้าหมาย','saved':'ออมแล้ว','spent':'ใช้ไป','remaining':'คงเหลือ'}
            values=[f'{title} {money(item[key])} บาท' for key,title in fields.items() if type(item.get(key)) is int]
            lines.append('- '+label+(': '+' · '.join(values) if values else ''))
        if row.get('has_more'):lines.append('ยังมีรายการถัดไป ยอดจากรายการหน้านี้ไม่ใช่ยอดรวมทั้งหมด')
    return '\n'.join(lines) if len(lines)>1 else 'ไม่พบรายการในขอบเขตที่ค้นค่ะ'


def finish(db,room,job,task,answer,cache):
    if task.kind=='mutation':
        if success_claim(answer):return NO_WRITE
        return answer if re.fullmatch(r'[^0-9๐-๙]{0,250}(?:ไหน|อะไร|เท่าไร|เท่าไหร่)[^0-9๐-๙]{0,80}',answer) else NO_WRITE
    if task.kind in ('balance','period','query') or cache:return grounded(db,room,job,task,cache)
    if success_claim(answer):return NO_WRITE
    if financial_claim(answer):
        # A question can request missing input but may not assert a financial fact.
        return UNVERIFIED
    return answer
