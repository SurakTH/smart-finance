"""Bounded draft batches and local duplicate evidence. No model may call apply."""
import re
from copy import deepcopy
from difflib import SequenceMatcher
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from .models import Entry, Line, ChatAction, Proposal, now
from .reporting import active_entry
from .schemas import TransactionInput


def duplicate_state(db,wid,payload):
    """Same day/kind/amount/source + similar description; scoped SQL, no AI roundtrip."""
    items=payload.get('items') if payload.get('type')=='transactions' else [payload]
    checks=[];warnings=[];seen={}
    normalize=lambda value:re.sub(r'[^\w]','',value.casefold())
    for index,item in enumerate(items,1):
        tx=item['transaction']
        source=select(Line.id).where(Line.workspace_id==wid,Line.entry_id==Entry.id,Line.account_id==tx['account_id']).correlate(Entry).exists()
        candidates=db.scalars(select(Entry).where(Entry.workspace_id==wid,active_entry(wid),Entry.kind==tx['kind'],Entry.amount==tx['amount'],Entry.occurred_on==tx['occurred_on'],source,Entry.id!=item.get('target','')).order_by(Entry.id).limit(51)).all()
        matches=[e for e in candidates[:50] if SequenceMatcher(None,normalize(e.description),normalize(tx['description'])).ratio()>=0.7]
        checks.append({'ids':[e.id for e in matches],'overflow':len(candidates)>50})
        for entry in matches[:3]:warnings.append(f'รายการที่ {index}: คล้าย {entry.description} วันที่ {entry.occurred_on} ยอดเดียวกันในบัญชีนี้')
        if len(candidates)>50:warnings.append(f'รายการที่ {index}: พบรายการยอดเดียวกันจำนวนมาก ตรวจประวัติก่อนยืนยัน')
        key=tuple(tx.get(k) for k in ('kind','amount','occurred_on','account_id','other_account_id','category_id'))+(normalize(tx['description']),)
        if key in seen:warnings.append(f'รายการที่ {index}: ซ้ำกับรายการที่ {seen[key]} ในชุดนี้')
        seen[key]=index
    return checks,warnings


def annotate(db,wid,payload):
    if payload.get('type')=='management':return payload
    checks,warnings=duplicate_state(db,wid,payload)
    return {**payload,'duplicate_checks':checks,'duplicate_warnings':warnings}


def apply(db,c,user_id,action):
    from .chat_actions import summary
    from .ledger import post
    p=action.payload;image_id=p.get('attachment_id')
    if image_id and db.scalar(select(Proposal.id).where(Proposal.workspace_id==c.workspace_id,Proposal.attachment_id==image_id,Proposal.status=='confirmed').limit(1)):
        action.status='conflict';return 'รูปนี้มีรายการบันทึกแล้วค่ะ ไม่บันทึกซ้ำ'
    try:
        transactions=[TransactionInput(**item['transaction']) for item in p['items']]
        if any(summary(db,c.workspace_id,item['transaction'])!=item['after'] for item in p['items']):raise HTTPException(409,'ชื่อบัญชีหรือหมวดเปลี่ยนไป')
        if duplicate_state(db,c.workspace_id,p)[0]!=p['duplicate_checks']:raise HTTPException(409,'รายการที่อาจซ้ำเปลี่ยนไป')
    except HTTPException:
        action.status='conflict';return 'ข้อมูลเปลี่ยนจากตอนทวนค่ะ ยังไม่บันทึกทั้งชุด กรุณาส่งคำขอใหม่'
    # Deliberately no savepoint/catch: any failure rolls back the caller's entire
    # transaction, including every journal, proposal, message and action status.
    entries=[post(db,c.workspace_id,user_id,tx) for tx in transactions]
    for tx,entry in zip(transactions,entries):
        if image_id:db.add(Proposal(workspace_id=c.workspace_id,source='ai_chat',description=tx.description,amount=tx.amount,kind=tx.kind,status='confirmed',entry_id=entry.id,attachment_id=image_id))
    action.status='confirmed';action.entry_id=entries[-1].id
    c.capture_context={**(c.capture_context or {}),'last_entry_id':entries[-1].id}
    db.flush()
    return 'บันทึกรายการเรียบร้อยแล้วทั้งชุด '+str(len(entries))+' รายการ\n\n'+'\n\n'.join(str(i)+'. '+item['after'] for i,item in enumerate(p['items'],1))


def edit(db,c,user_id,text):
    change=re.fullmatch(r'(?:แก้ยอด|เปลี่ยนยอด)?\s*รายการที่\s*(\d+)\s*(?:เป็น|ยอด)\s*([\d,.]+)\s*(?:บาท)?',text)
    remove=re.fullmatch(r'(?:ลบ|เอาออก)\s*รายการที่\s*(\d+)',text)
    if not change and not remove:return None
    action=db.scalar(select(ChatAction).where(ChatAction.workspace_id==c.workspace_id,ChatAction.conversation_id==c.id,ChatAction.user_id==user_id,ChatAction.status=='pending').with_for_update())
    if not action or action.expires<=now() or action.payload.get('type')!='transactions':return 'ยังไม่มีชุดรายการที่รอยืนยันค่ะ'
    p=deepcopy(action.payload);index=int((change or remove)[1])-1
    if not 0<=index<len(p['items']):return 'หมายเลขรายการไม่ตรงค่ะ ตรวจหมายเลขจากข้อความทวนก่อนนะคะ'
    from .chat_actions import amount,summary,prepare_review
    if remove:
        if len(p['items'])==1:return 'เหลือรายการเดียวค่ะ พิมพ์ ยกเลิก เพื่อยกเลิกทั้งชุดได้เลย'
        p['items'].pop(index)
    else:
        try:p['items'][index]['transaction']['amount']=amount(change[2])
        except ValueError:return 'ยอดยังไม่ชัดค่ะ ขอจำนวนบาทและทศนิยมไม่เกิน 2 ตำแหน่ง'
        p['items'][index]['transaction']['idempotency_key']=str(uuid4())
        try:p['items'][index]['after']=summary(db,c.workspace_id,p['items'][index]['transaction'])
        except HTTPException:return 'ข้อมูลบัญชีเปลี่ยนไปแล้วค่ะ กรุณาส่งคำขอใหม่'
    return prepare_review(db,c,user_id,p)
