import json
import uuid
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.db import SessionLocal
from app.models import Account,ChatAction,Conversation,Message,Provider,now,message_time
from app.reporting import today
from app.assistant_tools import all_tools,catalog
from app.assistant_context import clarification
from test_assistant_finance import assistant,tool,result,search
from test_ai_review_contract import draft
from test_secretary import transport
from test_chat_actions import count


def test_catalog_is_small_then_loads_management_and_confirms_plan(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    assert len(json.dumps(catalog(set())))<len(json.dumps(all_tools()))*.75
    def plan(body):
        assert result(body)['available']
        assert 'prepare_management_plan' in {t['function']['name'] for t in body['tools']}
        return tool('prepare_management_plan',{'operations':[{'operation':'create_goal','name':'วันพักผ่อน','target':100000}]})
    state['responses']=[tool('load_toolkit',{'toolkit':'management'}),plan]
    value=send('ช่วยสร้างเป้าออมสำหรับวันพักผ่อน 1000 บาท')
    assert 'prepare_management_plan' not in {t['function']['name'] for t in state['calls'][0]['tools']}
    assert 'แผนจัดการ' in value['content'] and c.get(b+'/goals').json()['items']==[]
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert c.get(b+'/goals').json()['items'][0]['target']==100000


def test_bad_draft_repairs_amount_type_without_asking_user_to_restart(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    bad=tool('prepare_transaction',dict(intent='create',kind='expense',description='อาหาร',amount='13860',account_id=wallet,category_id=cat))
    def repair(body):
        feedback=result(body)
        assert feedback['error']=='invalid_arguments' and {'field':'amount','code':'int_type'} in feedback['issues']
        return draft(wallet,cat)
    state['responses']=[bad,repair]
    assert 'กรุณาตรวจสอบ' in send('ช่วยจดอาหาร 138.60 บาท')['content'] and count(w)==0
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'});assert count(w)==1


def test_wrong_id_recovers_by_lookup_before_review(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[draft(str(uuid.uuid4()),cat),tool('lookup_workspace',{'queries':[{'resource':'accounts'}]}),draft(wallet,cat)]
    answer=send('จดอาหาร 138.60 จากเงินสด')
    assert 'กรุณาตรวจสอบ' in answer['content'] and count(w)==0
    error=json.loads(state['calls'][1]['messages'][-1]['content'])
    assert error['error']=='invalid_reference' and error['issues'][0]['code']=='unknown_reference'


def test_invalid_read_does_not_spend_successful_read_budget(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts','limit':50}]}),tool('lookup_workspace',{'queries':[{'resource':'accounts','limit':20}]}),draft(wallet,cat)]
    assert 'กรุณาตรวจสอบ' in send('ช่วยจดอาหาร 138.60 บาท')['content'] and len(state['calls'])==3


def test_lookup_cache_treats_omitted_and_empty_defaults_the_same(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'balances'}]}),tool('lookup_workspace',{'queries':[{'resource':'balances','q':None,'limit':None,'cursor':''}]})]
    assert 'ยอดคงเหลือ' in send('ตอนนี้มีเงินเท่าไร')['content'] and len(state['calls'])==2


def test_partial_draft_survives_history_window_and_expires(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='ค่าอาหารที่คุยค้าง',category_id=cat,account_id=wallet))]
    assert 'ยอดเท่าไหร่' in send('ช่วยจดค่าอาหารที่คุยค้าง')['content']
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        assert room.capture_context['ai_followup']['field']=='amount'
        for i in range(24):db.add(Message(workspace_id=w,conversation_id=cid,role='assistant',content='ข้อความอื่น '+str(i),created_at=message_time(db,w,cid)));db.flush()
    state['responses']=[draft(wallet,cat)]
    send('ยอด 138.60 บาท')
    system=' '.join(m['content'] for m in state['calls'][-1]['messages'] if m['role']=='system')
    assert 'ค่าอาหารที่คุยค้าง' in system and '"missing": "amount"' in system
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);assert 'ai_followup' not in room.capture_context
        room.capture_context={'ai_followup':{'expires':now()-1,'draft':{'description':'EXPIRED'}}}
        assert clarification(room) is None


def test_total_provider_requests_are_bounded_across_retries_and_fallback(assistant,monkeypatch):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        db.scalar(select(Provider).where(Provider.workspace_id==w)).retries=2
        db.add_all(Provider(workspace_id=w,task='chat',kind='ollama',model='fallback'+str(i),priority=i+20,retries=2) for i in range(2))
    def busy(body):raise httpx.ConnectError('synthetic unavailable')
    state['responses']=[busy]*8
    value=send('สวัสดี')
    assert len(state['calls'])==8 and 'จำนวนรอบ' in value['content'] and count(w)==0


def test_asking_account_does_not_dump_hundreds_of_names(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:db.add_all(Account(workspace_id=w,name='กระเป๋า-'+str(i),kind='asset') for i in range(100))
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='อาหาร',amount=8000,category_id=cat))]
    answer=send('ช่วยจดอาหาร 80 บาท')['content']
    assert 'ใช้บัญชีไหน' in answer and answer.count('กระเป๋า-')<=6 and len(answer)<1000


def test_batch_clarification_preserves_every_item_until_confirmation(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    first=dict(intent='create',kind='expense',description='ข้าว',account_id=wallet,category_id=cat)
    second={**first,'description':'น้ำ','amount':3000}
    state['responses']=[tool('prepare_transaction',dict(intent='create',transactions=[first,second]))]
    assert 'ยอดเท่าไหร่' in send('ช่วยจดข้าวกับน้ำ น้ำ 30 บาท')['content']
    with SessionLocal() as db:
        pending=db.get(Conversation,cid).capture_context['ai_followup']
        assert pending['field']=='transactions.0.amount' and len(pending['draft']['transactions'])==2
    state['responses']=[tool('prepare_transaction',dict(intent='create',transactions=[{**first,'amount':5000},second]))]
    assert '2 รายการ' in send('ข้าว 50 บาท')['content'] and count(w)==0
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert count(w)==2


def test_failed_continuation_reuses_read_result_without_repeating_provider(assistant,monkeypatch):
    from app import assistant_lookup
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:db.scalar(select(Provider).where(Provider.workspace_id==w)).retries=1
    reads=[];original=assistant_lookup.read
    def tracked(*args):reads.append(1);return original(*args)
    monkeypatch.setattr(assistant_lookup,'read',tracked)
    def fail(body):raise httpx.ConnectError('synthetic interrupted request')
    query=tool('lookup_workspace',{'queries':[{'resource':'accounts'}]})
    state['responses']=[query,fail]
    assert 'เงินสด' in send('มีบัญชีอะไรบ้าง')['content'] and len(reads)==1 and len(state['calls'])==2
