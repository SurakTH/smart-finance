import hashlib
import secrets
from fastapi import Depends, HTTPException, Request
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from redis import Redis
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select
from .db import get_db
from .models import User, Session, Membership, Workspace, now
from .config import REDIS_URL

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_hex(32))
redis = Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)

def digest(text): return hashlib.sha256(text.encode()).hexdigest()

def verify(password, encoded):
    try: return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError): return False

def login_limit(identity):
    # Atomic increment + expiry, no raw IP/email in Redis keys or logs.
    key = 'login:' + digest(identity)
    try:
        count = redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],900) end; return n", 1, key)
    except Exception:
        raise HTTPException(503, 'ระบบจำกัดการเข้าสู่ระบบยังไม่พร้อม')
    if count > 15: raise HTTPException(429, 'กรุณารอ 15 นาทีก่อนลองใหม่')

def current_user(request: Request, db: DBSession = Depends(get_db, scope='function')):
    token = request.cookies.get('sf_session', '')
    session = db.get(Session, digest(token))
    if not session or session.expires <= now(): raise HTTPException(401, 'กรุณาเข้าสู่ระบบ')
    return db.get(User, session.user_id)

def workspace_member(wid: str, request: Request, user: User = Depends(current_user), db: DBSession = Depends(get_db, scope='function')):
    # Reads authorize against committed membership without waiting for inference.
    # Mutations still serialize authorization with membership/ledger changes.
    query=select(Workspace).where(Workspace.id==wid)
    if request.method not in ('GET','HEAD','OPTIONS'):query=query.with_for_update()
    ws=db.scalar(query)
    if not ws or ws.archived_at is not None:raise HTTPException(404,'พื้นที่ถูกเก็บเข้าคลัง หรือไม่พบพื้นที่')
    member = db.get(Membership, (user.id, wid))
    if not member: raise HTTPException(404, 'ไม่พบ workspace')
    return member

def owner(member: Membership = Depends(workspace_member)):
    if member.role != 'owner': raise HTTPException(403, 'เฉพาะเจ้าของ workspace')
    return member
