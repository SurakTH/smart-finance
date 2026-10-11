"""Trusted text-command boundary. Models/OCR never invoke confirm or ledger writes.

Drafts use exact account names and explicit fields. Only a fresh authenticated
user message consisting entirely of ยืนยัน CODE can execute a frozen draft.
All callers hold the workspace lock, including concurrent/replayed confirmations.
"""
import re
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from .models import Account, ChatAction, now
from .schemas import TransactionInput, CorrectionInput
from .ledger import post, get_scoped
from .corrections import detail, revise
from .reporting import today

KINDS={'บันทึกรายจ่าย':'expense','บันทึกรายรับ':'income','โอนเงิน':'transfer','จ่ายบัตร':'card_payment'}
HELP='''ยังไม่บันทึกค่ะ กรุณาระบุข้อมูลให้ครบ เช่น
บันทึกรายจ่าย
รายละเอียด: กาแฟ
จำนวน: 75
บัญชี: เงินสด
หมวด: อาหารและเครื่องดื่ม
วันที่: YYYY-MM-DD

ใช้ชื่อบัญชีและหมวดตามที่ตั้งไว้ วันที่เว้นได้โดยใช้วันนี้ ระบบจะทวนก่อนให้พิมพ์ยืนยันพร้อมรหัส ภายใน 15 นาที
แก้รายการ: เปิดรายละเอียดรายการ แล้วคัดลอกคำขอแก้ผ่านแชท
รองรับรายรับ รายจ่าย โอนเงิน และจ่ายบัตร โดยโอน/จ่ายบัตรใช้ ปลายทาง: ชื่อบัญชี แทน หมวด:'''


def amount(text):
    if not re.fullmatch(r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?(?:\s*บาท)?',text):
        raise ValueError('จำนวนต้องเป็นบาท มากกว่า 0 และมีทศนิยมไม่เกิน 2 ตำแหน่ง')
    try: value=int(Decimal(re.sub(r'\s*บาท$','',text).replace(',',''))*100)
    except InvalidOperation: raise ValueError('จำนวนเงินไม่ถูกต้อง')
    if not 0<value<=100_000_000_000: raise ValueError('จำนวนเงินเกินขอบเขตที่รองรับ')
    return value


def named(db,wid,name,kinds):
    # Names are not unique in the database. Never guess among duplicate names.
    rows=db.scalars(select(Account).where(Account.workspace_id==wid,Account.kind.in_(kinds))).all()
    found=[a for a in rows if a.name.casefold()==name.casefold()]
    if len(found)!=1: raise ValueError('ไม่พบชื่อบัญชี/หมวดที่ตรงเพียงรายการเดียว กรุณาตรวจชื่อ: '+name)
    return found[0].id


def summary(db,wid,tx):
    names={}
    for field in ('account_id','other_account_id','category_id'):
        if tx.get(field): names[field]=get_scoped(db,Account,wid,tx[field]).name
    label={'income':'รายรับ','expense':'รายจ่าย','transfer':'โอนเงิน','card_payment':'จ่ายบัตร'}[tx['kind']]
    text=f"{label} · {tx['description']}\nจำนวน: ฿{Decimal(tx['amount'])/100:,.2f}\nวันที่: {tx['occurred_on']}\nบัญชี: {names['account_id']}"
    if names.get('other_account_id'): text+='\nปลายทาง: '+names['other_account_id']
    if names.get('category_id'): text+='\nหมวด: '+names['category_id']
    return text


def parse(db,wid,text):
    lines=[line.strip() for line in text.strip().splitlines() if line.strip()]
    first=lines[0]
    target=None; before=None
    edit=re.fullmatch(r'แก้รายการ\s+([0-9a-fA-F-]{36})(?:\s+เป็น\s+(.+?)(?:\s*บาท)?)?',first)
    fields={}
    if edit:
        target=edit[1]; before=detail(db,wid,target)
        if before['status']!='active': raise ValueError('รายการนี้ถูกแก้ไขหรือยกเลิกแล้ว กรุณาเปิดรายการล่าสุด')
        if before['kind'] not in KINDS.values(): raise ValueError('แก้ยอดตั้งต้นได้ที่หน้ารายการ')
        tx={k:before[k] for k in ('kind','description','amount','occurred_on')}
        tx['account_id']=before['accounts'][0]['id']
        tx['category_id']=before['category']['id'] if before['category'] else None
        tx['other_account_id']=before['accounts'][1]['id'] if len(before['accounts'])>1 else None
        if edit[2]: fields['จำนวน']=edit[2]
    else:
        # Convenient one-line form; each label must appear in this order.
        quick=re.fullmatch(r'(บันทึกรายจ่าย|บันทึกรายรับ)\s+(.+?)\s+([0-9,.]+)\s*บาท\s+บัญชี\s+(.+?)\s+หมวด\s+(.+?)(?:\s+วันที่\s+(\d{4}-\d{2}-\d{2}))?',first)
        if quick:
            fields=dict(zip(('รายละเอียด','จำนวน','บัญชี','หมวด'),quick.group(2,3,4,5)))
            if quick[6]: fields['วันที่']=quick[6]
            first=quick[1]
        if first not in KINDS: raise ValueError(HELP)
        tx={'kind':KINDS[first],'occurred_on':today().isoformat(),'other_account_id':None,'category_id':None}
    for line in lines[1:]:
        pair=re.fullmatch(r'(รายละเอียด|จำนวน|บัญชี|หมวด|ปลายทาง|วันที่|เหตุผล)\s*[:：]\s*(.+)',line)
        if not pair or pair[1] in fields: raise ValueError('รูปแบบไม่ถูกต้องหรือมีช่องข้อมูลซ้ำ\n'+HELP)
        fields[pair[1]]=pair[2].strip()
    if not fields: raise ValueError('กรุณาระบุข้อมูลที่จะเปลี่ยน เช่น จำนวน: 95')
    if not target and not {'รายละเอียด','จำนวน','บัญชี'}<=fields.keys(): raise ValueError(HELP)
    if not target and 'เหตุผล' in fields: raise ValueError('เหตุผลใช้กับการแก้ไขรายการเท่านั้น')
    if 'รายละเอียด' in fields: tx['description']=fields['รายละเอียด']
    if 'จำนวน' in fields: tx['amount']=amount(fields['จำนวน'])
    if 'วันที่' in fields:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',fields['วันที่']): raise ValueError('วันที่ต้องเป็น YYYY-MM-DD')
        try: tx['occurred_on']=date.fromisoformat(fields['วันที่']).isoformat()
        except ValueError: raise ValueError('วันที่ไม่มีอยู่จริง กรุณาตรวจวัน เดือน และปี')
    if 'บัญชี' in fields: tx['account_id']=named(db,wid,fields['บัญชี'],('asset',) if tx['kind']!='expense' else ('asset','liability'))
    if tx['kind'] in ('income','expense'):
        if 'ปลายทาง' in fields: raise ValueError('รายรับ/รายจ่ายใช้หมวด ไม่ใช้ปลายทาง')
        if 'หมวด' in fields: tx['category_id']=named(db,wid,fields['หมวด'],(tx['kind'],))
        if not tx.get('category_id'): raise ValueError(HELP)
    else:
        if 'หมวด' in fields: raise ValueError('โอนเงิน/จ่ายบัตรใช้ปลายทาง ไม่ใช้หมวด')
        if 'ปลายทาง' in fields: tx['other_account_id']=named(db,wid,fields['ปลายทาง'],('asset',) if tx['kind']=='transfer' else ('liability',))
        if not tx.get('other_account_id') or tx['other_account_id']==tx['account_id']: raise ValueError('กรุณาระบุบัญชีปลายทางที่ต่างจากต้นทาง')
    tx['idempotency_key']=str(uuid4())
    tx=TransactionInput(**tx).model_dump(mode='json')
    after=summary(db,wid,tx)
    old=summary(db,wid,{**tx,**{k:before[k] for k in ('kind','description','amount','occurred_on')},'account_id':before['accounts'][0]['id'],'other_account_id':before['accounts'][1]['id'] if len(before['accounts'])>1 else None,'category_id':before['category']['id'] if before['category'] else None}) if before else None
    reason=fields.get('เหตุผล','แก้ไขผ่านแชทตามคำขอผู้ใช้')
    if target: CorrectionInput(reason=reason,idempotency_key=uuid4(),transaction=tx)
    return dict(transaction=tx,target=target,reason=reason,before=old,after=after,revision_key=str(uuid4()))


def handle(db,c,user_id,text):
    """Return None for ordinary chat, safe reply for intercepted commands.

    Called ONLY by authenticated text POST, never workers, OCR or providers.
    The route owns the transaction and workspace lock; no commit occurs here.
    """
    text=text.strip()
    command=re.fullmatch(r'(ยืนยัน|ยกเลิก)\s+([0-9a-fA-F]{8})',text)
    scope=(ChatAction.workspace_id==c.workspace_id,ChatAction.conversation_id==c.id,ChatAction.user_id==user_id)
    if text in ('ยกเลิกการกรอก','เริ่มใหม่'):
        context=dict(c.capture_context or {});context.pop('pending',None);c.capture_context=context
        for old in db.scalars(select(ChatAction).where(*scope,ChatAction.status=='pending')):old.status='cancelled'
        return 'ยกเลิกข้อมูลที่กำลังกรอกและข้อเสนอในห้องนี้แล้ว ยังไม่ได้เปลี่ยนยอดเงิน'
    if command:
        action=db.scalar(select(ChatAction).where(*scope,ChatAction.code==command[2].upper()).with_for_update())
        if not action: return 'ไม่พบรหัสข้อเสนอในห้องนี้ ยังไม่บันทึกข้อมูล กรุณาตรวจรหัสจากข้อความทวนรายการ'
        if action.status=='confirmed': return 'ข้อเสนอนี้บันทึกแล้ว ไม่มีการบันทึกซ้ำ'
        if action.status!='pending':
            label={'cancelled':'ยกเลิกแล้ว','superseded':'มีข้อเสนอใหม่แทนแล้ว','expired':'หมดอายุแล้ว','conflict':'ข้อมูลเปลี่ยนไป'}[action.status]
            return 'ข้อเสนอนี้ใช้ไม่ได้แล้ว: '+label+' กรุณาส่งคำขอใหม่'
        if action.expires<=now():
            action.status='expired'; return 'ข้อเสนอหมดอายุแล้ว กรุณาส่งคำขอใหม่เพื่อตรวจสอบอีกครั้ง'
        if command[1]=='ยกเลิก':
            action.status='cancelled'; return 'ยกเลิกข้อเสนอแล้ว ยังไม่ได้เปลี่ยนข้อมูลทางการเงิน'
        p=action.payload
        # Validate stale reviews before any writes. Posting must remain in the
        # top-level transaction: PostgreSQL's immutable-ledger xmin guard rejects
        # journals inserted in a savepoint. Any posting failure rolls back the
        # whole HTTP request (including messages/status), never a partial ledger.
        try:
            if summary(db,c.workspace_id,p['transaction'])!=p['after']: raise HTTPException(409,'ชื่อบัญชีหรือหมวดเปลี่ยนไป กรุณาทวนใหม่')
            if p['target']:
                current=detail(db,c.workspace_id,p['target'])
                if current['status']!='active': raise HTTPException(409,'รายการถูกแก้ไขหรือยกเลิกไปแล้ว กรุณาเปิดรายการล่าสุด')
                original_tx={**p['transaction'],**{k:current[k] for k in ('kind','description','amount','occurred_on')},'account_id':current['accounts'][0]['id'],'other_account_id':current['accounts'][1]['id'] if len(current['accounts'])>1 else None,'category_id':current['category']['id'] if current['category'] else None}
                if summary(db,c.workspace_id,original_tx)!=p['before']: raise HTTPException(409,'ข้อมูลต้นฉบับเปลี่ยนไป กรุณาทวนใหม่')
        except HTTPException as exc:
            action.status='conflict'
            return 'ยังไม่บันทึก: '+str(exc.detail)+' กรุณาส่งคำขอใหม่'
        if p['target']:
            result=revise(db,c.workspace_id,user_id,p['target'],CorrectionInput(reason=p['reason'],idempotency_key=p['revision_key'],transaction=p['transaction']))
            entry_id=result['replacement']['id']
        else: entry_id=post(db,c.workspace_id,user_id,TransactionInput(**p['transaction'])).id
        action.status='confirmed'; action.entry_id=entry_id
        c.capture_context={'last_entry_id':entry_id}
        db.flush()
        return ('แก้ไขและเก็บประวัติเดิมเรียบร้อยแล้ว' if p['target'] else 'บันทึกรายการเรียบร้อยแล้ว')+'\n'+p['after']
    if text.startswith(('ยืนยัน','ยกเลิก')):
        return 'ยังไม่เปลี่ยนข้อมูล กรุณาพิมพ์เฉพาะ ยืนยัน ตามด้วยรหัส 8 ตัวจากข้อความทวนรายการ เช่น ยืนยัน A1B2C3D4 หรือ ยกเลิก A1B2C3D4'
    structured=text.splitlines()[0] in KINDS or ('\n' in text and text.startswith(tuple(KINDS))) or (text.startswith(('บันทึกรายจ่าย','บันทึกรายรับ')) and bool(re.search(r'\sบัญชี\s.+\sหมวด\s',text))) or bool(re.match(r'แก้รายการ\s+[0-9a-fA-F-]{36}',text))
    try:
        if not structured:
            from .natural_capture import normalize,NeedInfo
            try:normalized=normalize(db,c,user_id,text)
            except NeedInfo as exc:return 'ยังไม่บันทึกค่ะ '+str(exc)+' (ตอบต่อในห้องนี้ภายใน 15 นาที)'
            if normalized is None:return None
            text=normalized
        payload=parse(db,c.workspace_id,text)
    except ValidationError: return 'ยังไม่บันทึก กรุณาตรวจจำนวน วันที่ และความยาวรายละเอียด\n'+HELP
    except ValueError as exc:
        message=str(exc)
        return 'ยังไม่บันทึก: '+message+('' if HELP in message else '\n'+HELP)
    except HTTPException: return 'ไม่พบรายการที่แก้ไขได้ใน workspace นี้ ยังไม่เปลี่ยนข้อมูล'
    # Only a successfully validated new draft supersedes the old pending draft.
    for old in db.scalars(select(ChatAction).where(*scope,ChatAction.status=='pending')): old.status='superseded'
    code=secrets.token_hex(4).upper()
    while db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==c.id,ChatAction.code==code)):
        code=secrets.token_hex(4).upper()
    action=ChatAction(workspace_id=c.workspace_id,conversation_id=c.id,user_id=user_id,code=code,payload=payload,expires=now()+900)
    db.add(action);db.flush()
    review=('ก่อนแก้ไข:\n'+payload['before']+'\n\nหลังแก้ไข:\n' if payload['target'] else 'จะบันทึกรายการ:\n')+payload['after']
    if payload['target']: review+='\nเหตุผล: '+payload['reason']
    return 'กรุณาตรวจสอบ — ยังไม่บันทึก\n\n'+review+f'\n\nยืนยันเฉพาะข้อเสนอนี้ภายใน 15 นาที โดยพิมพ์:\nยืนยัน {code}\nหรือพิมพ์ ยกเลิก {code}\nหากต้องการเปลี่ยนข้อมูล ให้ส่งคำขอใหม่ รหัสเดิมจะใช้ไม่ได้'
