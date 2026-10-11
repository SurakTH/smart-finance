import io
import secrets
from typing import Literal
from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import Response as RawResponse
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session as DBSession
from PIL import Image, UnidentifiedImageError
from . import config
from .db import get_db
from .models import User, Workspace, Membership, Session, Account, Entry, Line, Proposal, Attachment, Conversation, Message, Job, LinkCode, TelegramLink, now, message_time
from .security import current_user, workspace_member, owner, digest, verify, dummy_hash, login_limit, redis, hasher
from .schemas import Login, Named, AccountInput, TransactionInput, ChatInput, CaptureInput, ConversationInput, ProposalInput, BudgetInput, RevisionInput, CorrectionInput, GoalCreate, GoalEdit, GoalArchive, GoalAllocation, RecurringCreate, RecurringEdit, RecurringPause, InviteEmail, InviteToken, InvitePreview, InviteRegister, MemberRole
from .ledger import initialize_workspace, post, get_scoped, account_balances

from .reporting import transaction_report, monthly_report, active_entry

app = FastAPI(title='Smart Finance', version='0.1.0', docs_url='/docs')

from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    if '/providers' in request.url.path:
        return JSONResponse(status_code=422,content={'detail':'กรุณาตรวจข้อมูลผู้ให้บริการ URL ชื่อโมเดล และค่าการตอบกลับ'})
    if request.url.path in ('/auth/password','/auth/forgot-password','/auth/reset-password','/auth/verify-email','/auth/register','/auth/register-invite','/invitations/preview','/invitations/accept'):
        return JSONResponse(status_code=422,content={'detail':'กรุณาตรวจรหัสผ่านใหม่ 12–200 ตัวอักษรและการยืนยัน' if request.url.path=='/auth/password' else 'กรุณาตรวจข้อมูลที่กรอกและรหัสผ่าน 12–200 ตัวอักษร'})
    return await request_validation_exception_handler(request,exc)


@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if request.headers.get('x-sf-request') != '1' or (origin and origin.rstrip('/') != config.APP_ORIGIN):
            return RawResponse('Forbidden request origin', status_code=403)
    try:
        response = await call_next(request)
    except Exception:
        # Do not emit tracebacks containing DB parameters, chat text or secrets.
        return RawResponse('{"detail":"ระบบไม่สามารถทำรายการได้ กรุณาลองใหม่"}',status_code=500,media_type='application/json',headers={'Cache-Control':'no-store'})
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.get('/health')
def health(db: DBSession = Depends(get_db, scope='function')):
    db.execute(select(1))
    return {'status':'ok'}

from .schemas import PublicRegister
from .bootstrap import create_user
from sqlalchemy.exc import IntegrityError

@app.get('/auth/options')
def auth_options():
    from .email_recovery import available
    return {'allow_registration':config.ALLOW_REGISTRATION,'email_delivery':available()}

@app.post('/auth/register',status_code=201)
def register(data: PublicRegister,request: Request,response: Response,db: DBSession=Depends(get_db,scope='function')):
    if not config.ALLOW_REGISTRATION:
        raise HTTPException(403,'ขณะนี้ปิดการสมัครบัญชีใหม่ กรุณาติดต่อผู้ดูแล')
    login_limit('register-ip:'+(request.client.host if request.client else 'unknown'))
    login_limit('register-email:'+data.email)
    if data.password!=data.confirm_password:
        raise HTTPException(422,'รหัสผ่านและการยืนยันไม่ตรงกัน')
    try:
        # Keep user, personal workspace and session in one outer transaction.
        user=create_user(db,data.email,data.password)
        user.name=data.name
        db.flush()
    except (ValueError,IntegrityError):
        raise HTTPException(409,'ไม่สามารถสมัครด้วยอีเมลนี้ได้ หากมีบัญชีแล้วกรุณาเข้าสู่ระบบ') from None
    from .email_recovery import issue
    issue(db,user,'verify')
    wid=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
    token=secrets.token_urlsafe(48)
    db.add(Session(token_hash=digest(token),user_id=user.id,expires=now()+86400*7))
    response.set_cookie('sf_session',token,httponly=True,secure=config.COOKIE_SECURE,samesite='strict',max_age=86400*7,path='/')
    return {'id':user.id,'email':user.email,'name':user.name,'workspace_id':wid}

@app.post('/auth/login')
def login(data: Login, request: Request, response: Response, db: DBSession = Depends(get_db, scope='function')):
    email = data.email.strip().lower()
    login_limit('ip:' + (request.client.host if request.client else 'unknown'))
    login_limit('email:' + email)
    user = db.scalar(select(User).where(User.email == email).with_for_update())
    if not verify(data.password, user.password if user else dummy_hash): raise HTTPException(401, 'อีเมลหรือรหัสผ่านไม่ถูกต้อง')
    token = secrets.token_urlsafe(48)
    db.add(Session(token_hash=digest(token), user_id=user.id, expires=now()+86400*7))
    response.set_cookie('sf_session', token, httponly=True, secure=config.COOKIE_SECURE, samesite='strict', max_age=86400*7, path='/')
    return {'id':user.id, 'email':user.email, 'name':user.name, 'email_verified':user.email_verified_at is not None}

@app.post('/auth/logout')
def logout(request: Request, response: Response, db: DBSession = Depends(get_db, scope='function')):
    db.execute(delete(Session).where(Session.token_hash == digest(request.cookies.get('sf_session',''))))
    response.delete_cookie('sf_session', path='/')
    return {'ok':True}

@app.get('/auth/me')
def me(user: User = Depends(current_user)):
    return {'id':user.id, 'email':user.email, 'name':user.name, 'email_verified':user.email_verified_at is not None}

from .schemas import ProfileInput, PasswordChangeInput

def locked_account(db, user, request):
    # Recheck the session after the user lock: password changes revoke waiting requests.
    locked=db.scalar(select(User).where(User.id==user.id).with_for_update().execution_options(populate_existing=True))
    session=db.get(Session,digest(request.cookies.get('sf_session','')),populate_existing=True)
    if not session or session.user_id!=user.id or session.expires<=now():
        raise HTTPException(401,'กรุณาเข้าสู่ระบบใหม่')
    return locked

@app.put('/auth/profile')
def update_profile(data: ProfileInput, request: Request, user: User=Depends(current_user), db: DBSession=Depends(get_db,scope='function')):
    account=locked_account(db,user,request)
    account.name=data.name
    return {'id':account.id,'email':account.email,'name':account.name,'email_verified':account.email_verified_at is not None}

@app.post('/auth/password')
def change_password(data: PasswordChangeInput, request: Request, response: Response, user: User=Depends(current_user), db: DBSession=Depends(get_db,scope='function')):
    login_limit('password-change:'+user.id)
    account=locked_account(db,user,request)
    if not verify(data.current_password,account.password):
        raise HTTPException(400,'รหัสผ่านปัจจุบันไม่ถูกต้อง')
    if data.new_password!=data.confirm_password:
        raise HTTPException(422,'รหัสผ่านใหม่และการยืนยันไม่ตรงกัน')
    if verify(data.new_password,account.password):
        raise HTTPException(422,'กรุณาใช้รหัสผ่านใหม่ที่ต่างจากเดิม')
    from .email_recovery import invalidate
    invalidate(db,user.id)
    account.password=hasher.hash(data.new_password)
    db.execute(delete(Session).where(Session.user_id==user.id))
    token=secrets.token_urlsafe(48)
    db.add(Session(token_hash=digest(token),user_id=user.id,expires=now()+86400*7))
    response.set_cookie('sf_session',token,httponly=True,secure=config.COOKIE_SECURE,samesite='strict',max_age=86400*7,path='/')
    return {'ok':True}

from pydantic import BaseModel, Field
from .schemas import InviteEmail

class EmailLinkInput(BaseModel):
    token: str = Field(min_length=40,max_length=100)

class ResetPasswordInput(EmailLinkInput):
    password: str = Field(min_length=12,max_length=200)
    confirm_password: str = Field(min_length=12,max_length=200)

@app.post('/auth/forgot-password')
def forgot_password(data: InviteEmail, request: Request, db: DBSession=Depends(get_db,scope='function')):
    from .email_recovery import issue, GENERIC
    login_limit('reset-ip:'+(request.client.host if request.client else 'unknown'))
    login_limit('reset-email:'+data.email)
    user=db.scalar(select(User).where(User.email==data.email).with_for_update())
    if user:issue(db,user,'reset')
    return {'message':GENERIC}

@app.post('/auth/reset-password')
def reset_password(data: ResetPasswordInput, request: Request, db: DBSession=Depends(get_db,scope='function')):
    from .email_recovery import consume, invalidate
    login_limit('reset-consume:'+(request.client.host if request.client else 'unknown'))
    if data.password!=data.confirm_password:raise HTTPException(422,'รหัสผ่านและการยืนยันไม่ตรงกัน')
    user=consume(db,data.token,'reset')
    user.password=hasher.hash(data.password)
    user.email_verified_at=now()
    invalidate(db,user.id)
    db.execute(delete(Session).where(Session.user_id==user.id))
    return {'ok':True}

@app.get('/auth/email-status')
def email_status(user: User=Depends(current_user)):
    from .email_recovery import available
    return {'verified':user.email_verified_at is not None,'delivery_enabled':available()}

@app.post('/auth/request-verification')
def request_verification(request: Request, user: User=Depends(current_user),db: DBSession=Depends(get_db,scope='function')):
    from .email_recovery import issue, available
    login_limit('verify-user:'+user.id)
    account=locked_account(db,user,request)
    if not available():raise HTTPException(503,'ผู้ดูแลยังไม่ได้เปิดการส่งอีเมล')
    if account.email_verified_at is None:issue(db,account,'verify')
    return {'ok':True}

@app.post('/auth/verify-email')
def verify_email(data: EmailLinkInput,request: Request,db: DBSession=Depends(get_db,scope='function')):
    from .email_recovery import consume
    login_limit('verify-consume:'+(request.client.host if request.client else 'unknown'))
    user=consume(db,data.token,'verify')
    user.email_verified_at=now()
    return {'ok':True}

@app.get('/workspaces')
def workspaces(user: User = Depends(current_user), db: DBSession = Depends(get_db, scope='function')):
    return [dict(id=w.id,name=w.name,role=m.role) for w,m in db.execute(select(Workspace,Membership).join(Membership).where(Membership.user_id == user.id,Workspace.archived_at.is_(None)))]

@app.post('/workspaces')
def add_workspace(data: Named, user: User = Depends(current_user), db: DBSession = Depends(get_db, scope='function')):
    name=data.name.strip()
    if not name:raise HTTPException(422,'กรุณาระบุชื่อพื้นที่')
    ws = initialize_workspace(db, user.id, name)
    return {'id':ws.id,'name':ws.name}

@app.get('/workspaces/{wid}/accounts', dependencies=[Depends(workspace_member)])
def accounts(wid: str, db: DBSession = Depends(get_db, scope='function')):
    return account_balances(db, wid)

@app.post('/workspaces/{wid}/accounts', dependencies=[Depends(workspace_member)])
def add_account(wid: str, data: AccountInput, db: DBSession = Depends(get_db, scope='function')):
    account = Account(workspace_id=wid, **data.model_dump())
    db.add(account); db.flush()
    return {'id':account.id,'name':account.name,'kind':account.kind}

@app.get('/workspaces/{wid}/transactions', dependencies=[Depends(workspace_member)])
def transactions(wid: str, db: DBSession = Depends(get_db, scope='function'), limit: int = 100):
    rows = db.scalars(select(Entry).where(Entry.workspace_id == wid, active_entry(wid)).order_by(Entry.occurred_on.desc(), Entry.created_at.desc(),Entry.id).limit(max(1,min(limit,500))))
    return [entry_json(e) for e in rows]

def entry_json(e):
    return {key:getattr(e,key) for key in ('id','kind','description','amount','occurred_on')}

@app.post('/workspaces/{wid}/transactions')
def transaction(wid: str, data: TransactionInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    entry = post(db,wid,member.user_id,data)
    # Commit BEFORE response: deferred PostgreSQL invariants may fail at commit.
    db.commit()
    return entry_json(entry)


@app.get('/workspaces/{wid}/transaction-history', dependencies=[Depends(workspace_member)])
def revision_history(wid: str, page: int = Query(1,ge=1), start: date | None = None, end: date | None = None, db: DBSession = Depends(get_db, scope='function')):
    from .corrections import history
    return history(db,wid,page,start,end)

@app.get('/workspaces/{wid}/exports/transactions.csv', dependencies=[Depends(workspace_member)])
def export_transactions(wid: str, start: date | None = None, end: date | None = None, kind: str | None = None, account_id: str | None = None, category_id: str | None = None, q: str = Query('',max_length=100), db: DBSession = Depends(get_db, scope='function')):
    from .exports import transactions_csv
    return transactions_csv(db,wid,start,end,kind,account_id,category_id,q)

@app.get('/workspaces/{wid}/exports/history.csv', dependencies=[Depends(workspace_member)])
def export_history(wid: str, start: date | None = None, end: date | None = None, db: DBSession = Depends(get_db, scope='function')):
    from .exports import history_csv
    return history_csv(db,wid,start,end)

@app.get('/workspaces/{wid}/transactions/{eid}', dependencies=[Depends(workspace_member)])
def transaction_detail(wid: str, eid: str, db: DBSession = Depends(get_db, scope='function')):
    from .corrections import detail
    return detail(db,wid,eid)

@app.post('/workspaces/{wid}/transactions/{eid}/correct')
def correct_transaction(wid: str, eid: str, data: CorrectionInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    from .corrections import revise
    result=revise(db,wid,member.user_id,eid,data)
    db.commit()
    return result

@app.post('/workspaces/{wid}/transactions/{eid}/reverse')
def reverse_transaction(wid: str, eid: str, data: RevisionInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    from .corrections import revise
    result=revise(db,wid,member.user_id,eid,data)
    db.commit()
    return result

@app.get('/workspaces/{wid}/dashboard', dependencies=[Depends(workspace_member)])
def dashboard(wid: str, db: DBSession = Depends(get_db, scope='function'), month: str | None = None):
    return monthly_report(db,wid,month or datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m'))

@app.get('/workspaces/{wid}/transaction-report', dependencies=[Depends(workspace_member)])
def report_transactions(wid: str, start: date | None = None, end: date | None = None, kind: str | None = None, account_id: str | None = None, category_id: str | None = None, q: str = Query('',max_length=100), page: int = Query(1,ge=1), page_size: int = Query(30,ge=1,le=100), db: DBSession = Depends(get_db, scope='function')):
    return transaction_report(db,wid,start,end,kind,account_id,category_id,q,page,page_size)

@app.get('/workspaces/{wid}/proposals', dependencies=[Depends(workspace_member)])
def proposals(wid: str, db: DBSession = Depends(get_db, scope='function')):
    from .recurring import proposal_list
    return proposal_list(db,wid)

@app.post('/workspaces/{wid}/proposals', dependencies=[Depends(workspace_member)])
def add_proposal(wid: str, data: ProposalInput, db: DBSession = Depends(get_db, scope='function')):
    p = Proposal(workspace_id=wid, **data.model_dump()); db.add(p); db.flush()
    return {'id':p.id}

@app.post('/workspaces/{wid}/proposals/{pid}/confirm')
def confirm(wid: str, pid: str, data: TransactionInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    proposal = get_scoped(db,Proposal,wid,pid,lock=True)
    if proposal.status=='confirmed': return entry_json(get_scoped(db,Entry,wid,proposal.entry_id))
    if proposal.status!='pending' or data.kind not in ('income','expense'): raise HTTPException(409,'รายการนี้ไม่พร้อมยืนยัน')
    if proposal.attachment_id and db.scalar(select(Proposal.id).where(Proposal.workspace_id==wid,Proposal.attachment_id==proposal.attachment_id,Proposal.status=='confirmed').limit(1)):
        raise HTTPException(409,'รูปนี้มีรายการบันทึกแล้ว ไม่บันทึกซ้ำ')
    entry = post(db,wid,member.user_id,data)
    proposal.status='confirmed'; proposal.entry_id=entry.id
    db.commit()
    return entry_json(entry)

@app.post('/workspaces/{wid}/proposals/{pid}/reject', dependencies=[Depends(workspace_member)])
def reject(wid: str, pid: str, db: DBSession = Depends(get_db, scope='function')):
    p = get_scoped(db,Proposal,wid,pid,lock=True)
    if p.status!='pending': raise HTTPException(409,'ตรวจสอบรายการนี้แล้ว')
    p.status='rejected'
    return {'ok':True}

def store_image(db, wid, data):
    if len(data)>8*1024*1024: raise HTTPException(413,'รูปต้องไม่เกิน 8 MB')
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ('JPEG','PNG','WEBP') or img.width*img.height>16_000_000: raise ValueError()
            img = img.convert('RGB'); img.thumbnail((2000,2000))
            buf = io.BytesIO(); img.save(buf,format='JPEG',quality=90)
            clean = buf.getvalue()
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError): raise HTTPException(422,'รูปภาพไม่ถูกต้อง')
    image_hash = __import__('hashlib').sha256(clean).hexdigest()
    # Same workspace lock avoids duplicate upload races.
    db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    existing = db.scalar(select(Attachment).where(Attachment.workspace_id==wid,Attachment.digest==image_hash))
    if existing: return existing, True
    image = Attachment(workspace_id=wid,digest=image_hash,data=clean); db.add(image); db.flush()
    return image, False

def enqueue(db,wid,user_id,task,payload):
    job = Job(workspace_id=wid,user_id=user_id,task=task,payload=payload)
    db.add(job); db.flush()
    if task=='chat' and payload.get('conversation_id'):
        from .models import ChatGeneration
        db.add(ChatGeneration(job_id=job.id,conversation_id=payload['conversation_id']));db.flush()
    # DB is the durable outbox. Worker also polls, so a wake-up lost before commit is safe.
    try: redis.lpush('sf:wakeup','1'); redis.ltrim('sf:wakeup',0,100)
    except Exception: pass
    return job

@app.post('/workspaces/{wid}/attachments')
async def upload(wid: str, file: UploadFile = File(...), privacy: Literal['private','standard'] = Form('private'), member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    data = await file.read(8*1024*1024+1)
    image, duplicate = store_image(db,wid,data)
    job = None if duplicate else enqueue(db,wid,member.user_id,'extract',{'attachment_id':image.id,'privacy':privacy})
    return {'id':image.id,'duplicate':duplicate,'job_id':job.id if job else None}

@app.get('/workspaces/{wid}/attachments/{aid}')
def attachment(wid: str, aid: str, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    image = get_scoped(db,Attachment,wid,aid)
    # Private chat evidence becomes workspace-visible only when linked to Inbox.
    shared = db.scalar(select(Proposal.id).where(Proposal.workspace_id==wid,Proposal.attachment_id==aid).limit(1))
    from .chat_privacy import rooms,live
    active=rooms().where(Conversation.workspace_id==wid,Conversation.user_id==member.user_id,live()).with_only_columns(Conversation.id)
    mine=db.scalar(select(Message.id).where(Message.workspace_id==wid,Message.attachment_id==aid,Message.conversation_id.in_(active)).limit(1))
    pending = db.scalars(select(Job).where(Job.workspace_id==wid,Job.user_id==member.user_id,Job.status=='pending')).all()
    if not shared and not mine and not any(j.payload.get('attachment_id')==aid and (not j.payload.get('conversation_id') or db.scalar(active.where(Conversation.id==j.payload['conversation_id']))) for j in pending):
        raise HTTPException(404,'ไม่พบรูปภาพ')
    return RawResponse(image.data,media_type='image/jpeg')

@app.get('/workspaces/{wid}/conversations')
def conversations(wid: str, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    from .chat_privacy import rooms,live,serialize
    return [serialize(c) for c in db.scalars(rooms().where(Conversation.workspace_id==wid,Conversation.user_id==member.user_id,Conversation.temporary==0,live()).order_by(Conversation.updated_at.desc(),Conversation.id))]

@app.post('/workspaces/{wid}/conversations')
def new_conversation(wid: str, data: ConversationInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    c = Conversation(workspace_id=wid,user_id=member.user_id,**{**data.model_dump(),'temporary':int(data.temporary)}); db.add(c); db.flush()
    from .chat_privacy import serialize
    return serialize(c)

def owned_conversation(db,wid,cid,user_id):
    c = get_scoped(db,Conversation,wid,cid)
    from .chat_privacy import expired
    if c.user_id!=user_id or expired(db,c): raise HTTPException(404,'ไม่พบห้องสนทนา หรือหมดอายุแล้ว')
    return c

@app.get('/workspaces/{wid}/conversations/{cid}/messages')
def messages(wid: str, cid: str, focus_id: str | None = Query(None,min_length=36,max_length=36), member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    owned_conversation(db,wid,cid,member.user_id)
    from .chat_search import window
    return [dict(id=m.id,role=m.role,content=m.content,attachment_id=m.attachment_id,references=m.references) for m in window(db,wid,cid,focus_id)]

@app.get('/workspaces/{wid}/conversations/{cid}/messages/page')
def message_page(wid: str,cid: str,before: str|None=Query(None,min_length=36,max_length=36),after: str|None=Query(None,min_length=36,max_length=36),member: Membership=Depends(workspace_member),db: DBSession=Depends(get_db,scope='function')):
    owned_conversation(db,wid,cid,member.user_id)
    from .chat_search import page
    return page(db,wid,cid,before,after)

@app.delete('/workspaces/{wid}/conversations/{cid}')
def remove_conversation(wid: str, cid: str, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    c = owned_conversation(db,wid,cid,member.user_id)
    from .chat_privacy import erase
    erase(db,c)
    return {'ok':True}

@app.post('/workspaces/{wid}/conversations/{cid}/messages')
def send_message(wid: str, cid: str, data: ChatInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    c = owned_conversation(db,wid,cid,member.user_id)
    from .models import now
    c.updated_at=now()
    user_message=Message(workspace_id=wid,conversation_id=cid,role='user',content=data.text,created_at=message_time(db,wid,cid))
    db.add(user_message);db.flush()
    from .chat_actions import handle
    reply=handle(db,c,member.user_id,data.text,data.review_message_id,allow_model_dialogue=True)
    if reply is not None:
        message=Message(workspace_id=wid,conversation_id=cid,role='assistant',content=reply,created_at=message_time(db,wid,cid))
        db.add(message);db.flush()
        from .chat_actions import bind_review
        bind_review(db,c,member.user_id,message)
        return {'job_id':None}
    from .chat_actions import begin_request
    begin_request(db,c,member.user_id)
    job = enqueue(db,wid,member.user_id,'chat',{'conversation_id':cid,'text':data.text,'routing':'workspace','user_message_id':user_message.id})
    return {'job_id':job.id}

@app.post('/workspaces/{wid}/conversations/{cid}/images')
async def send_chat_image(wid: str, cid: str, file: UploadFile = File(...), text: str = Form('',max_length=4000), member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    c = owned_conversation(db,wid,cid,member.user_id)
    image, duplicate = store_image(db,wid,await file.read(8*1024*1024+1))
    from .models import now
    c.updated_at=now()
    message=Message(workspace_id=wid,conversation_id=cid,role='user',content=text.strip(),attachment_id=image.id,created_at=message_time(db,wid,cid))
    db.add(message);db.flush()
    from .chat_actions import begin_request
    begin_request(db,c,member.user_id)
    job = enqueue(db,wid,member.user_id,'chat',{'conversation_id':cid,'attachment_id':image.id,'text':text.strip(),'routing':'workspace','user_message_id':message.id})
    db.commit()
    return {'job_id':job.id,'attachment_id':image.id,'duplicate':duplicate}

@app.post('/workspaces/{wid}/conversations/{cid}/jobs/{jid}/stop')
def stop_chat(wid:str,cid:str,jid:str,user:User=Depends(current_user),db:DBSession=Depends(get_db,scope='function')):
    # Read-only authorization, like SSE: waiting for Workspace FOR UPDATE here
    # would make Stop wait for the very generation it must interrupt.
    ws=db.get(Workspace,wid);member=db.get(Membership,(user.id,wid))
    if not ws or ws.archived_at is not None or not member:raise HTTPException(404,'ไม่พบห้องสนทนา')
    owned_conversation(db,wid,cid,member.user_id)
    from .models import ChatGeneration
    control=db.scalar(select(ChatGeneration).join(Job,Job.id==ChatGeneration.job_id).where(ChatGeneration.job_id==jid,ChatGeneration.conversation_id==cid,Job.workspace_id==wid,Job.user_id==member.user_id,Job.task=='chat').with_for_update(of=ChatGeneration))
    if not control:raise HTTPException(404,'ไม่พบงานในห้องนี้')
    job=db.scalar(select(Job).where(Job.id==jid).execution_options(populate_existing=True))
    if job.status!='pending':return {'job_id':jid,'status':job.status}
    control.stop_requested=True;db.flush()
    # Queued jobs can finish cancellation now; a running job is locked by its
    # worker and will observe the durable flag without waiting for that lock.
    # Inserting the stop notice needs a workspace FK lock. Do not wait if a
    # different room's worker owns this workspace; its queued job will cancel
    # itself when picked up, without ever reaching a model.
    free_workspace=db.scalar(select(Workspace.id).where(Workspace.id==wid).with_for_update(skip_locked=True))
    queued=db.scalar(select(Job).where(Job.id==jid,Job.status=='pending').with_for_update(skip_locked=True)) if free_workspace else None
    if queued:
        from .chat_stop import stopped_message
        queued.status='cancelled';queued.error=None;queued.payload={}
        stopped_message(db,wid,cid)
    db.commit()
    from .worker import notify
    notify((wid,cid,jid),'cancelled' if queued else 'stopping')
    return {'job_id':jid,'status':'cancelled' if queued else 'stopping'}

@app.get('/workspaces/{wid}/jobs')
def jobs(wid: str, member: Membership=Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    from .models import ChatGeneration
    from .ai_errors import message
    rows=db.execute(select(Job,ChatGeneration).outerjoin(ChatGeneration,ChatGeneration.job_id==Job.id).where(Job.workspace_id==wid).order_by(Job.created_at.desc()).limit(30)).all()
    return [dict(id=j.id,task=j.task,status=j.status,error=j.error,message=message(j.error) if j.status=='failed' else None,conversation_id=g.conversation_id if g and j.user_id==member.user_id else None,stopping=bool(g and g.stop_requested and j.status=='pending')) for j,g in rows]

@app.post('/workspaces/{wid}/capture')
def capture(wid: str, data: CaptureInput, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    job = enqueue(db,wid,member.user_id,'extract',{'text':data.text,'privacy':data.privacy})
    return {'job_id':job.id}

from .ai_settings import router as ai_settings_router
app.include_router(ai_settings_router)
from .assistant_preferences import router as preferences_router
from .ai_usage import router as usage_router
app.include_router(preferences_router)
app.include_router(usage_router)

@app.post('/workspaces/{wid}/telegram/link-code')
def link_code(wid: str, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    code = secrets.token_urlsafe(24)
    db.add(LinkCode(code_hash=digest(code),workspace_id=wid,user_id=member.user_id,expires=now()+600))
    return {'code':code,'expires_in':600}

@app.delete('/workspaces/{wid}/telegram/link')
def unlink(wid: str, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    db.execute(delete(TelegramLink).where(TelegramLink.workspace_id==wid,TelegramLink.user_id==member.user_id))
    db.execute(delete(LinkCode).where(LinkCode.workspace_id==wid,LinkCode.user_id==member.user_id))
    return {'ok':True}


@app.get('/workspaces/{wid}/budgets', dependencies=[Depends(workspace_member)])
def budgets(wid: str, month: str, db: DBSession = Depends(get_db, scope='function')):
    from .budgets import budget_report
    return budget_report(db,wid,month)

@app.put('/workspaces/{wid}/budgets/{month}/{category_id}', dependencies=[Depends(workspace_member)])
def save_budget(wid: str, month: str, category_id: str, data: BudgetInput, db: DBSession = Depends(get_db, scope='function')):
    from .budgets import set_budget
    set_budget(db,wid,month,category_id,data.amount)
    return {'ok':True}

@app.delete('/workspaces/{wid}/budgets/{month}/{category_id}', dependencies=[Depends(workspace_member)])
def delete_budget(wid: str, month: str, category_id: str, db: DBSession = Depends(get_db, scope='function')):
    from .budgets import remove_budget
    remove_budget(db,wid,month,category_id)
    return {'ok':True}

@app.post('/workspaces/{wid}/budgets/{month}/copy-previous', dependencies=[Depends(workspace_member)])
def copy_budgets(wid: str, month: str, db: DBSession = Depends(get_db, scope='function')):
    from .budgets import copy_previous
    return {'copied':copy_previous(db,wid,month)}


@app.get('/workspaces/{wid}/goals', dependencies=[Depends(workspace_member)])
def goals(wid: str, db: DBSession = Depends(get_db, scope='function')):
    from .goals import list_goals
    return list_goals(db,wid)

@app.post('/workspaces/{wid}/goals')
def create_goal(wid: str, data: GoalCreate, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    from .goals import create
    return create(db,wid,member.user_id,data)

@app.put('/workspaces/{wid}/goals/{gid}', dependencies=[Depends(workspace_member)])
def edit_goal(wid: str, gid: str, data: GoalEdit, db: DBSession = Depends(get_db, scope='function')):
    from .goals import edit
    return edit(db,wid,gid,data)

@app.post('/workspaces/{wid}/goals/{gid}/archive', dependencies=[Depends(workspace_member)])
def archive_goal(wid: str, gid: str, data: GoalArchive, db: DBSession = Depends(get_db, scope='function')):
    from .goals import archive
    return archive(db,wid,gid,data)

@app.post('/workspaces/{wid}/goals/{gid}/allocations')
def goal_allocate(wid: str, gid: str, data: GoalAllocation, member: Membership = Depends(workspace_member), db: DBSession = Depends(get_db, scope='function')):
    from .goals import allocate
    return allocate(db,wid,member.user_id,gid,data)

@app.get('/workspaces/{wid}/goals/{gid}/allocations', dependencies=[Depends(workspace_member)])
def goal_allocations(wid: str, gid: str, page: int = Query(1,ge=1), db: DBSession = Depends(get_db, scope='function')):
    from .goals import movements
    return movements(db,wid,gid,page)


@app.get('/workspaces/{wid}/recurring',dependencies=[Depends(workspace_member)])
def recurring_list(wid: str,db: DBSession = Depends(get_db,scope='function')):
    from .recurring import rules
    return rules(db,wid)

@app.post('/workspaces/{wid}/recurring')
def recurring_create(wid: str,data: RecurringCreate,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    from .recurring import create
    return create(db,wid,member.user_id,data)

@app.put('/workspaces/{wid}/recurring/{rid}',dependencies=[Depends(workspace_member)])
def recurring_edit(wid: str,rid: str,data: RecurringEdit,db: DBSession = Depends(get_db,scope='function')):
    from .recurring import edit
    return edit(db,wid,rid,data)

@app.post('/workspaces/{wid}/recurring/{rid}/pause',dependencies=[Depends(workspace_member)])
def recurring_pause(wid: str,rid: str,data: RecurringPause,db: DBSession = Depends(get_db,scope='function')):
    from .recurring import pause
    return pause(db,wid,rid,data)

@app.get('/workspaces/{wid}/recurring/{rid}/history',dependencies=[Depends(workspace_member)])
def recurring_history(wid: str,rid: str,page: int = Query(1,ge=1),db: DBSession = Depends(get_db,scope='function')):
    from .recurring import history
    return history(db,wid,rid,page)

@app.post('/workspaces/{wid}/recurring/check-due',dependencies=[Depends(workspace_member)])
def recurring_check(wid: str,db: DBSession = Depends(get_db,scope='function')):
    from .recurring import generate_due
    return generate_due(db,wid=wid)


@app.get('/workspaces/{wid}/members')
def workspace_members(wid: str,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    from .members import roster
    return roster(db,wid,member.user_id)

@app.get('/workspaces/{wid}/invitations',dependencies=[Depends(owner)])
def invitations(wid: str,db: DBSession = Depends(get_db,scope='function')):
    from .members import invitations
    return invitations(db,wid)

@app.post('/workspaces/{wid}/invitations')
def invite(wid: str,data: InviteEmail,member: Membership = Depends(owner),db: DBSession = Depends(get_db,scope='function')):
    from .members import invite
    return invite(db,wid,member.user_id,data.email)

@app.post('/workspaces/{wid}/invitations/{iid}/revoke')
def revoke_invite(wid: str,iid: str,member: Membership = Depends(owner),db: DBSession = Depends(get_db,scope='function')):
    from .members import revoke
    return revoke(db,wid,member.user_id,iid)

@app.post('/workspaces/{wid}/members/{uid}/role')
def change_role(wid: str,uid: str,data: MemberRole,member: Membership = Depends(owner),db: DBSession = Depends(get_db,scope='function')):
    from .members import change_role
    return change_role(db,wid,member.user_id,uid,data.role)

@app.delete('/workspaces/{wid}/members/{uid}')
def remove_member(wid: str,uid: str,member: Membership = Depends(owner),db: DBSession = Depends(get_db,scope='function')):
    from .members import remove
    return remove(db,wid,member.user_id,uid)

@app.post('/workspaces/{wid}/leave')
def leave_workspace(wid: str,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    from .members import remove
    return remove(db,wid,member.user_id,member.user_id,leaving=True)

@app.get('/workspaces/{wid}/membership-history',dependencies=[Depends(owner)])
def membership_history(wid: str,page: int = Query(1,ge=1),db: DBSession = Depends(get_db,scope='function')):
    from .members import history
    return history(db,wid,page)

@app.post('/invitations/preview')
def preview_invite(data: InvitePreview,request: Request,db: DBSession = Depends(get_db,scope='function')):
    from .members import preview
    login_limit('invite-ip:'+(request.client.host if request.client else 'unknown'))
    return preview(db,data.token,data.email)

@app.post('/invitations/accept')
def accept_invite(data: InviteToken,request: Request,user: User = Depends(current_user),db: DBSession = Depends(get_db,scope='function')):
    from .members import accept
    login_limit('invite-ip:'+(request.client.host if request.client else 'unknown'))
    return accept(db,user,data.token)

@app.post('/auth/register-invite')
def register_invite(data: InviteRegister,request: Request,response: Response,db: DBSession = Depends(get_db,scope='function')):
    from .members import register
    login_limit('invite-ip:'+(request.client.host if request.client else 'unknown'))
    user,wid=register(db,data)
    token=secrets.token_urlsafe(48)
    db.add(Session(token_hash=digest(token),user_id=user.id,expires=now()+86400*7))
    response.set_cookie('sf_session',token,httponly=True,secure=config.COOKIE_SECURE,samesite='strict',max_age=86400*7,path='/')
    return {'workspace_id':wid}


@app.get('/workspaces/{wid}/chat-preferences')
def chat_preferences(wid: str,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    from .models import ChatPreference
    p=db.get(ChatPreference,(member.user_id,wid))
    return {'retention_days':p.retention_days if p else 0}

from .schemas import ChatRetentionInput
@app.put('/workspaces/{wid}/chat-preferences')
def set_chat_preferences(wid: str,data: ChatRetentionInput,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    from .models import ChatPreference
    p=db.get(ChatPreference,(member.user_id,wid))
    if not p:p=ChatPreference(user_id=member.user_id,workspace_id=wid);db.add(p)
    p.retention_days=data.retention_days
    return {'retention_days':p.retention_days}


from .schemas import ChatSearchInput,ChatRenameInput
@app.post('/workspaces/{wid}/conversations/search')
def search_conversations(wid: str,data: ChatSearchInput,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    from .chat_search import search
    return search(db,wid,member.user_id,data.q,data.page)

@app.post('/workspaces/{wid}/conversations/{cid}/rename')
def rename_conversation(wid: str,cid: str,data: ChatRenameInput,member: Membership = Depends(workspace_member),db: DBSession = Depends(get_db,scope='function')):
    c=owned_conversation(db,wid,cid,member.user_id)
    if c.temporary:raise HTTPException(409,'ห้องชั่วคราวไม่เก็บในประวัติ')
    c.title=data.title
    from .chat_privacy import serialize
    return serialize(c)


@app.get('/workspaces/{wid}/conversations/{cid}/events')
def chat_events(wid: str,cid: str,request: Request):
    from .chat_stream import authorized,events
    from fastapi.responses import StreamingResponse
    token=request.cookies.get('sf_session','')
    authorized(token,wid,cid)
    return StreamingResponse(events(request,token,wid,cid),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

from .schemas import WorkspaceRename,WorkspaceArchive,WorkspaceConfirm

@app.get('/workspace-management')
def managed_workspaces(user:User=Depends(current_user),db:DBSession=Depends(get_db,scope='function')):
    from .workspaces import listing
    return listing(db,user.id)

@app.put('/workspace-management/{wid}')
def rename_workspace(wid:str,data:WorkspaceRename,user:User=Depends(current_user),db:DBSession=Depends(get_db,scope='function')):
    from .workspaces import rename
    return rename(db,wid,user.id,data)

@app.post('/workspace-management/{wid}/archive')
def archive_workspace(wid:str,data:WorkspaceArchive,user:User=Depends(current_user),db:DBSession=Depends(get_db,scope='function')):
    from .workspaces import archive
    return archive(db,wid,user.id,data)

@app.post('/workspace-management/{wid}/delete')
def delete_workspace(wid:str,data:WorkspaceConfirm,user:User=Depends(current_user),db:DBSession=Depends(get_db,scope='function')):
    from .workspaces import remove
    return remove(db,wid,user.id,data)

@app.post('/workspaces/{wid}/account-invitations')
def invite_personal_account(wid:str,data:InviteEmail,member:Membership=Depends(owner),db:DBSession=Depends(get_db,scope='function')):
    from .members import invite
    return invite(db,wid,member.user_id,data.email,mode='personal')


@app.get('/workspaces/{wid}/assistant-changes', dependencies=[Depends(workspace_member)])
def assistant_changes(wid: str, page: int = Query(1,ge=1,le=10000), db: DBSession = Depends(get_db, scope='function')):
    from .models import AssistantChange
    rows=db.execute(select(AssistantChange,User.name).join(User,User.id==AssistantChange.user_id).where(AssistantChange.workspace_id==wid).order_by(AssistantChange.created_at.desc(),AssistantChange.id.desc()).offset((page-1)*10).limit(11)).all()
    return {'items':[dict(id=r.id,summary=r.summary,created_at=r.created_at,actor=name or 'สมาชิก') for r,name in rows[:10]],'has_more':len(rows)>10,'page':page}
