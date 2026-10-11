import json
import uuid
import httpx
import pytest
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import Job,Entry,ChatAction,Proposal,Conversation,Message,Provider,Membership,AIUsage,now
from app import ai,config
from app.worker import run_once
from app.ai_sandbox import CASH,FOOD
from app.ai_diagnostics import cleanup,record
from test_assistant_finance import tool
from test_chat_actions import setup,say
from test_secretary import provider,transport,reply

@pytest.fixture
def lab(actor,monkeypatch):
    monkeypatch.setattr('app.ai_diagnostics.login_limit',lambda _:None)
    c,w,u,b,cid=setup(actor);pid=provider(w)
    return c,w,u,b,cid,pid

def start(c,b,case='balance',pid=None):
    response=c.post(b+'/ai/tests',json={'case':case,'provider_id':pid});assert response.status_code==200,response.text
    return response.json()['job_id']

def result(c,b,jid):return c.get(b+'/ai/diagnostics/'+jid).json()

def run_all():
    while run_once():pass

def counts(w):
    with SessionLocal() as db:return tuple(db.scalar(select(func.count()).select_from(m).where(m.workspace_id==w)) for m in (Entry,ChatAction,Proposal,Conversation,Message))

@pytest.mark.parametrize('case',['balance','monthly','transaction','followup','receipt'])
def test_synthetic_scenarios_use_real_provider_tools_but_never_finance_records(lab,monkeypatch,case):
    from app.reporting import today
    c,w,u,b,cid,pid=lab
    with SessionLocal.begin() as db:
        db.get(Provider,pid).supports_images=True
        # A private name from the real workspace must not reach evaluation prompts.
        from app.models import Account
        db.scalar(select(Account).where(Account.workspace_id==w,Account.kind=='asset')).name='PRIVATE-real-wallet'
    calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        assert 'PRIVATE-real-wallet' not in req.content.decode() and cid not in req.content.decode()
        if case in ('transaction','followup','receipt'):
            if case=='receipt':assert any(isinstance(m['content'],list) and m['content'][1]['image_url']['url'].startswith('data:image/png;base64,') for m in body['messages'])
            answer=tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=12500 if case=='receipt' else 8000,account_id=CASH,category_id=FOOD,occurred_on=today().isoformat()))
        elif len(calls)==1:answer=tool('lookup_workspace',{'queries':[{'resource':'balances'}]}) if case=='balance' else tool('query_finance',{'operation':'monthly_analysis'})
        else:answer={'content':'เงินรวม 1,234.56 บาท หนี้ 234.56 สุทธิ 1,000 บาทค่ะ' if case=='balance' else 'เดือนนี้ใช้ไป 450.00 บาทค่ะ'}
        return httpx.Response(200,json={'choices':[{'message':answer}],'usage':{'prompt_tokens':70,'completion_tokens':25}})
    transport(monkeypatch,handler);before=counts(w);jid=start(c,b,case,pid)
    pending=result(c,b,jid);assert pending['diagnostics']['test']['case']==case and pending['status']=='pending'
    run_all();value=result(c,b,jid);report=value['diagnostics']['test']
    assert report['status']=='passed' and report['synthetic_only'] and report['provider_id']==pid
    assert counts(w)==before
    raw=json.dumps(value);assert 'PRIVATE-real-wallet' not in raw and CASH not in raw and 'กาแฟ' not in raw
    requests=[e for e in value['diagnostics']['events'] if e['event']=='request']
    assert requests and requests[0]['input_tokens']==70 and requests[0]['estimated'] is False
    with SessionLocal() as db:
        assert db.get(Job,jid).payload=={}
        assert db.scalar(select(AIUsage.id).where(AIUsage.workspace_id==w,AIUsage.task=='ai_test'))


def test_test_routes_fallback_and_errors_are_sanitized(lab,monkeypatch,caplog):
    c,w,u,b,cid,pid=lab
    with SessionLocal.begin() as db:
        db.get(Provider,pid).priority=0;backup=Provider(workspace_id=w,kind='ollama',model='backup',task='chat',priority=1,retries=0);db.add(backup);db.flush();second=backup.id
    def handler(req):
        body=json.loads(req.content)
        if body['model']!='backup':return httpx.Response(401,json={'error':'secret upstream password and PRIVATE message'})
        if body['messages'][-1]['role']!='tool':answer=tool('lookup_workspace',{'queries':[{'resource':'balances'}]})
        else:answer={'content':'1,234.56 บาทค่ะ'}
        return httpx.Response(200,json={'choices':[{'message':answer}]})
    transport(monkeypatch,handler);jid=start(c,b);run_all();value=result(c,b,jid)
    assert value['diagnostics']['test']['provider_id']==second and value['diagnostics']['test']['status']=='passed'
    assert any(e['event']=='fallback' for e in value['diagnostics']['events'])
    assert any(e.get('error')=='authentication' for e in value['diagnostics']['events'])
    assert 'secret upstream' not in json.dumps(value) and 'PRIVATE' not in json.dumps(value) and 'secret upstream' not in caplog.text


def test_cloud_off_disabled_foreign_provider_and_single_pending_guard(lab,monkeypatch):
    c,w,u,b,cid,pid=lab
    monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',False)
    with SessionLocal.begin() as db:
        cloud=Provider(workspace_id=w,kind='openai',model='test',task='chat');db.add(cloud);db.flush();cloudid=cloud.id
    assert c.post(b+'/ai/tests',json={'case':'balance','provider_id':cloudid}).status_code==422
    assert c.post(b+'/ai/tests',json={'case':'balance','provider_id':str(uuid.uuid4())}).status_code==422
    jid=start(c,b);assert c.post(b+'/ai/tests',json={'case':'balance'}).status_code==409
    assert c.post(b+'/ai/tests',json={'case':'balance','text':'PRIVATE'}).status_code==422


def test_no_tool_wrong_amount_and_image_disabled_are_not_passed(lab,monkeypatch):
    c,w,u,b,cid,pid=lab
    transport(monkeypatch,lambda req:reply('ยอดเงิน 1,234.56 บาทค่ะ'))
    jid=start(c,b);run_all();assert result(c,b,jid)['diagnostics']['test']['reason']=='no_tool'
    with SessionLocal.begin() as db:db.get(Provider,pid).supports_images=False
    jid=start(c,b,'receipt');run_all();r=result(c,b,jid)['diagnostics']['test'];assert r['status']=='skipped' and r['calls']==0


def test_trace_real_chat_cached_reads_and_no_content(lab,monkeypatch):
    c,w,u,b,cid,pid=lab;calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'message':tool('lookup_workspace',{'queries':[{'resource':'balances'}]})}]})
    transport(monkeypatch,handler)
    say(c,b,cid,'PRIVATE-user-prompt ตอนนี้มีเงินเท่าไร');run_all()
    value=c.get(b+'/ai/diagnostics').json()['items'][0]
    assert value['task']=='chat' and any(e.get('status')=='cached' for e in value['diagnostics']['events'])
    assert 'PRIVATE-user-prompt' not in json.dumps(value) and cid not in json.dumps(value)
    assert len([e for e in value['diagnostics']['events'] if e['event']=='request'])==2


def test_owner_only_scoped_detail_clear_and_expiration(lab,monkeypatch):
    from app.bootstrap import create_user
    from app.main import app
    from fastapi.testclient import TestClient
    c,w,u,b,cid,pid=lab;transport(monkeypatch,lambda req:reply('hello'));jid=start(c,b);run_all()
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password');db.add(Membership(workspace_id=w,user_id=other.id,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as member:
        member.post('/auth/login',json={'email':other.email,'password':'secure-test-password'})
        assert member.get(b+'/ai/diagnostics').status_code==403
        assert member.post(b+'/ai/tests',json={'case':'balance'}).status_code==403
    foreign=c.post('/workspaces',json={'name':'another'}).json()['id']
    assert c.get('/workspaces/'+foreign+'/ai/diagnostics/'+jid).status_code==404
    with SessionLocal.begin() as db:
        db.get(Job,jid).diagnostics_expires=now()-1
        cleanup(db)
    assert result(c,b,jid)['diagnostics']=={}
    assert c.delete(b+'/ai/diagnostics').status_code==200
    assert c.get(b+'/ai/diagnostics').json()['items']==[]


def test_unknown_metadata_fields_never_stored():
    from types import SimpleNamespace
    job=SimpleNamespace()
    record(job,'request',status='ok',provider_id=str(uuid.uuid4()),prompt='PRIVATE',url='http://secret',error='raw-secret',tool='arbitrary-private',duration_ms=10)
    assert 'PRIVATE' not in json.dumps(job._diagnostic_events) and 'secret' not in json.dumps(job._diagnostic_events)

@pytest.mark.parametrize('problem,reason',[('amount','wrong_amount'),('foreign','invalid_arguments'),('schema','invalid_arguments'),('management','wrong_tool')])
def test_untrusted_draft_is_checked_and_never_resolved(lab,monkeypatch,problem,reason):
    from app.reporting import today
    c,w,u,b,cid,pid=lab
    value=dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account_id=CASH,category_id=FOOD,occurred_on=today().isoformat())
    name='prepare_transaction'
    if problem=='amount':value['amount']=99999
    if problem=='foreign':value['account_id']=str(uuid.uuid4())
    if problem=='schema':value={'unexpected':'PRIVATE'}
    if problem=='management':name='prepare_management_plan'
    transport(monkeypatch,lambda req:httpx.Response(200,json={'choices':[{'message':tool(name,value)}]}))
    before=counts(w);jid=start(c,b,'transaction');run_all()
    assert result(c,b,jid)['diagnostics']['test']['reason']==reason and counts(w)==before


def test_sandbox_respects_budget_before_network(lab,monkeypatch):
    c,w,u,b,cid,pid=lab
    with SessionLocal.begin() as db:db.get(Provider,pid).kind='openai'
    assert c.put(b+'/ai/settings',json={'cloud_enabled':True}).status_code==200
    assert c.put(b+'/ai/usage/policy',json={'monthly_limit':1,'prices':{}}).status_code==200
    calls=[];transport(monkeypatch,lambda req:calls.append(req))
    monkeypatch.setattr('app.ai_sandbox.target',lambda p:('https://example.test/v1',{},{}))
    jid=start(c,b,'balance',pid);run_all()
    assert result(c,b,jid)['diagnostics']['test']['reason']=='budget' and calls==[]

@pytest.mark.parametrize('case',['balance','transaction','followup','receipt'])
def test_lab_accepts_empty_optional_lookup_fields_and_default_discovery(lab,monkeypatch,case):
    c,w,u,b,cid,pid=lab;calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        assert len(body['tools'])==2
        if len(calls)==1:
            query={'resource':'balances' if case=='balance' else 'preferences','q':None,'kind':'','month':'','cursor':'','limit':None}
            answer=tool('lookup_workspace',{'queries':[query]})
        elif case=='balance':answer={'content':'ยอดเงิน 1,234.56 บาทค่ะ'}
        else:answer=tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=12500 if case=='receipt' else 8000,account_id=CASH,category_id=FOOD))
        return httpx.Response(200,json={'choices':[{'message':answer}]})
    transport(monkeypatch,handler);before=counts(w);jid=start(c,b,case,pid);run_all()
    assert result(c,b,jid)['diagnostics']['test']['status']=='passed' and counts(w)==before


def test_lab_invalid_lookup_gives_sanitized_feedback_and_one_repair(lab,monkeypatch):
    c,w,u,b,cid,pid=lab;calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        if len(calls)==1:answer=tool('lookup_workspace',{'queries':[{'resource':'balances','q':['PRIVATE']} ]})
        elif len(calls)==2:
            feedback=json.loads(body['messages'][-1]['content'])
            assert feedback['issues']==[{'field':'queries.q','code':'string_type'}] and 'PRIVATE' not in json.dumps(feedback)
            answer=tool('lookup_workspace',{'queries':[{'resource':'balances'}]})
        else:answer={'content':'ยอดเงิน 1,234.56 บาท'}
        return httpx.Response(200,json={'choices':[{'message':answer}]})
    transport(monkeypatch,handler);jid=start(c,b);run_all();value=result(c,b,jid)
    assert value['diagnostics']['test']['status']=='passed' and len(calls)==3
    assert any(e.get('issues')==[{'field':'queries.q','code':'string_type'}] for e in value['diagnostics']['events'])
    assert 'PRIVATE' not in json.dumps(value)


def test_batch_item_intent_defaults_but_root_intent_required():
    from app.chat_dialogue import Suggestion
    from pydantic import ValidationError
    value=Suggestion.model_validate({'intent':'create','transactions':[{'description':'กาแฟ','amount':8000}]})
    assert value.transactions[0].intent=='create'
    with pytest.raises(ValidationError):Suggestion.model_validate({'amount':8000})
    with pytest.raises(ValidationError):Suggestion.model_validate({'intent':'create','transactions':[{'amount':'8000'}]})


def test_lab_repairs_prose_once_without_posting(lab,monkeypatch):
    c,w,u,b,cid,pid=lab;calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        if len(calls)==1:return reply('เตรียมให้แล้ว พิมพ์ ยืนยัน ได้เลย')
        return httpx.Response(200,json={'choices':[{'message':tool('prepare_transaction',{'intent':'create','transactions':[dict(kind='expense',description='กาแฟ',amount=8000,account_id=CASH,category_id=FOOD)]})}]})
    transport(monkeypatch,handler);before=counts(w);jid=start(c,b,'followup',pid);run_all()
    assert result(c,b,jid)['diagnostics']['test']['status']=='passed'
    assert len(calls)==2 and counts(w)==before


def test_lab_does_not_pass_repeated_prose(lab,monkeypatch):
    c,w,u,b,cid,pid=lab;calls=[]
    def handler(req):calls.append(1);return reply('เตรียมแล้ว ยืนยันได้เลย')
    transport(monkeypatch,handler);before=counts(w);jid=start(c,b,'receipt',pid)
    with SessionLocal.begin() as db:db.get(Provider,pid).supports_images=True
    run_all()
    assert result(c,b,jid)['diagnostics']['test']['reason']=='no_tool'
    assert len(calls)==2 and counts(w)==before


def test_output_limit_distinguished_for_stream_and_json():
    from app.assistant_response import completion_choice,read_stream
    from app.ai_errors import AIRequestError,diagnose
    from types import SimpleNamespace
    with pytest.raises(AIRequestError) as failure:
        completion_choice({'finish_reason':'length','message':{'content':'partial'}})
    assert diagnose(failure.value)=='output_limit'
    class Response:
        def iter_lines(self):return iter(['data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'length'}]}),''])
    with pytest.raises(AIRequestError) as failure:read_stream(Response(),SimpleNamespace(task='ai_test'))
    assert diagnose(failure.value)=='output_limit'
