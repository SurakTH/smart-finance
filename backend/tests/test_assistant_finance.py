import json
import uuid
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.db import SessionLocal
from app.models import Provider,ChatAction,Conversation,Membership,Account
from app.worker import run_once
from app.reporting import today
from app.assistant_finance import read
from test_chat_actions import setup,say

@pytest.fixture
def assistant(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='assistant',task='chat',retries=0))
    accounts=c.get(b+'/accounts').json();wallet=next(a['id'] for a in accounts if a['kind']=='asset');cat=next(a['id'] for a in accounts if a['kind']=='expense');state={'calls':[],'responses':[]};real=httpx.Client
    def handler(req):
        body=json.loads(req.content);state['calls'].append(body)
        if 'tools' in body:assert {'query_finance','load_toolkit'}<={t['function']['name'] for t in body['tools']}
        else:assert 'tool_choice' not in body  # bounded final text-only synthesis
        answer=state['responses'].pop(0)
        if callable(answer):answer=answer(body)
        if isinstance(answer,httpx.Response):return answer
        return httpx.Response(200,json={'choices':[{'message':answer}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    def post(amount=9000,description='กาแฟ',on=None):
        r=c.post(b+'/transactions',json=dict(kind='expense',description=description,amount=amount,account_id=wallet,category_id=cat,occurred_on=on or today().isoformat(),idempotency_key=str(uuid.uuid4())));assert r.status_code==200;return r.json()['id']
    def send(text):
        say(c,b,cid,text)
        while run_once():pass
        return c.get(b+f'/conversations/{cid}/messages').json()[-1]
    return c,w,u,b,cid,wallet,cat,state,post,send

def tool(name,args):return {'tool_calls':[{'id':'call_finance_123','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
def search(**kw):return tool('query_finance',dict(operation='search_transactions',**kw))
def result(body):return json.loads(body['messages'][-1]['content'])

def test_search_and_correct_from_natural_request_preserves_ledger_until_confirm(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;eid=post()
    state['responses']=[search(q='กาแฟ',amount=9000),lambda body: tool('prepare_correction',dict(entry_id=result(body)['items'][0]['id'],changes={'amount':7500},reason='ผู้ใช้แก้ยอดกาแฟ'))]
    review=send('ค่ากาแฟวันนี้ที่ลง90 จริง ๆ 75 บาท ช่วยแก้ให้ที')
    assert len(state['calls'])==2 and 'ก่อนแก้ไข:' in review['content'] and '฿90.00' in review['content'] and '฿75.00' in review['content']
    assert c.get(b+'/transaction-report').json()['expense']==9000
    assert state['calls'][-1]['messages'][-1]['role']=='tool' and state['calls'][-1]['messages'][-1]['tool_call_id']=='call_finance_123'
    assert c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'}).status_code==200
    assert 'เก็บประวัติเดิม' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert c.get(b+'/transaction-report').json()['expense']==7500
    assert c.get(b+'/transactions/'+eid).json()['status']=='corrected'
    say(c,b,cid,'ยืนยัน');assert c.get(b+'/transaction-history').json()['total']==1


def test_ambiguous_results_require_user_choice_and_prevent_self_narrowing(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;first=post(description='กาแฟ A');second=post(description='กาแฟ B')
    state['responses']=[search(q='กาแฟ'),search(q='กาแฟ B'),tool('prepare_correction',dict(entry_id=second,changes={'amount':7500},reason='แก้ยอด'))]
    reply=send('ช่วยแก้ค่ากาแฟวันนี้เป็น75')
    assert 'พบหลายรายการ' in reply['content']
    with SessionLocal() as db:
        room=db.get(Conversation,cid);items=room.capture_context['finance_search']['items'];assert len(items)==2
        selected=items[1]['id']
        assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
    state['responses']=[tool('prepare_correction',dict(entry_id=selected,changes={'amount':7500},reason='ผู้ใช้เลือกรายการ2'))]
    review=send('รายการที่ 2 ค่ะ')
    assert 'ก่อนแก้ไข:' in review['content'];say(c,b,cid,'ยืนยัน')
    assert c.get(b+'/transactions/'+selected).json()['status']=='corrected'
    assert c.get(b+'/transactions/'+(second if selected==first else first)).json()['status']=='active'


def test_selected_item_cannot_be_swapped_by_model(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post();post()
    state['responses']=[search(q='กาแฟ'),{'content':'มีสองรายการ เลือกรายการไหนคะ?'}];send('ช่วยแก้กาแฟเป็น75')
    with SessionLocal() as db:items=db.get(Conversation,cid).capture_context['finance_search']['items']
    state['responses']=[tool('prepare_correction',dict(entry_id=items[0]['id'],changes={'amount':7500},reason='wrong item'))]
    r=send('รายการที่ 2')
    assert 'ยังไม่ตรง' in r['content']
    assert c.get(b+'/transaction-history').json()['total']==0


def test_month_analysis_uses_backend_totals_then_prepares_budget_plan(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;month=today().strftime('%Y-%m');previous=(today().replace(day=1)-timedelta(days=1)).isoformat()
    post(150000);post(100000,on=previous)
    c.put(b+f'/budgets/{month}/{cat}',json={'amount':120000})
    def plan(body):
        data=result(body)
        assert data['expense']==150000 and data['previous']['expense']==100000
        assert data['budgets']['remaining']==-30000 and data['unit']=='THB_satang'
        return tool('prepare_management_plan',dict(operations=[dict(operation='set_budget',category_id=cat,month=month,amount=180000)]))
    state['responses']=[tool('query_finance',dict(operation='monthly_analysis',month=month)),plan]
    review=send('ช่วยสรุปเดือนนี้ แล้วปรับงบอาหารให้หน่อยได้ไหม')
    assert '฿1,200.00 → หลัง: ฿1,800.00' in review['content']
    assert c.get(b+'/budgets',params={'month':month}).json()['planned']==120000
    say(c,b,cid,'ยืนยัน');assert c.get(b+'/budgets',params={'month':month}).json()['planned']==180000
    assert c.get(b+'/transaction-report').json()['expense']==250000


def test_read_only_analysis_does_not_create_action(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(10000)
    state['responses']=[tool('query_finance',dict(operation='monthly_analysis')),{'content':'เดือนนี้ใช้ไป100บาทค่ะ ยังไม่เปลี่ยนงบนะคะ'}]
    r=send('เดือนนี้ใช้เยอะไหม ช่วยวิเคราะห์หน่อย')
    assert '100.00 บาท' in r['content']
    with SessionLocal() as db:assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))

@pytest.mark.parametrize('query',[
    dict(operation='search_transactions',start='2020-01-01',end='2026-01-01'),
    dict(operation='search_transactions',account_id=str(uuid.uuid4())),
    dict(operation='search_transactions',sql='SELECT * FROM users'),
    dict(operation='search_transactions',amount=True),
    dict(operation='monthly_analysis',month='2026-99'),
    dict(operation='monthly_analysis',account_id=str(uuid.uuid4())),
])
def test_invalid_queries_are_sanitized(assistant,query):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        r=read(db,db.get(Conversation,cid),json.dumps(query),'turn');assert r['error']=='invalid_query';assert 'SELECT' not in json.dumps(r)


def test_search_caps_results_and_escapes_wildcards(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    for i in range(12):post(description='กาแฟ'+str(i))
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        data=read(db,room,json.dumps(dict(operation='search_transactions',q='กาแฟ')),'turn')
        assert len(data['items'])==10 and data['has_more'] and data['must_ask_user']
        assert read(db,room,json.dumps(dict(operation='search_transactions',q='%')),'turn')['items']==[]


def test_model_cannot_correct_unsearched_or_expired_target(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;eid=post()
    args=dict(entry_id=eid,changes={'amount':7500},reason='แก้ยอด')
    state['responses']=[tool('prepare_correction',args)]
    assert 'ขอค้นหา' in send('ช่วยแก้กาแฟเป็น75')['content']
    state['responses']=[search(q='กาแฟ'),{'content':'เจอรายการค่ะ'}];send('ค้นหากาแฟ')
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);context=dict(room.capture_context);context['finance_search']={**context['finance_search'],'expires':1};room.capture_context=context
    state['responses']=[tool('prepare_correction',args)]
    assert 'ขอค้นหา' in send('ช่วยแก้เป็น75')['content']


def test_read_loop_is_bounded(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[search(q='กาแฟ')]*2
    r=send('ช่วยค้นหากาแฟหน่อย')
    assert 'ไม่พบรายการ' in r['content'] and len(state['calls'])==2
    assert not state['responses']


def test_analysis_based_budget_plan_blocks_changed_ledger(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(10000);month=today().strftime('%Y-%m')
    state['responses']=[tool('query_finance',dict(operation='monthly_analysis',month=month)),tool('prepare_management_plan',dict(rationale='เผื่อรายจ่ายที่ผู้ใช้ขอปรับ',operations=[dict(operation='set_budget',category_id=cat,month=month,amount=20000)]))]
    r=send('ช่วยวิเคราะห์แล้วปรับงบให้หน่อย')
    assert 'ข้อมูลจริงจากระบบ' in r['content'] and 'รายจ่าย ฿100.00' in r['content'] and 'ข้อเสนอจากผู้ช่วย' in r['content']
    post(5000);say(c,b,cid,'ยืนยัน')
    assert 'ข้อมูลเปลี่ยน' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert c.get(b+'/budgets',params={'month':month}).json()['planned']==0

@pytest.mark.parametrize('changes',[
    {'amount':True},{'amount':0},{'amount':12.2},{'kind':'income'}, {'account_id':str(uuid.uuid4())},{'description':' '},{'category_id':None},{}
])
def test_correction_validation_rejects_untrusted_patch(assistant,changes):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;eid=post()
    state['responses']=[search(q='กาแฟ'),tool('prepare_correction',dict(entry_id=eid,changes=changes,reason='แก้ยอด'))]
    state['responses'].append(state['responses'][-1])  # Invalid drafts get one repair opportunity.
    r=send('ช่วยแก้กาแฟหน่อย')
    assert 'ยังเตรียมการแก้ไขไม่ได้' in r['content']
    with SessionLocal() as db:assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
    assert c.get(b+'/transaction-report').json()['expense']==9000


def test_foreign_account_and_explicit_entry_ids_stay_scoped(assistant):
    from app.bootstrap import create_user
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;eid=post()
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password');other_w=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id));foreign=db.scalar(select(Account.id).where(Account.workspace_id==other_w,Account.kind=='asset'))
    state['responses']=[search(q='กาแฟ'),tool('prepare_correction',dict(entry_id=eid,changes={'account_id':foreign},reason='แก้บัญชี'))]
    state['responses'].append(state['responses'][-1])
    assert 'ยังเตรียมการแก้ไขไม่ได้' in send('ช่วยแก้บัญชีค่ากาแฟ')['content']
    with SessionLocal.begin() as db:
        reply=read(db,db.get(Conversation,cid),json.dumps(dict(operation='search_transactions',account_id=foreign)),'turn')
        assert reply['error']=='invalid_query'


def test_correction_search_ignores_superseded_original_and_reversal(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;eid=post()
    tx=dict(kind='expense',description='กาแฟ',amount=7500,account_id=wallet,category_id=cat,occurred_on=today().isoformat(),idempotency_key=str(uuid.uuid4()))
    corrected=c.post(b+'/transactions/'+eid+'/correct',json=dict(reason='แก้ในหน้ารายการ',idempotency_key=str(uuid.uuid4()),transaction=tx)).json()
    with SessionLocal.begin() as db:
        found=read(db,db.get(Conversation,cid),json.dumps(dict(operation='search_transactions',q='กาแฟ')),'turn')
        assert len(found['items'])==1 and found['items'][0]['id']==corrected['replacement']['id'] and found['items'][0]['amount']==7500
