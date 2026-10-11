"""Savings plans only; allocations never create or change real ledger entries."""
import hashlib
import json
from datetime import date
from fastapi import HTTPException
from sqlalchemy import select, func
from .models import Goal, GoalMovement, Workspace
from .ledger import get_scoped
from .reporting import today

MAX_GOALS=500
MAX_AMOUNT=100_000_000_000


def lock(db,wid):
    db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())


def fingerprint(data,**extra):
    return hashlib.sha256(json.dumps({**extra,**data.model_dump(mode='json')},sort_keys=True).encode()).hexdigest()


def goal_json(goal,allocated):
    left=goal.target-allocated
    days=(date.fromisoformat(goal.due_on)-today()).days if goal.due_on else None
    status='archived' if goal.archived else 'reached' if left<=0 else 'overdue' if days is not None and days<0 else 'active'
    return dict(id=goal.id,name=goal.name,target=goal.target,due_on=goal.due_on,archived=bool(goal.archived),version=goal.version,
                allocated=int(allocated),remaining=max(0,left),percent=allocated*100//goal.target,status=status,days_remaining=days)


def amount(db,wid,gid):
    return int(db.scalar(select(func.coalesce(func.sum(GoalMovement.signed_amount),0)).where(GoalMovement.workspace_id==wid,GoalMovement.goal_id==gid)))


def list_goals(db,wid):
    rows=db.execute(select(Goal,func.coalesce(func.sum(GoalMovement.signed_amount),0)).outerjoin(GoalMovement,(GoalMovement.goal_id==Goal.id)&(GoalMovement.workspace_id==Goal.workspace_id)).where(Goal.workspace_id==wid).group_by(Goal.id).order_by(Goal.archived,Goal.created_at.desc(),Goal.id)).all()
    items=[goal_json(g,n) for g,n in rows]
    active=[g for g in items if not g['archived']]
    return dict(items=items,target=sum(g['target'] for g in active),allocated=sum(g['allocated'] for g in active),remaining=sum(g['remaining'] for g in active),reached=sum(g['status']=='reached' for g in active))


def create(db,wid,uid,data):
    lock(db,wid);fp=fingerprint(data)
    existing=db.scalar(select(Goal).where(Goal.workspace_id==wid,Goal.idempotency_key==str(data.idempotency_key)))
    if existing:
        if existing.fingerprint!=fp:raise HTTPException(409,'รหัสเป้าหมายถูกใช้กับข้อมูลอื่นแล้ว')
        return {'id':existing.id}
    if db.scalar(select(func.count()).select_from(Goal).where(Goal.workspace_id==wid))>=MAX_GOALS:
        raise HTTPException(409,'พื้นที่นี้มีเป้าหมายครบ 500 รายการแล้ว')
    goal=Goal(workspace_id=wid,created_by=uid,name=data.name,target=data.target,due_on=data.due_on.isoformat() if data.due_on else None,
              idempotency_key=str(data.idempotency_key),fingerprint=fp)
    db.add(goal);db.flush();return {'id':goal.id}


def check_version(goal,version):
    if goal.version!=version:raise HTTPException(409,'ข้อมูลเปลี่ยนแล้ว กรุณาปิดฟอร์ม โหลดใหม่ และเปิดอีกครั้ง')


def edit(db,wid,gid,data):
    lock(db,wid);goal=get_scoped(db,Goal,wid,gid);check_version(goal,data.version)
    if goal.archived:raise HTTPException(409,'เปิดใช้เป้าหมายอีกครั้งก่อนแก้ไข')
    goal.name=data.name;goal.target=data.target;goal.due_on=data.due_on.isoformat() if data.due_on else None;goal.version+=1
    db.flush();return goal_json(goal,amount(db,wid,gid))


def archive(db,wid,gid,data):
    lock(db,wid);goal=get_scoped(db,Goal,wid,gid);check_version(goal,data.version)
    goal.archived=int(data.archived);goal.version+=1;db.flush()
    return goal_json(goal,amount(db,wid,gid))


def movement_json(m):
    return {k:getattr(m,k) for k in ('id','goal_id','signed_amount','note','occurred_on','created_at','created_by')}


def allocate(db,wid,uid,gid,data):
    lock(db,wid);goal=get_scoped(db,Goal,wid,gid);fp=fingerprint(data,goal_id=gid)
    existing=db.scalar(select(GoalMovement).where(GoalMovement.workspace_id==wid,GoalMovement.idempotency_key==str(data.idempotency_key)))
    if existing:
        if existing.fingerprint!=fp:raise HTTPException(409,'รหัสจัดสรรถูกใช้กับข้อมูลอื่นแล้ว')
        return movement_json(existing)
    if goal.archived:raise HTTPException(409,'เปิดใช้เป้าหมายอีกครั้งก่อนจัดสรร')
    if data.occurred_on>today():raise HTTPException(422,'วันที่จัดสรรต้องไม่เกินวันนี้')
    signed=data.amount if data.kind=='add' else -data.amount
    total=amount(db,wid,gid)+signed
    if total<0:raise HTTPException(409,'นำออกได้ไม่เกินยอดที่จัดสรรไว้')
    if total>MAX_AMOUNT:raise HTTPException(422,'ยอดจัดสรรรวมต้องไม่เกิน 1,000,000,000 บาทต่อเป้าหมาย')
    movement=GoalMovement(workspace_id=wid,goal_id=gid,signed_amount=signed,note=data.note,occurred_on=data.occurred_on.isoformat(),
                          created_by=uid,idempotency_key=str(data.idempotency_key),fingerprint=fp)
    db.add(movement);goal.version+=1;db.flush();return movement_json(movement)


def movements(db,wid,gid,page):
    get_scoped(db,Goal,wid,gid)
    conditions=[GoalMovement.workspace_id==wid,GoalMovement.goal_id==gid]
    total=db.scalar(select(func.count()).select_from(GoalMovement).where(*conditions))
    rows=db.scalars(select(GoalMovement).where(*conditions).order_by(GoalMovement.created_at.desc(),GoalMovement.id).offset((page-1)*30).limit(30)).all()
    return dict(items=[movement_json(m) for m in rows],total=total,page=page,page_size=30)
