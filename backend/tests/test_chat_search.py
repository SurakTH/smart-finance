import uuid
from sqlalchemy import select,update
from app.models import Message,Conversation,Membership,now
from app.db import SessionLocal
from app.bootstrap import create_user
from fastapi.testclient import TestClient
from app.main import app

def room(c,w,**kw):return c.post(f'/workspaces/{w}/conversations',json=kw).json()['id']
def put(w,cid,text,stamp=1):
    with SessionLocal.begin() as db:
        m=Message(workspace_id=w,conversation_id=cid,role='user',content=text,created_at=stamp);db.add(m);db.flush();return m.id

def search(c,w,q='',page=1):
    r=c.post(f'/workspaces/{w}/conversations/search',json={'q':q,'page':page});assert r.status_code==200;return r.json()

def test_search_literal_case_snippet_and_pagination(actor):
    c,w,u=actor;cid=room(c,w,title='ค่าใช้จ่ายบ้าน');mid=put(w,cid,'x'*200+' Grocery ค่าไฟ 100%_\\ '+ 'y'*200)
    for q in ['ค่าไฟ','gRoCeRy','100%_\\']:
        data=search(c,w,q);assert data['total']==1
        row=data['items'][0];assert row['id']==cid and row['message_id']==mid and len(row['snippet'])<=162
    assert search(c,w,'ค่าใช้จ่าย')['items'][0]['snippet'] is None
    assert search(c,w,"' OR 1=1 --")['total']==0
    for _ in range(21):room(c,w)
    assert search(c,w)['total']==22 and len(search(c,w)['items'])==20 and len(search(c,w,page=2)['items'])==2
    assert search(c,w,page=999)['items']==[]
    assert c.post(f'/workspaces/{w}/conversations/search',json={'q':'x'*101}).status_code==422

def test_search_ownership_expiry_temporary_and_rename(actor):
    c,w,u=actor;cid=room(c,w,title='mine');temp=room(c,w,temporary=True);put(w,temp,'private needle')
    expired=room(c,w);put(w,expired,'private needle')
    with SessionLocal.begin() as db:
        bob=create_user(db,uuid.uuid4().hex+'@test.local','test-search-password');foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==bob.id));db.add(Membership(user_id=bob.id,workspace_id=w,role='member'))
        db.execute(update(Conversation).where(Conversation.id==expired).values(updated_at=now()-8*86400))
    c.put(f'/workspaces/{w}/chat-preferences',json={'retention_days':7})
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as other:
        other.post('/auth/login',json={'email':bob.email,'password':'test-search-password'});theirs=room(other,w);put(w,theirs,'private needle')
        assert search(c,w,'needle')['total']==0
        assert search(other,w,'needle')['total']==1
        assert c.post(f'/workspaces/{foreign}/conversations/search',json={}).status_code==404
        assert other.post(f'/workspaces/{w}/conversations/{cid}/rename',json={'title':'stolen'}).status_code==404
    path=f'/workspaces/{w}/conversations/{cid}/rename'
    assert c.post(path,json={'title':'   '}).status_code==422
    assert c.post(path,json={'title':'  <script> renamed  '}).json()['title']=='<script> renamed'
    assert search(c,w,'renamed')['items'][0]['id']==cid
    assert c.post(f'/workspaces/{w}/conversations/{expired}/rename',json={'title':'revive'}).status_code==404
    assert c.post(f'/workspaces/{w}/conversations/{temp}/rename',json={'title':'persist'}).status_code==409

def test_focus_old_message_and_latest_window(actor):
    c,w,u=actor;cid=room(c,w);ids=[]
    with SessionLocal.begin() as db:
        for i in range(650):
            m=Message(workspace_id=w,conversation_id=cid,role='user',content='old needle' if i==30 else 'message '+str(i),created_at=i);db.add(m);db.flush();ids.append(m.id)
    base=f'/workspaces/{w}/conversations/{cid}/messages'
    latest=c.get(base).json();assert len(latest)==500 and latest[-1]['id']==ids[-1] and ids[30] not in [m['id'] for m in latest]
    hit=search(c,w,'old needle')['items'][0];assert hit['message_id']==ids[30]
    window=c.get(base+'?focus_id='+ids[30]).json();assert len(window)==81 and window[30]['id']==ids[30]
    second=room(c,w);foreign=put(w,second,'other')
    assert c.get(base+'?focus_id='+foreign).status_code==404
    with SessionLocal() as db:assert db.get(Conversation,cid).updated_at>now()-10
