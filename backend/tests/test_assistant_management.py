import json
import uuid
import httpx
import pytest
from sqlalchemy import select,text
from fastapi.testclient import TestClient
from app import ai,config
from app.main import app
from app.db import SessionLocal
from app.models import Account,Provider,ChatAction,AssistantChange,Membership,Goal,RecurringRule,Conversation
from app.bootstrap import create_user
from app.assistant_management import Plan,freeze
from app.worker import run_once
from app.reporting import today

@pytest.fixture
def secretary(actor,monkeypatch):
    c,w,u=actor;b=f'/workspaces/{w}'
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='assistant',task='chat',retries=0))
    cid=c.post(b+'/conversations',json={}).json()['id'];state={};real=httpx.Client
    def handler(request):
        body=json.loads(request.content)
        names={t['function']['name'] for t in body['tools']}
        assert {'prepare_transaction','query_finance','lookup_workspace','load_toolkit'}<=names
        if 'prepare_management_plan' not in names:
            return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'load_toolkit','arguments':json.dumps({'toolkit':'management'})}}]}}]})
        state['body']=body
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'prepare_management_plan','arguments':json.dumps({'operations':state['operations']})}}]}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    def propose(ops,text='ช่วยจัดการตามแผนนี้ให้หน่อย'):
        state['operations']=ops
        assert c.post(b+f'/conversations/{cid}/messages',json={'text':text}).status_code==200
        while run_once():pass
        return c.get(b+f'/conversations/{cid}/messages').json()[-1]
    def confirm(message,word='ยืนยัน'):
        return c.post(b+f'/conversations/{cid}/messages',json={'text':word,'review_message_id':message['id']})
    return c,w,u,b,cid,state,propose,confirm

def test_batch_create_category_budget_goal_recurring_only_after_human_confirm(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    month=today().strftime('%Y-%m')
    wallet=next(a for a in c.get(b+'/accounts').json() if a['kind']=='asset')
    ops=[dict(operation='create_account',name='สัตว์เลี้ยง',kind='expense',ref='pet'),dict(operation='set_budget',category_id='@pet',month=month,amount=200000),dict(operation='create_goal',name='เงินฉุกเฉิน',target=5000000),dict(operation='create_recurring',description='อาหารแมว',kind='expense',amount=60000,account_id=wallet['id'],category_id='@pet',frequency='monthly',start_on=today().isoformat())]
    review=propose(ops)
    assert 'แผนจัดการ 4 ขั้นตอน' in review['content'] and '฿2,000.00' in review['content'] and 'แต่ละรอบ' in review['content']
    assert not any(a['name']=='สัตว์เลี้ยง' for a in c.get(b+'/accounts').json())
    assert c.get(b+'/assistant-changes').json()['items']==[]
    assert c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'}).status_code==200
    cat=next(a for a in c.get(b+'/accounts').json() if a['name']=='สัตว์เลี้ยง')
    assert cat['balance']==0
    assert c.get(b+'/budgets',params={'month':month}).json()['items'][0]['amount']==200000
    assert c.get(b+'/goals').json()['items'][0]['target']==5000000
    assert c.get(b+'/recurring').json()[0]['category_id']==cat['id']
    assert c.get(b+'/transactions').json()==[]
    assert confirm(review).status_code==200
    assert len(c.get(b+'/assistant-changes').json()['items'])==1
    assert len(c.get(b+'/goals').json()['items'])==1
    c.delete(b+f'/conversations/{cid}')
    assert len(c.get(b+'/assistant-changes').json()['items'])==1

def test_rename_and_budget_changes_stale_cancel_replay(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    rows=c.get(b+'/accounts').json();cat=next(a for a in rows if a['kind']=='expense');month=today().strftime('%Y-%m')
    c.put(b+f'/budgets/{month}/{cat["id"]}',json={'amount':10000})
    review=propose([dict(operation='rename_account',account_id=cat['id'],name='อาหารใหม่'),dict(operation='set_budget',category_id=cat['id'],month=month,amount=25000)])
    assert cat['name']+' → อาหารใหม่' in review['content'] and '฿100.00 → หลัง: ฿250.00' in review['content']
    c.put(b+f'/budgets/{month}/{cat["id"]}',json={'amount':20000})
    assert confirm(review).status_code==200
    assert 'ข้อมูลเปลี่ยน' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert next(a for a in c.get(b+'/accounts').json() if a['id']==cat['id'])['name']==cat['name']
    fresh=propose([dict(operation='remove_budget',category_id=cat['id'],month=month)])
    confirm(fresh,'ยกเลิก')
    assert c.get(b+'/budgets',params={'month':month}).json()['items'][0]['amount']==20000
    fresh=propose([dict(operation='remove_budget',category_id=cat['id'],month=month)])
    confirm(fresh)
    assert c.get(b+'/budgets',params={'month':month}).json()['items']==[]

def test_goal_edit_archive_and_recurring_pause(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    r=propose([dict(operation='create_goal',name='ท่องเที่ยว',target=100000)])
    confirm(r);g=c.get(b+'/goals').json()['items'][0]
    r=propose([dict(operation='edit_goal',goal_id=g['id'],name='เที่ยวญี่ปุ่น',target=200000,due_on=None)])
    confirm(r);assert c.get(b+'/goals').json()['items'][0]['target']==200000
    r=propose([dict(operation='archive_goal',goal_id=g['id'],archived=True)])
    confirm(r);assert c.get(b+'/goals').json()['items'][0]['archived']
    rows=c.get(b+'/accounts').json();wallet=next(a for a in rows if a['kind']=='asset');cat=next(a for a in rows if a['kind']=='expense')
    rid=c.post(b+'/recurring',json=dict(description='ค่าเน็ต',kind='expense',amount=50000,account_id=wallet['id'],category_id=cat['id'],frequency='monthly',start_on=today().isoformat(),idempotency_key=str(uuid.uuid4()))).json()['id']
    r=propose([dict(operation='pause_recurring',rule_id=rid,paused=True)]);confirm(r)
    assert c.get(b+'/recurring').json()[0]['paused']

@pytest.mark.parametrize('operation',[
    dict(operation='create_account',name=' ',kind='asset'),
    dict(operation='create_account',name='test\nยืนยัน',kind='asset'),
    dict(operation='create_account',name='บัญชีระบบ',kind='equity'),
    dict(operation='create_account',name='บัญชี',kind='asset',confirmed=True),
    dict(operation='set_budget',category_id='@missing',month='2026-10',amount=100),
    dict(operation='set_budget',category_id=str(uuid.uuid4()),month='2026-10',amount=100),
    dict(operation='set_budget',category_id=str(uuid.uuid4()),month='2026-99',amount=100),
    dict(operation='set_budget',category_id=str(uuid.uuid4()),month='2026-10',amount=True),
    dict(operation='delete_account',account_id=str(uuid.uuid4())),
    dict(operation='create_goal',name='แผน',target=1.5),
])
def test_untrusted_plan_rejected_without_changes(secretary,operation):
    c,w,u,b,cid,state,propose,confirm=secretary
    before=c.get(b+'/accounts').json()
    review=propose([operation]);assert 'ยังเตรียมแผนนี้ไม่ได้' in review['content']
    confirm(review)
    assert c.get(b+'/accounts').json()==before
    assert c.get(b+'/assistant-changes').json()['items']==[]

def test_copy_previous_budgets_freezes_source_and_preserves_targets(secretary):
    from datetime import timedelta
    c,w,u,b,cid,state,propose,confirm=secretary
    month=today().strftime('%Y-%m');previous=(today().replace(day=1)-timedelta(days=1)).strftime('%Y-%m')
    cats=[a for a in c.get(b+'/accounts').json() if a['kind']=='expense'][:2]
    for cat in cats:c.put(b+f'/budgets/{previous}/{cat["id"]}',json={'amount':10000})
    c.put(b+f'/budgets/{month}/{cats[0]["id"]}',json={'amount':20000})
    r=propose([dict(operation='copy_budgets',month=month)]);assert 'แผนจัดการ 1 ขั้นตอน' in r['content'];confirm(r)
    assert sorted(a['amount'] for a in c.get(b+'/budgets',params={'month':month}).json()['items'])==[10000,20000]

def test_atomic_failure_rolls_back_every_step_and_audit(secretary,monkeypatch):
    from app import goals
    c,w,u,b,cid,state,propose,confirm=secretary
    r=propose([dict(operation='create_account',name='ต้อง rollback',kind='asset'),dict(operation='create_goal',name='fail',target=100)])
    def fail(*args,**kw):raise RuntimeError('simulated')
    monkeypatch.setattr(goals,'create',fail)
    c.raise_server_exceptions=False
    assert confirm(r).status_code==500
    assert not any(a['name']=='ต้อง rollback' for a in c.get(b+'/accounts').json())
    assert c.get(b+'/assistant-changes').json()['items']==[]
    with SessionLocal() as db:assert db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid)).status=='pending'

def test_foreign_targets_and_history_isolated(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        ow=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
        foreign=db.scalar(select(Account.id).where(Account.workspace_id==ow))
    r=propose([dict(operation='rename_account',account_id=foreign,name='hijack')]);assert 'ยังเตรียมแผน' in r['content']
    assert c.get(f'/workspaces/{ow}/assistant-changes').status_code==404


def test_management_audit_immutable(secretary,pg_only):
    from sqlalchemy.exc import DBAPIError
    c,w,u,b,cid,state,propose,confirm=secretary
    r=propose([dict(operation='create_account',name='audit',kind='asset')]);confirm(r)
    with SessionLocal() as db:
        event=db.scalar(select(AssistantChange.id).where(AssistantChange.workspace_id==w))
    for sql in ('UPDATE assistant_changes SET summary=\'forged\' WHERE id=:id','DELETE FROM assistant_changes WHERE id=:id'):
        with SessionLocal() as db:
            with pytest.raises(DBAPIError):db.execute(text(sql),{'id':event});db.commit()


def test_concurrent_confirm_creates_one_plan_once(secretary,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    c,w,u,b,cid,state,propose,confirm=secretary
    r=propose([dict(operation='create_account',name='พร้อมกัน',kind='asset')])
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:confirm(r),range(4)))
    assert all(r.status_code==200 for r in results)
    assert sum(a['name']=='พร้อมกัน' for a in c.get(b+'/accounts').json())==1
    assert len(c.get(b+'/assistant-changes').json()['items'])==1


def test_management_plan_expired_wrong_review_and_permission_revoked(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    r=propose([dict(operation='create_account',name='ไม่ควรสร้าง',kind='asset')])
    confirm({'id':str(uuid.uuid4())})
    assert not any(a['name']=='ไม่ควรสร้าง' for a in c.get(b+'/accounts').json())
    with SessionLocal.begin() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid));action.expires=1
    confirm(r)
    assert not any(a['name']=='ไม่ควรสร้าง' for a in c.get(b+'/accounts').json())
    r=propose([dict(operation='create_account',name='หมดสิทธิ์',kind='asset')])
    with SessionLocal.begin() as db:
        replacement=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(user_id=replacement.id,workspace_id=w,role='owner'));db.flush()
        db.delete(db.get(Membership,(u.id,w)))
    assert confirm(r).status_code==404


def test_duplicate_names_targets_and_plan_limits(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    existing=next(a for a in c.get(b+'/accounts').json() if a['kind']=='asset')
    cases=[
        [dict(operation='create_account',name=existing['name'],kind='asset')],
        [dict(operation='rename_account',account_id=existing['id'],name='หนึ่ง'),dict(operation='rename_account',account_id=existing['id'],name='สอง')],
        [dict(operation='create_account',name=f'บัญชี{i}',kind='asset') for i in range(11)],
    ]
    for ops in cases:
        r=propose(ops);assert 'ยังเตรียมแผนนี้ไม่ได้' in r['content']
    assert c.get(b+'/assistant-changes').json()['items']==[]


def test_changed_goal_and_copy_source_block_whole_plan(secretary):
    from datetime import timedelta
    c,w,u,b,cid,state,propose,confirm=secretary
    r=propose([dict(operation='create_goal',name='เป้าทดสอบ',target=10000)]);confirm(r)
    g=c.get(b+'/goals').json()['items'][0]
    r=propose([dict(operation='create_account',name='ต้องไม่สร้าง',kind='asset'),dict(operation='edit_goal',goal_id=g['id'],name=g['name'],target=20000,due_on=None)])
    with SessionLocal.begin() as db:db.get(Goal,g['id']).version+=1
    confirm(r);assert not any(a['name']=='ต้องไม่สร้าง' for a in c.get(b+'/accounts').json())
    previous=(today().replace(day=1)-timedelta(days=1)).strftime('%Y-%m');month=today().strftime('%Y-%m');cat=next(a for a in c.get(b+'/accounts').json() if a['kind']=='expense')
    c.put(b+f'/budgets/{previous}/{cat["id"]}',json={'amount':10000})
    r=propose([dict(operation='copy_budgets',month=month)])
    c.put(b+f'/budgets/{previous}/{cat["id"]}',json={'amount':20000})
    confirm(r);assert c.get(b+'/budgets',params={'month':month}).json()['items']==[]


def test_history_pagination_and_member_read_only_survives_chat_deletion(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary
    for i in range(11):
        r=propose([dict(operation='create_account',name=f'ประวัติ{i}',kind='asset')]);confirm(r)
    first=c.get(b+'/assistant-changes').json();second=c.get(b+'/assistant-changes?page=2').json()
    assert len(first['items'])==10 and first['has_more'] and len(second['items'])==1 and not second['has_more']
    assert set(first['items'][0])=={'id','summary','created_at','actor'}
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password');db.add(Membership(user_id=other.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as member:
        member.post('/auth/login',json={'email':other.email,'password':'secure-test-password'})
        assert len(member.get(b+'/assistant-changes').json()['items'])==10
        assert member.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน','review_message_id':r['id']}).status_code==404
    c.delete(b+f'/conversations/{cid}')
    assert len(c.get(b+'/assistant-changes?page=2').json()['items'])==1


def test_management_stream_tool_is_not_visible_text(monkeypatch):
    from app.assistant_response import read_stream
    from app import chat_stream
    seen=[];monkeypatch.setattr(chat_stream,'publish',lambda *a,**kw:seen.append(kw))
    parts=[{'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'prepare_management_','arguments':'{"operations":'}}]}}]},
           {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'plan','arguments':'[]}'}}]},'finish_reason':'tool_calls'}]}]
    result=read_stream(httpx.Response(200,text=''.join('data: '+json.dumps(p)+'\n\n' for p in parts)+'data: [DONE]\n\n'),object())
    assert result.tool_name=='prepare_management_plan' and result.draft=='{"operations":[]}' and seen==[]


def test_edit_pending_plan_keeps_original_operations_as_context(secretary):
    c,w,u,b,cid,state,propose,confirm=secretary;month=today().strftime('%Y-%m')
    ops=[dict(operation='create_account',name='แมว',kind='expense',ref='pet'),dict(operation='set_budget',category_id='@pet',month=month,amount=200000)]
    old=propose(ops)
    ops[1]['amount']=300000
    fresh=propose(ops,'จริง ๆ 3000 บาท')
    systems=[m['content'] for m in state['body']['messages'] if m['role']=='system']
    assert any('แผนเดิมที่ยังไม่ยืนยัน' in m and '200000' in m and '@pet' in m for m in systems)
    assert '฿3,000.00' in fresh['content'] and 'แผนจัดการ 2 ขั้นตอน' in fresh['content']
    confirm(old);assert not any(a['name']=='แมว' for a in c.get(b+'/accounts').json())
    # The failed stale confirmation is itself an assistant message: re-review the current plan.
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ทวนอีกที'})
    review=c.get(b+f'/conversations/{cid}/messages').json()[-1];confirm(review)
    assert c.get(b+'/budgets',params={'month':month}).json()['items'][0]['amount']==300000
    assert sum(a['name']=='แมว' for a in c.get(b+'/accounts').json())==1
