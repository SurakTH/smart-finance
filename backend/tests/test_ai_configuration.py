import json
from types import SimpleNamespace
import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from app import ai, ai_settings, config
from app.db import SessionLocal
from app.models import Provider, Job, Membership
from app.worker import run_once

@pytest.fixture
def configured(actor,monkeypatch):
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',False)
    monkeypatch.setattr(ai_settings,'login_limit',lambda _:None)
    c,w,u=actor
    return c,f'/workspaces/{w}',w,u

def payload(**kw):
    return dict(kind='compatible',model='test-model',task='extract',endpoint='https://api.example.com/v1',api_key='hidden-test-key',**kw)

def enable(c,b,**kw):
    return c.put(b+'/ai/settings',json=dict(cloud_enabled=True,demo_fallback=True,max_attempted_providers=3,**kw))

def test_encrypted_edit_retains_key_and_web_settings_override_environment(configured,monkeypatch):
    c,b,w,u=configured
    assert c.get(b+'/ai/settings').json()['cloud_enabled'] is False
    row=c.post(b+'/providers',json=payload()).json();pid=row['id']
    assert 'hidden-test-key' not in json.dumps(row) and row['has_key']
    update={**payload(),'api_key':'','name':'ผู้ช่วยใหม่','retries':2,'timeout_seconds':35,'temperature':75}
    assert c.put(b+'/providers/'+pid,json=update).status_code==200
    with SessionLocal() as db:
        p=db.get(Provider,pid);assert config.cipher().decrypt(p.encrypted_key.encode()).decode()=='hidden-test-key'
    assert enable(c,b).status_code==200
    assert c.get(b+'/ai/settings').json()['cloud_enabled'] is True
    monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',True)
    assert c.put(b+'/ai/settings',json={'cloud_enabled':False}).status_code==200
    assert c.get(b+'/ai/settings').json()['cloud_enabled'] is False
    assert c.put(b+'/providers/'+pid,json={**update,'clear_key':True}).json()['has_key'] is False
    assert c.put(b+'/providers/'+pid,json={**update,'api_key':'replacement-key'}).json()['has_key'] is True
    assert 'replacement-key' not in c.get(b+'/providers').text
    # Existing key must not follow a changed destination.
    changed={**update,'endpoint':'https://another.example.com/v1','api_key':''}
    assert c.put(b+'/providers/'+pid,json=changed).json()['has_key'] is False
    # Legacy rows use the old server URL; those keys must not follow a new web URL either.
    monkeypatch.setattr(config,'COMPATIBLE_URL','https://legacy.example.com/v1')
    with SessionLocal.begin() as db:
        old=db.get(Provider,pid);old.endpoint='';old.encrypted_key=config.cipher().encrypt(b'legacy-key').decode()
    assert c.put(b+'/providers/'+pid,json=changed).json()['has_key'] is False

@pytest.mark.parametrize('url',['ftp://api.example.com/v1','http://169.254.169.254/v1','http://[fe80::1]/v1','http://0.0.0.0/v1','http://224.0.0.1/v1','https://user:password@example.com/v1','https://api.example.com/v1?key=secret','https://api.example.com/v1#secret','http://api.example.com:0/v1'])
def test_unsafe_urls_and_secret_validation_not_echoed(configured,url):
    c,b,*_=configured
    response=c.post(b+'/providers',json={**payload(),'endpoint':url})
    assert response.status_code==422
    assert url not in response.text and 'hidden-test-key' not in response.text
    response=c.post(b+'/providers',json={**payload(),'timeout_seconds':'hidden-test-key'})
    assert response.status_code==422 and 'hidden-test-key' not in response.text

def test_dns_checked_and_pinned_with_sni(monkeypatch):
    p=SimpleNamespace(kind='compatible',endpoint='https://api.example.com/v1')
    monkeypatch.setattr(ai_settings.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    url,headers,extensions=ai_settings.target(p)
    assert url=='https://93.184.216.34/v1' and headers=={'Host':'api.example.com'} and extensions=={'sni_hostname':'api.example.com'}
    monkeypatch.setattr(ai_settings.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('169.254.169.254',443))])
    with pytest.raises(ValueError):ai_settings.target(p)

def test_owner_only_edit_probe_routes_and_tenant_isolation(configured):
    from app.bootstrap import create_user
    from app.main import app
    from fastapi.testclient import TestClient
    import uuid
    c,b,w,u=configured
    pid=c.post(b+'/providers',json=payload()).json()['id']
    with SessionLocal.begin() as db:
        bob=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        other_w=db.scalar(select(Membership.workspace_id).where(Membership.user_id==bob.id))
        db.add(Membership(user_id=bob.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as other:
        other.post('/auth/login',json={'email':bob.email,'password':'secure-test-password'})
        for method,path,data in [('GET','/ai/settings',None),('PUT','/ai/settings',{'cloud_enabled':True}),('PUT','/ai/routes',{'task':'extract','provider_ids':[pid]}),('PUT','/providers/'+pid,payload()),('POST','/providers/'+pid+'/test',{}),('POST','/providers/'+pid+'/models',{})]:
            assert other.request(method,b+path,json=data).status_code==403
        assert other.put(f'/workspaces/{other_w}/providers/{pid}',json=payload()).status_code==404
        assert other.post(f'/workspaces/{other_w}/providers/{pid}/test',json={}).status_code==404
    second=c.post(b+'/providers',json=payload()).json()['id']
    assert c.put(b+'/ai/routes',json={'task':'extract','provider_ids':[second,pid]}).status_code==200
    assert [p['id'] for p in c.get(b+'/providers').json()]==[second,pid]
    assert c.put(b+'/ai/routes',json={'task':'extract','provider_ids':[second,second]}).status_code==409
    assert c.put(b+'/ai/routes',json={'task':'chat','provider_ids':[pid]}).status_code==409

def test_probe_synthetic_prompt_and_filtered_model_discovery(configured,monkeypatch):
    c,b,*_=configured
    pid=c.post(b+'/providers',json=payload()).json()['id']
    assert c.post(b+'/providers/'+pid+'/test',json={}).status_code==403
    enable(c,b)
    monkeypatch.setattr(ai_settings,'target',lambda p:('https://api.example.com/v1',{},{}))
    real=httpx.Client;calls=[]
    def handler(req):
        calls.append(req)
        if req.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'valid/model'},{'id':'<script>secret</script>'},{'id':False}]})
        assert json.loads(req.content)['messages']==[{'role':'user','content':'Reply OK.'}]
        assert req.headers['authorization']=='Bearer hidden-test-key'
        return httpx.Response(200,json={'choices':[{'message':{'content':'provider-secret-not-returned'}}]})
    monkeypatch.setattr(ai_settings.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    response=c.post(b+'/providers/'+pid+'/test',json={})
    assert response.status_code==200 and 'provider-secret' not in response.text
    assert c.post(b+'/providers/'+pid+'/models',json={}).json()=={'models':['valid/model']}
    assert len(calls)==2

def test_runtime_routes_retries_disabled_cloud_and_demo(configured,monkeypatch):
    c,b,w,u=configured;enable(c,b)
    first=c.post(b+'/providers',json={**payload(),'model':'first','retries':0,'max_tokens':333,'temperature':80}).json()['id']
    second=c.post(b+'/providers',json={**payload(),'model':'second','retries':0}).json()['id']
    disabled=c.post(b+'/providers',json={**payload(),'model':'disabled','priority':0,'enabled':False}).json()['id']
    c.put(b+'/ai/routes',json={'task':'extract','provider_ids':[first,disabled,second]})
    monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}))
    real=httpx.Client;calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body['model'])
        if body['model']=='first':
            assert body['max_tokens']==333 and body['temperature']==.8
            return httpx.Response(503,json={'error':'hidden provider error'})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'proposals':[{'description':'AI draft','amount':8500,'kind':'expense'}]})}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    jobid=c.post(b+'/capture',json={'text':'test','privacy':'standard'}).json()['job_id']
    while run_once():pass
    assert calls==['first','second']
    assert c.get(b+'/proposals').json()[0]['source']=='ai'
    assert c.get(b+'/transactions').json()==[]
    calls.clear()
    c.put(b+'/ai/settings',json={'cloud_enabled':True,'demo_fallback':True,'max_attempted_providers':1})
    c.post(b+'/capture',json={'text':'ข้าว 50','privacy':'standard'})
    while run_once():pass
    assert calls==['first']
    # Private jobs never try either cloud route, even with a saved opt-in.
    calls.clear();c.post(b+'/capture',json={'text':'ข้าว 50','privacy':'private'})
    while run_once():pass
    assert calls==[]
    c.put(b+'/ai/settings',json={'cloud_enabled':False,'demo_fallback':False})
    jobid=c.post(b+'/capture',json={'text':'ข้าว 50','privacy':'standard'}).json()['job_id']
    while run_once():pass
    with SessionLocal() as db:assert db.get(Job,jobid).status=='failed'
    assert calls==[]

@pytest.mark.parametrize('url',[
    'http://api.example.com/v1','http://192.168.1.20:11434/v1',
    'http://100.90.1.2:8000/v1','http://ollama:11434/v1',
    'http://host.docker.internal:11434/v1','http://localhost:8081/v1',
    'http://[::1]:11434/v1','https://ai.home.local:8443/v1',
])
def test_custom_http_lan_tailscale_and_ports_saved_from_web(configured,url):
    c,b,*_=configured
    for kind in ('compatible','ollama'):
        response=c.post(b+'/providers',json={**payload(),'kind':kind,'endpoint':url})
        assert response.status_code==200 and response.json()['endpoint']==url
        assert 'hidden-test-key' not in response.text

@pytest.mark.parametrize('address',['169.254.169.254','fe80::1','::ffff:169.254.169.254','0.0.0.0','224.0.0.1','100.100.100.200','fd00:ec2::254'])
def test_dns_metadata_and_unusable_addresses_stay_blocked(monkeypatch,address):
    monkeypatch.setattr(ai_settings.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(address,11434))])
    with pytest.raises(ValueError):ai_settings.target(SimpleNamespace(kind='ollama',endpoint='http://ai.example.com:11434/v1'))

def test_http_pins_ip_preserves_port_and_named_cloud_stays_public(monkeypatch):
    calls=[]
    def resolve(host,port,**kw):calls.append((host,port));return [(2,1,6,'',('100.90.1.2',port))]
    monkeypatch.setattr(ai_settings.socket,'getaddrinfo',resolve)
    url,headers,extensions=ai_settings.target(SimpleNamespace(kind='compatible',endpoint='http://ai.example.com:8081/v1'))
    assert url=='http://100.90.1.2:8081/v1' and headers=={'Host':'ai.example.com:8081'} and extensions=={}
    assert calls==[('ai.example.com',8081)]
    with pytest.raises(ValueError):ai_settings.target(SimpleNamespace(kind='openai',endpoint=''))

def test_each_ollama_machine_used_by_probe_discovery_and_runtime_fallback(configured,monkeypatch):
    c,b,w,u=configured
    rows=[c.post(b+'/providers',json=dict(kind='ollama',model=model,task='chat',endpoint=url,retries=0)).json() for model,url in [('machine-one','http://192.168.1.20:11434/v1'),('machine-two','http://100.90.1.2:11435/v1')]]
    real_dns=ai_settings.socket.getaddrinfo
    # Mock only model IPs; cancellation opens independent PostgreSQL connections.
    monkeypatch.setattr(ai_settings.socket,'getaddrinfo',lambda host,port,**kw:[(2,1,6,'',(host,port))] if host in ('192.168.1.20','100.90.1.2') else real_dns(host,port,**kw))
    real=httpx.Client;calls=[]
    def handler(req):
        calls.append((req.url.host,req.url.port,req.url.path))
        if req.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'machine-one'}]})
        body=json.loads(req.content)
        if body['messages'][0].get('role')=='user':return httpx.Response(200,json={'choices':[{'message':{'content':'OK'}}]})
        if body['model']=='machine-two':return httpx.Response(503,json={'error':'unavailable'})
        return httpx.Response(200,json={'choices':[{'message':{'content':'ตอบจากเครื่องแรกค่ะ'}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    assert c.post(b+'/providers/'+rows[0]['id']+'/models',json={}).json()=={'models':['machine-one']}
    assert c.post(b+'/providers/'+rows[1]['id']+'/test',json={}).status_code==200
    assert calls==[('192.168.1.20',11434,'/v1/models'),('100.90.1.2',11435,'/v1/chat/completions')]
    assert c.put(b+'/ai/routes',json=dict(task='chat',provider_ids=[rows[1]['id'],rows[0]['id']])).status_code==200
    cid=c.post(b+'/conversations',json={}).json()['id']
    c.post(b+f'/conversations/{cid}/messages',json={'text':'สวัสดี เลขา'})
    while run_once():pass
    assert c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']=='ตอบจากเครื่องแรกค่ะ'
    assert calls[-2:]==[('100.90.1.2',11435,'/v1/chat/completions'),('192.168.1.20',11434,'/v1/chat/completions')]
    assert c.get(b+'/transactions').json()==[]


def test_ollama_default_and_key_does_not_follow_new_machine(configured,monkeypatch):
    c,b,*_=configured
    monkeypatch.setattr(config,'OLLAMA_URL','http://ollama:11434/v1')
    row=c.post(b+'/providers',json=dict(kind='ollama',model='local',task='chat',api_key='test-local-key')).json()
    with SessionLocal() as db:assert ai_settings.target(db.get(Provider,row['id']))==('http://ollama:11434/v1',{}, {})
    edited=c.put(b+'/providers/'+row['id'],json=dict(kind='ollama',model='local',task='chat',endpoint='http://192.168.1.20:11434/v1')).json()
    assert edited['has_key'] is False

@pytest.mark.parametrize('status,error,expected',[
    (404,'model secret-model not found','ไม่พบโมเดล'),(404,'404 page not found','เส้นทาง API'),
    (400,'model does not support tools','ไม่รองรับ tools'),(400,'model does not support images','ไม่รองรับรูป'),
    (400,'reasoning effort unsupported','Thinking'),(401,'hidden upstream credentials','ปฏิเสธสิทธิ์'),
    (500,'backend oom secret dump','RAM/VRAM'),(429,'secret rate limit','จำกัดจำนวนคำขอ'),(302,'redirect','เปลี่ยนเส้นทาง'),
])
def test_probe_specific_errors_never_echo_upstream(configured,monkeypatch,status,error,expected):
    c,b,*_=configured;row=c.post(b+'/providers',json=dict(kind='ollama',model='test',task='chat')).json();real=httpx.Client
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(status,json={'error':error+' secret-never-echo'})),**kw))
    response=c.post(b+'/providers/'+row['id']+'/test',json={})
    assert response.status_code==422 and expected in response.json()['detail']
    assert 'secret-never-echo' not in response.text and 'secret-model' not in response.text

@pytest.mark.parametrize('exception,expected',[(httpx.ConnectError,'เชื่อมต่อเครื่อง'),(httpx.ConnectTimeout,'Timeout'),(httpx.ReadTimeout,'Timeout')])
def test_probe_network_diagnostics_and_configured_timeout(configured,monkeypatch,exception,expected):
    c,b,*_=configured;row=c.post(b+'/providers',json=dict(kind='ollama',model='test',task='chat',timeout_seconds=45)).json();real=httpx.Client
    def handler(req):
        assert req.extensions['timeout']['read']==45
        raise exception('secret url/password must not be echoed',request=req)
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    response=c.post(b+'/providers/'+row['id']+'/test',json={})
    assert response.status_code==422 and expected in response.json()['detail'] and 'secret' not in response.text


def test_ollama_root_url_normalized_and_probe_accepts_tool_reply_without_posting(configured,monkeypatch):
    c,b,*_=configured;row=c.post(b+'/providers',json=dict(kind='ollama',model='test',task='chat',endpoint='http://192.168.1.20:11434')).json()
    assert row['endpoint']=='http://192.168.1.20:11434/v1'
    real_dns=ai_settings.socket.getaddrinfo
    # Mock only model IPs; cancellation opens independent PostgreSQL connections.
    monkeypatch.setattr(ai_settings.socket,'getaddrinfo',lambda host,port,**kw:[(2,1,6,'',(host,port))] if host in ('192.168.1.20','100.90.1.2') else real_dns(host,port,**kw));real=httpx.Client
    def handler(req):
        assert req.url.path=='/v1/chat/completions'
        return httpx.Response(200,json={'choices':[{'message':{'content':None,'tool_calls':[{'type':'function','function':{'name':'prepare_transaction','arguments':'{"intent":"create"}'}}]}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    assert c.post(b+'/providers/'+row['id']+'/test',json={}).status_code==200
    assert c.get(b+'/transactions').json()==[]
