import asyncio,json
from types import SimpleNamespace
import httpx,pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import main,chat_stream,ai
from app.db import SessionLocal
from app.models import Job,Provider,Membership,Session,Workspace
from app.security import digest

def fake_job():return SimpleNamespace(id='job',workspace_id='workspace',task='chat',payload={'conversation_id':'room','privacy':'private'})
def response(parts):return httpx.Response(200,content=('\n\n'.join('data: '+(p if isinstance(p,str) else json.dumps(p)) for p in parts)+'\n\n').encode(),headers={'content-type':'text/event-stream'})
def chunk(text):return {'choices':[{'delta':{'content':text},'finish_reason':None}]}

def test_parser_bounds_finish_and_untrusted_text(monkeypatch):
    events=[];monkeypatch.setattr(chat_stream,'publish',lambda j,k,**kw:events.append((k,kw)))
    assert chat_stream.read_completion(response([chunk('สวัสดี '),chunk('<script>bad</script>'),'[DONE]']),fake_job())=='สวัสดี <script>bad</script>'
    assert [e[1]['text'] for e in events]==['สวัสดี ','สวัสดี <script>bad</script>']
    for parts in ([chunk('unfinished')],[chunk('x'*16001),'[DONE]'],['not-json'],[{'error':{'message':'secret'}}],[[]],[{'choices':[{'delta':{'content':42}}]}]):
        with pytest.raises(ValueError):chat_stream.read_completion(response(parts),fake_job())
    assert chat_stream.read_completion(response([chunk('ok'),{'choices':[{'delta':{},'finish_reason':'stop'}]}]),fake_job())=='ok'

def test_provider_retry_resets_partial(actor,monkeypatch):
    client,wid,user=actor;room=client.post(f'/workspaces/{wid}/conversations',json={}).json()['id']
    client.post(f'/workspaces/{wid}/conversations/{room}/messages',json={'text':'ช่วยอธิบายแนวคิดการจัดเงินทั่วไป'})
    events=[];monkeypatch.setattr(ai,'publish',lambda j,k,**kw:events.append(k));monkeypatch.setattr(chat_stream,'publish',lambda *a,**k:None);monkeypatch.setattr(ai.time,'sleep',lambda _:None)
    real=httpx.Client;calls=[]
    def handler(request):
        body=json.loads(request.content);assert body['stream'] is True;calls.append(body)
        return response([chunk('partial')]) if len(calls)==1 else response([chunk('คำตอบใหม่'),'[DONE]'])
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=wid,kind='ollama',model='test',task='chat',priority=1,encrypted_key=''));db.flush()
        job=db.scalar(select(Job).where(Job.workspace_id==wid))
        output,demo=ai.call_model(db,job)
        assert output=='คำตอบใหม่' and not demo
        job.status='done';job.payload={}
    assert len(calls)==2 and events==['start','start']

def test_authorization_headers_and_expiry(actor,monkeypatch):
    client,wid,user=actor;room=client.post(f'/workspaces/{wid}/conversations',json={}).json()['id'];token=client.cookies.get('sf_session');chat_stream.authorized(token,wid,room)
    async def finite(*args):yield chat_stream.frame({'kind':'ready'})
    monkeypatch.setattr(chat_stream,'events',finite)
    result=client.get(f'/workspaces/{wid}/conversations/{room}/events')
    assert result.status_code==200 and 'text/event-stream' in result.headers['content-type']
    assert result.headers['cache-control']=='no-store' and result.headers['x-accel-buffering']=='no'
    assert client.get(f'/workspaces/foreign/conversations/{room}/events').status_code==404
    with TestClient(main.app,base_url='https://testserver') as anonymous:assert anonymous.get(f'/workspaces/{wid}/conversations/{room}/events').status_code==401
    from app.bootstrap import create_user
    import uuid
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','other-secret-password');db.add(Membership(user_id=other.id,workspace_id=wid,role='member'))
    with TestClient(main.app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as c:
        c.post('/auth/login',json={'email':other.email,'password':'other-secret-password'})
        assert c.get(f'/workspaces/{wid}/conversations/{room}/events').status_code==404
    with SessionLocal.begin() as db:db.delete(db.get(Session,digest(token)))
    with pytest.raises(HTTPException) as error:chat_stream.authorized(token,wid,room)
    assert error.value.status_code==401

def test_generator_rechecks_and_closes_resources(actor,monkeypatch):
    client,wid,user=actor;room=client.post(f'/workspaces/{wid}/conversations',json={}).json()['id'];token=client.cookies.get('sf_session');closed=[]
    class Sub:
        async def subscribe(self,key):assert key==chat_stream.channel(wid,room)
        async def get_message(self,**kw):return {'type':'message','data':json.dumps({'kind':'delta','job_id':'j','text':'ทดสอบ'}).encode()}
        async def aclose(self):closed.append('subscription')
    class Redis:
        def pubsub(self):return Sub()
        async def aclose(self):closed.append('redis')
        @classmethod
        def from_url(cls,*a,**kw):return cls()
    class Request:
        async def is_disconnected(self):return False
    monkeypatch.setattr(chat_stream,'AsyncRedis',Redis)
    async def check():
        stream=chat_stream.events(Request(),token,wid,room)
        assert 'ready' in await anext(stream)
        assert 'ทดสอบ' in await anext(stream)
        with SessionLocal.begin() as db:db.delete(db.get(Session,digest(token)))
        assert 'closed' in await anext(stream)
        with pytest.raises(StopAsyncIteration):await anext(stream)
    asyncio.run(check());assert closed==['subscription','redis']

def test_authorization_does_not_wait_worker_lock(actor,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    client,wid,user=actor;room=client.post(f'/workspaces/{wid}/conversations',json={}).json()['id'];token=client.cookies.get('sf_session')
    with SessionLocal.begin() as db:
        db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
        with ThreadPoolExecutor(1) as pool:pool.submit(chat_stream.authorized,token,wid,room).result(timeout=3)

def test_real_pubsub_previews_before_commit_and_done_after_commit(actor,pg_only,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.worker import run_once
    from app.models import Message
    client,wid,user=actor;room=client.post(f'/workspaces/{wid}/conversations',json={}).json()['id']
    jid=client.post(f'/workspaces/{wid}/conversations/{room}/messages',json={'text':'เล่าแนวคิดการจัดเงินทั่วไปให้ฟังหน่อย'}).json()['job_id']
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=wid,kind='ollama',model='test',task='chat',priority=1,encrypted_key=''))
    release=Event()
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            yield ('data: '+json.dumps(chunk('คำตอบส่วนแรก'))+'\n\n').encode()
            assert release.wait(5)
            yield ('data: '+json.dumps(chunk(' และส่วนท้าย'))+'\n\ndata: [DONE]\n\n').encode()
    real=httpx.Client
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Body())),**kw))
    sub=chat_stream.redis.pubsub();sub.subscribe(chat_stream.channel(wid,room));sub.get_message(timeout=2)
    def work():
        while run_once():pass
    kinds=[]
    try:
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(work)
            try:
                for _ in range(50):
                    event=sub.get_message(ignore_subscribe_messages=True,timeout=.2)
                    if not event:continue
                    data=json.loads(event['data']);kinds.append(data['kind'])
                    if data['kind']=='delta' and not release.is_set():
                        with SessionLocal() as db:
                            assert not db.scalar(select(Message.id).where(Message.conversation_id==room,Message.role=='assistant'))
                        release.set()
                    if data['kind']=='done':
                        with SessionLocal() as db:
                            assert db.get(Job,jid).status=='done'
                            assert db.scalar(select(Message.content).where(Message.conversation_id==room,Message.role=='assistant'))=='คำตอบส่วนแรก และส่วนท้าย'
                        break
            finally:release.set()
            future.result(timeout=10)
        assert kinds==['start','delta','delta','done']
    finally:sub.close()
