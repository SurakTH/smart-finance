"""Deterministic due reminders: generate proposals only, never post ledger entries."""
import calendar
import time
from datetime import date,timedelta
from sqlalchemy import select,func,or_,case
from fastapi import HTTPException
from .models import Workspace,Account,Proposal,RecurringRule,RecurringOccurrence
from .ledger import get_scoped
from .goals import fingerprint,check_version
from .reporting import today

MAX_RULES=200
MAX_PENDING=100
BATCH_SIZE=25
PER_RULE=10


def advance(value,frequency,anchor):
    if frequency!='monthly':return value+timedelta(days=1 if frequency=='daily' else 7)
    year=value.year+(value.month==12);month=value.month%12+1
    return date(year,month,min(anchor,calendar.monthrange(year,month)[1]))


def lock(db,wid):db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())


def validate_accounts(db,wid,data):
    a=get_scoped(db,Account,wid,str(data.account_id));c=get_scoped(db,Account,wid,str(data.category_id))
    if a.kind not in ('asset','liability') or (data.kind=='income' and a.kind!='asset'):
        raise HTTPException(422,'บัญชีไม่ตรงกับประเภทรายการ')
    if c.kind!=data.kind:raise HTTPException(422,'หมวดหมู่ไม่ตรงกับประเภทรายการ')


def row(rule):
    ended=bool(rule.end_on and rule.next_on>rule.end_on)
    return {**{key:getattr(rule,key) for key in ('id','description','kind','amount','account_id','category_id','frequency','start_on','next_on','end_on','version')},
            'paused':bool(rule.paused),'status':'ended' if ended else 'paused' if rule.paused else 'due' if rule.next_on<=today().isoformat() else 'active'}


def rules(db,wid):
    return [row(r) for r in db.scalars(select(RecurringRule).where(RecurringRule.workspace_id==wid).order_by(RecurringRule.paused,RecurringRule.next_on,RecurringRule.id))]


def create(db,wid,uid,data):
    lock(db,wid);fp=fingerprint(data)
    existing=db.scalar(select(RecurringRule).where(RecurringRule.workspace_id==wid,RecurringRule.idempotency_key==str(data.idempotency_key)))
    if existing:
        if existing.fingerprint!=fp:raise HTTPException(409,'รหัสรายการประจำถูกใช้กับข้อมูลอื่นแล้ว')
        return {'id':existing.id}
    if data.start_on<today():raise HTTPException(422,'วันเริ่มต้นต้องเป็นวันนี้หรือหลังจากนี้')
    if data.start_on.year>9998 or (data.end_on and (data.end_on<data.start_on or data.end_on.year>9998)):
        raise HTTPException(422,'วันสิ้นสุดต้องไม่ก่อนวันเริ่ม และปีต้องไม่เกิน 9998')
    if db.scalar(select(func.count()).select_from(RecurringRule).where(RecurringRule.workspace_id==wid))>=MAX_RULES:
        raise HTTPException(409,'พื้นที่นี้มีรายการประจำครบ 200 รายการแล้ว')
    validate_accounts(db,wid,data)
    rule=RecurringRule(workspace_id=wid,created_by=uid,description=data.description,kind=data.kind,amount=data.amount,
        account_id=str(data.account_id),category_id=str(data.category_id),frequency=data.frequency,start_on=data.start_on.isoformat(),next_on=data.start_on.isoformat(),
        end_on=data.end_on.isoformat() if data.end_on else None,idempotency_key=str(data.idempotency_key),fingerprint=fp)
    db.add(rule);db.flush();return {'id':rule.id}


def edit(db,wid,rid,data):
    lock(db,wid);rule=get_scoped(db,RecurringRule,wid,rid);check_version(rule,data.version);validate_accounts(db,wid,data)
    for key in ('description','kind','amount','account_id','category_id'):setattr(rule,key,str(getattr(data,key)) if key.endswith('_id') else getattr(data,key))
    rule.version+=1;db.flush();return row(rule)


def pause(db,wid,rid,data):
    lock(db,wid);rule=get_scoped(db,RecurringRule,wid,rid);check_version(rule,data.version)
    rule.paused=int(data.paused);rule.version+=1;db.flush();return row(rule)


def generate_due(db,wid=None):
    cutoff=today().isoformat();conditions=[Workspace.archived_at.is_(None),RecurringRule.paused==0,RecurringRule.next_on<=cutoff,or_(RecurringRule.end_on.is_(None),RecurringRule.next_on<=RecurringRule.end_on)]
    if wid is not None:conditions.append(RecurringRule.workspace_id==wid)
    candidates=db.execute(select(RecurringRule.id,RecurringRule.workspace_id).join(Workspace).where(*conditions).order_by(RecurringRule.checked_at,RecurringRule.next_on,RecurringRule.id).limit(BATCH_SIZE)).all()
    created=0;blocked=False
    # Always acquire workspace locks in a consistent order across worker/API calls.
    for workspace in sorted({w for _,w in candidates}):lock(db,workspace)
    for rid,workspace in candidates:
        ws=db.get(Workspace,workspace);db.refresh(ws)
        if ws.archived_at is not None:continue
        rule=get_scoped(db,RecurringRule,workspace,rid)
        # Refresh after waiting for another scheduler, edit or pause operation.
        db.refresh(rule)
        if rule.paused:continue
        rule.checked_at=time.time_ns()//1_000_000
        pending=db.scalar(select(func.count()).select_from(Proposal).where(Proposal.workspace_id==workspace,Proposal.status=='pending'))
        generated=0
        while rule.next_on<=cutoff and (not rule.end_on or rule.next_on<=rule.end_on) and generated<PER_RULE and created<BATCH_SIZE:
            occurrence=db.scalar(select(RecurringOccurrence.id).where(RecurringOccurrence.rule_id==rid,RecurringOccurrence.workspace_id==workspace,RecurringOccurrence.scheduled_on==rule.next_on))
            if not occurrence:
                if pending>=MAX_PENDING:blocked=True;break
                proposal=Proposal(workspace_id=workspace,source='recurring',description=rule.description,amount=rule.amount,kind=rule.kind)
                db.add(proposal);db.flush()
                db.add(RecurringOccurrence(workspace_id=workspace,rule_id=rid,proposal_id=proposal.id,scheduled_on=rule.next_on,account_id=rule.account_id,category_id=rule.category_id));db.flush()
                created+=1;pending+=1
            scheduled=date.fromisoformat(rule.next_on)
            if scheduled.year>=9998:rule.paused=1;break
            rule.next_on=advance(scheduled,rule.frequency,date.fromisoformat(rule.start_on).day).isoformat();rule.version+=1;generated+=1
        db.flush()
        if created>=BATCH_SIZE:break
    remaining=db.scalar(select(func.count()).select_from(RecurringRule).join(Workspace).where(*conditions))
    return {'created':created,'due_rules':remaining,'blocked_by_inbox':blocked}


def proposal_list(db,wid):
    # Due proposals retain their original date/account/category even after editing a rule.
    records=db.execute(select(Proposal,RecurringOccurrence).outerjoin(RecurringOccurrence,(RecurringOccurrence.proposal_id==Proposal.id)&(RecurringOccurrence.workspace_id==Proposal.workspace_id)).where(Proposal.workspace_id==wid).order_by(case((Proposal.status=='pending',0),else_=1),Proposal.created_at.desc(),Proposal.id).limit(100)).all()
    return [dict(id=p.id,description=p.description,amount=p.amount,kind=p.kind,status=p.status,source=p.source,attachment_id=p.attachment_id,
                 occurred_on=o.scheduled_on if o else None,account_id=o.account_id if o else None,category_id=o.category_id if o else None) for p,o in records]


def history(db,wid,rid,page):
    get_scoped(db,RecurringRule,wid,rid)
    conditions=[RecurringOccurrence.workspace_id==wid,RecurringOccurrence.rule_id==rid]
    total=db.scalar(select(func.count()).select_from(RecurringOccurrence).where(*conditions))
    records=db.execute(select(RecurringOccurrence,Proposal).join(Proposal,(Proposal.id==RecurringOccurrence.proposal_id)&(Proposal.workspace_id==RecurringOccurrence.workspace_id)).where(*conditions).order_by(RecurringOccurrence.scheduled_on.desc(),RecurringOccurrence.id).offset((page-1)*30).limit(30)).all()
    return dict(items=[dict(id=o.id,scheduled_on=o.scheduled_on,proposal_id=p.id,status=p.status,description=p.description,kind=p.kind,amount=p.amount,entry_id=p.entry_id) for o,p in records],page=page,page_size=30,total=total)
