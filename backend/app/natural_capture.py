"""Deterministic Thai capture assistance; only authenticated text enters here.

Category suggestions are visible in the review. Ambiguous accounts/amounts ask
again; model output and images cannot authorize or fill this conversation state.
"""
import re
from datetime import timedelta
from sqlalchemy import select
from .models import Account,now
from .reporting import today

class NeedInfo(ValueError):pass

QUESTIONS=r'^(?:เดือน|สัปดาห์|ปีนี้|สรุป|รายงาน|ดู|ถาม|ทำไม|เท่าไหร่|ถ้า|สมมติ|ตัวอย่าง|ช่วยอธิบาย|ขอตัวอย่าง|วิธี|สอน)'
AMOUNT=r'(?<![\d.,-])\d[\d,]*(?:\.\d+)?(?![\d.,])'
ALIASES={'อาหารและเครื่องดื่ม':('กาแฟ','อาหาร','ข้าว','ชาเย็น','ชานม','กิน','น้ำดื่ม'), 'เดินทาง':('แท็กซี่','แท๊กซี่','รถไฟ','รถเมล์','น้ำมัน','รถรับจ้าง'), 'เงินเดือน':('เงินเดือน',)}

def is_question(text):
    return bool(re.search(QUESTIONS,text) or re.search(r'เท่าไหร่|เท่าไร|มีอะไรบ้าง|สรุป|ยอดรวม|ใช้ไป|ใช่ไหม|ได้ไหม|สมมติ|ตัวอย่าง|ช่วยอธิบาย',text) or re.search(r'(?:ไหม|มั้ย|เหรอ|หรอ|หรือเปล่า)\s*(?:คะ|ค่ะ|ครับ|นะ)?[?？!]*$',text) or '?' in text)

def normalize(db,c,user_id,text):
    if is_question(text):return None
    text=re.sub(r'^(?:ช่วย|รบกวน)(?:จด|บันทึก)?(?:ให้หน่อย)?\s*','',text.strip())
    text=re.sub(r'(?:\s*(?:ให้หน่อย|ด้วยนะ|หน่อยนะ|หน่อย|นะคะ|นะครับ|ครับ|ค่ะ|จ้า|จ้ะ|ทีนะ|ที|นะ))+[!。]*$','',text).strip()
    if is_question(text):return None
    context=dict(c.capture_context or {})
    pending=context.get('pending')
    rows=db.scalars(select(Account).where(Account.workspace_id==c.workspace_id)).all()
    if pending and pending['expires']>now() and (text in [a.name for a in rows] or re.match(r'^(?:บัญชี|หมวด|จาก|วันที่|ปลายทาง)\s*[:：]?\s*',text) or (pending.get('field')=='amount' and re.fullmatch(AMOUNT+r'\s*(?:บาท)?',text))):
        match=[a for a in rows if a.name==text]
        if len(match)==1 and match[0].kind in ('income','expense'):text='หมวด '+text
        elif len(match)==1 and pending.get('field')=='destination':text='ปลายทาง '+text
        text=pending['text']+' '+text
    elif pending:context.pop('pending',None);c.capture_context=context
    edit=re.fullmatch(r'(?:ช่วย)?แก้(?:รายการ|ยอด)(?:ล่าสุด|เมื่อกี้)\s*(?:เป็น|ให้เป็น)\s*([\d,.]+)\s*(?:บาท)?',text)
    if edit:
        target=context.get('last_entry_id')
        if not target:raise ValueError('ยังไม่มีรายการที่ยืนยันผ่านห้องนี้ กรุณาเลือกคำขอแก้ไขจากหน้ารายการ')
        return f'แก้รายการ {target} เป็น {edit[1]} บาท'
    action=re.search(r'จ่าย|ซื้อ|กิน|กาแฟ|รายจ่าย|รายรับ|เงินเดือน|รับเงิน|ได้เงิน|โอน|บันทึก|บาท|ค่า|ยอด|เงินเข้า',text)
    if not action:return None
    original=text
    def ask(message,field=None):
        context['pending']={'text':original,'expires':now()+900,'field':field,'question':message};c.capture_context=context
        raise NeedInfo(message)
    if not re.search(r'\d',text):
        if not re.search(r'จ่าย|ซื้อ|กิน|กาแฟ|เงินเดือนเข้า|รับเงิน|ได้เงิน|โอน|บันทึก',text):return None
        ask('ยอดเท่าไหร่คะ?', 'amount')
    if '\n' in text or len(text)>600:raise ValueError('กรุณาส่งครั้งละหนึ่งรายการ หรือใช้ช่องข้อมูลตามตัวอย่าง')
    occurred=today()
    if 'เมื่อวาน' in text:occurred-=timedelta(days=1)
    dates=re.findall(r'\d{4}-\d{2}-\d{2}',text)
    if len(dates)>1:raise ValueError('พบหลายวันที่ กรุณาส่งครั้งละหนึ่งรายการ')
    if dates:
        from datetime import date
        occurred=date.fromisoformat(dates[0]);text=text.replace(dates[0],'')
    matches=list(re.finditer(AMOUNT,text))
    if len(matches)!=1 or re.search(r'-\s*\d|\d\s*ถึง\s*\d|หรือ|ประมาณ|รวมทั้งหมด',text):
        raise ValueError('จำนวนเงินไม่ชัดเจน กรุณาระบุยอดเดียวที่แน่นอนต่อรายการ')
    value=matches[0].group()
    # Strict amount validation remains in chat_actions.parse (no float arithmetic).
    kind='card_payment' if re.search(r'จ่าย(?:ค่า)?บัตร|ชำระบัตร',text) else 'transfer' if re.search(r'โอน',text) else 'income' if re.search(r'รายรับ|เงินเดือน(?:เข้า|ออก)?|รับเงิน|ได้เงิน|เงินเข้า',text) else 'expense'
    wallets=[a for a in rows if a.kind in (('asset','liability') if kind=='expense' else ('asset',))]
    def mentioned(accounts):
        hits=[a for a in accounts if a.name.casefold() in text.casefold()]
        # Do not interpret a shorter account name inside a longer one.
        return [a for a in hits if not any(a.name!=b.name and a.name in b.name for b in hits)]
    names=mentioned(wallets)
    destination=None
    if kind in ('transfer','card_payment'):
        targets=[a for a in rows if a.kind==('asset' if kind=='transfer' else 'liability')]
        dests=[a for a in targets if re.search(r'(?:ไป(?:ที่)?|เข้า|ถึง|ปลายทาง)\s*(?:บัญชี\s*)?'+re.escape(a.name),text)]
        if len(dests)!=1:ask('โอนไปบัญชีไหนคะ? '+', '.join(a.name for a in targets), 'destination')
        destination=dests[0]
        names=[a for a in names if a.id!=destination.id]
    explicit_source=re.search(r'(?:จาก|ด้วย|ผ่าน|บัญชี)\s*([^\d]+)',text)
    if len(names)==1:account=names[0]
    elif not names and len(wallets)==1 and not explicit_source:account=wallets[0]
    else:ask('ใช้บัญชีไหนคะ? '+', '.join(a.name for a in wallets), 'account')
    category=None
    if kind in ('income','expense'):
        cats=[a for a in rows if a.kind==kind]
        explicit=re.search(r'หมวด\s*[:：]?\s*(.+)$',text)
        if explicit:
            hits=[a for a in cats if a.name==explicit[1].strip()]
        else:
            hits=mentioned(cats)
            if not hits:hits=[a for a in cats if any(word in text for word in ALIASES.get(a.name,()))]
            if not hits and len(cats)==1:hits=cats
        if len(hits)!=1:ask('จัดเข้าหมวดไหนคะ? '+', '.join(a.name for a in cats), 'category')
        category=hits[0]
    description=text[:matches[0].start()]+text[matches[0].end():]
    for a in [account,destination]:
        if a:description=description.replace(a.name,'')
    if category:description=re.sub(r'หมวด\s*[:：]?\s*'+re.escape(category.name)+r'\s*$','',description)
    description=description.replace('รับเงินเดือน','เงินเดือน').replace('ได้เงินเดือน','เงินเดือน')
    description=re.sub(r'^(?:ช่วย|ให้|บันทึก|เพิ่ม|รายจ่าย|รายรับ|เมื่อกี้|วันนี้|เมื่อวาน|จ่าย|ซื้อ|กิน|รับเงิน|ได้เงิน|เงินเข้า|โอนเงิน|โอน|ชำระบัตร|จ่ายบัตร|ค่า|\s)+','',description)
    description=re.sub(r'(?:จาก|ด้วย|ผ่าน|เข้าบัญชี|บัญชี|หมวด|วันที่|ปลายทาง|ไปที่|บาท|เข้า|ไป)\s*',' ',description).strip()
    description=description or ('โอนเงิน' if kind=='transfer' else 'จ่ายบัตร' if kind=='card_payment' else category.name)
    context.pop('pending',None);c.capture_context=context
    title={'expense':'บันทึกรายจ่าย','income':'บันทึกรายรับ','transfer':'โอนเงิน','card_payment':'จ่ายบัตร'}[kind]
    return f'{title}\nรายละเอียด: {description[:300]}\nจำนวน: {value}\nบัญชี: {account.name}\nวันที่: {occurred.isoformat()}\n'+('ปลายทาง: '+destination.name if destination else 'หมวด: '+category.name)
