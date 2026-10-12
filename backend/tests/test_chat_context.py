import uuid
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Conversation,Message
from app.chat_context import history_and_notes


def test_bounded_history_and_local_notes_are_scoped_and_preserve_source(actor):
    c,w,u=actor
    with SessionLocal.begin() as db:
        room=Conversation(workspace_id=w,user_id=u.id);other=Conversation(workspace_id=w,user_id=u.id)
        db.add_all([room,other]);db.flush();cid=room.id
        for i in range(60):
            db.add(Message(workspace_id=w,conversation_id=cid,role='user' if i%2==0 else 'assistant',
                content=('หัวข้อ '+str(i)+' '+('ก'*5000)),created_at=1000+i))
        db.add(Message(workspace_id=w,conversation_id=other.id,role='user',content='secret-other-room',created_at=1020))
    with SessionLocal() as db:
        history,note=history_and_notes(db,w,cid)
        assert len(history)==6 and sum(min(len(m.content),4000) for m in history)<=24000
        assert len(note)<=2400 and 'secret-other-room' not in note
        assert 'หัวข้อ 52' in note and 'หัวข้อ 0 ' not in note
        assert 'ไม่ใช่ยอดเงินจริง' in note
        assert len(__import__('json').loads(note)['items'])==8
        assert history_and_notes(db,str(uuid.uuid4()),cid)==([],None)
        # Compacting is read-only: original text/history remain available on web.
        assert len(db.scalar(select(Message.content).where(Message.conversation_id==cid)).strip())>5000


def test_short_chat_has_no_notes(actor):
    c,w,u=actor
    with SessionLocal.begin() as db:
        room=Conversation(workspace_id=w,user_id=u.id);db.add(room);db.flush();cid=room.id
        db.add(Message(workspace_id=w,conversation_id=cid,role='user',content='สวัสดี',created_at=100))
    with SessionLocal() as db:
        history,note=history_and_notes(db,w,cid)
        assert len(history)==1 and note is None
