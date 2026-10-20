"""Owner workspace lifecycle; immutable financial history is never purged."""
from sqlalchemy import select,func,delete
from fastapi import HTTPException
from . import models as m



def managed(db,wid,uid):
    ws=db.scalar(select(m.Workspace).where(m.Workspace.id==wid).with_for_update().execution_options(populate_existing=True))
    member=db.get(m.Membership,(uid,wid))
    if not ws or not member:raise HTTPException(404,'ไม่พบพื้นที่')
    if member.role!='owner':raise HTTPException(403,'เฉพาะเจ้าของพื้นที่')
    return ws


def version(ws,data):
    if ws.version!=data.version:raise HTTPException(409,'พื้นที่นี้เปลี่ยนไปแล้ว กรุณาเปิดข้อมูลล่าสุด')


CONTENT=(m.StatementRow,m.StatementImport,m.AIConnection,m.AssistantPreference,m.AIUsagePolicy,m.AIUsage,m.Entry,m.Proposal,m.Attachment,m.Conversation,m.Job,m.Provider,m.LinkCode,m.TelegramLink,m.Budget,m.EntryRevision,m.Goal,m.GoalMovement,m.RecurringRule,m.RecurringOccurrence,m.Invitation,m.MembershipEvent,m.ChatPreference,m.ChatAction,m.AssistantChange)
DEFAULTS={('เงินสด','asset'),('ยอดตั้งต้น','equity'),('อาหารและเครื่องดื่ม','expense'),('เดินทาง','expense'),('อื่น ๆ','expense'),('เงินเดือน','income')}


def default_accounts(rows):return len(rows)==len(DEFAULTS) and set(rows)==DEFAULTS


def empty(db,wid,uid):
    if db.scalar(select(func.count()).select_from(m.Membership).where(m.Membership.workspace_id==wid))!=1:return False
    if not default_accounts(db.execute(select(m.Account.name,m.Account.kind).where(m.Account.workspace_id==wid)).all()):return False
    for model in CONTENT:
        if db.scalar(select(model).where(model.workspace_id==wid).limit(1)) is not None:return False
    return True


def listing(db,uid):
    rows=db.execute(select(m.Workspace,m.Membership).join(m.Membership).where(m.Membership.user_id==uid).order_by(m.Workspace.archived_at.is_not(None),m.Workspace.name,m.Workspace.id)).all()
    ids=[w.id for w,_ in rows]
    if not ids:return []
    counts=dict(db.execute(select(m.Membership.workspace_id,func.count()).where(m.Membership.workspace_id.in_(ids)).group_by(m.Membership.workspace_id)).all())
    entries=dict(db.execute(select(m.Entry.workspace_id,func.count()).where(m.Entry.workspace_id.in_(ids)).group_by(m.Entry.workspace_id)).all())
    occupied=set()
    for model in CONTENT:occupied.update(db.scalars(select(model.workspace_id).where(model.workspace_id.in_(ids)).distinct()))
    accounts={wid:[] for wid in ids}
    for wid,name,kind in db.execute(select(m.Account.workspace_id,m.Account.name,m.Account.kind).where(m.Account.workspace_id.in_(ids))):accounts[wid].append((name,kind))
    return [dict(id=w.id,name=w.name,role=member.role,version=w.version,archived=w.archived_at is not None,
                 members=counts.get(w.id,0),entries=entries.get(w.id,0),
                 can_delete=member.role=='owner' and counts.get(w.id)==1 and w.id not in occupied and default_accounts(accounts[w.id])) for w,member in rows]


def rename(db,wid,uid,data):
    ws=managed(db,wid,uid);version(ws,data)
    ws.name=data.name;ws.version+=1;db.flush();return {'ok':True}


def archive(db,wid,uid,data):
    ws=managed(db,wid,uid);version(ws,data)
    if data.confirm_name!=ws.name:raise HTTPException(422,'กรุณาพิมพ์ชื่อพื้นที่ให้ตรงเพื่อยืนยัน')
    ws.archived_at=m.now() if data.archived else None;ws.version+=1
    # Workers, SSE, bot and invite consumption all recheck archived state.
    # Keep pending jobs and scheduling state: processing resumes on restore.
    db.flush();return {'ok':True}


def remove(db,wid,uid,data):
    ws=managed(db,wid,uid);version(ws,data)
    if data.confirm_name!=ws.name:raise HTTPException(422,'กรุณาพิมพ์ชื่อพื้นที่ให้ตรงเพื่อยืนยัน')
    if not empty(db,wid,uid):raise HTTPException(409,'พื้นที่มีข้อมูล สมาชิก หรือประวัติแล้ว ใช้เก็บเข้าคลังเพื่อรักษาข้อมูล')
    db.execute(delete(m.Account).where(m.Account.workspace_id==wid))
    db.execute(delete(m.Membership).where(m.Membership.workspace_id==wid))
    db.delete(ws);db.flush();return {'ok':True}
