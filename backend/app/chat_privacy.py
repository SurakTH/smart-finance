"""Chat deletion retains shared financial evidence; all mutations hold workspace locks."""
from sqlalchemy import select,delete,and_,or_,func
from .models import Conversation,Message,Job,Attachment,Proposal,ChatPreference,Workspace,ChatAction,now

def live():
    days=func.coalesce(ChatPreference.retention_days,0)
    return or_(and_(Conversation.temporary==1,Conversation.created_at>now()-86400),and_(Conversation.temporary==0,or_(days==0,Conversation.updated_at>now()-days*86400)))

def rooms():
    return select(Conversation).outerjoin(ChatPreference,and_(ChatPreference.user_id==Conversation.user_id,ChatPreference.workspace_id==Conversation.workspace_id))

def expired(db,c):
    pref=db.get(ChatPreference,(c.user_id,c.workspace_id))
    return c.created_at<=now()-86400 if c.temporary else bool(pref and pref.retention_days and c.updated_at<=now()-pref.retention_days*86400)

def serialize(c):return dict(id=c.id,title=c.title,privacy=c.privacy,temporary=bool(c.temporary))

def erase(db,c):
    wid=c.workspace_id
    images=set(db.scalars(select(Message.attachment_id).where(Message.workspace_id==wid,Message.conversation_id==c.id,Message.attachment_id.is_not(None))))
    jobs=db.scalars(select(Job).where(Job.workspace_id==wid).with_for_update()).all()
    remaining=[]
    for j in jobs:
        if j.payload.get('conversation_id')==c.id:
            if j.payload.get('attachment_id'):images.add(j.payload['attachment_id'])
            db.delete(j)
        else:remaining.append(j)
    db.execute(delete(ChatAction).where(ChatAction.workspace_id==wid,ChatAction.conversation_id==c.id))
    db.execute(delete(Message).where(Message.workspace_id==wid,Message.conversation_id==c.id))
    db.delete(c);db.flush()
    for aid in images:
        if db.scalar(select(Proposal.id).where(Proposal.workspace_id==wid,Proposal.attachment_id==aid).limit(1)):continue
        if db.scalar(select(Message.id).where(Message.workspace_id==wid,Message.attachment_id==aid).limit(1)):continue
        if any(j.payload.get('attachment_id')==aid for j in remaining):continue
        db.execute(delete(Attachment).where(Attachment.workspace_id==wid,Attachment.id==aid))

def cleanup(db):
    candidates=db.scalars(rooms().where(~live()).order_by(Conversation.updated_at,Conversation.id).limit(50)).all()
    for wid in sorted({c.workspace_id for c in candidates}):db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    count=0
    for c in candidates:
        # Another cleanup or a user send can win while we wait for the lock.
        fresh=db.scalar(select(Conversation).where(Conversation.id==c.id).execution_options(populate_existing=True))
        if fresh and expired(db,fresh):erase(db,fresh);count+=1
    return count
