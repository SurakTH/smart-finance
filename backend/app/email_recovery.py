"""Account email links. Only trusted HTTP handlers may consume tokens."""
import json
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from fastapi import HTTPException
from sqlalchemy import select, update
from . import config
from .models import User, EmailToken, now
from .security import digest

GENERIC = 'หากอีเมลนี้มีบัญชี ระบบจะส่งลิงก์ให้เมื่อเปิดใช้งานการส่งอีเมลแล้ว กรุณาตรวจกล่องจดหมายและสแปม'

def available():
    return bool(config.MAIL_ENABLED and config.SMTP_HOST and config.SMTP_FROM and config.SMTP_SECURITY in ('starttls','ssl'))

def invalidate(db, user_id, purpose=None):
    query=update(EmailToken).where(EmailToken.user_id==user_id,EmailToken.used.is_(False))
    if purpose:query=query.where(EmailToken.purpose==purpose)
    db.execute(query.values(used=True,encrypted_payload=None,delivery='cancelled'))

def issue(db,user,purpose):
    # Caller holds User FOR UPDATE. Issuing a replacement invalidates older links.
    if not available():return
    invalidate(db,user.id,purpose)
    raw=secrets.token_urlsafe(48)
    expires=now()+(1800 if purpose=='reset' else 86400)
    path='/reset-password' if purpose=='reset' else '/verify-email'
    payload=json.dumps({'email':user.email,'url':config.APP_ORIGIN+path+'#token='+raw,'purpose':purpose},ensure_ascii=False)
    db.add(EmailToken(token_hash=digest(raw),user_id=user.id,purpose=purpose,expires=expires,
        encrypted_payload=config.cipher().encrypt(payload.encode()).decode()))

def consume(db,raw,purpose):
    # Lock ordering matches issue/password change/worker: User, then EmailToken.
    key=digest(raw)
    uid=db.scalar(select(EmailToken.user_id).where(EmailToken.token_hash==key,EmailToken.purpose==purpose))
    user=db.scalar(select(User).where(User.id==uid).with_for_update()) if uid else None
    token=db.scalar(select(EmailToken).where(EmailToken.token_hash==key).with_for_update().execution_options(populate_existing=True)) if user else None
    if not token or token.purpose!=purpose or token.used or token.expires<=now():
        raise HTTPException(400,'ลิงก์ไม่ถูกต้อง หมดอายุ หรือถูกใช้แล้ว กรุณาขอลิงก์ใหม่')
    token.used=True;token.encrypted_payload=None;token.delivery='cancelled'
    return user

def send(payload):
    message=EmailMessage()
    message['From']=config.SMTP_FROM
    message['To']=payload['email']
    reset=payload['purpose']=='reset'
    message['Subject']='Smart Finance · '+('ตั้งรหัสผ่านใหม่' if reset else 'ยืนยันอีเมล')
    message.set_content(('เปิดลิงก์เพื่อตั้งรหัสผ่านใหม่ (อายุ 30 นาที)' if reset else 'เปิดลิงก์เพื่อยืนยันอีเมล (อายุ 24 ชั่วโมง)')+'\n\n'+payload['url']+'\n\nหากไม่ได้เป็นผู้ขอ สามารถละเว้นอีเมลนี้ได้')
    context=ssl.create_default_context()
    factory=smtplib.SMTP_SSL if config.SMTP_SECURITY=='ssl' else smtplib.SMTP
    options={'context':context} if config.SMTP_SECURITY=='ssl' else {}
    with factory(config.SMTP_HOST,config.SMTP_PORT,timeout=10,**options) as server:
        if config.SMTP_SECURITY=='starttls':server.ehlo();server.starttls(context=context);server.ehlo()
        if config.SMTP_USERNAME:server.login(config.SMTP_USERNAME,config.SMTP_PASSWORD)
        server.send_message(message)

def cleanup(db):
    # Clear expired outbox bodies even after the administrator disables SMTP.
    db.execute(update(EmailToken).where(EmailToken.expires<=now(),EmailToken.encrypted_payload.is_not(None)).values(encrypted_payload=None,delivery='cancelled',used=True))

def deliver_once():
    from .db import SessionLocal
    if not available():return False
    with SessionLocal.begin() as db:
        candidate=db.execute(select(EmailToken.token_hash,EmailToken.user_id).where(EmailToken.delivery=='pending',EmailToken.next_attempt<=now()).order_by(EmailToken.next_attempt).limit(1)).first()
        if not candidate:return False
        db.scalar(select(User).where(User.id==candidate.user_id).with_for_update())
        token=db.scalar(select(EmailToken).where(EmailToken.token_hash==candidate.token_hash).with_for_update().execution_options(populate_existing=True))
        if token.delivery!='pending':return False
        if token.used or token.expires<=now():
            token.delivery='cancelled';token.encrypted_payload=None
            return True
        token.attempts+=1
        try:
            send(json.loads(config.cipher().decrypt(token.encrypted_payload.encode())))
            token.delivery='sent';token.encrypted_payload=None
        except Exception:
            # Store no exception text, address, credential or message body.
            if token.attempts>=3:token.delivery='failed';token.encrypted_payload=None
            else:token.next_attempt=now()+60*token.attempts
        return True
