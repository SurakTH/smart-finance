import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal
from app.models import Budget,Membership
from app.bootstrap import create_user
from app.budgets import set_budget
from app import ai,finance_chat
from app.worker import run_once
from test_finance import ids,payload
from test_reporting import record


def test_budget_real_spending_month_scope_and_edit_delete(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    second=c.post(b+'/accounts',json={'name':'Travel','kind':'expense'}).json()['id']
    record(c,w,a,amount=8000,day='2026-10-01');record(c,w,a,amount=1000,day='2026-10-31');record(c,w,a,amount=99000,day='2026-09-30')
    c.post(b+'/transactions',json=payload('expense',a['asset'],2000,category_id=second))
    c.post(b+'/proposals',json={'description':'Unconfirmed','amount':900000})
    bank=c.post(b+'/accounts',json={'name':'Bank','kind':'asset'}).json()['id']
    record(c,w,a,'transfer',50000,other_account_id=bank)
    assert c.put(b+'/budgets/2026-10/'+a['expense'],json={'amount':10000}).status_code==200
    result=c.get(b+'/budgets?month=2026-10').json()
    assert (result['planned'],result['spent'],result['remaining'],result['unbudgeted_expense'])==(10000,9000,1000,2000)
    assert result['items'][0]['status']=='near' and result['unbudgeted_categories'][0]['id']==second
    c.put(b+'/budgets/2026-10/'+a['expense'],json={'amount':8500})
    result=c.get(b+'/budgets?month=2026-10').json()
    assert len(result['items'])==1 and result['items'][0]['status']=='over' and result['over_count']==1 and result['remaining']==-500
    c.put(b+'/budgets/2026-10/'+a['expense'],json={'amount':9000})
    assert c.get(b+'/budgets?month=2026-10').json()['items'][0]['status']=='reached'
    assert c.get(b+'/budgets?month=2026-11').json()['items']==[]
    before=c.get(b+'/accounts').json()
    assert c.delete(b+'/budgets/2026-10/'+a['expense']).status_code==200
    assert c.get(b+'/accounts').json()==before
    assert c.get(b+'/budgets?month=2026-10').json()['unbudgeted_expense']==11000
    assert c.delete(b+'/budgets/2026-10/'+a['expense']).status_code==404

@pytest.mark.parametrize('amount',[0,-1,True,1.1,'100',100_000_000_001])
def test_budget_money_validation(actor,amount):
    c,w,_=actor;a=ids(c,w)
    assert c.put(f'/workspaces/{w}/budgets/2026-10/{a["expense"]}',json={'amount':amount}).status_code==422


def test_budget_isolation_validation_and_database_fk(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    other=c.post('/workspaces',json={'name':'Separate'}).json()['id'];foreign=ids(c,other)['expense']
    assert c.put(b+'/budgets/2026-10/'+foreign,json={'amount':100}).status_code==404
    for wrong in ('asset','income'):
        assert c.put(b+'/budgets/2026-10/'+a[wrong],json={'amount':100}).status_code==422
    for month in ('2026-13','2026-1','0001-01'):
        assert c.get(b+'/budgets',params={'month':month}).status_code==422
    c.put(f'/workspaces/{other}/budgets/2026-10/{foreign}',json={'amount':100})
    assert c.get(b+'/budgets?month=2026-10').json()['items']==[]
    assert c.delete(b+'/budgets/2026-10/'+foreign).status_code==404
    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as db: db.add(Budget(workspace_id=w,category_id=foreign,month='2026-10',amount=100))
    with SessionLocal.begin() as db:
        user=create_user(db,uuid.uuid4().hex+'@test.local','budget-test-password')
        wid=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
    for method,path,body in [('get','/budgets?month=2026-10',None),('put','/budgets/2026-10/'+a['expense'],{'amount':100}),('delete','/budgets/2026-10/'+a['expense'],None),('post','/budgets/2026-10/copy-previous',{})]:
        assert c.request(method,f'/workspaces/{wid}'+path,json=body).status_code==404


def test_budget_copy_previous_only_missing_and_year_boundary(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    second=c.post(b+'/accounts',json={'name':'Travel','kind':'expense'}).json()['id']
    for cid,month,amount in [(a['expense'],'2025-12',1000),(second,'2025-12',2000),(a['expense'],'2026-01',9000)]:
        assert c.put(f'{b}/budgets/{month}/{cid}',json={'amount':amount}).status_code==200
    assert c.post(b+'/budgets/2026-01/copy-previous',json={}).json()=={'copied':1}
    assert c.post(b+'/budgets/2026-01/copy-previous',json={}).json()=={'copied':0}
    rows=c.get(b+'/budgets?month=2026-01').json()['items']
    assert {r['category_id']:r['amount'] for r in rows}=={a['expense']:9000,second:2000}
    assert c.post(b+'/budgets/2026-03/copy-previous',json={}).json()=={'copied':0}
    assert c.get(b+'/transactions').json()==[]


def test_budget_chat_read_only_no_provider(actor,monkeypatch):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    monkeypatch.setattr(finance_chat,'today',lambda:date(2026,10,11))
    monkeypatch.setattr('app.reporting.today',lambda:date(2026,10,11))
    def forbidden(*args,**kw):raise AssertionError('Budget reports must stay local')
    monkeypatch.setattr(ai.httpx,'Client',forbidden)
    c.put(b+'/budgets/2026-10/'+a['expense'],json={'amount':10000});record(c,w,a,amount=2500)
    room=c.post(b+'/conversations',json={'privacy':'private'}).json()['id']
    c.post(b+f'/conversations/{room}/messages',json={'text':'งบเดือนนี้เหลือเท่าไหร่'})
    while run_once():pass
    answer=c.get(b+f'/conversations/{room}/messages').json()[-1]['content']
    assert 'งบประมาณจากระบบโดยตรง' in answer and '฿75.00' in answer and 'ยังไม่ได้สร้างหรือเปลี่ยนงบ' in answer
    assert c.get(b+'/budgets?month=2026-10').json()['planned']==10000 and len(c.get(b+'/transactions').json())==1


def test_budget_concurrent_upsert_is_single_row(actor,pg_only):
    c,w,_=actor;a=ids(c,w)
    def save(n):
        with SessionLocal.begin() as db: set_budget(db,w,'2026-10',a['expense'],1000+n)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(save,range(4)))
    with SessionLocal() as db:
        rows=db.scalars(select(Budget).where(Budget.workspace_id==w)).all()
        assert len(rows)==1 and rows[0].amount in range(1000,1004)
