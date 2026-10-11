import asyncio
import io
import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message as TGMessage
from sqlalchemy import select, delete
from .db import SessionLocal
from .models import LinkCode, TelegramLink, Membership, Workspace, Conversation, Message, now, message_time
from .security import digest
from .main import enqueue, store_image

dp = Dispatcher()

def linked(db,telegram_id):
    link = db.get(TelegramLink,str(telegram_id))
    if not link:return None
    ws=db.scalar(select(Workspace).where(Workspace.id==link.workspace_id).with_for_update())
    if not ws or ws.archived_at is not None:return None
    link=db.scalar(select(TelegramLink).where(TelegramLink.telegram_id==str(telegram_id)).execution_options(populate_existing=True))
    return link if link and db.get(Membership,(link.user_id,link.workspace_id)) else None

@dp.message(CommandStart())
async def start(message: TGMessage):
    if message.chat.type!='private': return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts)!=2:
        await message.answer('สร้างรหัสเชื่อมต่อจาก Settings บนเว็บ แล้วส่ง /start รหัส'); return
    with SessionLocal.begin() as db:
        code = db.scalar(select(LinkCode).where(LinkCode.code_hash==digest(parts[1])))
        if code:
            db.scalar(select(Workspace).where(Workspace.id==code.workspace_id).with_for_update())
            code=db.scalar(select(LinkCode).where(LinkCode.code_hash==digest(parts[1])).with_for_update().execution_options(populate_existing=True))
        if not code or not db.get(Workspace,code.workspace_id) or db.get(Workspace,code.workspace_id).archived_at is not None or code.expires<=now() or not db.get(Membership,(code.user_id,code.workspace_id)):
            success=False
        else:
            db.execute(delete(TelegramLink).where(TelegramLink.telegram_id==str(message.from_user.id)))
            db.add(TelegramLink(telegram_id=str(message.from_user.id),workspace_id=code.workspace_id,user_id=code.user_id))
            db.delete(code); success=True
    await message.answer('เชื่อมต่อแล้ว ส่งข้อความหรือรูปได้ ส่งรายจ่าย เช่น กาแฟ 75 จากเงินสด แล้วตรวจและพิมพ์ยืนยันพร้อมรหัสในแชทนี้ได้ รูปสลิปตรวจและยืนยันบนเว็บ ข้อมูลที่ส่งผ่านบอตจะผ่าน Telegram' if success else 'รหัสไม่ถูกต้องหรือหมดอายุ')

@dp.message(Command('unlink'))
async def unlink(message: TGMessage):
    if message.chat.type!='private': return
    with SessionLocal.begin() as db:
        db.execute(delete(TelegramLink).where(TelegramLink.telegram_id==str(message.from_user.id)))
    await message.answer('ยกเลิกการเชื่อมต่อแล้ว')

def text_capture(db,telegram_id,message_id,text):
    from uuid import uuid5,NAMESPACE_URL
    from .chat_actions import handle
    from .chat_privacy import expired,erase
    link=linked(db,telegram_id)
    if not link:return 'กรุณาเชื่อมต่อจากเว็บก่อน'
    if len(text)>4000:return 'ข้อความยาวเกิน 4,000 ตัวอักษร กรุณาส่งครั้งละหนึ่งรายการ'
    prefix=f'telegram:{telegram_id}:{link.user_id}:{link.workspace_id}:'
    cid=str(uuid5(NAMESPACE_URL,prefix+'room'))
    input_id=str(uuid5(NAMESPACE_URL,prefix+str(message_id)+':input'))
    reply_id=str(uuid5(NAMESPACE_URL,prefix+str(message_id)+':reply'))
    previous=db.get(Message,reply_id)
    if previous:return previous.content
    c=db.get(Conversation,cid)
    if c and expired(db,c):erase(db,c);c=None
    if not c:
        c=Conversation(id=cid,workspace_id=link.workspace_id,user_id=link.user_id,title='Telegram · บันทึก',privacy='private');db.add(c);db.flush()
    c.updated_at=now()
    db.add(Message(id=input_id,workspace_id=c.workspace_id,conversation_id=c.id,role='user',content=text,created_at=message_time(db,c.workspace_id,c.id)));db.flush()
    reply=handle(db,c,link.user_id,text)
    if reply is None:
        enqueue(db,c.workspace_id,link.user_id,'extract',{'text':text,'privacy':'private'})
        reply='รับข้อมูลแล้ว กรุณาตรวจสอบ AI Inbox บนเว็บก่อนยืนยัน ไม่มีการบันทึกยอดอัตโนมัติ'
    db.add(Message(id=reply_id,workspace_id=c.workspace_id,conversation_id=c.id,role='assistant',content=reply,created_at=message_time(db,c.workspace_id,c.id)));db.flush()
    return reply

@dp.message(F.text | F.photo)
async def capture(message: TGMessage, bot: Bot):
    if message.chat.type!='private': return
    with SessionLocal() as db: link=linked(db,message.from_user.id)
    if not link:
        await message.answer('กรุณาเชื่อมต่อจากเว็บก่อน'); return
    if message.text and not message.photo:
        with SessionLocal.begin() as db:
            reply=text_capture(db,message.from_user.id,message.message_id,message.text)
        # Telegram limits replies to 4096 characters. Keep the review and code together.
        await message.answer(reply[:4000]); return
    data = None
    if message.photo:
        if (message.photo[-1].file_size or 0)>8*1024*1024:
            await message.answer('รูปต้องไม่เกิน 8 MB'); return
        buf=io.BytesIO(); await bot.download(message.photo[-1],destination=buf); data=buf.getvalue()
    with SessionLocal.begin() as db:
        link=linked(db,message.from_user.id)
        if not link: return
        if data:
            image,duplicate=store_image(db,link.workspace_id,data)
            if not duplicate: enqueue(db,link.workspace_id,link.user_id,'extract',{'attachment_id':image.id,'privacy':'private'})
        else:
            enqueue(db,link.workspace_id,link.user_id,'extract',{'text':(message.text or '')[:4000],'privacy':'private'})
    await message.answer('รับข้อมูลแล้ว กรุณาตรวจสอบ AI Inbox บนเว็บก่อนยืนยัน ไม่มีการบันทึกยอดอัตโนมัติ')

if __name__=='__main__':
    # aiogram request URLs contain bot tokens; keep library logs off.
    logging.disable(logging.CRITICAL)
    token=os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token: raise SystemExit('Configure TELEGRAM_BOT_TOKEN before starting telegram profile')
    asyncio.run(dp.start_polling(Bot(token)))
