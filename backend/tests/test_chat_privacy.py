import uuid,io
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from sqlalchemy import select,update,func
from app.db import SessionLocal
from app.models import Conversation,Message,Job,Attachment,Proposal,ChatPreference,Membership,now
from app.worker import cleanup_once,run_once
from app.bootstrap import create_user
from fastapi.testclient import TestClient
from app.main import app

def room(c,w,**kw):
    r=c.post(f'/workspaces/{w}/conversations',json=kw);assert r.status_code==200;return r.json()['id']
def age(cid,days):
    with SessionLocal.begin() as db:db.execute(update(Conversation).where(Conversation.id==cid).values(created_at=now()-days*86400,updated_at=now()-days*86400))
def image():
    out=io.BytesIO();Image.new('RGB',(30,30),(80,120,100)).save(out,format='PNG');return out.getvalue()
def test_temporary_hidden_expired_inaccessible_and_no_model(actor,monkeypatch):
    c,w,u=actor;cid=room(c,w,temporary=True);b=f'/workspaces/{w}'
    assert c.get(b+'/conversations').json()==[]
    assert c.post(b+f'/conversations/{cid}/messages',json={'text':'hello temporary'}).status_code==200
    age(cid,1)
    assert c.get(b+f'/conversations/{cid}/messages').status_code==404
    assert c.post(b+f'/conversations/{cid}/messages',json={'text':'too late'}).status_code==404
    monkeypatch.setattr('app.ai.call_model',lambda *a:(_ for _ in ()).throw(AssertionError('expired room called model')))
    while run_once():pass
    with SessionLocal() as db:
        j=db.scalar(select(Job).where(Job.workspace_id==w));assert j.error=='conversation_expired'
    assert cleanup_once()>=1
    with SessionLocal() as db:assert db.get(Conversation,cid) is None and not db.scalar(select(Message.id).where(Message.conversation_id==cid))

def test_retention_personal_workspace_scope_and_touch(actor):
    c,w,u=actor;cid=room(c,w);age(cid,8);b=f'/workspaces/{w}'
    assert c.get(b+'/chat-preferences').json()=={'retention_days':0}
    assert len(c.get(b+'/conversations').json())==1
    assert c.put(b+'/chat-preferences',json={'retention_days':1}).status_code==422
    assert c.put(b+'/chat-preferences',json={'retention_days':7}).status_code==200
    assert c.get(b+'/conversations').json()==[]
    assert c.get(b+f'/conversations/{cid}/messages').status_code==404
    # Before purge, extending retention can keep a room; purged rooms never return.
    c.put(b+'/chat-preferences',json={'retention_days':30})
    assert c.post(b+f'/conversations/{cid}/messages',json={'text':'new activity'}).status_code==200
    c.put(b+'/chat-preferences',json={'retention_days':7});cleanup_once()
    assert c.get(b+f'/conversations/{cid}/messages').status_code==200
    with SessionLocal.begin() as db:
        bob=create_user(db,uuid.uuid4().hex+'@test.local','test-private-password');db.add(Membership(user_id=bob.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as other:
        other.post('/auth/login',json={'email':bob.email,'password':'test-private-password'})
        assert other.get(b+'/chat-preferences').json()=={'retention_days':0}
        theirs=room(other,w);age(theirs,100)
        age(cid,8);cleanup_once()
        assert other.get(b+f'/conversations/{theirs}/messages').status_code==200
        assert c.get(b+f'/conversations/{theirs}/messages').status_code==404
    assert c.get(b+f'/conversations/{cid}/messages').status_code==404

def test_cleanup_unshared_image_pending_job_and_access(actor):
    c,w,u=actor;cid=room(c,w,temporary=True);b=f'/workspaces/{w}'
    r=c.post(b+f'/conversations/{cid}/images',files={'file':('private.png',image(),'image/png')});assert r.status_code==200;aid=r.json()['attachment_id'];age(cid,1)
    assert c.get(b+'/attachments/'+aid).status_code==404
    cleanup_once()
    with SessionLocal() as db:
        assert db.get(Attachment,aid) is None
        assert not db.scalar(select(Job.id).where(Job.workspace_id==w))
    assert c.get(b+'/transactions').json()==[]

def test_shared_inbox_image_preserved_after_chat_delete(actor):
    c,w,u=actor;cid=room(c,w,temporary=True);b=f'/workspaces/{w}'
    r=c.post(b+f'/conversations/{cid}/images',files={'file':('receipt.png',image(),'image/png')});aid=r.json()['attachment_id']
    # Explicitly sharing evidence in Inbox is independent of private chat processing.
    with SessionLocal.begin() as db:db.add(Proposal(workspace_id=w,attachment_id=aid,description='หลักฐานที่แชร์',status='pending'))
    while run_once():pass
    proposals=c.get(b+'/proposals').json();assert len(proposals)==1
    age(cid,1);cleanup_once()
    assert c.get(b+'/attachments/'+aid).status_code==200
    assert c.get(b+'/proposals').json()==proposals
    with SessionLocal() as db:assert db.get(Attachment,aid) is not None

def test_delete_one_room_preserves_duplicate_image_other_room(actor):
    c,w,u=actor;one=room(c,w);two=room(c,w);b=f'/workspaces/{w}'
    first=c.post(b+f'/conversations/{one}/images',files={'file':('one.png',image(),'image/png')}).json()
    second=c.post(b+f'/conversations/{two}/images',files={'file':('two.png',image(),'image/png')}).json()
    assert first['attachment_id']==second['attachment_id']
    assert c.delete(b+f'/conversations/{one}').status_code==200
    assert c.get(b+'/attachments/'+first['attachment_id']).status_code==200
    assert c.delete(b+f'/conversations/{two}').status_code==200
    with SessionLocal() as db:assert db.get(Attachment,first['attachment_id']) is None

def test_pg_concurrent_purge_once(actor,pg_only):
    c,w,u=actor;cid=room(c,w,temporary=True);age(cid,2)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:cleanup_once(),range(2)))
    assert sum(results)==1
    with SessionLocal() as db:assert db.get(Conversation,cid) is None

def test_db_conversation_checks_preserved(actor):
    import pytest
    from sqlalchemy.exc import DBAPIError
    c,w,u=actor;cid=room(c,w)
    for values in ({'privacy':'unknown'},{'temporary':2}):
        with pytest.raises(DBAPIError):
            with SessionLocal.begin() as db:db.execute(update(Conversation).where(Conversation.id==cid).values(**values))
