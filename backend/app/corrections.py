"""Append-only corrections: original + exact inverse + optional replacement."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import hashlib
import json
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func
from .models import Entry, EntryRevision, Line, Workspace
from .ledger import get_scoped, post
from .reporting import entry_details
from .schemas import CorrectionInput


def audit_json(db,wid,revision):
    entries=db.scalars(select(Entry).where(Entry.workspace_id==wid,Entry.id.in_([revision.original_id,revision.replacement_id]))).all()
    details={e['id']:e for e in entry_details(db,wid,entries)}
    return dict(id=revision.id,original=details[revision.original_id],replacement=details.get(revision.replacement_id),
                reason=revision.reason,created_at=revision.created_at,created_by=revision.created_by,
                operation='correct' if revision.replacement_id else 'reverse')


def revision_conditions(wid,start=None,end=None):
    if start and end and start>end: raise HTTPException(422,'วันเริ่มต้นต้องไม่เกินวันสิ้นสุด')
    conditions=[EntryRevision.workspace_id==wid]
    if start:
        conditions.append(EntryRevision.created_at>=int(datetime.combine(start,time.min,ZoneInfo('Asia/Bangkok')).timestamp())*1000)
    if end:
        conditions.append(EntryRevision.created_at<=int(datetime.combine(end,time(23,59,59),ZoneInfo('Asia/Bangkok')).timestamp())*1000+999)
    return conditions


def history(db,wid,page,start=None,end=None):
    conditions=revision_conditions(wid,start,end)
    total=db.scalar(select(func.count()).select_from(EntryRevision).where(*conditions))
    rows=db.scalars(select(EntryRevision).where(*conditions).order_by(EntryRevision.created_at.desc(),EntryRevision.id).offset((page-1)*30).limit(30)).all()
    return dict(items=[audit_json(db,wid,r) for r in rows],total=total,page=page,page_size=30)


def detail(db,wid,eid):
    entry=get_scoped(db,Entry,wid,eid)
    if db.scalar(select(EntryRevision.id).where(EntryRevision.workspace_id==wid,EntryRevision.reversal_id==eid)):
        raise HTTPException(404,'ไม่พบรายการ')
    row=entry_details(db,wid,[entry])[0]
    revision=db.scalar(select(EntryRevision).where(EntryRevision.workspace_id==wid,EntryRevision.original_id==eid))
    prior=db.scalar(select(EntryRevision).where(EntryRevision.workspace_id==wid,EntryRevision.replacement_id==eid))
    row.update(status=('corrected' if revision.replacement_id else 'reversed') if revision else 'active',
               revision=audit_json(db,wid,revision) if revision else None,
               previous=audit_json(db,wid,prior) if prior else None)
    return row


def revise(db,wid,uid,eid,data):
    ws=db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    if not ws or ws.archived_at is not None:raise HTTPException(409,'พื้นที่ถูกเก็บเข้าคลัง กรุณากู้คืนก่อนแก้ไข')
    fingerprint=hashlib.sha256(json.dumps({'original':eid,**data.model_dump(mode='json')},sort_keys=True).encode()).hexdigest()
    existing=db.scalar(select(EntryRevision).where(EntryRevision.workspace_id==wid,EntryRevision.idempotency_key==str(data.idempotency_key)))
    if existing:
        if existing.fingerprint!=fingerprint: raise HTTPException(409,'รหัสการแก้ไขถูกใช้กับข้อมูลอื่นแล้ว')
        return audit_json(db,wid,existing)
    original=get_scoped(db,Entry,wid,eid)
    used=db.scalar(select(EntryRevision.id).where(EntryRevision.workspace_id==wid,(EntryRevision.original_id==eid)|(EntryRevision.reversal_id==eid)))
    if used: raise HTTPException(409,'รายการนี้ถูกแก้ไขหรือยกเลิกแล้ว กรุณาเปิดรายการล่าสุด')
    lines=db.scalars(select(Line).where(Line.workspace_id==wid,Line.entry_id==eid)).all()
    replacement=None
    if isinstance(data,CorrectionInput):
        tx=data.transaction
        if tx.kind!=original.kind: raise HTTPException(422,'การแก้ไขต้องใช้ประเภทรายการเดิม')
        if db.scalar(select(Entry.id).where(Entry.workspace_id==wid,Entry.idempotency_key==str(tx.idempotency_key))):
            raise HTTPException(409,'รหัสรายการทดแทนถูกใช้แล้ว')
        opening_account=None
        if original.kind=='opening':
            from .models import Account
            opening_account=db.scalar(select(Account.id).join(Line,(Line.account_id==Account.id)&(Line.workspace_id==Account.workspace_id)).where(Line.entry_id==eid,Line.workspace_id==wid,Account.kind.in_(('asset','liability'))))
            if tx.account_id!=opening_account: raise HTTPException(422,'แก้ยอดตั้งต้นได้ในบัญชีเดิมเท่านั้น')
        replacement=post(db,wid,uid,tx,_opening_account=opening_account)
    # The inverse journal has the same kind but is never a reportable transaction:
    # its immutable audit role and lines are committed together with the replacement.
    inverse=Entry(workspace_id=wid,created_by=uid,kind=original.kind,description='กลับรายการ: '+original.description[:285],
                  amount=original.amount,occurred_on=original.occurred_on,idempotency_key=str(uuid4()),fingerprint=fingerprint)
    db.add(inverse);db.flush()
    for line in lines:
        db.add(Line(workspace_id=wid,entry_id=inverse.id,account_id=line.account_id,signed_amount=-line.signed_amount))
    db.flush()
    revision=EntryRevision(workspace_id=wid,original_id=eid,reversal_id=inverse.id,replacement_id=replacement.id if replacement else None,
                           reason=data.reason,created_by=uid,idempotency_key=str(data.idempotency_key),fingerprint=fingerprint)
    db.add(revision);db.flush()
    return audit_json(db,wid,revision)
