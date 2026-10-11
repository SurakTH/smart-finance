import uuid
from datetime import date
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account, Membership
from app.bootstrap import create_user
from app.worker import run_once
from app import finance_chat, ai
from test_finance import ids, payload


def record(c,w,a,kind='expense',amount=100,day='2026-10-10',description='กาแฟ',**kw):
    data=payload(kind,a['asset'],amount,**({'category_id':a[kind]} if kind in ('expense','income') else {}),**kw)
    data.update(occurred_on=day,description=description)
    response=c.post(f'/workspaces/{w}/transactions',json=data)
    assert response.status_code==200,response.text
    return response.json()


def test_inclusive_filter_pagination_full_totals_and_literal_search(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    for i in range(32): record(c,w,a,amount=100+i,day='2026-10-01' if i<16 else '2026-10-31',description='กาแฟ 100%_แท้' if i==0 else 'กาแฟ')
    record(c,w,a,'income',20000)
    record(c,w,a,amount=999999,day='2026-09-30')
    result=c.get(b+'/transaction-report?start=2026-10-01&end=2026-10-31&page_size=30').json()
    assert (result['total'],result['expense'],result['income'])==(33,sum(range(100,132)),20000)
    second=c.get(b+'/transaction-report?start=2026-10-01&end=2026-10-31&page_size=30&page=2').json()
    assert len(second['items'])==3
    assert not {r['id'] for r in result['items']} & {r['id'] for r in second['items']}
    exact=c.get(b+'/transaction-report',params={'q':'%_'}).json()
    assert exact['total']==1
    assert exact['items'][0]['accounts'][0]['id']==a['asset']
    assert exact['items'][0]['category']['id']==a['expense']
    assert c.get(b+'/transaction-report?start=2026-11-01&end=2026-10-01').status_code==422
    assert c.get(b+'/transaction-report?page_size=101').status_code==422
    assert c.get(b+'/transaction-report?kind=unknown').status_code==422


def test_account_category_scope_transfer_and_foreign_filters(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    bank=c.post(b+'/accounts',json={'name':'Bank','kind':'asset'}).json()['id']
    record(c,w,a,amount=550)
    record(c,w,a,'transfer',700,other_account_id=bank)
    result=c.get(b+'/transaction-report',params={'account_id':a['asset']}).json()
    assert (result['total'],result['expense'])==(2,550)
    transfer=next(r for r in result['items'] if r['kind']=='transfer')
    assert [r['direction'] for r in transfer['accounts']]==['out','in']
    assert c.get(b+'/transaction-report',params={'account_id':bank,'category_id':a['expense']}).json()['total']==0
    with SessionLocal.begin() as db:
        user=create_user(db,uuid.uuid4().hex+'@test.local','secure-report-password')
        foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
        fa=db.scalar(select(Account.id).where(Account.workspace_id==foreign))
    assert c.get(b+'/transaction-report',params={'account_id':fa}).status_code==404
    assert c.get(f'/workspaces/{foreign}/transaction-report').status_code==404
    assert c.get(f'/workspaces/{foreign}/dashboard').status_code==404
    assert c.get(b+'/transaction-report',params={'account_id':a['expense']}).status_code==422


def test_dashboard_month_recent_previous_breakdowns(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    record(c,w,a,amount=500,day='2026-01-01',description='selected')
    record(c,w,a,amount=1000,day='2025-12-31',description='previous')
    record(c,w,a,amount=7000,day='2026-02-01',description='future')
    result=c.get(b+'/dashboard?month=2026-01').json()
    assert result['expense']==500 and result['previous']['expense']==1000
    assert result['previous']['start']=='2025-12-01'
    assert [r['description'] for r in result['recent']]==['selected']
    assert result['categories'][0]['amount']==500
    assert result['spending_accounts'][0]['expense']==500
    assert result['net_worth']==-8500
    for month in ('2026-13','2026-1','0001-01','9999-01'):
        assert c.get(b+'/dashboard',params={'month':month}).status_code==422


def test_report_chat_real_data_no_model_no_posting_and_context(actor,monkeypatch):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    monkeypatch.setattr(finance_chat,'today',lambda:date(2026,10,10))
    def forbidden(*args,**kw): raise AssertionError('report must not call a provider')
    monkeypatch.setattr(ai.httpx,'Client',forbidden)
    record(c,w,a,amount=7550,description='ข้าว',day='2026-09-10')
    record(c,w,a,amount=9900,description='กาแฟ',day='2026-10-10')
    room=c.post(b+'/conversations',json={'privacy':'private'}).json()['id']
    def ask(text):
        assert c.post(b+f'/conversations/{room}/messages',json={'text':text}).status_code==200
        while run_once(): pass
        return c.get(b+f'/conversations/{room}/messages').json()[-1]['content']
    answer=ask('เดือนที่แล้วใช้เท่าไหร่ มีอะไรบ้าง บัญชีไหน')
    assert '2026-09-01 ถึง 2026-09-30' in answer
    assert '฿75.50' in answer and 'ข้าว' in answer and 'กาแฟ' not in answer
    assert '2026-09-01 ถึง 2026-09-30' in ask('แล้วบัญชีไหนล่ะ')
    assert '฿99.00' in ask('2026-10 เดือนนี้ใช้เท่าไหร่')
    assert 'ช่วงวันไม่ถูกต้อง' in ask('รายการ 2026-99-99')
    assert 'ยังจับคู่ชื่อบัญชีไม่ได้' in ask('เดือนนี้บัญชีที่ไม่มีอยู่ใช้เท่าไหร่'.replace('บัญชีที่ไม่มีอยู่','บัญชีธนาคารปลอม'))
    account_name=next(r['name'] for r in c.get(b+'/accounts').json() if r['id']==a['asset'])
    assert '฿99.00' in ask('2026-10 ใช้เท่าไหร่ บัญชี'+account_name)
    assert len(c.get(b+'/transactions').json())==2


def test_period_resolution():
    assert finance_chat.resolve_period('เดือนกันยายน 2569')==(date(2026,9,1),date(2026,9,30))
    assert finance_chat.resolve_period('2026-02-01 ถึง 2026-02-04')==(date(2026,2,1),date(2026,2,4))
