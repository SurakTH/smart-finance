"""Regression coverage for the five findings in the 2026-10-14 AI audit."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Conversation,Message,ChatAction,TelegramDelivery
from test_assistant_finance import assistant,tool
from test_telegram_assistant import channel,Sender

@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    from app import finance_chat,reporting
    monkeypatch.setattr(finance_chat,'today',lambda:date(2026,10,14))
    monkeypatch.setattr(reporting,'today',lambda:date(2026,10,14))


def test_fixed_abbreviated_month_overrides_correct_model_month(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กันยายน','2026-09-15');post(90000,'ตุลาคม','2026-10-10')
    state['responses']=[tool('answer_finance_summary',{'report':'monthly','month':'2026-09'})]
    text=send('รายจ่าย ก.ย. 2569 เท่าไหร่')['content']
    assert '2026-09' in text and '80.00' in text and '900.00' not in text


def test_description_total_preserves_user_filter(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-11')
    state['responses']=[tool('query_finance',{'operation':'search_transactions','q':'กาแฟ','start':'2026-10-01','end':'2026-10-31'}),{'content':'กาแฟเดือนนี้ 80.00 บาทค่ะ'}]
    text=send('กาแฟเดือนนี้ใช้ไปเท่าไหร่')['content']
    assert '80.00' in text and '1,000.00' not in text
    result=json.loads(state['calls'][-1]['messages'][-1]['content'])
    assert result['matches_shown']==1 and result['items'][0]['amount']==8000


def test_comparison_uses_complete_verified_monthly_data(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กันยายน','2026-09-15');post(90000,'ตุลาคม','2026-10-10')
    state['responses']=[tool('query_finance',{'operation':'monthly_analysis','month':'2026-10'}),{'content':'เดือนนี้ 900 บาท เดือนก่อน 80 บาทค่ะ'}]
    text=send('เปรียบเทียบรายจ่ายเดือนนี้กับเดือนก่อนให้หน่อย')['content']
    assert '900.00' in text and '80.00' in text and 'เปรียบเทียบ' in text
    data=json.loads(state['calls'][-1]['messages'][-1]['content'])
    assert data['expense']==90000 and data['previous']['expense']==8000


def test_budget_remaining_uses_verified_backend_spending(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    assert c.put(b+'/budgets/2026-10/'+cat,json={'amount':50000}).status_code==200
    state['responses']=[tool('query_finance',{'operation':'monthly_analysis','month':'2026-10'}),{'content':'งบเดือนนี้เหลือ 420 บาทค่ะ'}]
    text=send('งบเดือนนี้เหลือเท่าไหร่')['content']
    assert '420.00' in text and '500.00' in text and '80.00' in text
    data=json.loads(state['calls'][-1]['messages'][-1]['content'])
    assert data['budgets']['remaining']==42000


def test_search_result_preserves_date_account_and_selection_numbers(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(8000,'กาแฟ','2026-10-11')
    state['responses']=[tool('query_finance',{'operation':'search_transactions','q':'กาแฟ','start':'2026-10-01','end':'2026-10-31'}),{'content':'พบสองรายการค่ะ'}]
    text=send('ค้นรายการกาแฟ')['content']
    assert text.count('80.00 บาท')==2
    assert '2026-10-10' in text and '2026-10-11' in text
    assert '1.' in text and '2.' in text and 'เงินสด' in text


def test_telegram_confirm_result_is_durable_and_retried_without_posting_again(channel):
    from app.bot import capture as receive
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',amount=8000,description='กาแฟ',account_id=wallet,category_id=cat,occurred_on='2026-10-14'))]
    capture(1,'จดกาแฟ 80');process();asyncio.run(deliver_once(Sender()))
    async def failure(text,**kwargs):raise RuntimeError('synthetic Telegram connection failure')
    msg=SimpleNamespace(chat=SimpleNamespace(type='private'),from_user=SimpleNamespace(id=tid),photo=None,caption=None,text='ยืนยัน',message_id=2,answer=failure)
    asyncio.run(receive(msg,Sender()))  # capture commits and queues, never sends inline
    assert len(c.get(b+'/transactions').json())==1
    assert asyncio.run(deliver_once(Sender(fail=True)))
    with SessionLocal.begin() as db:
        delivery=db.scalar(select(TelegramDelivery).where(TelegramDelivery.workspace_id==w,TelegramDelivery.status=='pending'))
        assert delivery and delivery.job_id is None and delivery.reply_message_id
        delivery.next_attempt=0
    bot=Sender();assert asyncio.run(deliver_once(bot))
    assert 'บันทึกรายการเรียบร้อย' in bot.sent[0][1]
    assert len(c.get(b+'/transactions').json())==1


@pytest.mark.parametrize('word',['ก.ย. 2569','กันยายน 2569','2026-09'])
def test_month_forms_share_the_same_verified_scope(assistant,word):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กันยายน','2026-09-15');post(90000,'ตุลาคม','2026-10-10')
    state['responses']=[tool('answer_finance_summary',{'report':'monthly','month':'2026-09'})]
    content=send('รายจ่าย '+word+' เท่าไหร่')['content']
    assert '80.00' in content and '900.00' not in content and '2026-09' in content


@pytest.mark.parametrize('word',['เดือน 9','2026/09','ก.ย. 2569 กับ ต.ค. 2569'])
def test_unresolved_date_never_defaults_to_current_month(assistant,word):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(90000,'ตุลาคม','2026-10-10')
    state['responses']=[tool('answer_finance_summary',{'report':'monthly'})]
    content=send('รายจ่าย '+word+' เท่าไหร่')['content']
    assert '900.00' not in content and 'ระบุ' in content


def test_filtered_total_includes_all_matches_and_followup_keeps_filter(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    for i in range(13):post(8000,'กาแฟ','2026-10-10')
    post(92000,'อาหาร','2026-10-11')
    state['responses']=[tool('query_finance',{'operation':'search_transactions','q':'กาแฟ','start':'2026-10-01','end':'2026-10-31'}),{'content':'กาแฟ 800 บาทค่ะ'}]
    content=send('กาแฟเดือนนี้ใช้ไปเท่าไหร่')['content']
    assert '1,040.00' in content and '1,960.00' not in content
    assert any(r['filters'].get('q')=='กาแฟ' for r in c.get(b+f'/conversations/{cid}/messages').json()[-1]['references'])
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='เดือนนี้',q='กาแฟ',metric='expense')),{'content':'กาแฟรวม 1,040.00 บาทค่ะ'}]
    assert '1,040.00' in send('ต่อ')['content']


def test_list_number_is_bound_to_displayed_entry_for_correction(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    first=post(8000,'กาแฟ','2026-10-10');second=post(9000,'กาแฟ','2026-10-11')
    state['responses']=[tool('answer_finance_summary',{'report':'monthly'})]
    content=send('กาแฟเดือนนี้มีรายการอะไรบ้าง')['content']
    assert '1.' in content and '2.' in content
    with SessionLocal() as db:shown=db.get(Conversation,cid).capture_context['finance_search']['items']
    state['responses']=[tool('load_toolkit',{'toolkit':'corrections'}),tool('prepare_correction',{'entry_id':shown[1]['id'],'changes':{'amount':7500},'reason':'ผู้ใช้เลือกรายการสอง'})]
    review=send('แก้รายการที่ 2 เป็น 75 บาท')['content']
    assert '75.00' in review and 'กรุณาตรวจสอบ' in review
    with SessionLocal() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.status=='pending'))
        assert action.payload['target']==shown[1]['id']


def test_sync_review_requires_complete_delivery_before_plain_confirm(channel):
    from app.telegram_chat import deliver_once
    from test_chat_actions import CREATE
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    assert 'กรุณาตรวจสอบ' in capture(1,CREATE)
    assert 'ยังส่งข้อความทวนล่าสุดให้ไม่ครบ' in capture(2,'ยืนยัน')
    assert c.get(b+'/transactions').json()==[]
    bot=Sender()
    while asyncio.run(deliver_once(bot)):pass
    assert 'กรุณาตรวจสอบ' in bot.sent[0][1]
    assert 'บันทึกรายการเรียบร้อย' in capture(3,'ยืนยัน')
    assert len(c.get(b+'/transactions').json())==1


@pytest.mark.parametrize('text,expected',[
    ('รายรับเงินเดือนเดือนนี้เท่าไหร่','เงินเดือน'),
    ('ค่าหนังสือเดือนนี้ใช้ไปเท่าไร','หนังสือ'),
    ('ค่ากับข้าวเดือนนี้เท่าไหร่','กับข้าว'),
    ('เดือนนี้ใช้เยอะไหม ช่วยวิเคราะห์หน่อย',''),
    ('กาแฟเดือนนี้มีรายการอะไรบ้าง','กาแฟ'),
])
def test_subject_request_grammar_never_erases_words_inside_names(text,expected):
    from app.assistant_scope import subject
    assert subject(text,[])==expected


def test_model_month_mismatch_is_repaired_not_broadened(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กันยายน','2026-09-15');post(90000,'ตุลาคม','2026-10-10')
    state['responses']=[tool('answer_finance_summary',{'report':'monthly','month':'2026-10'}),tool('answer_finance_summary',{'report':'monthly','month':'2026-09'})]
    content=send('รายจ่าย ก.ย. 2569 เท่าไหร่')['content']
    assert '80.00' in content and '900.00' not in content and len(state['calls'])==2
