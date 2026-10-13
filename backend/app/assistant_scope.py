"""One typed, user-derived scope shared by verified renderers; never broaden silently."""
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal
from sqlalchemy import select,literal,func
from .models import Account,now
from .reporting import month_bounds
from .finance_chat import resolve_period,normalize_months,MONTHS

@dataclass
class Scope:
    kind:Literal['mutation','balance','period','budget','comparison','query','conversation']
    text:str
    start:date|None=None
    end:date|None=None
    account:Account|None=None
    category:Account|None=None
    error:bool=False
    q:str=''
    transaction_kind:str|None=None
    include_items:bool=False


def subject(text,names):
    """Strip request grammar at edges only; never erase words inside a subject."""
    value=normalize_months(text)
    for name in sorted(names,key=len,reverse=True):value=value.replace(name,' ')
    value=re.sub(r'\d{4}-\d{2}(?:-\d{2})?|(?<!\d)(?:20|25)\d{2}(?!\d)',' <period> ',value)
    for name in MONTHS:value=value.replace(name,' <period> ')
    for word in ('เดือนที่แล้ว','เดือนก่อน','เดือนนี้','เมื่อวาน','วันนี้'):
        value=value.replace(word,' <period> ')
    prefixes=['รายรับหักรายจ่าย','เปรียบเทียบ','ค่าใช้จ่าย','โอนเงิน','โอน','จ่ายบัตรเครดิต','จ่ายบัตร','รายจ่าย','รายรับ','รายการ','ใช้จ่าย','ใช้ไป','ใช้เงิน','จ่ายไป','ช่วย','สรุป','แสดง','อยากรู้ว่า','อยากรู้','ขอทราบ','ขอดู','รบกวน','เทียบกับ','เทียบ','เฉพาะ','ทุกบัญชี','ทุกหมวด','ทั้งหมด','ภาพรวม','รายละเอียด','หมวด','บัญชี','จาก','ผ่าน','ค้นหา','ค้น','ดู','ค่า','จ่าย','ใช้','ถาม','รวม','ของฉัน','มีรายจ่าย','มีรายรับ','ใน','ช่วง']
    suffixes=['ใช้ไปเท่าไหร่','ใช้ไปเท่าไร','จ่ายไปเท่าไหร่','จ่ายไปเท่าไร','เท่าไหร่','เท่าไร','เท่าใด','อะไรบ้าง','มีอะไร','บัญชีไหน','รายละเอียด','ทั้งหมด','ภาพรวม','หน่อย','ได้ไหม','ให้หน่อย','คงเหลือ','ยอดรวม','ยอด','กี่บาท','ค่ะ','ครับ','นะ','ล่ะ','ละ','แล้ว','วิเคราะห์','ช่วย','ใช้ไป','จ่ายไป','ที่จ่าย','ที่ใช้','ของฉัน','ใน']
    pre=re.compile(r'^(?:'+'|'.join(re.escape(w) for w in sorted(prefixes,key=len,reverse=True))+r')')
    post=re.compile(r'(?:'+'|'.join(re.escape(w) for w in sorted(suffixes,key=len,reverse=True))+r')$')
    parts=[]
    for part in value.split('<period>'):
        old=None
        while part!=old:
            old=part;part=pre.sub('',post.sub('',part.strip(' :：?？'))).strip()
        if part in ('','เยอะไหม','น้อยไหม','เยอะ','น้อย','มี','เป็นอย่างไร','ยังไง','เดือน','กับ','และ','ถึง','มีรายการ','มีรายการบ้าง'):continue
        if part not in parts:parts.append(part)
    if len(parts)>1:raise ValueError('ambiguous description filter')
    return parts[0] if parts else ''


def scope(db,room,text):
    if re.search(r'จด|บันทึก|แก้|เพิ่ม|สร้าง|ตั้งงบ|ปรับงบ|เปลี่ยน|ลบ|record|save|update|delete',text,re.I):return Scope('mutation',text)
    balance=bool(re.search(r'มีเงิน|ยอด(?:เงิน|บัญชี|คงเหลือ)|เงิน.*เหลือ|balance|how much money',text,re.I))
    period=bool(re.search(r'รายจ่าย|รายรับ|ใช้(?:ไป|เงิน)|จ่าย(?:ไป|อะไร)|เดือน|spent|income|expense',text,re.I) or (re.search(r'วันนี้|เมื่อวาน|ย้อนหลัง',text) and re.search(r'เท่าไร|เท่าไหร่|กี่บาท|กิน|ซื้อ',text)))
    kind='budget' if 'งบ' in text else 'comparison' if period and re.search(r'เปรียบเทียบ|เทียบ.*กับ',text) else 'balance' if balance and not period else 'period' if period else 'query' if re.search(r'บัญชี|หมวด|รายการ|เป้าหมาย|ต่อ|ที่เหลือ',text) else 'conversation'
    result=Scope(kind,text)
    if re.search(r'แนวโน้ม|เฉลี่ย|สูงสุด|ต่ำสุด|มากที่สุด|น้อยที่สุด|คาดการณ์',text) and kind in ('period','balance'):
        result.error=True;return result
    if balance and (period or re.search(r'เมื่อวาน|ย้อนหลัง|สิ้น|ณ |\d{4}-\d{2}',text)):
        result.error=True;return result
    prior=(room.capture_context or {}).get('verified_scope',{})
    followup=bool(re.fullmatch(r'(?:ต่อ|ดูต่อ|แล้ว.*ล่ะ|.*เดือน.*ล่ะ)[?？\s]*',text.strip()))
    if followup and prior.get('expires',0)>now() and prior.get('kind') in ('balance','period','budget','comparison'):
        result.kind=kind=prior['kind']
    if kind not in ('balance','period','budget','comparison'):return result
    match=(func.instr(literal(text),Account.name) if db.bind.dialect.name=='sqlite' else func.strpos(literal(text),Account.name))>0
    rows=db.scalars(select(Account).where(Account.workspace_id==room.workspace_id,match).limit(4)).all()
    if followup and prior.get('expires',0)>now() and not rows:
        ids=[v for v in (prior.get('account_id'),prior.get('category_id')) if v]
        rows=db.scalars(select(Account).where(Account.workspace_id==room.workspace_id,Account.id.in_(ids))).all()
        if len(rows)!=len(ids):result.error=True
        result.q=prior.get('q','');result.transaction_kind=prior.get('transaction_kind')
    wallets=[a for a in rows if a.kind in ('asset','liability')];categories=[a for a in rows if a.kind in ('income','expense')]
    if len(wallets)>1 or len(categories)>1:result.error=True;return result
    result.account=wallets[0] if wallets else None;result.category=categories[0] if categories else None
    if re.search(r'เฉพาะ|หมวด|บัญชี(?!ไหน|อะไร|ทั้งหมด|ทุก)',text) and not rows:result.error=True
    if kind=='balance' and categories:result.error=True
    if kind=='balance':return result
    try:
        if kind=='comparison':
            # This operation compares one whole month to its immediate predecessor.
            # Other comparisons require clarification instead of silently guessing.
            if not re.search(r'เดือนนี้.*เดือน(?:ก่อน|ที่แล้ว)',text):raise ValueError()
            result.start,result.end=resolve_period('เดือนนี้')
        elif followup and text.strip() in ('ต่อ','ดูต่อ') and prior.get('start') and prior.get('end'):
            result.start,result.end=date.fromisoformat(prior['start']),date.fromisoformat(prior['end'])
        else:result.start,result.end=resolve_period(text)
        if (result.end-result.start).days>366:raise ValueError()
        if kind in ('budget','comparison') and (result.start,result.end)!=month_bounds(result.start.strftime('%Y-%m')):raise ValueError()
    except Exception:result.error=True;return result
    if kind in ('period','comparison') and not (followup and text.strip() in ('ต่อ','ดูต่อ')):
        try:result.q=subject(text,[a.name for a in rows]) or result.q
        except ValueError:result.error=True;return result
        if len(result.q)>100:result.error=True
        if re.search(r'โอน',text):result.transaction_kind='transfer';result.q=result.q.replace('โอน','').strip()
        elif re.search(r'จ่ายบัตร',text):result.transaction_kind='card_payment';result.q=result.q.replace('จ่ายบัตร','').strip()
    if kind=='comparison' and result.transaction_kind:result.error=True
    if kind=='budget' and (wallets or (categories and categories[0].kind!='expense')):result.error=True
    return result
