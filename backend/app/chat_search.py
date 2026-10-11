"""Literal substring search restricted to live, persistent rooms owned by the caller."""
from sqlalchemy import select,func,or_,and_
from .models import Conversation,Message
from .chat_privacy import rooms,live,serialize

def search(db,wid,uid,q,page):
    q=q.strip()
    match=Message.content.icontains(q,autoescape=True)
    messages=select(Message).where(Message.workspace_id==wid,Message.conversation_id==Conversation.id,match).correlate(Conversation)
    query=rooms().where(Conversation.workspace_id==wid,Conversation.user_id==uid,Conversation.temporary==0,live())
    if q:query=query.where(or_(Conversation.title.icontains(q,autoescape=True),messages.exists()))
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    latest=messages.order_by(Message.created_at.desc(),Message.id.desc()).limit(1)
    mid=latest.with_only_columns(Message.id).scalar_subquery() if q else None
    content=latest.with_only_columns(Message.content).scalar_subquery() if q else None
    query=query.order_by(Conversation.updated_at.desc(),Conversation.id).offset((page-1)*20).limit(20)
    items=[]
    if q:
        for c,message_id,text in db.execute(query.add_columns(mid,content)):
            snippet=None
            if text:
                start=max(0,text.casefold().find(q.casefold())-35)
                snippet=('…' if start else '')+text[start:start+160]+('…' if len(text)>start+160 else '')
            items.append({**serialize(c),'message_id':message_id,'snippet':snippet})
    else:items=[{**serialize(c),'message_id':None,'snippet':None} for c in db.scalars(query)]
    return dict(items=items,total=total,page=page,page_size=20)

def window(db,wid,cid,focus=None):
    base=select(Message).where(Message.workspace_id==wid,Message.conversation_id==cid)
    if not focus:
        return list(reversed(db.scalars(base.order_by(Message.created_at.desc(),Message.id.desc()).limit(500)).all()))
    from fastapi import HTTPException
    target=db.scalar(base.where(Message.id==focus))
    if not target:raise HTTPException(404,'ไม่พบข้อความในห้องนี้')
    before=or_(Message.created_at<target.created_at,and_(Message.created_at==target.created_at,Message.id<target.id))
    after=or_(Message.created_at>target.created_at,and_(Message.created_at==target.created_at,Message.id>target.id))
    previous=list(reversed(db.scalars(base.where(before).order_by(Message.created_at.desc(),Message.id.desc()).limit(50)).all()))
    following=db.scalars(base.where(after).order_by(Message.created_at,Message.id).limit(50)).all()
    return previous+[target]+following

def page(db,wid,cid,before=None,after=None):
    from fastapi import HTTPException
    if before and after:raise HTTPException(422,'เลือก cursor ได้ครั้งละทิศทางเดียว')
    base=select(Message).where(Message.workspace_id==wid,Message.conversation_id==cid)
    cursor=before or after
    target=db.scalar(base.where(Message.id==cursor)) if cursor else None
    if cursor and not target:raise HTTPException(404,'ไม่พบข้อความในห้องนี้')
    older=lambda m:or_(Message.created_at<m.created_at,and_(Message.created_at==m.created_at,Message.id<m.id))
    newer=lambda m:or_(Message.created_at>m.created_at,and_(Message.created_at==m.created_at,Message.id>m.id))
    query=base.where(older(target)) if before else base.where(newer(target)) if after else base
    rows=db.scalars(query.order_by(Message.created_at,Message.id).limit(50) if after else query.order_by(Message.created_at.desc(),Message.id.desc()).limit(50)).all()
    if not after:rows=list(reversed(rows))
    return {'items':[dict(id=m.id,role=m.role,content=m.content,attachment_id=m.attachment_id,references=m.references) for m in rows],
            'has_older':bool(rows and db.scalar(base.where(older(rows[0])).with_only_columns(Message.id).limit(1))),
            'has_newer':bool(rows and db.scalar(base.where(newer(rows[-1])).with_only_columns(Message.id).limit(1)))}
