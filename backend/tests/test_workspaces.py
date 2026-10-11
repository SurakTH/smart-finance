import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Workspace,Entry,Invitation,Job,now
from app import ai,chat_stream
from app.worker import run_once
from app.recurring import generate_due
from app.workspaces import archive
from app.schemas import WorkspaceArchive,TransactionInput
from app.ledger import post
from test_finance import ids,payload
from test_members import recipient,client,email,PW

def row(c,w):return next(x for x in c.get('/workspace-management').json() if x['id']==w)
def change(c,w,archived=True,name=None,version=None):
    r=row(c,w)
    return c.post(f'/workspace-management/{w}/archive',json={'archived':archived,'confirm_name':r['name'] if name is None else name,'version':r['version'] if version is None else version})

def test_workspace_rename_role_version_and_scope(actor):
    c,w,u=actor;other,uid,_=recipient(c,w)
    assert row(c,w)['members']==2
    old=row(c,w);url=f'/workspace-management/{w}'
    assert other.put(url,json={'name':'no','version':1}).status_code==403
    foreign=c.post('/workspaces',json={'name':'private'}).json()['id']
    assert all(x['id']!=foreign for x in other.get('/workspace-management').json())
    assert other.put(f'/workspace-management/{foreign}',json={'name':'no','version':1}).status_code==404
    assert c.put(url,json={'name':' บ้านใหม่ ','version':old['version']}).status_code==200
    assert row(c,w)['name']=='บ้านใหม่'
    assert c.put(url,json={'name':'stale','version':old['version']}).status_code==409
    assert c.put(url,json={'name':'   ','version':2}).status_code==422
    assert row(other,w)['name']=='บ้านใหม่' and change(other,w).status_code==403
    other.close()

def test_empty_delete_requires_exact_name_and_preserves_user(actor):
    c,w,u=actor;r=row(c,w);assert r['can_delete']
    url=f'/workspace-management/{w}/delete'
    assert c.post(url,json={'confirm_name':'wrong','version':r['version']}).status_code==422
    assert c.post(url,json={'confirm_name':r['name'],'version':r['version']}).status_code==200
    assert c.get('/workspaces').json()==[] and c.get('/workspace-management').json()==[]
    assert c.get('/auth/me').status_code==200
    assert c.post(url,json={'confirm_name':r['name'],'version':r['version']}).status_code==404
    assert c.post('/workspaces',json={'name':'เริ่มใหม่'}).status_code==200

def test_nonempty_cannot_delete_archive_preserves_and_restores_data(actor):
    c,w,u=actor;a=ids(c,w);b=f'/workspaces/{w}'
    posted=c.post(b+'/transactions',json=payload('expense',a['asset'],category_id=a['expense'])).json()
    assert not row(c,w)['can_delete']
    r=row(c,w);assert c.post(f'/workspace-management/{w}/delete',json={'confirm_name':r['name'],'version':r['version']}).status_code==409
    assert change(c,w,name='wrong').status_code==422 and change(c,w).status_code==200
    assert c.get('/workspaces').json()==[] and row(c,w)['archived']
    for path in ('accounts','dashboard','transactions','conversations','proposals','members'):assert c.get(b+'/'+path).status_code==404
    assert c.post(b+'/transactions',json=payload('expense',a['asset'],category_id=a['expense'])).status_code==404
    with SessionLocal.begin() as db:
        assert db.get(Entry,posted['id']) is not None
        with pytest.raises(HTTPException):post(db,w,u.id,TransactionInput(**payload('expense',a['asset'],category_id=a['expense'])))
    assert change(c,w,False).status_code==200 and c.get(b+'/transactions').json()[0]['id']==posted['id']

def test_archive_suspends_jobs_scheduler_invites_bot_and_sse(actor,monkeypatch):
    from app.bot import linked
    from app.models import TelegramLink
    from app.reporting import today
    c,w,u=actor;b=f'/workspaces/{w}';a=ids(c,w)
    while run_once():pass
    cid=c.post(b+'/conversations',json={}).json()['id']
    jid=c.post(b+f'/conversations/{cid}/messages',json={'text':'ทดสอบหยุดงาน'}).json()['job_id']
    rule=c.post(b+'/recurring',json={'kind':'expense','description':'รอบพัก','amount':100,'account_id':a['asset'],'category_id':a['expense'],'frequency':'daily','start_on':today().isoformat(),'idempotency_key':str(uuid.uuid4())});assert rule.status_code==200,rule.text
    e=email();inv=c.post(b+'/account-invitations',json={'email':e}).json();tg=str(uuid.uuid4().int%10**18)
    with SessionLocal.begin() as db:db.add(TelegramLink(telegram_id=tg,workspace_id=w,user_id=u.id))
    assert change(c,w).status_code==200 and not run_once()
    with SessionLocal.begin() as db:
        assert generate_due(db,wid=w)['created']==0 and db.get(Job,jid).status=='pending'
        assert linked(db,tg) is None
    with pytest.raises(HTTPException):chat_stream.authorized(c.cookies.get('sf_session'),w,cid)
    with client() as other:
        assert other.post('/invitations/preview',json={'email':e,'token':inv['token']}).status_code==404
        assert other.post('/auth/register-invite',json={'email':e,'token':inv['token'],'password':PW}).status_code==404
    assert change(c,w,False).status_code==200
    monkeypatch.setattr(ai,'call_model',lambda db,job:('กลับมาทำงานแล้ว',True));assert run_once()
    assert c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']=='กลับมาทำงานแล้ว'
    with SessionLocal.begin() as db:assert generate_due(db,wid=w)['created']==1

def test_private_account_is_not_workspace_sharing(actor):
    c,w,u=actor;e=email();b=f'/workspaces/{w}'
    invite=c.post(b+'/account-invitations',json={'email':e});assert invite.status_code==200
    token=invite.json()['token'];iid=invite.json()['id']
    with SessionLocal() as db:
        from app.security import digest
        assert db.get(Invitation,iid).token_hash==digest(token)
    with client() as other:
        assert other.post('/invitations/preview',json={'email':email(),'token':token}).status_code==410
        assert other.post('/invitations/preview',json={'email':e,'token':token}).json()['mode']=='personal'
        bad=other.post('/auth/register-invite',json={'email':e,'token':token,'password':'short'});assert bad.status_code==422 and 'short' not in bad.text and token not in bad.text
        result=other.post('/auth/register-invite',json={'email':e,'token':token,'password':PW});assert result.status_code==200
        personal=result.json()['workspace_id'];assert personal!=w
        assert len(other.get('/workspaces').json())==1
        assert other.get(b+'/accounts').status_code==404 and c.get(f'/workspaces/{personal}/accounts').status_code==404
        assert other.post('/invitations/accept',json={'token':token}).json()['workspace_id']==personal
        assert other.post('/auth/register-invite',json={'email':e,'token':token,'password':PW}).status_code==410
        a=ids(other,personal);other.post(f'/workspaces/{personal}/transactions',json=payload('expense',a['asset'],category_id=a['expense']))
        assert c.get(f'/workspaces/{personal}/transactions').status_code==404 and len(c.get(b+'/members').json())==1
        shared=c.post(b+'/invitations',json={'email':e}).json()
        assert other.post('/invitations/accept',json={'token':shared['token']}).status_code==200
        assert other.get(b+'/accounts').status_code==200
    assert c.post(b+'/account-invitations',json={'email':e}).status_code==409

def test_personal_invite_revoke_expiry_and_content_blocks_delete(actor):
    c,w,u=actor;b=f'/workspaces/{w}';e=email();inv=c.post(b+'/account-invitations',json={'email':e}).json()
    assert not row(c,w)['can_delete'] and c.post(b+f"/invitations/{inv['id']}/revoke").status_code==200
    with client() as other:assert other.post('/auth/register-invite',json={'email':e,'token':inv['token'],'password':PW}).status_code==410
    inv=c.post(b+'/account-invitations',json={'email':e}).json()
    with SessionLocal.begin() as db:db.get(Invitation,inv['id']).expires=now()-1
    with client() as other:assert other.post('/auth/register-invite',json={'email':e,'token':inv['token'],'password':PW}).status_code==410

def test_pg_archive_versions_serialize_and_empty_delete_commits(actor,pg_only):
    c,w,u=actor;data=WorkspaceArchive(archived=True,confirm_name=row(c,w)['name'],version=1)
    def attempt(_):
        try:
            with SessionLocal.begin() as db:archive(db,w,u.id,data)
            return 200
        except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(attempt,range(2)))==[200,409]
    assert change(c,w,False).status_code==200
    r=row(c,w);assert c.post(f'/workspace-management/{w}/delete',json={'confirm_name':r['name'],'version':r['version']}).status_code==200
