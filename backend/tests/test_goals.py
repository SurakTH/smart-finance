import uuid
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from sqlalchemy import select,update,delete
from sqlalchemy.exc import DBAPIError,IntegrityError
from app import goals
from app.db import SessionLocal
from app.models import GoalMovement,Membership
from app.bootstrap import create_user
from app.schemas import GoalCreate,GoalAllocation

def create(c,b,**kw):
    data=dict(name='บ้านของเรา',target=10000,due_on='2026-12-31',idempotency_key=str(uuid.uuid4()));data.update(kw)
    r=c.post(b,json=data);assert r.status_code==200,r.text
    return r.json()['id'],data

def allocation(**kw):
    data=dict(kind='add',amount=2500,note='จัดสรรเดือนนี้',occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()));data.update(kw);return data

def test_goal_lifecycle_idempotency_no_ledger_changes(actor,monkeypatch):
    c,w,_=actor;b=f'/workspaces/{w}/goals';monkeypatch.setattr(goals,'today',lambda:date(2026,10,11))
    before=c.get(f'/workspaces/{w}/accounts').json();gid,data=create(c,b)
    assert c.post(b,json=data).json()=={'id':gid}
    assert c.post(b,json={**data,'target':20000}).status_code==409
    move=allocation();url=b+'/'+gid+'/allocations';response=c.post(url,json=move);assert response.status_code==200
    assert c.post(url,json=move).json()==response.json()
    assert c.post(url,json={**move,'amount':1}).status_code==409
    assert c.post(url,json=allocation(kind='remove',amount=2501)).status_code==409
    assert c.post(url,json=allocation(occurred_on='2026-10-12')).status_code==422
    row=c.get(b).json()['items'][0];assert (row['allocated'],row['remaining'],row['version'])==(2500,7500,2)
    edit=dict(name='บ้านใหม่',target=2000,due_on='2026-10-01',version=row['version'])
    assert c.put(b+'/'+gid,json=edit).json()['status']=='reached'
    assert c.put(b+'/'+gid,json=edit).status_code==409
    row=c.get(b).json()['items'][0]
    assert c.post(b+'/'+gid+'/archive',json={'archived':True,'version':row['version']}).status_code==200
    assert c.get(b).json()['allocated']==0
    assert c.post(url,json=move).json()==response.json()
    assert c.post(url,json=allocation()).status_code==409
    row=c.get(b).json()['items'][0]
    assert c.post(b+'/'+gid+'/archive',json={'archived':False,'version':row['version']}).status_code==200
    assert c.post(url,json=allocation(kind='remove',amount=1000)).status_code==200
    assert c.get(b).json()['items'][0]['status']=='overdue'
    assert c.get(url).json()['total']==2
    assert c.get(f'/workspaces/{w}/accounts').json()==before
    assert c.get(f'/workspaces/{w}/transactions').json()==[]

@pytest.mark.parametrize('target',[0,-1,True,1.1,'100',100_000_000_001])
def test_goal_money_validation(actor,target):
    c,w,_=actor
    assert c.post(f'/workspaces/{w}/goals',json=dict(name='เป้า',target=target,idempotency_key=str(uuid.uuid4()))).status_code==422

def test_goal_scope_validation_member_pagination(actor):
    c,w,user=actor;b=f'/workspaces/{w}/goals';gid,data=create(c,b)
    other=c.post('/workspaces',json={'name':'Separate'}).json()['id'];foreign=f'/workspaces/{other}/goals/{gid}'
    assert c.get(f'/workspaces/{other}/goals').json()['items']==[]
    assert c.post(foreign+'/allocations',json=allocation()).status_code==404
    assert c.get(foreign+'/allocations').status_code==404
    for wrong in ({'name':'   '},{'due_on':'not-a-date'}):assert c.post(b,json={**data,**wrong}).status_code==422
    for wrong in ({'amount':True},{'amount':'100'},{'note':'  '},{'kind':'transfer'}):assert c.post(b+'/'+gid+'/allocations',json=allocation(**wrong)).status_code==422
    for _ in range(31):assert c.post(b+'/'+gid+'/allocations',json=allocation(amount=1)).status_code==200
    first=c.get(b+'/'+gid+'/allocations').json();second=c.get(b+'/'+gid+'/allocations?page=2').json()
    assert first['total']==31 and len(first['items'])==30 and len(second['items'])==1
    assert len({r['id'] for r in first['items']+second['items']})==31
    with pytest.raises(IntegrityError):
        with SessionLocal.begin() as db:db.add(GoalMovement(workspace_id=other,goal_id=gid,signed_amount=1,note='bad',occurred_on='2026-10-10',created_by=user.id,idempotency_key=str(uuid.uuid4()),fingerprint='x'*64))
    with SessionLocal.begin() as db:
        outsider=create_user(db,uuid.uuid4().hex+'@test.local','test-password-long')
        secret=db.scalar(select(Membership.workspace_id).where(Membership.user_id==outsider.id))
        db.add(Membership(workspace_id=w,user_id=outsider.id,role='owner'))
        db.scalar(select(Membership).where(Membership.workspace_id==w,Membership.user_id==user.id)).role='member'
    assert c.get(f'/workspaces/{secret}/goals').status_code==404
    assert c.post(f'/workspaces/{secret}/goals',json=data).status_code==404
    assert c.post(b+'/'+gid+'/allocations',json=allocation(amount=1)).status_code==200

def test_goal_limits(actor,monkeypatch):
    c,w,_=actor;b=f'/workspaces/{w}/goals';monkeypatch.setattr(goals,'MAX_GOALS',1);gid,_=create(c,b)
    assert c.post(b,json={'name':'second','target':1,'idempotency_key':str(uuid.uuid4())}).status_code==409
    assert c.post(b+'/'+gid+'/allocations',json=allocation(amount=100_000_000_000)).status_code==200
    assert c.post(b+'/'+gid+'/allocations',json=allocation(amount=1)).status_code==422

def test_goal_pg_concurrency_immutable_history(actor,pg_only):
    c,w,user=actor;b=f'/workspaces/{w}/goals';data=GoalCreate(name='Concurrent',target=100,idempotency_key=uuid.uuid4())
    def save(_):
        with SessionLocal.begin() as db:return goals.create(db,w,user.id,data)['id']
    with ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(save,range(4)))
    assert len(set(ids))==1;gid=ids[0];move=GoalAllocation(**allocation(amount=100))
    def add(_):
        with SessionLocal.begin() as db:return goals.allocate(db,w,user.id,gid,move)['id']
    with ThreadPoolExecutor(max_workers=4) as pool:mids=list(pool.map(add,range(4)))
    assert len(set(mids))==1
    def remove(_):
        try:
            with SessionLocal.begin() as db:goals.allocate(db,w,user.id,gid,GoalAllocation(**allocation(kind='remove',amount=75)))
            return 200
        except HTTPException as e:return e.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:statuses=list(pool.map(remove,range(4)))
    assert sorted(statuses)==[200,409,409,409]
    assert c.get(b).json()['items'][0]['allocated']==25
    for stmt in (update(GoalMovement).where(GoalMovement.id==mids[0]).values(note='tampered'),delete(GoalMovement).where(GoalMovement.id==mids[0])):
        with pytest.raises(DBAPIError):
            with SessionLocal.begin() as db:db.execute(stmt)
    with pytest.raises(DBAPIError):
        with SessionLocal.begin() as db:db.add(GoalMovement(workspace_id=w,goal_id=gid,signed_amount=-26,note='bad',occurred_on='2026-10-10',created_by=user.id,idempotency_key=str(uuid.uuid4()),fingerprint='x'*64))
    assert c.get(b).json()['items'][0]['allocated']==25
