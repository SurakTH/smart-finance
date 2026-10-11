import io
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.db import SessionLocal
from app.models import Account, Entry, Line, Job, Conversation, Message, Provider, Proposal, Membership, uid
from app.bootstrap import create_user
from app.worker import run_once
from app import config, ai
from app.schemas import TransactionInput
from app.ledger import post

def payload(kind,account,amount=10000,**kw):
    return dict(kind=kind,account_id=account,amount=amount,description='ทดสอบรายการ',occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()),**kw)

def ids(client,wid):
    rows=client.get(f'/workspaces/{wid}/accounts').json()
    return {kind:next(a['id'] for a in rows if a['kind']==kind) for kind in ('asset','income','expense')}

def test_ledger_flows_and_dashboard(actor):
    c,w,u=actor; b=f'/workspaces/{w}'; a=ids(c,w)
    bank=c.post(b+'/accounts',json={'name':'Bank','kind':'asset'}).json()['id']
    card=c.post(b+'/accounts',json={'name':'Card','kind':'liability'}).json()['id']
    rows=[payload('opening',a['asset'],1_000_000),payload('income',a['asset'],30_000,category_id=a['income']),payload('expense',a['asset'],5_000,category_id=a['expense']),payload('transfer',a['asset'],10_000,other_account_id=bank),payload('expense',card,5_000,category_id=a['expense']),payload('card_payment',a['asset'],5_000,other_account_id=card)]
    for p in rows:
        r=c.post(b+'/transactions',json=p); assert r.status_code==200,r.text
    balances={x['id']:x['balance'] for x in c.get(b+'/accounts').json()}
    assert balances[a['asset']]==1_010_000 and balances[bank]==10_000 and balances[card]==0
    s=c.get(b+'/dashboard?month=2026-10').json()
    assert (s['income'],s['expense'],s['net_worth'])==(30_000,10_000,1_020_000)
    assert s['categories'][0]['amount']==10_000
    with SessionLocal() as db:
        totals=db.execute(select(Line.entry_id,func.sum(Line.signed_amount)).where(Line.workspace_id==w).group_by(Line.entry_id)).all()
        assert len(totals)==6 and all(total==0 for _,total in totals)

def test_opening_liability_and_duplicate_opening(actor):
    c,w,_=actor;b=f'/workspaces/{w}'
    card=c.post(b+'/accounts',json={'name':'Card','kind':'liability'}).json()['id']
    assert c.post(b+'/transactions',json=payload('opening',card,25000)).status_code==200
    assert next(a for a in c.get(b+'/accounts').json() if a['id']==card)['balance']==25000
    assert c.post(b+'/transactions',json=payload('opening',card,25000)).status_code==409

def test_idempotency_and_conflict(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    p=payload('expense',a['asset'],category_id=a['expense'])
    one=c.post(b+'/transactions',json=p);two=c.post(b+'/transactions',json=p)
    assert one.json()['id']==two.json()['id']
    p['amount']=999
    assert c.post(b+'/transactions',json=p).status_code==409
    assert len(c.get(b+'/transactions').json())==1

@pytest.mark.parametrize('amount',[0,-1,1.5,True,'100',100_000_000_001])
def test_invalid_money_cannot_post(actor,amount):
    c,w,_=actor;a=ids(c,w)
    assert c.post(f'/workspaces/{w}/transactions',json=payload('expense',a['asset'],amount,category_id=a['expense'])).status_code==422
    assert c.get(f'/workspaces/{w}/transactions').json()==[]

def test_validation_atomic_and_cross_workspace(actor):
    c,w,_=actor;a=ids(c,w)
    with SessionLocal.begin() as db:
        bob=create_user(db,uuid.uuid4().hex+'@test.local','another-secure-password')
        other=db.scalar(select(Membership.workspace_id).where(Membership.user_id==bob.id))
        foreign=db.scalar(select(Account.id).where(Account.workspace_id==other,Account.kind=='expense'))
    assert c.get(f'/workspaces/{other}/accounts').status_code==404
    assert c.get(f'/workspaces/{other}/transactions').status_code==404
    assert c.post(f'/workspaces/{w}/transactions',json=payload('expense',a['asset'],category_id=foreign)).status_code==404
    assert c.post(f'/workspaces/{w}/transactions',json=payload('expense',a['asset'],category_id=a['income'])).status_code==422
    assert c.post(f'/workspaces/{w}/transactions',json=payload('transfer',a['asset'],other_account_id=a['asset'])).status_code==422
    assert c.get(f'/workspaces/{w}/transactions').json()==[]

def test_proposal_requires_confirm_and_replay_safe(actor):
    c,w,_=actor;b=f'/workspaces/{w}';a=ids(c,w)
    p=c.post(b+'/proposals',json={'description':'untrusted','amount':7500}).json()['id']
    assert c.get(b+'/transactions').json()==[]
    data=payload('expense',a['asset'],7500,category_id=a['expense'])
    r=c.post(b+f'/proposals/{p}/confirm',json=data)
    assert r.status_code==200
    data['idempotency_key']=str(uuid.uuid4())
    assert c.post(b+f'/proposals/{p}/confirm',json=data).json()['id']==r.json()['id']
    assert len(c.get(b+'/transactions').json())==1

def test_rejected_proposal_cannot_confirm(actor):
    c,w,_=actor;b=f'/workspaces/{w}';a=ids(c,w)
    p=c.post(b+'/proposals',json={'description':'No'}).json()['id']
    assert c.post(b+f'/proposals/{p}/reject',json={}).status_code==200
    assert c.post(b+f'/proposals/{p}/confirm',json=payload('expense',a['asset'],category_id=a['expense'])).status_code==409

def test_upload_validation_duplicate_and_isolation(actor):
    c,w,u=actor;b=f'/workspaces/{w}'
    assert c.post(b+'/attachments',files={'file':('bad.png',b'not an image','image/png')}).status_code==422
    buf=io.BytesIO();Image.new('RGB',(20,20),'white').save(buf,'PNG');data=buf.getvalue()
    result=c.post(b+'/attachments',files={'file':('ok.png',data,'image/png')}).json()
    assert not result['duplicate']
    assert c.post(b+'/attachments',files={'file':('ok.png',data,'image/png')}).json()['duplicate']
    assert c.get(b+'/attachments/'+result['id']).headers['content-type']=='image/jpeg'
    new=c.post('/workspaces',json={'name':'Isolated'}).json()['id']
    assert c.get(f'/workspaces/{new}/attachments/'+result['id']).status_code==404

def test_worker_mock_inbox_never_posts(actor):
    c,w,_=actor;b=f'/workspaces/{w}'
    c.post(b+'/capture',json={'text':'ข้าว 75 น้ำ 25'})
    while run_once(): pass
    rows=c.get(b+'/proposals').json()
    assert sorted(p['amount'] for p in rows)==[2500,7500]
    assert all(p['source']=='demo' and p['status']=='pending' for p in rows)
    assert c.get(b+'/transactions').json()==[]

def test_workspace_cloud_disabled_never_calls_cloud_and_delete(actor,monkeypatch):
    c,w,u=actor;b=f'/workspaces/{w}'
    monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',True)
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='openai',task='chat',model='fake',priority=1,encrypted_key='must-never-decrypt'))
    c.put(b+'/ai/settings',json={'cloud_enabled':False})
    def forbidden(*args,**kwargs): raise AssertionError('Private mode attempted external network')
    monkeypatch.setattr(ai.httpx,'Client',forbidden)
    room=c.post(b+'/conversations',json={'privacy':'private'}).json()['id']
    c.post(b+f'/conversations/{room}/messages',json={'text':'ยอดเงินเท่าไร'})
    while run_once(): pass
    messages=c.get(b+f'/conversations/{room}/messages').json()
    assert [m['role'] for m in messages]==['user','assistant']
    assert 'รายงานจากระบบโดยตรง' in messages[1]['content']
    assert c.delete(b+f'/conversations/{room}').status_code==200
    assert c.get(b+f'/conversations/{room}/messages').status_code==404

def test_provider_encryption_and_not_returned(actor,monkeypatch):
    from cryptography.fernet import Fernet
    c,w,_=actor;b=f'/workspaces/{w}'
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',True)
    p=c.post(b+'/providers',json={'kind':'gemini','model':'test-model','task':'chat','api_key':'secret-test-key'}).json()['id']
    assert 'secret-test-key' not in c.get(b+'/providers').text
    with SessionLocal() as db:
        value=db.get(Provider,p).encrypted_key
        assert 'secret-test-key' not in value
        assert config.cipher().decrypt(value.encode()).decode()=='secret-test-key'

def test_external_ai_disabled_by_default(actor,monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    c,w,_=actor;monkeypatch.setattr(config,'EXTERNAL_AI_ENABLED',False)
    assert c.get(f'/workspaces/{w}/ai/settings').json()['cloud_enabled'] is False
    # Configuration can be saved while cloud is off; runtime still enforces opt-in.
    assert c.post(f'/workspaces/{w}/providers',json={'kind':'openai','model':'fake','task':'chat','api_key':'key'}).status_code==200

def test_csrf_logout_and_session_flags(actor):
    c,w,_=actor
    assert c.post('/workspaces',json={'name':'evil'},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/workspaces',json={'name':'evil'},headers={'X-SF-Request':''}).status_code==403
    token=c.cookies.get('sf_session')
    assert token
    c.post('/auth/logout',json={})
    c.cookies.set('sf_session',token)
    assert c.get('/auth/me').status_code==401

def test_composite_fk_blocks_cross_tenant_lines(actor):
    c,w,u=actor;a=ids(c,w)
    other=c.post('/workspaces',json={'name':'other'}).json()['id']
    foreign=ids(c,other)['asset']
    with pytest.raises(IntegrityError),SessionLocal.begin() as db:
        e=Entry(workspace_id=w,created_by=u.id,idempotency_key=uid(),fingerprint='a'*64,kind='expense',description='invalid',amount=100,occurred_on='2026-10-10')
        db.add(e);db.flush()
        db.add(Line(workspace_id=w,entry_id=e.id,account_id=foreign,signed_amount=100));db.flush()

def test_pg_deferred_balance_and_immutability(actor,pg_only):
    c,w,u=actor;a=ids(c,w)
    with pytest.raises(DBAPIError),SessionLocal.begin() as db:
        e=Entry(workspace_id=w,created_by=u.id,idempotency_key=uid(),fingerprint='a'*64,kind='expense',description='unbalanced',amount=100,occurred_on='2026-10-10')
        db.add(e);db.flush();db.add(Line(workspace_id=w,entry_id=e.id,account_id=a['asset'],signed_amount=100))
    p=payload('expense',a['asset'],category_id=a['expense'])
    entry=c.post(f'/workspaces/{w}/transactions',json=p).json()['id']
    with pytest.raises(DBAPIError),SessionLocal.begin() as db:
        db.execute(text('UPDATE entries SET description=\'tampered\' WHERE id=:id'),{'id':entry})
    with pytest.raises(DBAPIError),SessionLocal.begin() as db:
        db.add(Line(workspace_id=w,entry_id=entry,account_id=a['asset'],signed_amount=100))

def test_pg_concurrent_posting_idempotent(actor,pg_only):
    c,w,u=actor;a=ids(c,w);p=TransactionInput(**payload('expense',a['asset'],category_id=a['expense']))
    def attempt(_):
        with SessionLocal.begin() as db: return post(db,w,u.id,p).id
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(attempt,range(4)))
    assert len(set(results))==1
    assert len(c.get(f'/workspaces/{w}/transactions').json())==1
