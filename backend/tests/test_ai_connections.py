import json
import uuid
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from app import config
from app.db import SessionLocal
from app.models import AIConnection,Provider,Membership,Workspace
from app.ai_connections import credential
from app.bootstrap import create_user


@pytest.fixture
def setup(actor,monkeypatch):
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    c,w,u=actor
    return c,w,u,f'/workspaces/{w}'


def test_shared_key_rotation_task_profiles_and_deletion(setup):
    c,w,u,b=setup
    data=dict(name='เครื่องหลัก',kind='compatible',endpoint='http://192.168.1.20:11434/v1',api_key='secret-one')
    response=c.post(b+'/ai/connections',json=data);assert response.status_code==200,response.text
    conn=response.json();assert conn['has_key'] and 'secret-one' not in response.text
    profiles=[]
    for task in ('chat','extract'):
        p=c.post(b+'/providers',json=dict(connection_id=conn['id'],kind='compatible',model='test-model',task=task))
        assert p.status_code==200,p.text
        profiles.append(p.json())
    assert c.get(b+'/ai/connections').json()[0]['models']==2
    assert c.delete(b+'/ai/connections/'+conn['id']).status_code==409
    with SessionLocal() as db:before_epoch=db.get(Workspace,w).ai_epoch
    assert c.put(b+'/ai/connections/'+conn['id'],json={**data,'api_key':'secret-two'}).status_code==200
    with SessionLocal() as db:assert db.get(Workspace,w).ai_epoch>before_epoch
    with SessionLocal() as db:
        for p in profiles:
            row=db.get(Provider,p['id'])
            assert row.encrypted_key=='' and config.cipher().decrypt(credential(row).encode()).decode()=='secret-two'
    assert 'secret-two' not in c.get(b+'/providers').text
    # Key must not follow changed destinations, even for all linked models.
    changed={**data,'endpoint':'http://192.168.1.21:11434/v1','api_key':''}
    assert c.put(b+'/ai/connections/'+conn['id'],json=changed).json()['has_key'] is False
    for p in c.get(b+'/providers').json():
        assert p['endpoint']==changed['endpoint'] and not p['has_key']
        assert c.delete(b+'/providers/'+p['id']).status_code==200
    assert c.delete(b+'/ai/connections/'+conn['id']).status_code==200


def test_connection_scope_and_secret_validation(setup):
    c,w,u,b=setup
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
        connection=AIConnection(workspace_id=foreign,name='private',kind='ollama',endpoint='',encrypted_key='');db.add(connection);db.flush();cid=connection.id
    assert c.post(b+'/providers',json=dict(connection_id=cid,kind='ollama',model='test',task='chat')).status_code==404
    assert c.put(b+'/ai/connections/'+cid,json=dict(name='x',kind='ollama')).status_code==404
    assert c.get(f'/workspaces/{foreign}/ai/connections').status_code==404
    for values in (dict(name='x',kind='compatible',endpoint='http://169.254.169.254/v1',api_key='not-for-response'),dict(name='x',kind='invalid',api_key='not-for-response')):
        r=c.post(b+'/ai/connections',json=values)
        assert r.status_code==422 and 'not-for-response' not in r.text


def test_named_provider_retains_encrypted_key_and_linked_updates_use_connection(setup):
    c,w,u,b=setup
    data=dict(name='cloud',kind='openai',api_key='secret-original')
    connection=c.post(b+'/ai/connections',json=data).json()
    p=c.post(b+'/providers',json=dict(kind='openai',connection_id=connection['id'],model='gpt-test',task='chat')).json()
    assert c.put(b+'/ai/connections/'+connection['id'],json={**data,'api_key':''}).json()['has_key']
    # Profile edits cannot silently replace a shared key.
    r=c.put(b+'/providers/'+p['id'],json=dict(kind='openai',connection_id=connection['id'],model='gpt-test',task='chat',api_key='bad-replacement'))
    assert r.status_code==422
    assert c.put(b+'/providers/'+p['id'],json=dict(kind='openai',connection_id=connection['id'],model='gpt-test',task='extract',max_tokens=32000)).status_code==200
    assert c.get(b+'/providers').json()[0]['max_tokens']==32000


def test_connection_owner_only(setup):
    from fastapi.testclient import TestClient
    from app.main import app
    c,w,u,b=setup
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(user_id=other.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        assert client.post('/auth/login',json={'email':other.email,'password':'secure-test-password'}).status_code==200
        assert client.get(b+'/ai/connections').status_code==403
        assert client.post(b+'/ai/connections',json=dict(name='x',kind='ollama')).status_code==403


def test_linked_runtime_uses_rotated_key_and_existing_fallback(setup,monkeypatch,pg_only):
    import httpx
    from app import ai
    from app.worker import run_once
    c,w,u,b=setup
    c.put(b+'/ai/settings',json={'cloud_enabled':True,'demo_fallback':False})
    data=dict(name='shared',kind='compatible',endpoint='https://api.example.com/v1',api_key='first-key')
    connection=c.post(b+'/ai/connections',json=data).json()
    p=c.post(b+'/providers',json=dict(kind='compatible',connection_id=connection['id'],model='reader',task='extract',retries=0)).json()
    c.put(b+'/ai/connections/'+connection['id'],json={**data,'api_key':'rotated-key'})
    monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}))
    real=httpx.Client;calls=[]
    def handler(req):
        calls.append(req.headers.get('Authorization'))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'proposals':[{'description':'synthetic receipt','amount':8000,'kind':'expense'}]})}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    assert c.post(b+'/capture',json={'text':'synthetic receipt','privacy':'standard'}).status_code==200
    while run_once():pass
    assert calls==['Bearer rotated-key']
    assert c.get(b+'/proposals').json()[0]['amount']==8000


def test_reviewed_connection_removal_deletes_only_linked_profiles_and_preserves_history(setup):
    from app.models import AIUsage,AIUsagePolicy,Conversation,Message
    c,w,u,b=setup
    conns=[c.post(b+'/ai/connections',json=dict(name=name,kind='ollama')).json() for name in ('remove','keep')]
    profiles=[]
    for conn,task in [(conns[0],'chat'),(conns[0],'extract'),(conns[1],'chat')]:
        r=c.post(b+'/providers',json=dict(connection_id=conn['id'],kind='ollama',model='model-'+task,task=task))
        assert r.status_code==200,r.text
        profiles.append(r.json())
    with SessionLocal.begin() as db:
        room=Conversation(workspace_id=w,user_id=u.id,title='keep history');db.add(room);db.flush()
        message=Message(workspace_id=w,conversation_id=room.id,role='assistant',content='retained synthetic reply');db.add(message)
        usage=AIUsage(workspace_id=w,provider_id=profiles[0]['id'],model='model-chat',task='chat',month='2026-10',input_tokens=10,output_tokens=5,cost=1,status='done');db.add(usage)
        db.add(AIUsagePolicy(workspace_id=w,monthly_limit=100,prices={p['id']:{'input':1,'output':2} for p in profiles}));db.flush()
        mid=message.id;usage_id=usage.id;before_epoch=db.get(Workspace,w).ai_epoch
    path=b+'/ai/connections/'+conns[0]['id']
    plan=c.get(path+'/deletion-preview');assert plan.status_code==200
    assert {p['id'] for p in plan.json()['models']}=={p['id'] for p in profiles[:2]}
    assert set(plan.json())=={'id','name','models'} and 'encrypted_key' not in plan.text
    assert c.delete(path).status_code==409
    body={'expected_model_ids':[p['id'] for p in plan.json()['models']]}
    assert c.request('DELETE',path,json=body).json()=={'ok':True,'deleted_models':2}
    assert [p['id'] for p in c.get(b+'/providers').json()]==[profiles[2]['id']]
    with SessionLocal() as db:
        assert db.get(AIConnection,conns[0]['id']) is None
        assert db.get(AIConnection,conns[1]['id']) is not None
        assert db.get(Message,mid).content=='retained synthetic reply'
        assert db.get(AIUsage,usage_id).cost==1
        assert set(db.get(AIUsagePolicy,w).prices)=={profiles[2]['id']}
        assert db.get(Workspace,w).ai_epoch>before_epoch


def test_connection_deletion_rejects_stale_plan_including_previously_unused_connection(setup):
    c,w,u,b=setup
    conn=c.post(b+'/ai/connections',json=dict(name='test',kind='ollama')).json()
    path=b+'/ai/connections/'+conn['id']
    plan=c.get(path+'/deletion-preview').json();assert plan['models']==[]
    profile=c.post(b+'/providers',json=dict(connection_id=conn['id'],kind='ollama',model='new-model',task='chat')).json()
    assert c.request('DELETE',path,json={'expected_model_ids':[]}).status_code==409
    assert c.get(path+'/deletion-preview').json()['models'][0]['id']==profile['id']
    assert c.request('DELETE',path,json={'expected_model_ids':[profile['id'],profile['id']]}).status_code==422
    assert c.request('DELETE',path,json={'expected_model_ids':[str(uuid.uuid4())]}).status_code==409
    assert len(c.get(b+'/providers').json())==1


def test_connection_deletion_owner_and_tenant_checks(setup):
    from fastapi.testclient import TestClient
    from app.main import app
    c,w,u,b=setup
    conn=c.post(b+'/ai/connections',json=dict(name='owned',kind='ollama')).json()
    path=b+'/ai/connections/'+conn['id']
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
        db.add(Membership(user_id=other.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        assert client.post('/auth/login',json={'email':other.email,'password':'secure-test-password'}).status_code==200
        assert client.get(path+'/deletion-preview').status_code==403
        assert client.request('DELETE',path,json={'expected_model_ids':[]}).status_code==403
        foreign_path=f'/workspaces/{foreign}/ai/connections/{conn["id"]}'
        assert client.get(foreign_path+'/deletion-preview').status_code==404
        assert client.request('DELETE',foreign_path,json={'expected_model_ids':[]}).status_code==404
    assert c.get(path+'/deletion-preview').status_code==200
