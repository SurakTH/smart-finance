"""End-to-end typed analytics, SQL totals, provenance and no-write guarantees."""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account,Conversation,ChatAction,Job,Message
from app.assistant_scope import Scope
from app.assistant_analytics import analyze,ratio,buckets
from app.request_interpreter import Period,date_range,NeedInfo
from test_assistant_finance import assistant,tool
from test_telegram_assistant import channel,Sender


def period(start='2026-10-01',end='2026-10-14'):
    return dict(mode='range',phrase=f'{start} ถึง {end}',start=start,end=end)


def plan(operation='summary',**kw):
    options=kw.pop('analysis',{})
    return tool('interpret_request',dict(intent='analytics',period=period(),analysis=dict(operation=operation,**options),**kw))


def raw_task(db,w,**kw):
    return Scope('analytics','',start=date(2026,10,1),end=date(2026,10,14),transaction_kind='expense',analysis={'operation':'summary'},**kw)


def test_arbitrary_range_averages_full_data_not_search_page(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    for i in range(35):post(125,'กาแฟ','2026-10-02')
    post(99999,'นอกช่วง','2026-10-15')
    state['responses']=[plan('average')]
    answer=send('ค่าเฉลี่ยรายจ่าย 2026-10-01 ถึง 2026-10-14')
    assert '43.75 บาท' in answer['content'] and '35 รายการ' in answer['content']
    assert '3.13 บาท/วัน' in answer['content'] and '1.25 บาท/รายการ' in answer['content']
    assert 'รวมวันที่ไม่มีรายการ' in answer['content'] and len(state['calls'])==1
    assert answer['references'][0]['expense']==4375
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


def test_compare_unequal_ranges_with_zero_baseline_and_evidence(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(14000,on='2026-10-03')
    compare=period('2026-09-01','2026-09-07')
    state['responses']=[plan('compare',compare_period=compare)]
    answer=send('เปรียบเทียบรายจ่าย 2026-10-01 ถึง 2026-10-14 กับ 2026-09-01 ถึง 2026-09-07')
    assert 'จำนวนวันไม่เท่ากัน' in answer['content'] and 'คำนวณเปอร์เซ็นต์ไม่ได้' in answer['content']
    assert '140.00 บาท' in answer['content'] and '10.00 บาท/วัน' in answer['content']
    assert {r['filters']['start'] for r in answer['references']}=={'2026-10-01','2026-09-01'}


def test_compare_negative_delta_percentage_and_overlapping_windows(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(10000,on='2026-10-02');post(30000,on='2026-09-30')
    state['responses']=[plan('compare',compare_period=period('2026-09-30','2026-10-02'))]
    content=send('เปรียบเทียบรายจ่าย 2026-10-01 ถึง 2026-10-14 กับ 2026-09-30 ถึง 2026-10-02')['content']
    assert 'ลดลง **300.00 บาท** (75.00%)' in content and 'วันที่ซ้อนกัน' in content


@pytest.mark.parametrize('operation',['summary','average','trend','ranking'])
def test_empty_analytics_is_defined_and_never_invents_values(assistant,operation):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan(operation)]
    content=send('วิเคราะห์รายจ่าย 2026-10-01 ถึง 2026-10-14')['content']
    assert 'ไม่พบรายการ' in content and 'ยังไม่มีรายการ จึงคำนวณไม่ได้' in content
    assert '0.00 บาท/วัน' in content and 'NaN' not in content and 'Infinity' not in content


def test_trend_daily_zeros_and_truncation_use_complete_extrema(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(99000,on='2026-10-01');post(10000,on='2026-10-14')
    state['responses']=[plan('trend',analysis=dict(bucket='day'))]
    content=send('แนวโน้มรายจ่ายรายวัน 2026-10-01 ถึง 2026-10-14')['content']
    assert 'แสดง 12 ช่วงท้ายจากทั้งหมด 14' in content
    assert 'สูงสุด: 2026-10-01 ถึง 2026-10-01 · 990.00' in content
    assert 'ต่ำสุด: 2026-10-02 ถึง 2026-10-02 · 0.00' in content
    with SessionLocal() as db:
        task=raw_task(db,w);task.analysis=dict(operation='trend',bucket='day')
        result=analyze(db,w,task)
    assert sum(r['amount'] for r in result['buckets'])==result['current']['amount']==109000


@pytest.mark.parametrize('unit,expected',[
    ('week',[('2024-02-28','2024-03-03'),('2024-03-04','2024-03-04')]),
    ('month',[('2024-02-28','2024-02-29'),('2024-03-01','2024-03-04')]),
])
def test_calendar_buckets_clip_edges_and_include_leap_day(unit,expected):
    assert [(str(s),str(e)) for s,e in buckets(date(2024,2,28),date(2024,3,4),unit)]==expected


def test_ranking_all_groups_denominator_and_deterministic_ties(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    for text,amount in [('A',10000),('B',10000),('C',20000)]:post(amount,text,'2026-10-01')
    with SessionLocal() as db:
        task=raw_task(db,w);task.analysis=dict(operation='ranking',group_by='description',limit=2)
        analyze(db,w,task)
    state['responses']=[plan('ranking',analysis=dict(group_by='description',limit=2))]
    content=send('อันดับรายจ่ายตามรายละเอียด 2026-10-01 ถึง 2026-10-14')['content']
    assert '1. C: **200.00 บาท**' in content and '50.00% ของยอดกรองทั้งหมด' in content
    assert '2. A: **100.00 บาท**' in content and 'แสดง 2 จาก 3 กลุ่ม' in content
    state['responses']=[plan('ranking',analysis=dict(group_by='description',order='lowest',limit=1))]
    assert '1. A: **100.00 บาท**' in send('อันดับรายจ่ายน้อยที่สุดตามรายละเอียด 2026-10-01 ถึง 2026-10-14')['content']


@pytest.mark.parametrize('group',['category','account'])
def test_category_and_account_ranking_preserve_filter_in_links(assistant,group):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-10')
    state['responses']=[plan('ranking',q='กาแฟ',analysis=dict(group_by=group))]
    answer=send('อันดับรายจ่ายกาแฟ 2026-10-01 ถึง 2026-10-14')
    assert '80.00 บาท' in answer['content'] and '100.00%' in answer['content'] and '1,000.00' not in answer['content']
    refs=answer['references'];assert len(refs)==2
    assert all(r['filters']['q']=='กาแฟ' and r['filters']['kind']=='expense' for r in refs)
    assert refs[1]['filters']['category_id' if group=='category' else 'account_id']==(cat if group=='category' else wallet)


def test_filtered_description_omission_is_not_silently_broadened(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-10')
    state['responses']=[plan('average')]
    content=send('ค่าเฉลี่ยรายจ่ายกาแฟ 2026-10-01 ถึง 2026-10-14')['content']
    assert 'คำที่จะค้น' in content and '1,000.00' not in content


def test_income_only_excludes_transfer_card_opening_and_expense(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    income=c.post(b+'/accounts',json={'name':'รายรับทดสอบ','kind':'income'}).json()['id']
    other=c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'}).json()['id']
    card=c.post(b+'/accounts',json={'name':'บัตรทดสอบ','kind':'liability'}).json()['id']
    for kind,category,other_id,amount in [('opening',None,None,99999),('income',income,None,20000),('transfer',None,other,50000),('card_payment',None,card,1000)]:
        payload=dict(kind=kind,description='ทดสอบ',account_id=wallet,amount=amount,occurred_on='2026-10-02',idempotency_key=str(uuid.uuid4()))
        if category:payload['category_id']=category
        if other_id:payload['other_account_id']=other_id
        assert c.post(b+'/transactions',json=payload).status_code==200
    post(8000,on='2026-10-02')
    state['responses']=[plan(transaction_kind='income')]
    content=send('วิเคราะห์รายรับ 2026-10-01 ถึง 2026-10-14')['content']
    assert '200.00 บาท' in content and '1 รายการ' in content and '999.99' not in content


@pytest.mark.parametrize('extra,prompt',[
    ({'analysis':dict(operation='compare')},'เปรียบเทียบรายจ่าย 2026-10-01 ถึง 2026-10-14'),
    ({'analysis':dict(operation='average')},'แนวโน้มรายจ่าย 2026-10-01 ถึง 2026-10-14'),
    ({'transaction_kind':'income'},'รายจ่าย 2026-10-01 ถึง 2026-10-14'),
    ({'transaction_kind':'transfer'},'รายจ่าย 2026-10-01 ถึง 2026-10-14'),
    ({'analysis':dict(operation='ranking',order='highest')},'อันดับรายจ่ายน้อยที่สุด 2026-10-01 ถึง 2026-10-14'),
    ({'analysis':dict(operation='trend',bucket='week')},'แนวโน้มรายจ่ายรายวัน 2026-10-01 ถึง 2026-10-14'),
    ({'analysis':dict(operation='ranking',group_by='category')},'อันดับรายจ่ายตามบัญชี 2026-10-01 ถึง 2026-10-14'),
])
def test_semantic_mismatches_ask_instead_of_answering_wrong_report(assistant,extra,prompt):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    raw=dict(intent='analytics',period=period(),analysis=dict(operation='summary'),**{})
    raw.update(extra);state['responses']=[tool('interpret_request',raw)]
    content=send(prompt)['content']
    assert '0.00 บาท' not in content and ('ช่วงไหน' in content or 'ดูข้อมูล' in content)


@pytest.mark.parametrize('extra',[
    {'workspace_id':'foreign'}, {'sql':'select * from entries'},
    {'analysis':dict(operation='ranking',limit=1000)},
    {'analysis':dict(operation='ranking',limit=True)},
    {'analysis':dict(operation='forecast')},
    {'analysis':dict(operation='trend',bucket='hour')},
])
def test_model_cannot_supply_authority_sql_or_unbounded_analysis(assistant,extra):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    raw=dict(intent='analytics',period=period(),analysis=dict(operation='summary'));raw.update(extra)
    state['responses']=[tool('interpret_request',raw)]*2
    assert '0.00 บาท' not in send('วิเคราะห์รายจ่าย 2026-10-01 ถึง 2026-10-14')['content']


@pytest.mark.parametrize('raw,start,end',[
    ('1/10/2569 ถึง 14/10/2569','2026-10-01','2026-10-14'),
    ('๒๘/๒/๒๕๖๗ ถึง ๑/๓/๒๕๖๗','2024-02-28','2024-03-01'),
])
def test_numeric_thai_date_range_is_checked_not_model_arithmetic(raw,start,end):
    assert date_range(Period(mode='range',phrase=raw,start=start,end=end))==(date.fromisoformat(start),date.fromisoformat(end))


@pytest.mark.parametrize('raw',[
    dict(mode='range',phrase='1/10/2569 ถึง 14/10/2569',start='2026-10-02',end='2026-10-14'),
    dict(mode='range',phrase='2025-01-01 ถึง 2026-01-02',start='2025-01-01',end='2026-01-02'),
])
def test_range_mismatch_and_over_limit_are_rejected(raw):
    with pytest.raises(NeedInfo):date_range(Period(**raw))


def test_exact_ratios_and_zero_denominators():
    assert ratio(1,3)==Decimal('.33') and ratio(1,200)==Decimal('.01')
    assert ratio(12,0) is None and ratio(-1,8,100)==Decimal('-12.50')


def test_telegram_analytics_shared_runtime_no_new_confirmation(channel):
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[plan('trend')]
    capture(1,'แนวโน้มรายจ่าย 2026-10-01 ถึง 2026-10-14');process()
    sender=Sender();assert asyncio.run(deliver_once(sender))
    assert 'แนวโน้มรายวัน' in sender.sent[0][1] and '0.00 บาท/วัน' in sender.sent[0][1]
    assert c.get(b+'/transactions').json()==[]


def test_analytics_is_discarded_if_workspace_changes_during_inference(assistant,pg_only):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def changed(body):
        assert c.post(b+'/accounts',json={'name':'เปลี่ยนระหว่างรอ','kind':'asset'}).status_code==200
        return plan('average')
    state['responses']=[changed];send('ค่าเฉลี่ยรายจ่าย 2026-10-01 ถึง 2026-10-14')
    with SessionLocal() as db:
        job=db.scalar(select(Job).where(Job.workspace_id==w))
        assert job.status=='failed' and job.error=='context_changed'
        assert not db.scalar(select(Message.id).where(Message.conversation_id==cid,Message.role=='assistant'))


def test_sql_analytics_excludes_superseded_and_reversal_journals(assistant):
    from test_corrections import correction
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    original=post(9000,'กาแฟ','2026-10-10');cancelled=post(99999,'ยกเลิก','2026-10-10')
    response=c.post(b+f'/transactions/{original}/correct',json=correction({'asset':wallet,'expense':cat},amount=12500,day='2026-10-10'))
    assert response.status_code==200,response.text
    assert c.post(b+f'/transactions/{cancelled}/reverse',json={'reason':'รายการซ้ำ','idempotency_key':str(uuid.uuid4())}).status_code==200
    with SessionLocal() as db:
        task=raw_task(db,w)
        for operation in ('summary','trend','ranking'):
            task.analysis=dict(operation=operation)
            result=analyze(db,w,task)
            assert result['current']['amount']==12500 and result['current']['count']==1
            if operation=='trend':assert sum(r['amount'] for r in result['buckets'])==12500
            if operation=='ranking':assert result['items'][0]['amount']==12500


def test_same_names_in_another_workspace_never_enter_aggregates(assistant):
    from test_finance import ids
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    foreign=c.post('/workspaces',json={'name':'อีกพื้นที่'}).json()['id'];fa=ids(c,foreign)
    assert c.post(f'/workspaces/{foreign}/transactions',json=dict(kind='expense',description='กาแฟ',amount=999999,
        account_id=fa['asset'],category_id=fa['expense'],occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()))).status_code==200
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan('ranking',analysis=dict(group_by='account'))]
    content=send('อันดับรายจ่ายตามบัญชี 2026-10-01 ถึง 2026-10-14')['content']
    assert '80.00 บาท' in content and '9,999.99' not in content
    foreign_name=c.post(f'/workspaces/{foreign}/accounts',json={'name':'ต่างพื้นที่เท่านั้น','kind':'asset'}).json()['name']
    state['responses']=[plan(account={'phrase':foreign_name})]
    content=send(f'วิเคราะห์รายจ่าย{foreign_name} 2026-10-01 ถึง 2026-10-14')['content']
    assert 'บัญชีไหน' in content and '80.00' not in content


@pytest.mark.parametrize('unit',['week','month'])
def test_sql_calendar_trend_groups_include_leap_day(assistant,unit):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    for day in ('2024-02-28','2024-02-29','2024-03-01','2024-03-04'):post(100,day,day)
    with SessionLocal() as db:
        task=raw_task(db,w);task.start=date(2024,2,28);task.end=date(2024,3,4)
        task.analysis=dict(operation='trend',bucket=unit)
        result=analyze(db,w,task)
    assert [r['amount'] for r in result['buckets']]==([300,100] if unit=='week' else [200,200])
    assert sum(r['days'] for r in result['buckets'])==6


def test_filtered_comparison_uses_identical_account_and_literal_query(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ 100%','2026-10-10');post(4000,'กาแฟ 100%','2026-09-10');post(99999,'กาแฟ 1000','2026-09-10')
    state['responses']=[plan('compare',q='100%',account={'phrase':'เงินสด'},compare_period=period('2026-09-01','2026-09-14'))]
    answer=send('เปรียบเทียบรายจ่ายเงินสด 100% 2026-10-01 ถึง 2026-10-14 กับ 2026-09-01 ถึง 2026-09-14')
    assert 'เพิ่มขึ้น **40.00 บาท** (100.00%)' in answer['content'] and '999.99' not in answer['content']
    assert all(r['filters']['q']=='100%' and r['filters']['account_id']==wallet for r in answer['references'])


def test_partial_account_filter_does_not_become_a_description(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    bank=c.post(b+'/accounts',json={'name':'ธนาคารกสิกร','kind':'asset'}).json()['id']
    assert c.post(b+'/transactions',json=dict(kind='expense',description='กาแฟ',amount=8800,account_id=bank,
        category_id=cat,occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()))).status_code==200
    state['responses']=[plan('average',account={'phrase':'กสิกร'})]
    assert '88.00 บาท' in send('ค่าเฉลี่ยรายจ่ายกสิกร 2026-10-01 ถึง 2026-10-14')['content']


@pytest.mark.parametrize('description',['กับข้าว','ค่าเฉลี่ยหนังสือ','อาหารรายเดือน'])
def test_literal_description_keeps_words_that_resemble_analysis_grammar(assistant,description):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,description,'2026-10-10');post(92000,'รายการอื่น','2026-10-10')
    state['responses']=[plan('average',q=description)]
    content=send(f'ค่าเฉลี่ยรายจ่าย{description} 2026-10-01 ถึง 2026-10-14')['content']
    assert '80.00 บาท' in content and '1,000.00' not in content


def test_highest_request_cannot_be_downgraded_to_total(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('summary')]
    assert 'ดูข้อมูล' in send('รายจ่ายสูงสุด 2026-10-01 ถึง 2026-10-14')['content']



def test_daily_average_delta_uses_exact_fraction_before_rounding(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(4,'สี่สตางค์','2026-10-01');post(5,'ห้าสตางค์','2026-09-01')
    with SessionLocal() as db:
        task=raw_task(db,w);task.end=date(2026,10,3)
        task.analysis=dict(operation='compare',compare_start='2026-09-01',compare_end='2026-09-06')
        result=analyze(db,w,task)
    # (4/3 - 5/6) satang = 0.005 baht -> 0.01 half up.
    # Subtracting recurring Decimals can land just below the half-cent boundary.
    assert result['daily_delta']==Decimal('.01')
