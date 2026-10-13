"""Fail-closed answer boundary. Model prose is never a financial execution receipt."""
import json,re
from .models import now
from .assistant_summary import Summary,render

UNVERIFIED='ฉันยังไม่มีข้อมูลที่ตรวจสอบได้พอสำหรับคำตอบนี้ค่ะ ช่วยระบุบัญชี หมวด หรือช่วงวันที่ต้องการได้ไหมคะ? ยังไม่ได้บันทึกหรือแก้ข้อมูล'
NO_WRITE='ยังไม่ได้บันทึกหรือแก้ข้อมูลค่ะ ต้องมีร่างให้ตรวจและให้คุณยืนยันก่อน'

def success_claim(text):
    return bool(re.search(r'(?:บันทึก|แก้ไข|เปลี่ยน|ลบ|เพิ่ม|สร้าง|โอน|จ่าย|ปรับ).{0,65}(?:สำเร็จ|เรียบร้อย|แล้ว)|(?:saved|updated|deleted|recorded|transferred|added|done|completed)\b|เสร็จแล้ว|ดำเนินการ.{0,30}แล้ว|จัดให้แล้ว',text,re.I|re.S))

def financial_claim(text):
    return bool(re.search(r'เงิน|หนี้|ออม|งบประมาณ|วงเงิน|กำไร|ขาดทุน|บาท|สตางค์|฿|ยอด(?:เงิน|คงเหลือ|ใช้|ราย|รวม)|รายจ่าย|รายรับ|balance|spent|income|expense|money|debt',text,re.I))

from .assistant_scope import Scope,scope


def clean(text):return re.sub(r'[\\`*_{}\[\]()<>#!|~]','',str(text)).replace('\n',' ')[:300]
def money(n):return ('-' if n<0 else '')+f'{abs(n)//100:,}.{abs(n)%100:02d}'


def grounded(db,room,job,task,cache):
    if task.error:return UNVERIFIED
    if task.kind in ('balance','period','budget','comparison'):
        room.capture_context={**(room.capture_context or {}),'verified_scope':dict(kind=task.kind,account_id=task.account.id if task.account else None,category_id=task.category.id if task.category else None,start=str(task.start) if task.start else None,end=str(task.end) if task.end else None,q=task.q,transaction_kind=task.transaction_kind,expires=now()+900)}
    if task.kind=='balance':
        from .assistant_lookup import read
        query={'resource':'balances'}
        if task.account:query['q']=task.account.name
        data=read(db,room,json.dumps({'queries':[query]}))
        if task.account and data.get('results',[{}])[0].get('summary',{}).get('account_count')!=1:return UNVERIFIED
        return render(Summary(report='balances'),data)
    if task.kind in ('period','budget','comparison'):
        from .assistant_render import financial_report
        return financial_report(db,room,job,task)
    if task.kind=='analytics':
        from .assistant_analytics import report
        return report(db,room,job,task)
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
            if item.get('occurred_on') and item.get('id'):
                from .assistant_render import transaction_line
                lines.append(transaction_line(item,item.get('number',len(lines))))
            else:lines.append('- '+label+(': '+' · '.join(values) if values else ''))
        if row.get('has_more'):lines.append('ยังมีรายการถัดไป ยอดจากรายการหน้านี้ไม่ใช่ยอดรวมทั้งหมด')
    return '\n'.join(lines) if len(lines)>1 else 'ไม่พบรายการในขอบเขตที่ค้นค่ะ'


def finish(db,room,job,task,answer,cache):
    if task.kind=='mutation':
        if success_claim(answer):return NO_WRITE
        return answer if re.fullmatch(r'[^0-9๐-๙]{0,250}(?:ไหน|อะไร|เท่าไร|เท่าไหร่)[^0-9๐-๙]{0,80}',answer) else NO_WRITE
    if task.kind in ('balance','period','budget','comparison','analytics','query') or cache:return grounded(db,room,job,task,cache)
    if success_claim(answer):return NO_WRITE
    if financial_claim(answer):
        # A question can request missing input but may not assert a financial fact.
        return UNVERIFIED
    return answer
