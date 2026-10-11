import io
import uuid
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import ai, config
from app.main import app
from app.bootstrap import create_user
from app.db import SessionLocal
from app.models import Job, Membership, Provider
from app.worker import run_once


def receipt():
    out=io.BytesIO()
    Image.new('RGB',(64,64),'white').save(out,format='PNG')
    return ('receipt.png',out.getvalue(),'image/png')


def test_chat_image_history_private_fallback_and_duplicate(actor,monkeypatch):
    c,w,u=actor
    root=f'/workspaces/{w}'
    cid=c.post(root+'/conversations',json={'privacy':'private'}).json()['id']
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='openai',model='never-call',task='extract'))
    monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',True)
    def forbidden(*args,**kwargs): raise AssertionError('Private image sent externally')
    monkeypatch.setattr(ai.httpx,'Client',forbidden)
    r=c.post(root+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'เลขอ้างอิง 999999 ไม่ใช่ยอดเงิน','privacy':'standard'})
    assert r.status_code==200
    aid=r.json()['attachment_id']
    rows=c.get(root+f'/conversations/{cid}/messages').json()
    assert rows[0]['attachment_id']==aid and '999999' in rows[0]['content']
    assert c.get(root+f'/attachments/{aid}').headers['content-type']=='image/jpeg'
    with SessionLocal() as db:
        job=db.get(Job,r.json()['job_id'])
        assert job.payload['privacy']=='private' and job.task=='extract'
    while run_once(): pass
    proposals=c.get(root+'/proposals').json()
    assert len(proposals)==1 and proposals[0]['amount'] is None
    assert proposals[0]['status']=='pending'
    assert 'ยังไม่ได้อ่านยอด' in c.get(root+f'/conversations/{cid}/messages').json()[-1]['content']
    assert c.get(root+'/transactions').json()==[]
    c.post(root+f'/conversations/{cid}/images',files={'file':receipt()})
    while run_once(): pass
    assert len(c.get(root+'/proposals').json())==1
    assert 'ไม่สร้างรายการซ้ำ' in c.get(root+f'/conversations/{cid}/messages').json()[-1]['content']


def test_image_access_requires_owner_until_shared_inbox_and_delete_cancels(actor):
    c,w,u=actor;root=f'/workspaces/{w}'
    cid=c.post(root+'/conversations',json={}).json()['id']
    r=c.post(root+f'/conversations/{cid}/images',files={'file':receipt()}).json()
    with SessionLocal.begin() as db:
        bob=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(user_id=bob.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as other:
        other.post('/auth/login',json={'email':bob.email,'password':'secure-test-password'})
        assert other.get(root+f'/attachments/{r["attachment_id"]}').status_code==404
        assert other.post(root+f'/conversations/{cid}/images',files={'file':receipt()}).status_code==404
        assert c.delete(root+f'/conversations/{cid}').status_code==200
        while run_once(): pass
        assert c.get(root+'/proposals').json()==[]
        assert c.get(root+f'/attachments/{r["attachment_id"]}').status_code==404


def test_invalid_chat_image_is_atomic_and_cross_workspace_denied(actor):
    c,w,u=actor;root=f'/workspaces/{w}'
    cid=c.post(root+'/conversations',json={}).json()['id']
    route=root+f'/conversations/{cid}/images'
    assert c.post(route,files={'file':('bad.png',b'not an image','image/png')}).status_code==422
    assert c.post(route,files={'file':receipt()},data={'text':'a'*4001}).status_code==422
    assert c.get(root+f'/conversations/{cid}/messages').json()==[]
    assert c.get(root+'/jobs').json()==[]
    other=c.post('/workspaces',json={'name':'Second'}).json()['id']
    assert c.post(f'/workspaces/{other}/conversations/{cid}/images',files={'file':receipt()}).status_code==404


def test_vision_extraction_caption_and_inbox_manual_only(actor,monkeypatch):
    import json
    from test_ai_security import FakeResponse, install_model
    c,w,u=actor;root=f'/workspaces/{w}'
    install_model(monkeypatch,w)
    calls=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def stream(self,method,url,**kwargs):
            calls.append(kwargs['json']['messages'])
            return FakeResponse(json.dumps({'proposals':[{'description':'ข้าว','amount':5000,'kind':'expense','auto_post':True}]}))
    monkeypatch.setattr(ai.httpx,'Client',Client)
    cid=c.post(root+'/conversations',json={}).json()['id']
    c.post(root+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'มื้อกลางวัน'})
    while run_once(): pass
    parts=calls[0][-1]['content']
    assert 'มื้อกลางวัน' in parts[0]['text']
    assert parts[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    proposal=c.get(root+'/proposals').json()[0]
    assert proposal['amount']==5000 and proposal['status']=='pending'
    assert c.get(root+'/transactions').json()==[]
