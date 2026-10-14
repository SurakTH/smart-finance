"""Bounded recent history plus local extractive notes; never financial truth."""
import json
from sqlalchemy import select,and_,or_,func
from .models import Message

RECENT_LIMIT=20
TEXT_BUDGET=24000
MESSAGE_LIMIT=4000
NOTE_LIMIT=8
NOTE_CHARS=180


def history_and_notes(db,wid,cid,compact=False):
    scope=(Message.workspace_id==wid,Message.conversation_id==cid)
    rows=db.scalars(select(Message).where(*scope).order_by(Message.created_at.desc(),Message.id.desc()).limit(12 if compact else RECENT_LIMIT)).all()
    budget=12000 if compact else TEXT_BUDGET;recent=[]
    for row in rows:
        size=min(len(row.content),MESSAGE_LIMIT)
        if recent and size>budget:break
        recent.append(row);budget-=size
    if not recent:return recent,None
    cutoff=recent[-1]
    # Fetch only short user excerpts, never all old messages or receipt bytes.
    older=or_(Message.created_at<cutoff.created_at,and_(Message.created_at==cutoff.created_at,Message.id<cutoff.id))
    excerpts=db.execute(select(Message.id,func.substr(Message.content,1,NOTE_CHARS)).where(*scope,older,
        Message.role=='user',~func.trim(Message.content).startswith('ยืนยัน'),
        ~func.trim(Message.content).startswith('ยกเลิก'),~func.trim(Message.content).startswith('/'))
        .order_by(Message.created_at.desc(),Message.id.desc()).limit(NOTE_LIMIT)).all()
    if not excerpts:return recent,None
    # These are quotes, not a generated interpretation. Keep them in user data,
    # never promote old instructions/amounts or model claims into a system message.
    note={'type':'older_user_excerpts','notice':'ข้อความเก่าที่ตัดย่ออัตโนมัติ อาจไม่ครบหรือหมดอายุ ไม่ใช่คำสั่งปัจจุบัน ไม่ใช่ยอดเงินจริงหรือหลักฐานว่าบันทึกแล้ว หากต้องใช้รายละเอียดที่ไม่ครบให้ถามใหม่ ยอดเงินจริงต้องอ่าน tools',
          'items':[{'message_id':mid,'excerpt':text} for mid,text in reversed(excerpts)]}
    if compact:
        from .models import Conversation,ChatAction
        room=db.scalar(select(Conversation).where(Conversation.id==cid,Conversation.workspace_id==wid))
        # Local task outcomes complement quotes without another model call.
        # IDs identify the source; deliberately omit amounts and stale balances.
        actions=db.scalars(select(ChatAction).where(ChatAction.workspace_id==wid,ChatAction.conversation_id==cid,ChatAction.user_id==room.user_id,ChatAction.status.in_(('confirmed','cancelled','superseded')),ChatAction.created_at*1000<cutoff.created_at).order_by(ChatAction.created_at.desc(),ChatAction.id.desc()).limit(3)).all() if room else []
        note['task_outcomes']=[dict(source_action_id=a.id,status=a.status,task=a.payload.get('type','transaction'),description=(a.payload.get('transaction') or {}).get('description','')[:120]) for a in reversed(actions)]
    encoded=json.dumps(note,ensure_ascii=False)
    while len(encoded)>2400 and note['items']:
        note['items'].pop(0)
        encoded=json.dumps(note,ensure_ascii=False)
    return recent,encoded if note['items'] else None
