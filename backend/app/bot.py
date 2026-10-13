import asyncio
import io
import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message as TGMessage
from sqlalchemy import select, delete
from .db import SessionLocal
from .models import LinkCode, TelegramLink, Membership, Workspace, now
from .security import digest

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
    await message.answer('เชื่อมต่อแล้วค่ะ คุยกับฉันได้เลย เช่น ถามยอดเงิน หรือส่งรูปสลิปพร้อมคำบรรยาย ฉันจะใช้ AI ตามที่ตั้งไว้ในพื้นที่นี้ ถ้าต้องบันทึกหรือแก้ข้อมูล ฉันจะทวนให้ตรวจ แล้วรอคุณพิมพ์ ยืนยัน ก่อนค่ะ พิมพ์ /new หรือ /reset เพื่อเริ่มบทสนทนาใหม่ได้ ข้อความและรูปช่องทางนี้ผ่าน Telegram' if success else 'รหัสไม่ถูกต้องหรือหมดอายุ')

@dp.message(Command('unlink'))
async def unlink(message: TGMessage):
    if message.chat.type!='private': return
    with SessionLocal.begin() as db:
        db.execute(delete(TelegramLink).where(TelegramLink.telegram_id==str(message.from_user.id)))
    await message.answer('ยกเลิกการเชื่อมต่อแล้ว')

def text_capture(db,telegram_id,message_id,text):
    from .telegram_chat import submit
    return submit(db,telegram_id,message_id,text)

@dp.message(Command('new','reset'))
async def new_chat(message: TGMessage, bot: Bot):
    await capture(message,bot)

@dp.message(F.text | F.photo)
async def capture(message: TGMessage, bot: Bot):
    if message.chat.type!='private': return
    with SessionLocal() as db: link=linked(db,message.from_user.id)
    if not link:
        await message.answer('กรุณาเชื่อมต่อจากเว็บก่อนค่ะ'); return
    data=None
    if message.photo:
        if (message.photo[-1].file_size or 0)>8*1024*1024:
            await message.answer('รูปต้องไม่เกิน 8 MB'); return
        buf=io.BytesIO()
        await bot.download(message.photo[-1],destination=buf)
        data=buf.getvalue()
    from .telegram_chat import submit
    text=(message.caption or '') if message.photo else (message.text or '')
    with SessionLocal.begin() as db:
        reply=submit(db,message.from_user.id,message.message_id,text,data)
    # Every linked reply (including confirmations) is committed with its outbox.
    # Unlinked validation is the only reply that has no authorized room to queue.
    if reply=='กรุณาเชื่อมต่อจากเว็บก่อน':await message.answer(reply,parse_mode=None)

async def start_delivery(bot: Bot):
    from .telegram_chat import delivery_loop
    dp['delivery_task']=asyncio.create_task(delivery_loop(bot))

async def stop_delivery():
    task=dp.get('delivery_task')
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

dp.startup.register(start_delivery)
dp.shutdown.register(stop_delivery)

if __name__=='__main__':
    # aiogram request URLs contain bot tokens; keep library logs off.
    logging.disable(logging.CRITICAL)
    token=os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token: raise SystemExit('Configure TELEGRAM_BOT_TOKEN before starting telegram profile')
    asyncio.run(dp.start_polling(Bot(token)))
