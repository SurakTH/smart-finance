"""Telegram uses the web assistant boundary; only reviewed user commands post money."""
import asyncio
import re
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from .db import SessionLocal
from .models import Conversation, Message, Job, TelegramDelivery, TelegramLink, Membership, Workspace, now, message_time

ACK = 'ได้ค่ะ กำลังดูให้สักครู่นะคะ ถ้ามีรายการให้บันทึก ฉันจะทวนให้ตรวจและรอให้คุณพิมพ์ ยืนยัน ก่อนค่ะ'


def submit(db, telegram_id, message_id, text, data=None):
    from .bot import linked
    from .main import enqueue, store_image
    from .chat_actions import handle, begin_request, bind_review
    from .chat_privacy import expired, erase
    link = linked(db, telegram_id)
    if not link:
        return 'กรุณาเชื่อมต่อจากเว็บก่อน'
    if len(text) > 4000:
        return 'ข้อความยาวเกิน 4,000 ตัวอักษร กรุณาแบ่งส่งนะคะ'
    prefix = f'telegram:{telegram_id}:{link.user_id}:{link.workspace_id}:'
    cid = str(uuid5(NAMESPACE_URL, prefix + 'room'))
    input_id = str(uuid5(NAMESPACE_URL, prefix + str(message_id) + ':input'))
    reply_id = str(uuid5(NAMESPACE_URL, prefix + str(message_id) + ':reply'))
    previous = db.get(Message, reply_id)
    if previous:
        return previous.content
    c = db.get(Conversation, cid)
    if c and expired(db, c):
        erase(db, c)
        c = None
    if not c:
        c = Conversation(id=cid, workspace_id=link.workspace_id, user_id=link.user_id,
                         title='Telegram · ผู้ช่วย AI', privacy='private')
        db.add(c)
        db.flush()
    # Telegram updates can be retried; never enqueue or post twice for one input.
    if db.get(Message, input_id):
        return ACK
    c.updated_at = now()
    image = store_image(db, link.workspace_id, data)[0] if data else None
    db.add(Message(id=input_id, workspace_id=c.workspace_id, conversation_id=c.id,
                   role='user', content=text, attachment_id=image.id if image else None,
                   created_at=message_time(db, c.workspace_id, c.id)))
    db.flush()
    # A completed AI job is not proof that Telegram received its review. Do not
    # confirm a newer draft while its response is still queued or only partly sent.
    if not image and re.fullmatch(r'ยืนยัน(?:\s+[a-fA-F0-9]{8})?',text.strip()):
        review_id=(c.capture_context or {}).get('review_message_id')
        waiting=db.scalar(select(TelegramDelivery.job_id).where(
            TelegramDelivery.conversation_id==c.id,TelegramDelivery.workspace_id==c.workspace_id,
            TelegramDelivery.user_id==link.user_id,TelegramDelivery.reply_message_id==review_id,
            TelegramDelivery.status!='sent').limit(1)) if review_id else None
        if waiting:
            return 'ยังส่งข้อความทวนล่าสุดให้ไม่ครบค่ะ ยังไม่บันทึก รอข้อความทวนก่อน แล้วพิมพ์ ยืนยัน อีกครั้งนะคะ'
    reply = None if image else handle(db, c, link.user_id, text, allow_model_dialogue=True)
    if reply is not None:
        message = Message(id=reply_id, workspace_id=c.workspace_id, conversation_id=c.id,
                          role='assistant', content=reply, created_at=message_time(db, c.workspace_id, c.id))
        db.add(message)
        db.flush()
        bind_review(db, c, link.user_id, message)
        return reply
    begin_request(db, c, link.user_id)
    job = enqueue(db, c.workspace_id, link.user_id, 'chat', {
        'conversation_id':c.id, 'text':text, 'routing':'workspace', 'user_message_id':input_id,
        **({'attachment_id':image.id} if image else {})})
    db.add(TelegramDelivery(job_id=job.id, workspace_id=c.workspace_id, conversation_id=c.id,
                            user_id=link.user_id, telegram_id=str(telegram_id)))
    db.flush()
    return ACK


def claim():
    """Lease only committed terminal results. Recheck recipient permissions each part."""
    from .ai_errors import message as error_message
    from .chat_privacy import expired
    with SessionLocal.begin() as db:
        rows = db.scalars(select(TelegramDelivery).join(Job, Job.id==TelegramDelivery.job_id).where(
            TelegramDelivery.status=='pending', TelegramDelivery.next_attempt<=now(),
            Job.status.in_(['done','failed','cancelled'])).order_by(Job.created_at,Job.id)
            .with_for_update(skip_locked=True, of=TelegramDelivery).limit(20)).all()
        for row in rows:
            job = db.get(Job,row.job_id)
            room = db.get(Conversation,row.conversation_id)
            link = db.get(TelegramLink,row.telegram_id)
            ws = db.get(Workspace,row.workspace_id)
            if not (ws and ws.archived_at is None and room and room.workspace_id==row.workspace_id
                    and room.user_id==row.user_id and not expired(db,room)
                    and job.workspace_id==row.workspace_id and job.user_id==row.user_id
                    and link and link.workspace_id==row.workspace_id and link.user_id==row.user_id
                    and db.get(Membership,(row.user_id,row.workspace_id))):
                row.status='cancelled'
                continue
            if job.status=='done':
                reply = db.get(Message,row.reply_message_id) if row.reply_message_id else None
                if not (reply and reply.role=='assistant' and reply.workspace_id==row.workspace_id
                        and reply.conversation_id==row.conversation_id):
                    row.status='cancelled'
                    continue
                body = reply.content
            elif job.status=='failed':
                body = error_message(job.error)
            else:
                body = 'คำขอก่อนหน้าหยุดแล้วค่ะ คุณส่งรายละเอียดล่าสุดมาได้เลย ยังไม่ได้บันทึกจากคำขอที่หยุดนี้ค่ะ'
            parts = [body[i:i+3500] for i in range(0,len(body),3500)] or ['ยังไม่มีคำตอบค่ะ ลองส่งใหม่อีกครั้งนะคะ']
            if row.part>=len(parts):
                row.status='sent'
                continue
            row.attempts+=1
            row.next_attempt=now()+120
            return row.job_id, int(row.telegram_id), row.part, parts[row.part], len(parts)
    return None


def completed(jid, part, total, failure=False, permanent=False, delay=10):
    with SessionLocal.begin() as db:
        row=db.scalar(select(TelegramDelivery).where(TelegramDelivery.job_id==jid).with_for_update())
        if not row or row.status!='pending' or row.part!=part:
            return
        if failure:
            row.status='failed' if permanent or row.attempts>=5 else 'pending'
            row.next_attempt=now()+max(1,int(delay))
        else:
            row.part+=1
            row.attempts=0
            row.next_attempt=now()
            if row.part>=total:
                row.status='sent'


async def deliver_once(bot):
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    from aiogram.types import LinkPreviewOptions
    item=await asyncio.to_thread(claim)
    if not item:
        return False
    jid,tid,part,body,total=item
    try:
        # Plain text prevents untrusted model output injecting Telegram markup/links.
        await bot.send_message(tid,body,parse_mode=None,request_timeout=60,link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramForbiddenError:
        await asyncio.to_thread(completed,jid,part,total,True,True)
    except TelegramRetryAfter as exc:
        await asyncio.to_thread(completed,jid,part,total,True,False,exc.retry_after)
    except Exception:
        await asyncio.to_thread(completed,jid,part,total,True)
    else:
        await asyncio.to_thread(completed,jid,part,total)
    return True


async def delivery_loop(bot):
    while True:
        try:
            worked=await deliver_once(bot)
            await asyncio.sleep(.1 if worked else 1)
        except Exception:
            # Telegram exceptions may contain request URLs with credentials.
            await asyncio.sleep(2)
