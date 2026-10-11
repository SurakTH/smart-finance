import json
import time
import threading
import uuid
import httpx
import pytest
from sqlalchemy import select
from app import ai,ai_settings
from app.db import SessionLocal
from app.models import Job,ChatAction,ChatGeneration,Membership,AIUsage
from app.worker import run_once
from test_chat_actions import setup,say
from test_secretary import provider,transport,draft,suggestion


def pending(c,b,cid,text='ช่วยจดกาแฟ 80 บาทหน่อย'):
    response=c.post(b+f'/conversations/{cid}/messages',json={'text':text});assert response.status_code==200
    return response.json()['job_id']

def stop(c,b,cid,jid):return c.post(b+f'/conversations/{cid}/jobs/{jid}/stop',json={})

def test_queued_stop_is_durable_idempotent_and_never_calls_model(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w)
    transport(monkeypatch,lambda req:pytest.fail('Cancelled job reached model'))
    jid=pending(c,b,cid);assert jid
    response=stop(c,b,cid,jid);assert response.status_code==200 and response.json()['status']=='cancelled'
    assert stop(c,b,cid,jid).json()['status']=='cancelled'
    while run_once():pass
    with SessionLocal() as db:
        job=db.get(Job,jid);assert job.status=='cancelled' and job.payload=={}
        assert db.get(ChatGeneration,jid).stop_requested
        assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
    messages=c.get(b+f'/conversations/{cid}/messages').json()
    assert sum('หยุดคำตอบแล้ว' in m['content'] for m in messages)==1
    say(c,b,cid,'ยืนยัน');assert c.get(b+'/transactions').json()==[]


def test_stop_while_worker_holds_job_and_workspace_drops_late_draft(actor,monkeypatch,pg_only):
    c,w,u,b,cid=setup(actor);provider(w);state={}
    def handler(req):
        before=time.monotonic();response=stop(c,b,cid,state['jid']);elapsed=time.monotonic()-before
        assert response.status_code==200 and response.json()['status']=='stopping' and elapsed<2
        return draft(suggestion(w))
    transport(monkeypatch,handler);state['jid']=pending(c,b,cid)
    while run_once():pass
    with SessionLocal() as db:
        assert db.get(Job,state['jid']).status=='cancelled'
        assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
        # Attempted provider usage survives the cancellation savepoint rollback.
        assert db.scalar(select(AIUsage.id).where(AIUsage.workspace_id==w))
    assert c.get(b+'/transactions').json()==[]
    assert 'หยุดคำตอบแล้ว' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']


def test_silent_thinking_stop_closes_stream_and_rejects_late_text(actor,monkeypatch,pg_only):
    c,w,u,b,cid=setup(actor);provider(w);closed=threading.Event();stopping=[];threads=[];real=httpx.Client
    class Quiet(httpx.SyncByteStream):
        def __iter__(self):
            def request_stop():stopping.append(stop(c,b,cid,jid).json()['status'])
            thread=threading.Thread(target=request_stop);threads.append(thread);thread.start()
            assert closed.wait(3),'Stop did not close a silent response'
            yield b'data: {"choices":[{"delta":{"content":"late text"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        def close(self):closed.set()
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Quiet())),**kw))
    jid=pending(c,b,cid,'สวัสดี ช่วยคุยหน่อย')
    while run_once():pass
    for thread in threads:thread.join(3)
    assert stopping==['stopping'] and closed.is_set()
    with SessionLocal() as db:assert db.get(Job,jid).status=='cancelled'
    messages=c.get(b+f'/conversations/{cid}/messages').json()
    assert not any('late text' in m['content'] for m in messages)


def test_stop_scoped_to_room_owner_and_job_not_other_member(actor):
    from app.bootstrap import create_user
    from app.main import app
    from fastapi.testclient import TestClient
    c,w,u,b,cid=setup(actor)
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password');db.add(Membership(user_id=other.id,workspace_id=w,role='member'))
    provider(w);jid=pending(c,b,cid)
    room=c.post(b+'/conversations',json={}).json()['id']
    assert stop(c,b,room,jid).status_code==404
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        client.post('/auth/login',json={'email':other.email,'password':'secure-test-password'})
        assert stop(client,b,cid,jid).status_code==404
    with SessionLocal() as db:assert db.get(ChatGeneration,jid).stop_requested is False
    assert stop(c,b,cid,str(uuid.uuid4())).status_code==404


def test_completed_generation_stop_returns_done_and_does_not_change_history(actor,monkeypatch):
    from test_secretary import reply
    c,w,u,b,cid=setup(actor);provider(w);transport(monkeypatch,lambda req:reply('สวัสดีค่ะ'))
    jid=pending(c,b,cid,'สวัสดี ช่วยคุยหน่อย')
    while run_once():pass
    before=c.get(b+f'/conversations/{cid}/messages').json()
    assert stop(c,b,cid,jid).json()['status']=='done'
    assert c.get(b+f'/conversations/{cid}/messages').json()==before
    with SessionLocal() as db:assert not db.get(ChatGeneration,jid).stop_requested


def test_provider_error_is_actionable_without_raw_error_and_fallback_still_works(actor,monkeypatch):
    from app.models import Provider
    from test_secretary import reply
    c,w,u,b,cid=setup(actor);first=provider(w)
    with SessionLocal.begin() as db:
        db.get(Provider,first).priority=0
        db.add(Provider(workspace_id=w,kind='ollama',model='backup',task='chat',priority=1,retries=0))
    calls=[];state={'fail_all':False}
    def handler(req):
        if state['fail_all']:return httpx.Response(400,json={'error':'model does not support tools secret-upstream-detail'})
        model=json.loads(req.content)['model'];calls.append(model)
        return reply('ตอบจากตัวสำรองค่ะ') if model=='backup' else httpx.Response(404,json={'error':'model not found secret-upstream-detail'})
    transport(monkeypatch,handler);pending(c,b,cid,'สวัสดี ช่วยคุยหน่อย')
    while run_once():pass
    assert calls==['vision','backup']
    assert 'ตอบจากตัวสำรอง' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    state['fail_all']=True
    pending(c,b,cid,'ช่วยตอบอีกครั้ง')
    while run_once():pass
    text=c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'ไม่รองรับ tools' in text and 'secret-upstream-detail' not in text
    assert c.get(b+'/transactions').json()==[]


def test_queued_room_stop_does_not_wait_for_another_rooms_workspace_lock(actor,monkeypatch,pg_only):
    from test_secretary import reply
    c,w,u,b,cid=setup(actor);provider(w)
    other=c.post(b+'/conversations',json={}).json()['id'];calls=[]
    first=pending(c,b,cid,'คุยกับฉันหน่อย')
    queued=pending(c,b,other,'คุยกับฉันหน่อย')
    def handler(req):
        calls.append(1);before=time.monotonic();response=stop(c,b,other,queued)
        assert response.status_code==200 and response.json()['status']=='cancelled'
        assert time.monotonic()-before<2
        return reply('ห้องแรกตอบตามปกติค่ะ')
    transport(monkeypatch,handler)
    while run_once():pass
    assert calls==[1]
    with SessionLocal() as db:
        assert db.get(Job,first).status=='done'
        assert db.get(Job,queued).status=='cancelled'
    assert 'หยุดคำตอบแล้ว' in c.get(b+f'/conversations/{other}/messages').json()[-1]['content']
