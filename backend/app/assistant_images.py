"""Send current images and short receipt clarification only, not every old image."""
import re
from .models import now

def selected_images(history,job,db=None):
    current=job.payload.get('attachment_id')
    if current:return [current]
    if db is not None:
        from sqlalchemy import select
        from .models import Conversation,Message
        room=db.scalar(select(Conversation).where(Conversation.id==job.payload.get('conversation_id'),Conversation.workspace_id==job.workspace_id,Conversation.user_id==job.user_id))
        pending=(room.capture_context or {}).get('ai_followup',{}) if room else {}
        focus=(room.capture_context or {}).get('receipt_focus',{}) if room else {}
        identifier=(pending.get('draft') or {}).get('attachment_id') if pending.get('expires',0)>now() else None
        identifier=identifier or (focus.get('attachment_id') if focus.get('expires',0)>now() else None)
        if identifier:
            owned=db.scalar(select(Message.id).where(Message.workspace_id==job.workspace_id,Message.conversation_id==room.id,Message.role=='user',Message.attachment_id==identifier))
            if owned:return [identifier]
    text=job.payload.get('text','').strip()
    previous=next((m for m in history if m.role=='assistant'),None)
    image=next((m for m in history if m.role=='user' and m.attachment_id),None)
    if not image:return []
    # Old receipts stay in text history; bytes have a bounded follow-up window.
    if now()*1000-image.created_at>900_000:return []
    explicit=bool(re.search(r'รูป|สลิป|ใบเสร็จ',text))
    from .natural_capture import is_question
    unrelated=is_question(text) or bool(re.match(r'^(?:สวัสดี|หวัดดี|ขอบคุณ|hello|hi)' ,text,re.I))
    clarification=bool(not unrelated and previous and len(text)<=160 and re.search(r'บัญชี|หมวด|ยอด|จำนวน|วันไหน|เมื่อไหร่',previous.content) and re.search(r'ไหม|ไหน|เท่าไหร่|อะไร|คะ|\?',previous.content))
    if clarification:
        # A short unrelated sentence is not a receipt answer. Match a bounded
        # account/category name or an amount/date that the assistant asked for.
        question=previous.content
        numeric=bool(re.search(r'ยอด|จำนวน|เท่าไหร่',question) and re.fullmatch(r'[\d,./\-\s]+(?:บาท|สตางค์)?(?:ค่ะ|ครับ|จ้า|นะ)?',text))
        dated=bool(re.search(r'วันไหน|เมื่อไหร่|วันที่',question) and re.fullmatch(r'(?:วันนี้|เมื่อวาน|เมื่อวานซืน|\d{4}-\d{2}-\d{2})(?:ค่ะ|ครับ|จ้า|นะ)?',text))
        named=False
        if re.search(r'บัญชี|หมวด',question):
            name=re.sub(r'(?:ค่ะ|ครับ|จ้า|นะ)+$','',text).strip()
            name=re.sub(r'^(?:จ่ายจาก|ใช้|จาก)?\s*(?:บัญชี|หมวด)?\s*','',name).strip()
            if db is not None:
                from sqlalchemy import select
                from .models import Account
                named=bool(db.scalar(select(Account.id).where(Account.workspace_id==job.workspace_id,Account.name.in_((name,text))).limit(1)))
            else:named=name in ('เงินสด','อาหาร','ธนาคาร','บัตรเครดิต')
        clarification=numeric or dated or named
    if previous and re.search(r'พิมพ์.*ยืนยัน|บันทึก.*แล้ว|ยืนยัน.*แล้ว',previous.content):clarification=False
    if explicit or clarification:return [image.attachment_id]
    return []
