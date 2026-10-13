"""Natural language plans use real scoped reads with mock model transport."""
import json
import uuid
from datetime import date
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Conversation,Message,ChatAction,Account,Job,now
from app.request_interpreter import Period,date_range,NeedInfo
from test_assistant_finance import assistant,tool
from test_telegram_assistant import channel,Sender

@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    from app import request_interpreter,reporting,finance_chat
    for module in (request_interpreter,reporting,finance_chat):monkeypatch.setattr(module,'today',lambda:date(2026,10,14))


def plan(intent='period',**kw):return tool('interpret_request',{'intent':intent,**kw})

@pytest.mark.parametrize('prompt,period,start,end',[
    ('อาทิตย์ก่อนฉันจ่ายอะไรบ้าง',dict(mode='previous_week',phrase='อาทิตย์ก่อน'),'2026-10-05','2026-10-11'),
    ('ช่วยดูรายจ่ายเจ็ดวันที่ผ่านมาให้ที',dict(mode='last_days',phrase='เจ็ดวันที่ผ่านมา',days=7),'2026-10-08','2026-10-14'),
    ('รายจ่ายตั้งแต่ต้นเดือนถึงวันนี้',dict(mode='month_to_date',phrase='ตั้งแต่ต้นเดือนถึงวันนี้'),'2026-10-01','2026-10-14'),
    ('รายจ่ายกันยาเป็นไงบ้าง',dict(mode='month',phrase='กันยา',month='2026-09'),'2026-09-01','2026-09-30'),
    ('รายจ่ายเดือน 9 เท่าไหร่',dict(mode='month',phrase='เดือน 9',month='2026-09'),'2026-09-01','2026-09-30'),
])
def test_varied_date_phrases_answer_in_one_request(assistant,prompt,period,start,end):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ',start);post(90000,'นอกช่วง','2026-10-20')
    state['responses']=[plan(period=period)]
    content=send(prompt)['content']
    assert start in content and end in content and '80.00' in content and '900.00' not in content
    assert len(state['calls'])==1
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


def test_casual_month_mention_is_not_a_financial_report(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('conversation',reply='งานเยอะเลยสินะคะ พักสักนิดแล้วค่อยจัดลำดับงานกันค่ะ')]
    content=send('เดือนนี้งานเยอะมากเลย')['content']
    assert 'พักสักนิด' in content and 'รายจ่าย' not in content


def test_plan_cannot_turn_money_question_into_unverified_casual_numbers(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('conversation',reply='999999')]
    content=send('ตอนนี้ฉันมีเงินเท่าไร')['content']
    assert '999999' not in content and 'ดูข้อมูล' in content


def test_read_plan_preserves_explicit_coffee_filter(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-10')
    state['responses']=[plan(period=dict(mode='current_month',phrase='เดือนนี้'),q='กาแฟ')]
    content=send('กาแฟเดือนนี้ใช้ไปเท่าไหร่')['content']
    assert '80.00' in content and '1,000.00' not in content
    state['responses']=[plan(period=dict(mode='current_month',phrase='เดือนนี้'))]
    content=send('กาแฟเดือนนี้ใช้ไปเท่าไหร่')['content']
    assert '1,000.00' not in content and 'คำที่จะค้น' in content


def test_ambiguous_account_is_asked_not_chosen(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    assert c.post(b+'/accounts',json={'name':'เงินสดสำรอง','kind':'asset'}).status_code==200
    state['responses']=[plan('balances',account=dict(phrase='เงินสด',name='เงินสด'))]
    content=send('ดูยอดเงินสดหน่อย')['content']
    assert 'บัญชีไหน' in content and '0.00' not in content


def test_partial_account_name_resolves_only_when_unique(assistant):
    from test_balance_summary import opening
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    bank=c.post(b+'/accounts',json={'name':'ธนาคารกสิกร','kind':'asset'}).json()['id'];opening(c,b,bank,12345)
    state['responses']=[plan('balances',account=dict(phrase='กสิกร'))]
    content=send('ขอดูเงินในกสิกรหน่อย')['content']
    assert '123.45' in content


def test_clarification_then_account_reply_uses_original_period(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-06')
    state['responses']=[plan('clarify',missing='account')]
    assert 'บัญชีไหน' in send('อาทิตย์ก่อนใช้ไปเท่าไร')['content']
    with SessionLocal() as db:
        old=db.get(Conversation,cid).capture_context['request_clarification']['source_message_id']
    state['responses']=[plan(source_message_id=old,period=dict(mode='previous_week',phrase='อาทิตย์ก่อน'),account=dict(phrase='เงินสด',name='เงินสด'))]
    content=send('เงินสด')['content']
    assert '80.00' in content and '2026-10-05' in content
    assert 'request_clarification' in str(state['calls'][-1]['messages'])


def test_latest_period_cannot_be_replaced_by_historical_period(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('clarify',missing='account')];send('รายจ่ายกันยาเท่าไหร่')
    with SessionLocal() as db:old=db.get(Conversation,cid).capture_context['request_clarification']['source_message_id']
    state['responses']=[plan(source_message_id=old,period=dict(mode='month',phrase='กันยา',month='2026-09'))]
    assert 'ช่วงไหน' in send('แล้วเดือนนี้ล่ะ')['content']


@pytest.mark.parametrize('source_kind',['other_room','other_user','expired'])
def test_historical_source_is_owned_recent_and_same_room(assistant,source_kind):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    if source_kind=='other_user':
        from app.bootstrap import create_user
        with SessionLocal.begin() as db:owner=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
    else:owner=u
    with SessionLocal.begin() as db:
        room=Conversation(workspace_id=w,user_id=owner.id) if source_kind!='expired' else db.get(Conversation,cid)
        if source_kind!='expired':db.add(room);db.flush()
        message=Message(workspace_id=w,conversation_id=room.id,role='user',content='เดือนนี้',created_at=(now()-3600)*1000 if source_kind=='expired' else now()*1000)
        db.add(message);db.flush();mid=message.id
    state['responses']=[plan(source_message_id=mid,period=dict(mode='current_month',phrase='เดือนนี้'))]
    content=send('ช่วยดูรายจ่ายให้หน่อย')['content']
    assert 'ดูข้อมูล' in content and '0.00' not in content


@pytest.mark.parametrize('arguments',[
    {'workspace_id':'foreign'}, {'user_id':'foreign'}, {'sql':'DROP TABLE entries'},
    {'intent':'confirm'}, {'q':'คำที่ไม่ได้พูด'},
])
def test_unknown_authority_and_unquoted_filters_are_rejected(assistant,arguments):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    raw={'intent':'period','period':dict(mode='current_month',phrase='เดือนนี้'),**arguments}
    state['responses']=[tool('interpret_request',raw)]*2
    content=send('รายจ่ายเดือนนี้เท่าไร')['content']
    assert '0.00' not in content
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


@pytest.mark.parametrize('value',[
    dict(mode='last_days',phrase='เจ็ดวันที่ผ่านมา',days=3),
    dict(mode='month',phrase='ก.ย. 2569',month='2026-10'),
    dict(mode='current_month',phrase='อาทิตย์ก่อน'),
    dict(mode='range',phrase='2026-10-02 ถึง 2026-10-01',start='2026-10-02',end='2026-10-01'),
    dict(mode='current_month',phrase='เดือนนี้',start='2026-09-01'),
])
def test_model_dates_cannot_override_phrase(value):
    with pytest.raises(NeedInfo):date_range(Period(**value))


def test_natural_write_intent_routes_to_real_draft_and_still_requires_confirmation(assistant):
    from test_chat_actions import say,count
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('mutation',action='transaction'),tool('prepare_transaction',dict(intent='create',kind='expense',amount=8000,description='กาแฟ',account_id=wallet,category_id=cat,occurred_on='2026-10-14'))]
    content=send('ลืมลงกาแฟแปดสิบเมื่อเช้า ช่วยเก็บให้หน่อย')['content']
    assert 'กรุณาตรวจสอบ' in content and count(w)==0
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==1


def test_telegram_uses_same_interpreter_and_durable_answer(channel):
    import asyncio
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[plan(period=dict(mode='previous_week',phrase='อาทิตย์ก่อน'))]
    capture(1,'อาทิตย์ก่อนใช้ไปเท่าไร');process()
    bot=Sender();assert asyncio.run(deliver_once(bot))
    assert '2026-10-05' in bot.sent[0][1] and bot.sent[0][0]==tid


@pytest.mark.parametrize('value',[
    dict(mode='current_month',phrase='เดือนนี้กับเดือนก่อน'),
    dict(mode='last_days',phrase='เจ็ดวันที่ผ่านมาไม่รวมวันนี้',days=7),
    dict(mode='current_week',phrase='อาทิตย์นี้กับอาทิตย์ก่อน'),
])
def test_conflicting_period_phrase_requires_clarification(value):
    with pytest.raises(NeedInfo):date_range(Period(**value))


def test_interpreted_read_is_discarded_if_workspace_changes_during_model(assistant,pg_only):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def changed(body):
        assert c.post(b+'/accounts',json={'name':'ระหว่างรอ','kind':'asset'}).status_code==200
        return plan(period=dict(mode='current_month',phrase='เดือนนี้'))
    state['responses']=[changed]
    send('รายจ่ายเดือนนี้เท่าไหร่')
    with SessionLocal() as db:
        job=db.scalar(select(Job).where(Job.workspace_id==w))
        assert job.status=='failed' and job.error=='context_changed'
        assert not db.scalar(select(Message.id).where(Message.conversation_id==cid,Message.role=='assistant'))


def test_interpreted_comparison_preserves_description_filter(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(5000,'กาแฟ','2026-09-10');post(8000,'กาแฟ','2026-10-10');post(90000,'อาหาร','2026-10-10')
    state['responses']=[plan('comparison',period=dict(mode='current_month',phrase='เดือนนี้'),q='กาแฟ')]
    content=send('เปรียบเทียบค่ากาแฟเดือนนี้กับเดือนก่อน')['content']
    assert '80.00' in content and '50.00' in content and '30.00' in content and '980.00' not in content


def test_interpreted_transactions_show_rows_with_matching_scope(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-06');post(9000,'อาหาร','2026-10-07')
    state['responses']=[plan('transactions',period=dict(mode='previous_week',phrase='อาทิตย์ก่อน'),transaction_kind='expense')]
    content=send('อาทิตย์ก่อนจ่ายอะไรบ้าง')['content']
    assert '1.' in content and '2.' in content and '2026-10-06' in content and '2026-10-07' in content


def test_need_info_retains_owned_origin_for_followup(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan(period=dict(mode='month',phrase='เดือนก่อน',month='2026-10'))]
    assert 'ช่วงไหน' in send('รายจ่ายเดือนก่อนเท่าไหร่')['content']
    with SessionLocal() as db:
        pending=db.get(Conversation,cid).capture_context['request_clarification']
        original=db.get(Message,pending['source_message_id'])
        assert original.content=='รายจ่ายเดือนก่อนเท่าไหร่' and pending['missing']=='period'


def test_optional_null_query_does_not_require_model_repair(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan(period=dict(mode='current_month',phrase='เดือนนี้'),q=None)]
    assert '0.00' in send('รายจ่ายเดือนนี้เท่าไร')['content'] and len(state['calls'])==1


def test_tool_conversation_reply_strips_private_thinking(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('conversation',reply='<think>private synthetic reasoning</think>พักสักนิดได้เลยค่ะ')]
    content=send('เหนื่อยจังเลย')['content']
    assert 'พักสักนิด' in content and 'private' not in content and '<think>' not in content
