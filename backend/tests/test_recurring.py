import uuid
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select,update,delete,func
from sqlalchemy.exc import IntegrityError,DBAPIError
from app import recurring
from app.db import SessionLocal
from app.models import RecurringOccurrence,RecurringRule,Membership,Proposal
from app.schemas import RecurringCreate
from app.bootstrap import create_user
from app.worker import schedule_once
from test_finance import ids,payload

@pytest.fixture
def clock(monkeypatch):
    box=[date(2026,10,11)];monkeypatch.setattr(recurring,'today',lambda:box[0]);return box

def body(accounts,**kw):
    data=dict(description='ค่าเช่าประจำ',amount=10000,kind='expense',account_id=accounts['asset'],category_id=accounts['expense'],frequency='monthly',start_on='2026-10-11',idempotency_key=str(uuid.uuid4()));data.update(kw);return data

def make(c,w,accounts,**kw):
    b=f'/workspaces/{w}/recurring';data=body(accounts,**kw);r=c.post(b,json=data);assert r.status_code==200,r.text
    return b,r.json()['id'],data

def test_recurring_proposals_require_confirm_keep_snapshots_and_replay(actor,clock):
    c,w,_=actor;a=ids(c,w);b,rid,data=make(c,w,a);balance=c.get(f'/workspaces/{w}/accounts').json()
    assert c.post(b,json=data).json()=={'id':rid}
    assert c.post(b,json={**data,'amount':1}).status_code==409
    assert c.post(b+'/check-due').json()['created']==1
    assert c.post(b+'/check-due').json()['created']==0
    proposals=c.get(f'/workspaces/{w}/proposals').json();assert len(proposals)==1
    p=proposals[0];assert (p['source'],p['occurred_on'],p['account_id'],p['category_id'],p['amount'])==('recurring','2026-10-11',a['asset'],a['expense'],10000)
    assert c.get(f'/workspaces/{w}/accounts').json()==balance and c.get(f'/workspaces/{w}/transactions').json()==[]
    row=c.get(b).json()[0];edit={k:data[k] for k in ('description','amount','kind','account_id','category_id')};edit.update(amount=20000,version=row['version'])
    assert c.put(b+'/'+rid,json=edit).status_code==200
    assert c.put(b+'/'+rid,json=edit).status_code==409
    assert c.get(f'/workspaces/{w}/proposals').json()[0]['amount']==10000
    request=payload('expense',a['asset'],9000,category_id=a['expense']);request['occurred_on']=p['occurred_on']
    url=f'/workspaces/{w}/proposals/{p["id"]}/confirm'
    assert c.post(url,json=request).status_code==200
    assert c.post(url,json=request).status_code==200
    assert len(c.get(f'/workspaces/{w}/transactions').json())==1
    history=c.get(b+'/'+rid+'/history').json();assert history['items'][0]['status']=='confirmed' and history['items'][0]['amount']==10000
    clock[0]=date(2026,11,11);assert c.post(b+'/check-due').json()['created']==1
    assert c.get(f'/workspaces/{w}/proposals').json()[0]['amount']==20000
    new=c.get(f'/workspaces/{w}/proposals').json()[0];c.post(f'/workspaces/{w}/proposals/{new["id"]}/reject')
    assert c.post(b+'/check-due').json()['created']==0

@pytest.mark.parametrize('start,expected',[('2028-01-31',['2028-01-31','2028-02-29','2028-03-31']),('2027-01-30',['2027-01-30','2027-02-28','2027-03-30'])])
def test_monthly_anchor_leap_year_and_end(actor,clock,start,expected):
    c,w,_=actor;a=ids(c,w);clock[0]=date.fromisoformat(start);b,rid,_=make(c,w,a,start_on=start,end_on=expected[-1])
    clock[0]=date.fromisoformat(expected[-1]);assert c.post(b+'/check-due').json()['created']==3
    assert [r['scheduled_on'] for r in reversed(c.get(b+'/'+rid+'/history').json()['items'])]==expected
    assert c.get(b).json()[0]['status']=='ended';assert c.post(b+'/check-due').json()['created']==0


def test_pause_resume_daily_backlog_bounded_pagination_and_inbox_cap(actor,clock,monkeypatch):
    c,w,_=actor;a=ids(c,w);b,rid,_=make(c,w,a,frequency='daily');row=c.get(b).json()[0]
    assert c.post(b+'/'+rid+'/pause',json={'paused':True,'version':row['version']}).status_code==200
    clock[0]=date(2026,11,15);assert c.post(b+'/check-due').json()['created']==0
    row=c.get(b).json()[0];assert c.post(b+'/'+rid+'/pause',json={'paused':False,'version':row['version']}).status_code==200
    monkeypatch.setattr(recurring,'MAX_PENDING',12)
    assert c.post(b+'/check-due').json()['created']==10
    result=c.post(b+'/check-due').json();assert result['created']==2 and result['blocked_by_inbox']
    assert c.get(b).json()[0]['next_on']=='2026-10-23'
    assert c.post(b+'/check-due').json()['created']==0
    monkeypatch.setattr(recurring,'MAX_PENDING',100)
    assert c.post(b+'/check-due').json()['created']==10
    assert c.post(b+'/check-due').json()['created']==10
    assert c.get(b+'/'+rid+'/history').json()['total']==32
    assert len(c.get(b+'/'+rid+'/history?page=2').json()['items'])==2
    assert c.get(f'/workspaces/{w}/transactions').json()==[]


def test_weekly_schedule_worker_and_pending_first(actor,clock):
    c,w,_=actor;a=ids(c,w);b,rid,_=make(c,w,a,frequency='weekly');clock[0]=date(2026,10,25)
    # Worker scheduling uses the same durable generator as manual checks.
    assert schedule_once(w)['created']==3
    assert [r['scheduled_on'] for r in c.get(b+'/'+rid+'/history').json()['items']]==['2026-10-25','2026-10-18','2026-10-11']
    with SessionLocal.begin() as db:
        db.add_all([Proposal(workspace_id=w,description='Old processed',amount=1,status='rejected',created_at=9999999999) for _ in range(101)])
    listed=c.get(f'/workspaces/{w}/proposals').json();assert len(listed)==100 and all(r['status']=='pending' for r in listed[:3])

@pytest.mark.parametrize('kw',[{'amount':True},{'amount':0},{'amount':1.1},{'amount':'100'},{'amount':100_000_000_001},{'description':'  '},{'frequency':'yearly'},{'start_on':'2026-10-10'},{'end_on':'2026-10-10'},{'start_on':'9999-01-01'}])
def test_recurring_validation(actor,clock,kw):
    c,w,_=actor
    assert c.post(f'/workspaces/{w}/recurring',json=body(ids(c,w),**kw)).status_code==422


def test_recurring_isolation_and_limits(actor,clock,monkeypatch):
    c,w,user=actor;a=ids(c,w);b,rid,_=make(c,w,a)
    other=c.post('/workspaces',json={'name':'Other'}).json()['id'];foreign=ids(c,other)
    assert c.post(b,json=body(a,account_id=foreign['asset'])).status_code==404
    assert c.post(b,json=body(a,category_id=a['income'])).status_code==422
    assert c.get(f'/workspaces/{other}/recurring/{rid}/history').status_code==404
    assert c.post(f'/workspaces/{other}/recurring/{rid}/pause',json={'paused':True,'version':1}).status_code==404
    assert c.post(f'/workspaces/{other}/recurring/check-due').json()['created']==0
    assert c.get(f'/workspaces/{other}/proposals').json()==[]
    c.post(b+'/check-due');proposal=c.get(f'/workspaces/{w}/proposals').json()[0]
    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as db:db.add(RecurringOccurrence(workspace_id=other,rule_id=rid,proposal_id=proposal['id'],scheduled_on='2026-11-11',account_id=foreign['asset'],category_id=foreign['expense']))
    with SessionLocal.begin() as db:
        outsider=create_user(db,uuid.uuid4().hex+'@test.local','long-test-password')
        secret=db.scalar(select(Membership.workspace_id).where(Membership.user_id==outsider.id))
        db.add(Membership(workspace_id=w,user_id=outsider.id,role='owner'))
        db.scalar(select(Membership).where(Membership.workspace_id==w,Membership.user_id==user.id)).role='member'
    assert c.get(f'/workspaces/{secret}/recurring').status_code==404
    assert c.post(f'/workspaces/{secret}/recurring/check-due').status_code==404
    monkeypatch.setattr(recurring,'MAX_RULES',1)
    assert c.post(b,json=body(a)).status_code==409
    row=c.get(b).json()[0];assert c.post(b+'/'+rid+'/pause',json={'paused':True,'version':row['version']}).status_code==200


def test_recurring_concurrent_generation_and_rollback(actor,clock,pg_only):
    c,w,user=actor;a=ids(c,w);data=RecurringCreate(**body(a))
    def create(_):
        with SessionLocal.begin() as db:return recurring.create(db,w,user.id,data)['id']
    with ThreadPoolExecutor(max_workers=4) as pool:rids=list(pool.map(create,range(4)))
    assert len(set(rids))==1;rid=rids[0]
    with pytest.raises(RuntimeError):
        with SessionLocal.begin() as db:recurring.generate_due(db,w);raise RuntimeError('simulate crash before commit')
    assert c.get(f'/workspaces/{w}/proposals').json()==[]
    assert c.get(f'/workspaces/{w}/recurring').json()[0]['next_on']=='2026-10-11'
    def generate(_):
        with SessionLocal.begin() as db:return recurring.generate_due(db,w)['created']
    with ThreadPoolExecutor(max_workers=4) as pool:counts=list(pool.map(generate,range(4)))
    assert sum(counts)==1
    with SessionLocal() as db:oid=db.scalar(select(RecurringOccurrence.id).where(RecurringOccurrence.rule_id==rid))
    for stmt in (update(RecurringOccurrence).where(RecurringOccurrence.id==oid).values(scheduled_on='2026-10-12'),delete(RecurringOccurrence).where(RecurringOccurrence.id==oid)):
        with pytest.raises(DBAPIError):
            with SessionLocal.begin() as db:db.execute(stmt)
    assert c.get(f'/workspaces/{w}/transactions').json()==[]
