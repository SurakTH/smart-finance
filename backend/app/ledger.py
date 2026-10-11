import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, func
from .models import Workspace, Account, Entry, Line, Membership
from .schemas import TransactionInput

def get_scoped(db, model, wid, item_id, lock=False):
    q = select(model).where(model.id == item_id, model.workspace_id == wid)
    if lock: q = q.with_for_update()
    item = db.scalar(q)
    if item is None: raise HTTPException(404, 'ไม่พบข้อมูล')
    return item

def initialize_workspace(db, user_id, name):
    ws = Workspace(name=name)
    db.add(ws); db.flush()
    db.add(Membership(user_id=user_id, workspace_id=ws.id, role='owner'))
    for title, kind in [('เงินสด','asset'), ('ยอดตั้งต้น','equity'), ('อาหารและเครื่องดื่ม','expense'), ('เดินทาง','expense'), ('อื่น ๆ','expense'), ('เงินเดือน','income')]:
        db.add(Account(workspace_id=ws.id, name=title, kind=kind))
    db.flush()
    return ws

def post(db, wid, user_id, data: TransactionInput, *, _opening_account=None):
    # Serializes writes per workspace, including replay and proposal confirmation.
    ws=db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    if not ws or ws.archived_at is not None:raise HTTPException(409,'พื้นที่ถูกเก็บเข้าคลัง กรุณากู้คืนก่อนบันทึก')
    fingerprint = hashlib.sha256(json.dumps(data.model_dump(mode='json'), sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(Entry).where(Entry.workspace_id == wid, Entry.idempotency_key == str(data.idempotency_key)))
    if existing:
        if existing.fingerprint != fingerprint: raise HTTPException(409, 'รหัสรายการนี้ถูกใช้กับข้อมูลอื่นแล้ว')
        return existing
    account = get_scoped(db, Account, wid, data.account_id)
    if account.kind not in ('asset','liability'): raise HTTPException(422, 'บัญชีต้นทางไม่ถูกต้อง')
    amount = data.amount
    if data.kind == 'opening':
        used = db.scalar(select(Line.id).where(Line.workspace_id == wid, Line.account_id == account.id).limit(1))
        if used and account.id != _opening_account: raise HTTPException(409, 'กำหนดยอดตั้งต้นได้เฉพาะบัญชีที่ยังไม่มีรายการ')
        equity = db.scalar(select(Account).where(Account.workspace_id == wid, Account.kind == 'equity'))
        delta = amount if account.kind == 'asset' else -amount
        lines = [(account.id, delta),(equity.id, -delta)]
    elif data.kind in ('income','expense'):
        category = get_scoped(db, Account, wid, data.category_id)
        if category.kind != data.kind: raise HTTPException(422, 'หมวดหมู่ไม่ตรงกับประเภทรายการ')
        if data.kind == 'income' and account.kind != 'asset': raise HTTPException(422, 'รายรับต้องเข้าบัญชีสินทรัพย์')
        delta = amount if data.kind == 'income' else -amount
        lines = [(account.id, delta),(category.id, -delta)]
    else:
        other = get_scoped(db, Account, wid, data.other_account_id)
        if account.id == other.id or account.kind != 'asset': raise HTTPException(422, 'กรุณาเลือกบัญชีต้นทางและปลายทางให้ถูกต้อง')
        expected = 'asset' if data.kind == 'transfer' else 'liability'
        if other.kind != expected: raise HTTPException(422, 'ประเภทบัญชีปลายทางไม่ถูกต้อง')
        lines = [(account.id,-amount),(other.id,amount)]
    if sum(n for _, n in lines) != 0: raise ValueError('Unbalanced journal')
    entry = Entry(workspace_id=wid, created_by=user_id, kind=data.kind, description=data.description,
                  amount=amount, occurred_on=data.occurred_on.isoformat(), idempotency_key=str(data.idempotency_key), fingerprint=fingerprint)
    db.add(entry); db.flush()
    for account_id, signed in lines:
        db.add(Line(workspace_id=wid, entry_id=entry.id, account_id=account_id, signed_amount=signed))
    db.flush()
    return entry

def account_balances(db, wid):
    rows = db.execute(select(Account, func.coalesce(func.sum(Line.signed_amount),0)).outerjoin(Line, (Line.account_id == Account.id) & (Line.workspace_id == Account.workspace_id)).where(Account.workspace_id == wid).group_by(Account.id))
    return [dict(id=a.id, name=a.name, kind=a.kind, balance=int(balance) * (-1 if a.kind in ('liability','income','equity') else 1)) for a,balance in rows]
