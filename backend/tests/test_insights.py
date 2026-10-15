import uuid
from sqlalchemy import select
from app.db import SessionLocal
from app.bootstrap import create_user
from app.models import Account, Membership
from test_finance import ids
from test_reporting import record
from test_corrections import correction


def test_insights_exact_comparison_zeros_ranking_and_excluded_kinds(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    bank=c.post(b+'/accounts',json={'name':'Bank','kind':'asset'}).json()['id']
    record(c,w,a,'opening',80000,day='2026-09-01')
    card=c.post(b+'/accounts',json={'name':'Card','kind':'liability'}).json()['id']
    record(c,w,{**a,'asset':card},'opening',5000,day='2026-09-01')
    record(c,w,a,'card_payment',5000,day='2026-10-02',other_account_id=card)
    record(c,w,a,amount=3000,day='2026-09-30')
    record(c,w,a,amount=1000,day='2026-10-01')
    record(c,w,a,amount=5000,day='2026-10-02')
    record(c,w,a,'income',20000,day='2026-10-02')
    record(c,w,a,'transfer',7000,day='2026-10-02',other_account_id=bank)
    record(c,w,a,amount=99999,day='2026-10-04')
    r=c.get(b+'/insights?start=2026-10-01&end=2026-10-03');assert r.status_code==200,r.text
    d=r.json()
    assert (d['expense'],d['income'],d['net'])==(6000,20000,14000)
    assert (d['days'],d['expense_count'],d['average_daily'],d['average_transaction'],d['active_days'])==(3,2,2000,3000,2)
    assert (d['previous']['start'],d['previous']['end'],d['previous']['expense'])==('2026-09-28','2026-09-30',3000)
    assert [x['amount'] for x in d['largest']]==[5000,1000]
    assert sum(x['days'] for x in d['weekdays'])==3
    assert sum(x['expense'] for x in d['weekdays'])==6000
    assert d['monthly']==[{'month':'2026-10','income':20000,'expense':6000}]
    assert d['categories'][0]['amount']==d['spending_accounts'][0]['expense']==6000
    assert c.get(b+'/insights',params={'start':'2026-10-01','end':'2026-10-03','account_id':bank}).json()['expense']==0


def test_insights_corrections_empty_months_and_scope(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    old=record(c,w,a,amount=10000,day='2026-10-01')
    corrected=c.post(b+f'/transactions/{old["id"]}/correct',json=correction(a,amount=6500,day='2026-10-01'))
    assert corrected.status_code==200
    d=c.get(b+'/insights?start=2026-09-01&end=2026-11-30').json()
    assert d['expense']==6500 and d['expense_count']==1
    assert [row['expense'] for row in d['monthly']]==[0,6500,0]
    assert len(d['largest'])==1 and d['largest'][0]['id']!=old['id']
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-report-password')
        foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
        account=db.scalar(select(Account.id).where(Account.workspace_id==foreign))
    params={'start':'2026-09-01','end':'2026-11-30'}
    assert c.get(f'/workspaces/{foreign}/insights',params=params).status_code==404
    assert c.get(b+'/insights',params={**params,'account_id':account}).status_code==404
    assert c.get(b+'/insights',params={**params,'category_id':account}).status_code==404
    assert c.get(b+'/insights',params={**params,'account_id':a['expense']}).status_code==422
    for start,end in [('2026-10-03','2026-10-01'),('2025-01-01','2026-12-31'),('0001-01-01','0001-01-01')]:
        assert c.get(b+'/insights',params={'start':start,'end':end}).status_code==422
    empty=c.get(b+'/insights?start=2027-01-01&end=2027-01-31').json()
    assert empty['expense']==empty['average_daily']==empty['average_transaction']==0
    assert empty['categories']==empty['largest']==[]
