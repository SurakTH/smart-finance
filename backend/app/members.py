"""Workspace membership and email-bound, one-time invitations; no automatic mail."""
import secrets
from sqlalchemy import select,func,delete
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from .models import User,Workspace,Membership,Invitation,MembershipEvent,TelegramLink,LinkCode,now
from .security import digest
from .ledger import get_scoped
from .bootstrap import create_user

MAX_MEMBERS=100
MAX_INVITES=100

def lock(db,wid):
    ws=db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    if not ws or ws.archived_at is not None:raise HTTPException(404,'พื้นที่ถูกเก็บเข้าคลัง หรือไม่พบพื้นที่')

def owner_check(db,wid,uid):
    lock(db,wid)
    member=db.get(Membership,(uid,wid))
    if not member:raise HTTPException(404,'ไม่พบ workspace')
    if member.role!='owner':raise HTTPException(403,'เฉพาะเจ้าของ workspace')


def event(db,wid,actor,email,action,target=None,previous=None,next_role=None):
    db.add(MembershipEvent(workspace_id=wid,actor_id=actor,target_id=target,email=email,action=action,previous_role=previous,next_role=next_role))


def roster(db,wid,uid):
    return [dict(user_id=u.id,email=u.email,role=m.role,me=u.id==uid) for u,m in db.execute(select(User,Membership).join(Membership,Membership.user_id==User.id).where(Membership.workspace_id==wid).order_by(Membership.role.desc(),User.email))]


def invitations(db,wid):
    return [dict(id=i.id,email=i.email,mode=i.mode,status='expired' if i.status=='pending' and i.expires<=now() else i.status,expires=i.expires) for i in db.scalars(select(Invitation).where(Invitation.workspace_id==wid).order_by(( (Invitation.status=='pending') & (Invitation.expires>now()) ).desc(),Invitation.created_at.desc(),Invitation.id).limit(100))]


def invite(db,wid,uid,email,mode='shared'):
    owner_check(db,wid,uid)
    if mode=='personal' and db.scalar(select(User.id).where(User.email==email)):raise HTTPException(409,'อีเมลนี้มีบัญชีแล้ว ใช้บัญชีเดิมเข้าสู่ระบบได้')
    if mode=='shared' and db.scalar(select(User.id).join(Membership,Membership.user_id==User.id).where(User.email==email,Membership.workspace_id==wid)):
        raise HTTPException(409,'อีเมลนี้เป็นสมาชิกพื้นที่อยู่แล้ว')
    pending=[Invitation.workspace_id==wid,Invitation.status=='pending',Invitation.expires>now()]
    if db.scalar(select(Invitation.id).where(*pending,Invitation.email==email)):raise HTTPException(409,'มีคำเชิญที่ยังใช้ได้สำหรับอีเมลนี้แล้ว หากรหัสหายให้ยกเลิกแล้วสร้างใหม่')
    if db.scalar(select(func.count()).select_from(Invitation).where(*pending))>=MAX_INVITES:raise HTTPException(409,'มีคำเชิญรอใช้งานครบ 100 รายการแล้ว')
    token=secrets.token_urlsafe(32);i=Invitation(workspace_id=wid,email=email,token_hash=digest(token),created_by=uid,expires=now()+7*86400,mode=mode)
    db.add(i);event(db,wid,uid,email,'invited');db.flush()
    return {'id':i.id,'token':token,'expires':i.expires}


def revoke(db,wid,uid,iid):
    owner_check(db,wid,uid);i=get_scoped(db,Invitation,wid,iid)
    if i.status=='revoked':return {'ok':True}
    if i.status!='pending':raise HTTPException(409,'คำเชิญนี้ถูกใช้แล้ว ให้นำสมาชิกออกแทน')
    i.status='revoked';event(db,wid,uid,i.email,'invite_revoked');db.flush();return {'ok':True}


def locked_invite(db,token):
    i=db.scalar(select(Invitation).where(Invitation.token_hash==digest(token)))
    if not i:raise HTTPException(410,'รหัสเชิญไม่ถูกต้อง ถูกใช้ ยกเลิก หรือหมดอายุแล้ว')
    lock(db,i.workspace_id);db.refresh(i);return i


def pending(i,email):
    if i.status!='pending' or i.expires<=now() or i.email!=email:
        raise HTTPException(410,'รหัสเชิญไม่ถูกต้อง ถูกใช้ ยกเลิก หรือหมดอายุแล้ว')


def preview(db,token,email):
    i=locked_invite(db,token);pending(i,email)
    return {'workspace_name':db.get(Workspace,i.workspace_id).name if i.mode=='shared' else 'บัญชีส่วนตัวของคุณ','email':i.email,'expires':i.expires,'mode':i.mode}


def join(db,user,i):
    if i.mode=='personal':
        i.status='accepted';i.accepted_by=user.id;db.flush();return
    wid=i.workspace_id
    if db.get(Membership,(user.id,wid)):raise HTTPException(409,'คุณเป็นสมาชิกพื้นที่นี้แล้ว')
    if db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id==wid))>=MAX_MEMBERS:raise HTTPException(409,'พื้นที่นี้มีสมาชิกครบ 100 คนแล้ว')
    db.add(Membership(workspace_id=wid,user_id=user.id,role='member'));i.status='accepted';i.accepted_by=user.id
    event(db,wid,user.id,user.email,'joined',user.id,next_role='member');db.flush()


def destination(db,user,i):
    if i.mode=='shared':return i.workspace_id
    wid=db.scalar(select(Workspace.id).join(Membership).where(Membership.user_id==user.id,Membership.role=='owner',Workspace.archived_at.is_(None)).order_by(Workspace.id).limit(1))
    if not wid:
        from .ledger import initialize_workspace
        wid=initialize_workspace(db,user.id,'การเงินส่วนตัว').id
    return wid


def accept(db,user,token):
    i=locked_invite(db,token)
    if i.status=='accepted' and i.accepted_by==user.id and (i.mode=='personal' or db.get(Membership,(user.id,i.workspace_id))):return {'workspace_id':destination(db,user,i)}
    pending(i,user.email);join(db,user,i);return {'workspace_id':destination(db,user,i)}


def register(db,data):
    i=locked_invite(db,data.token);pending(i,data.email)
    if db.scalar(select(User.id).where(User.email==data.email)):raise HTTPException(409,'หากมีบัญชีอยู่แล้ว ให้เข้าสู่ระบบแล้วรับคำเชิญ')
    try:
        with db.begin_nested():
            user=create_user(db,data.email,data.password);join(db,user,i)
    except (IntegrityError,ValueError):
        raise HTTPException(409,'อีเมลนี้มีบัญชีแล้ว ให้เข้าสู่ระบบแล้วรับคำเชิญ')
    return user,destination(db,user,i)


def keep_owner(db,member):
    if member.role=='owner' and db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id==member.workspace_id,Membership.role=='owner'))<=1:
        raise HTTPException(409,'ต้องมีเจ้าของพื้นที่อย่างน้อยหนึ่งคน มอบสิทธิ์เจ้าของให้สมาชิกอื่นก่อน')


def change_role(db,wid,actor,uid,role):
    owner_check(db,wid,actor);m=db.get(Membership,(uid,wid))
    if not m:raise HTTPException(404,'ไม่พบสมาชิก')
    if m.role==role:return {'ok':True}
    if role!='owner':keep_owner(db,m)
    previous=m.role;m.role=role;event(db,wid,actor,db.get(User,uid).email,'role_changed',uid,previous,role)
    db.flush();return {'ok':True}


def remove(db,wid,actor,uid,leaving=False):
    lock(db,wid)
    if not leaving:owner_check(db,wid,actor)
    if leaving and actor!=uid:raise HTTPException(403,'ออกได้เฉพาะบัญชีของตัวเอง')
    m=db.get(Membership,(uid,wid))
    if not m:raise HTTPException(404,'ไม่พบสมาชิก')
    keep_owner(db,m)
    event(db,wid,actor,db.get(User,uid).email,'left' if leaving else 'removed',uid,m.role)
    db.execute(delete(TelegramLink).where(TelegramLink.workspace_id==wid,TelegramLink.user_id==uid))
    db.execute(delete(LinkCode).where(LinkCode.workspace_id==wid,LinkCode.user_id==uid))
    # Keep ledger, audit and the user's private conversations. Queued jobs recheck membership.
    db.delete(m);db.flush();return {'ok':True}


def history(db,wid,page):
    condition=MembershipEvent.workspace_id==wid
    total=db.scalar(select(func.count()).select_from(MembershipEvent).where(condition))
    events=db.execute(select(MembershipEvent,User.email).join(User,User.id==MembershipEvent.actor_id).where(condition).order_by(MembershipEvent.created_at.desc(),MembershipEvent.id).offset((page-1)*30).limit(30))
    return dict(items=[{**{k:getattr(e,k) for k in ('id','actor_id','target_id','email','action','previous_role','next_role','created_at')},'actor_email':actor_email} for e,actor_email in events],total=total,page=page,page_size=30)
