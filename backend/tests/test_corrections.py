import uuid
import pytest
from sqlalchemy import select, func, update, delete
from sqlalchemy.exc import DBAPIError
from app.models import Entry, EntryRevision, Line
from app.db import SessionLocal
from app.worker import run_once
from app import ai
from test_finance import ids, payload
from test_reporting import record

def correction(a,amount=20000,day='2026-10-12',kind='expense',**kw):
    tx=payload(kind,a['asset'],amount,**({'category_id':a[kind]} if kind in ('expense','income') else {}),**kw)
    tx.update(occurred_on=day,description='แก้ไขแล้ว')
    return dict(reason='ตรวจสลิปแล้วแก้ยอด',idempotency_key=str(uuid.uuid4()),transaction=tx)

def test_correct_updates_balances_reports_budget_chat_and_preserves_original(actor,monkeypatch):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    old=record(c,w,a,amount=10000)
    c.put(b+f'/budgets/2026-10/{a["expense"]}',json={'amount':30000})
    data=correction(a);url=b+f'/transactions/{old["id"]}/correct'
    result=c.post(url,json=data);assert result.status_code==200,result.text
    new=result.json()['replacement'];assert new['amount']==20000
    assert c.post(url,json=data).json()==result.json()
    assert c.post(url,json={**data,'reason':'different'}).status_code==409
    assert c.post(url,json=correction(a)).status_code==409
    rows=c.get(b+'/transaction-report').json();assert rows['total']==1 and rows['expense']==20000
    assert c.get(b+'/dashboard?month=2026-10').json()['expense']==20000
    budget=c.get(b+'/budgets?month=2026-10').json();assert budget['spent']==20000
    balance=next(x['balance'] for x in c.get(b+'/accounts').json() if x['id']==a['asset']);assert balance==-20000
    detail=c.get(b+f'/transactions/{old["id"]}').json();assert detail['amount']==10000 and detail['status']=='corrected'
    assert detail['revision']['replacement']['id']==new['id']
    assert c.get(b+f'/transactions/{new["id"]}').json()['previous']['original']['id']==old['id']
    with SessionLocal() as db:
        entries=db.scalars(select(Entry).where(Entry.workspace_id==w)).all();assert len(entries)==3
        for entry in entries: assert db.scalar(select(func.sum(Line.signed_amount)).where(Line.entry_id==entry.id))==0
    def forbidden(*args,**kw): raise AssertionError('provider called')
    monkeypatch.setattr(ai.httpx,'Client',forbidden)
    room=c.post(b+'/conversations',json={'privacy':'private'}).json()['id']
    c.post(b+f'/conversations/{room}/messages',json={'text':'2026-10 ใช้เท่าไหร่'})
    while run_once(): pass
    assert '฿200.00' in c.get(b+f'/conversations/{room}/messages').json()[-1]['content']

def test_cross_month_category_account_changes_and_reverse_chain(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    bank=c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'}).json()['id']
    cat=c.post(b+'/accounts',json={'name':'ท่องเที่ยว','kind':'expense'}).json()['id']
    old=record(c,w,a,amount=10000)
    data=correction({**a,'asset':bank,'expense':cat},amount=5000,day='2026-09-30')
    result=c.post(b+f'/transactions/{old["id"]}/correct',json=data).json();new=result['replacement']
    assert c.get(b+'/dashboard?month=2026-10').json()['expense']==0
    summary=c.get(b+'/dashboard?month=2026-09').json();assert summary['expense']==5000 and summary['categories'][0]['id']==cat
    assert c.get(b+'/transaction-report',params={'account_id':a['asset']}).json()['total']==0
    url=b+f'/transactions/{new["id"]}/reverse';body={'reason':'รายการซ้ำ','idempotency_key':str(uuid.uuid4())}
    response=c.post(url,json=body);assert response.status_code==200,response.text
    assert c.post(url,json=body).json()==response.json()
    assert c.post(url,json={**body,'idempotency_key':str(uuid.uuid4())}).status_code==409
    assert c.get(b+'/transactions').json()==[]
    assert c.get(b+'/dashboard?month=2026-09').json()['expense']==0
    assert all(x['balance']==0 for x in c.get(b+'/accounts').json())
    audit=c.get(b+'/transaction-history').json();assert audit['total']==2
    assert {row['operation'] for row in audit['items']}=={'correct','reverse'}
    assert c.get(b+f'/transactions/{new["id"]}').json()['status']=='reversed'
    with SessionLocal() as db: inverse=db.scalar(select(EntryRevision.reversal_id).where(EntryRevision.workspace_id==w,EntryRevision.original_id==old['id']))
    assert c.get(b+f'/transactions/{inverse}').status_code==404
    assert c.post(b+f'/transactions/{inverse}/reverse',json=body).status_code==409

def test_invalid_correction_rolls_back_and_workspace_isolation(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}';old=record(c,w,a,amount=1000)
    foreign=c.post('/workspaces',json={'name':'other'}).json()['id'];fa=ids(c,foreign)
    for wrong in ({**a,'expense':fa['expense']},{**a,'asset':fa['asset']}):
        assert c.post(b+f'/transactions/{old["id"]}/correct',json=correction(wrong)).status_code==404
    for route in ('reverse','correct'):
        body=correction(a) if route=='correct' else {'reason':'a','idempotency_key':str(uuid.uuid4())}
        assert c.post(f'/workspaces/{foreign}/transactions/{old["id"]}/{route}',json=body).status_code==404
    assert c.get(f'/workspaces/{foreign}/transactions/{old["id"]}').status_code==404
    assert c.get(f'/workspaces/{foreign}/transaction-history').json()['total']==0
    assert c.get(b+'/transaction-history').json()['total']==0
    assert c.get(b+'/dashboard?month=2026-10').json()['expense']==1000
    assert c.post(b+f'/transactions/{old["id"]}/reverse',json={'reason':'  ','idempotency_key':str(uuid.uuid4())}).status_code==422
    replay=correction(a);replay['transaction']['idempotency_key']=old.get('idempotency_key','')
    # Reusing an existing posting key cannot silently link an old journal as a replacement.
    with SessionLocal() as db: replay['transaction']['idempotency_key']=db.get(Entry,old['id']).idempotency_key
    assert c.post(b+f'/transactions/{old["id"]}/correct',json=replay).status_code==409

@pytest.mark.parametrize('kind',['opening','income','expense','transfer','card_payment'])
def test_every_transaction_kind_corrects_then_reverses(actor,kind):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    extra={}
    if kind in ('transfer','card_payment'):
        other=c.post(b+'/accounts',json={'name':'ปลายทาง','kind':'asset' if kind=='transfer' else 'liability'}).json()['id'];extra={'other_account_id':other}
    old=record(c,w,a,kind=kind,amount=3000,**extra)
    response=c.post(b+f'/transactions/{old["id"]}/correct',json=correction(a,amount=7000,kind=kind,**extra));assert response.status_code==200,response.text
    new=response.json()['replacement'];assert len(c.get(b+'/transactions').json())==1
    if kind=='opening':
        assert c.post(b+'/transactions',json=payload('opening',a['asset'])).status_code==409
    result=c.post(b+f'/transactions/{new["id"]}/reverse',json={'reason':'ยกเลิก','idempotency_key':str(uuid.uuid4())});assert result.status_code==200,result.text
    assert all(row['balance']==0 for row in c.get(b+'/accounts').json())

def test_audit_is_immutable_and_inverse_is_validated(actor,pg_only):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}';old=record(c,w,a)
    response=c.post(b+f'/transactions/{old["id"]}/correct',json=correction(a));assert response.status_code==200,response.text
    for statement in (update(EntryRevision).where(EntryRevision.id==response.json()['id']).values(reason='tamper'),delete(EntryRevision).where(EntryRevision.id==response.json()['id'])):
        with pytest.raises(DBAPIError),SessionLocal.begin() as db: db.execute(statement)

def test_pg_concurrent_correction_only_one_replacement(actor,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    from app.corrections import revise
    from app.schemas import CorrectionInput
    c,w,user=actor;a=ids(c,w);old=record(c,w,a);data=CorrectionInput(**correction(a))
    def act(_):
        with SessionLocal.begin() as db: return revise(db,w,user.id,old['id'],data)['id']
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(act,range(4)))
    assert len(set(results))==1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Entry).where(Entry.workspace_id==w))==3
        assert db.scalar(select(func.count()).select_from(EntryRevision).where(EntryRevision.workspace_id==w))==1


def test_pg_rejects_fake_inverse_and_cross_tenant_audit(actor,pg_only):
    from app.ledger import post
    from app.schemas import TransactionInput
    c,w,user=actor;a=ids(c,w);old=record(c,w,a,amount=500)
    with pytest.raises(DBAPIError),SessionLocal.begin() as db:
        wrong=post(db,w,user.id,TransactionInput(**payload('income',a['asset'],600,category_id=a['income'])))
        db.add(EntryRevision(workspace_id=w,original_id=old['id'],reversal_id=wrong.id,reason='fake inverse',created_by=user.id,idempotency_key=str(uuid.uuid4()),fingerprint='x'*64));db.flush()
    other=c.post('/workspaces',json={'name':'foreign audit'}).json()['id'];fa=ids(c,other);foreign=record(c,other,fa)
    with pytest.raises(DBAPIError),SessionLocal.begin() as db:
        wrong=post(db,w,user.id,TransactionInput(**payload('income',a['asset'],500,category_id=a['income'])))
        db.add(EntryRevision(workspace_id=w,original_id=foreign['id'],reversal_id=wrong.id,reason='foreign',created_by=user.id,idempotency_key=str(uuid.uuid4()),fingerprint='x'*64));db.flush()
    assert c.get(f'/workspaces/{w}/transaction-history').json()['total']==0


def test_other_user_cannot_read_or_change_revision(actor):
    from app.bootstrap import create_user
    from app.models import Membership
    c,w,_=actor;a=ids(c,w);old=record(c,w,a)
    with SessionLocal.begin() as db:
        user=create_user(db,uuid.uuid4().hex+'@test.local','secure-correction-password')
        foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
    for suffix in ('transaction-history',f'transactions/{old["id"]}'):
        assert c.get(f'/workspaces/{foreign}/'+suffix).status_code==404
    for operation in ('correct','reverse'):
        data=correction(a) if operation=='correct' else {'reason':'test','idempotency_key':str(uuid.uuid4())}
        assert c.post(f'/workspaces/{foreign}/transactions/{old["id"]}/{operation}',json=data).status_code==404


def test_http_response_waits_for_session_and_workspace_commit(actor):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import Session, Workspace
    c,w,user=actor
    with SessionLocal() as db:
        baseline=db.scalar(select(func.count()).select_from(Session).where(Session.user_id==user.id))
    workspace_name='response-commit-'+uuid.uuid4().hex
    observed=[]
    async def checked(scope,receive,send):
        async def inspect(message):
            if message['type']=='http.response.start' and message['status']==200 and scope['method']=='POST':
                with SessionLocal() as db:
                    if scope['path']=='/auth/login':
                        assert db.scalar(select(func.count()).select_from(Session).where(Session.user_id==user.id))==baseline+1
                        observed.append('session')
                    elif scope['path']=='/workspaces':
                        assert db.scalar(select(Workspace.id).where(Workspace.name==workspace_name))
                        observed.append('workspace')
            await send(message)
        await app(scope,receive,inspect)
    with TestClient(checked,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        assert client.post('/auth/login',json={'email':user.email,'password':'secure-test-password'}).status_code==200
        assert client.post('/workspaces',json={'name':workspace_name}).status_code==200
    assert observed==['session','workspace']


def test_failed_commit_never_returns_success(actor,monkeypatch):
    from app.models import Workspace
    c,w,_=actor;name='failed-commit-'+uuid.uuid4().hex
    def fail(_): raise RuntimeError('simulated commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(SessionLocal.class_,'commit',fail)
        assert c.post('/workspaces',json={'name':name}).status_code==500
    with SessionLocal() as db:
        assert db.scalar(select(Workspace.id).where(Workspace.name==name)) is None
