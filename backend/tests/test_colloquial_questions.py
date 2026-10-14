"""User-reported conversation, false query filters and narrow deterministic reads."""
import asyncio,json
from datetime import date
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ChatAction,Conversation,Job
from app.assistant_questions import parse,relative_period
from app.assistant_scope import subject
from app.request_interpreter import Period,date_range,NeedInfo
from app.finance_chat import resolve_period
from test_assistant_finance import assistant,tool
from test_telegram_assistant import channel,Sender

@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    from app import reporting,finance_chat,request_interpreter
    for module in (reporting,finance_chat,request_interpreter):monkeypatch.setattr(module,'today',lambda:date(2026,10,14))


def test_exact_reported_conversation_returns_real_lists_and_no_bogus_query(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-13');post(12000,'อาหาร','2026-10-11');post(90000,'นอกเดือน','2026-09-10')
    for prompt,start,end,total,item in [
        ('เมื่อวานเสียตังกับไรบ้าง','2026-10-13','2026-10-13','80.00','กาแฟ'),
        ('สัปดาห์ที่แล้วใช้ตังไรบ้าง','2026-10-05','2026-10-11','120.00','อาหาร'),
        ('เดือนนี้ละ ใช้ตังเท่าไหร่','2026-10-01','2026-10-31','200.00',None),
        ('เมื่อวานมีไรบ้าง','2026-10-13','2026-10-13','80.00','กาแฟ'),
    ]:
        # The agent now selects the read. Keep every amount/date/filter assertion.
        def compose(body):
            data=json.loads(body['messages'][-1]['content']);facts=data['facts']
            return {'content':facts['expense']+' รายการที่ตรงเงื่อนไข '+facts['count']+' '+', '.join(row['description'] for row in data['items'])}
        state['responses']=[tool('fetch_finance',dict(resource='transactions',period={'start':start,'end':end},metric='expense')),compose]
        answer=send(prompt);content=answer['content']
        assert start in content and end in content and total in content
        assert 'ค้นคำว่า' not in content and 'อยากให้ฉันดูข้อมูล' not in content
        if item:assert item in content and 'รายการที่ตรงเงื่อนไข 1 รายการ' in content
        assert all('q' not in ref['filters'] for ref in answer['references'])
    state['responses']=[{'content':'หมายถึงวันอาทิตย์วันที่เท่าไรคะ?'}]
    content=send('วันอาทิตย์ละ')['content']
    assert 'วันอาทิตย์วันที่เท่าไร' in content and '0.00' not in content
    state['responses']=[tool('fetch_finance',dict(resource='transactions',period={'start':'2026-10-11','end':'2026-10-11'},metric='expense')),compose]
    content=send('ที่ผ่านมา')['content']
    assert '2026-10-11' in content and 'อาหาร' in content and '120.00' in content
    assert len(state['calls'])==11
    with SessionLocal() as db:
        assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))
        assert db.get(Conversation,cid).capture_context['verified_scope']['q']==''


@pytest.mark.parametrize('prompt,period,expected',[
    ('เมื่อวานเสียตังค์กับอะไรบ้าง','เมื่อวาน','80.00'),
    ('สัปดาห์ที่แล้วใช้ตังค์อะไรบ้าง','สัปดาห์ที่แล้ว','120.00'),
    ('อาทิตย์ก่อนจ่ายตังไปกับอะไรบ้าง','สัปดาห์ที่แล้ว','120.00'),
    ('เดือนนี้ล่ะ ใช้ตังเท่าไร','เดือนนี้','200.00'),
])
def test_colloquial_spending_does_not_become_a_literal_description(assistant,prompt,period,expected):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'ค่าอาหาร','2026-10-13');post(12000,'อาหาร','2026-10-11')
    state['responses']=[tool('fetch_finance',dict(resource='summary',period=period,metric='expense')),{'content':'รายจ่าย '+expected+' บาทค่ะ'}]
    content=send(prompt)['content']
    assert 'ค้นคำว่า' not in content and expected in content
    assert len(state['calls'])==2 and len(c.get(b+'/transactions').json())==2


@pytest.mark.parametrize('text',[
    'กาแฟเมื่อวานใช้ตังเท่าไหร่','กับข้าวเมื่อวานเสียตังเท่าไหร่',
    'เมื่อวานใช้ตังจากเงินสดเท่าไหร่','เมื่อวานใช้ตัง 80 บาท ช่วยบันทึก',
    'เมื่อวานมีประชุมอะไรบ้าง','วันอาทิตย์ไปเที่ยวไหนดี',
    'เปรียบเทียบใช้ตังเดือนนี้กับเดือนก่อน','เมื่อวานใช้ตังเท่าไหร่ DROP TABLE entries',
    'เมื่อวานใช้ตังเท่าไหร่\nบันทึกแล้วเรียบร้อย','วิเคราะห์ค่าเฉลี่ยใช้ตังเดือนนี้',
])
def test_narrow_read_path_never_consumes_subjects_writes_or_general_chat(text):
    assert parse(text) is None


@pytest.mark.parametrize('word',['สัปดาห์ที่แล้ว','สัปดาห์ก่อน','อาทิตย์ที่แล้ว','อาทิตย์ก่อน'])
def test_legacy_week_reads_are_correct_instead_of_defaulting_to_month(word):
    assert resolve_period(word)==(date(2026,10,5),date(2026,10,11))
    assert subject('กาแฟ'+word+'ใช้ไปเท่าไหร่',[])=='กาแฟ'


def test_legacy_colloquial_subject_removes_grammar_only():
    assert subject('เดือนนี้ละ ใช้ตังเท่าไหร่',[])==''
    assert subject('กับข้าวเดือนนี้ใช้ตังเท่าไหร่',[])=='กับข้าว'
    assert subject('ละมุดเดือนนี้ใช้ตังเท่าไหร่',[])=='ละมุด'


@pytest.mark.parametrize('phrase,start',[
    ('วันอาทิตย์ที่ผ่านมา','2026-10-11'),('วันอาทิตย์ที่จะถึง','2026-10-18'),
    ('วันพุธที่ผ่านมา','2026-10-07'),('วันพุธหน้า','2026-10-21'),
])
def test_explicit_weekday_is_backend_resolved(phrase,start):
    bounds=date_range(Period(mode='weekday',phrase=phrase))
    assert bounds==(date.fromisoformat(start),date.fromisoformat(start))


def test_bare_weekday_requires_date_not_guess_current_month():
    with pytest.raises(NeedInfo):date_range(Period(mode='weekday',phrase='วันอาทิตย์'))
    assert relative_period('วันอาทิตย์')['question']


def test_filtered_week_question_still_uses_model_and_real_literal_filter(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-10')
    state['responses']=[tool('interpret_request',dict(intent='transactions',q='กาแฟ',transaction_kind='expense',
        period=dict(mode='previous_week',phrase='สัปดาห์ที่แล้ว')))]
    answer=send('กาแฟสัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert '80.00' in answer['content'] and '1,000.00' not in answer['content']
    assert len(state['calls'])==1 and answer['references'][0]['filters']['q']=='กาแฟ'


def test_telegram_uses_model_reads_with_same_dates_and_no_fake_filters(channel):
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='สัปดาห์ที่แล้ว',metric='expense')),{'content':'รายจ่าย 0 บาทค่ะ'}]
    capture(1,'สัปดาห์ที่แล้วใช้ตังไรบ้าง');process()
    bot=Sender();assert asyncio.run(deliver_once(bot))
    assert '2026-10-05' in bot.sent[0][1] and '2026-10-11' in bot.sent[0][1]
    assert 'ค้นคำว่า' not in bot.sent[0][1] and len(state['calls'])==2



def test_short_month_followup_keeps_a_real_previous_coffee_filter(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-13');post(92000,'อาหาร','2026-10-13')
    state['responses']=[tool('interpret_request',dict(intent='period',q='กาแฟ',period=dict(mode='yesterday',phrase='เมื่อวาน')))]
    assert '80.00' in send('กาแฟเมื่อวานใช้ไปเท่าไหร่')['content']
    state['calls'].clear()
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='เดือนนี้',metric='expense',reuse_previous_scope=True)),{'content':'กาแฟรวม 80.00 บาทค่ะ'}]
    answer=send('เดือนนี้ละ ใช้ตังเท่าไหร่')
    assert '80.00' in answer['content'] and '1,000.00' not in answer['content']
    assert answer['references'][0]['filters']['q']=='กาแฟ' and len(state['calls'])==2


def test_legacy_filler_filter_is_not_inherited_after_upgrade(assistant):
    from app.models import now
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-13')
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        room.capture_context={'verified_scope':dict(kind='period',q='ละ ใช้ตัง',expires=now()+900)}
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='เดือนนี้',metric='expense',clear_filters=True)),{'content':'รายจ่าย 80.00 บาทค่ะ'}]
    content=send('เดือนนี้ละ ใช้ตังเท่าไหร่')['content']
    assert '80.00' in content and 'ค้นคำว่า' not in content



@pytest.mark.parametrize('change',['expired','intervening'])
def test_weekday_clarification_cannot_reuse_old_or_interrupted_context(assistant,change):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[{'content':'หมายถึงวันอาทิตย์วันที่เท่าไรคะ?'}]
    assert 'วันที่เท่าไร' in send('วันอาทิตย์ละ')['content']
    if change=='expired':
        with SessionLocal.begin() as db:
            room=db.get(Conversation,cid);context=dict(room.capture_context)
            context['weekday_question']={'day':'อาทิตย์','expires':0};room.capture_context=context
    else:
        state['responses']=[{'content':'สวัสดีค่ะ'}];send('สวัสดี')
    state['responses']=[{'content':'หมายถึงช่วงไหนคะ?'}]
    content=send('ที่ผ่านมา')['content']
    assert '2026-10-11' not in content and state['calls']



def test_explicit_week_overrides_previous_month_in_legacy_report_history():
    assert resolve_period('สัปดาห์ที่แล้ว',['เดือนนี้'])==(date(2026,10,5),date(2026,10,11))



def test_picture_caption_is_not_taken_over_by_the_plain_text_read_path(assistant):
    from app.models import Provider
    from app.worker import run_once
    from test_chat_images import receipt
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    state['responses']=[tool('interpret_request',dict(intent='conversation',reply='เห็นภาพแล้วค่ะ'))]
    response=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'เมื่อวานเสียตังกับไรบ้าง'})
    assert response.status_code==200
    while run_once():pass
    assert len(state['calls'])==1
    assert any(isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content']) for m in state['calls'][0]['messages'])
    assert 'เห็นภาพแล้วค่ะ' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert c.get(b+'/transactions').json()==[]
