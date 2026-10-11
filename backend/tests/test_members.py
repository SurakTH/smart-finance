import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,delete,update,func
from sqlalchemy.exc import DBAPIError
from app.db import SessionLocal
from app.main import app
from app import members
from app.bootstrap import create_user
from app.models import Invitation,Membership,MembershipEvent,TelegramLink,LinkCode,Job,User,now
from app.security import digest
from app.worker import run_once

PW='test-members-password'
def client():return TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'})
def email():return uuid.uuid4().hex+'@test.local'
def invite(c,w,e):
    r=c.post(f'/workspaces/{w}/invitations',json={'email':e});assert r.status_code==200
    return r.json()
def recipient(c,w):
    e=email();i=invite(c,w,e);other=client()
    r=other.post('/auth/register-invite',json={'email':e,'token':i['token'],'password':PW});assert r.status_code==200
    uid=other.get('/auth/me').json()['id']
    return other,uid,i

def test_invite_registration_hash_cookie_membership_and_audit(actor):
    c,w,u=actor;e=email();i=invite(c,w,' '+e.upper()+' ')
    with SessionLocal() as db:
        row=db.get(Invitation,i['id']);assert row.token_hash==digest(i['token']) and row.token_hash!=i['token']
    assert 'token' not in str(c.get(f'/workspaces/{w}/invitations').json())
    assert c.post(f'/workspaces/{w}/invitations',json={'email':e}).status_code==409
    with client() as other:
        assert other.post('/invitations/preview',json={'email':email(),'token':i['token']}).status_code==410
        assert other.post('/auth/register-invite',json={'email':e,'token':i['token'],'password':'short'}).status_code==422
        assert other.post('/invitations/preview',json={'email':e,'token':i['token']}).json()['workspace_name']
        r=other.post('/auth/register-invite',json={'email':e,'token':i['token'],'password':PW});assert r.status_code==200
        assert all(s in r.headers['set-cookie'].lower() for s in ('httponly','secure','samesite=strict'))
        # New cookie must already reference a committed session and account.
        me=other.get('/auth/me');assert me.status_code==200
        assert len(other.get('/workspaces').json())==2
        assert other.get(f'/workspaces/{w}/accounts').status_code==200
        assert other.post('/invitations/accept',json={'token':i['token']}).json()['workspace_id']==w
        assert other.post('/auth/register-invite',json={'email':e,'token':i['token'],'password':PW}).status_code==410
        assert other.get(f'/workspaces/{w}/invitations').status_code==403
        assert other.get(f'/workspaces/{w}/membership-history').status_code==403
        assert other.post(f'/workspaces/{w}/invitations',json={'email':email()}).status_code==403
        roster=other.get(f'/workspaces/{w}/members').json();assert len(roster)==2 and next(x for x in roster if x['me'])['role']=='member'
    events=c.get(f'/workspaces/{w}/membership-history').json()['items'];assert {x['action'] for x in events}=={'invited','joined'}
    assert all(i['token'] not in str(x) for x in events)

def test_revoke_expiry_email_and_existing_account(actor):
    c,w,u=actor
    with SessionLocal.begin() as db:bob=create_user(db,email(),PW)
    i=invite(c,w,bob.email)
    with client() as other:
        assert other.post('/auth/register-invite',json={'email':bob.email,'token':i['token'],'password':PW}).status_code==409
        assert other.post('/auth/login',json={'email':bob.email,'password':PW}).status_code==200
        assert other.post('/invitations/accept',json={'token':i['token']}).status_code==200
    assert c.post(f'/workspaces/{w}/invitations',json={'email':bob.email}).status_code==409
    i=invite(c,w,email());url=f'/workspaces/{w}/invitations/{i["id"]}/revoke'
    assert c.post(url).status_code==200 and c.post(url).status_code==200
    assert c.post('/invitations/preview',json={'email':email(),'token':i['token']}).status_code==410
    e=email();i=invite(c,w,e)
    with SessionLocal.begin() as db:db.get(Invitation,i['id']).expires=now()-1
    assert c.post('/invitations/preview',json={'email':e,'token':i['token']}).status_code==410
    assert any(x['status']=='expired' for x in c.get(f'/workspaces/{w}/invitations').json())
    assert c.post('/invitations/accept',json={'token':'x'*43}).status_code==410

def test_roles_last_owner_and_leaving(actor):
    c,w,u=actor;b=f'/workspaces/{w}'
    assert c.post(b+'/leave').status_code==409
    assert c.delete(b+'/members/'+u.id).status_code==409
    assert c.post(b+'/members/'+u.id+'/role',json={'role':'member'}).status_code==409
    other,uid,_=recipient(c,w)
    try:
        assert other.post(b+'/members/'+u.id+'/role',json={'role':'member'}).status_code==403
        assert c.post(b+'/members/'+uid+'/role',json={'role':'owner'}).status_code==200
        assert c.post(b+'/leave').status_code==200
        assert c.get(b+'/accounts').status_code==404
        assert other.post(b+'/leave').status_code==409
        assert other.get(b+'/members').json()==[{'user_id':uid,'email':other.get('/auth/me').json()['email'],'role':'owner','me':True}]
    finally:other.close()

def test_removal_revokes_every_surface_telegram_jobs_and_old_code(actor,monkeypatch):
    c,w,u=actor;other,uid,i=recipient(c,w);b=f'/workspaces/{w}'
    try:
        room=other.post(b+'/conversations',json={}).json()['id']
        assert c.get(b+'/conversations/'+room+'/messages').status_code==404
        assert other.post(b+'/capture',json={'text':'ข้าว 50'}).status_code==200
        code=other.post(b+'/telegram/link-code',json={}).json()['code']
        with SessionLocal.begin() as db:db.add(TelegramLink(telegram_id=str(uuid.uuid4().int%10**12),workspace_id=w,user_id=uid))
        assert c.delete(b+'/members/'+uid).status_code==200
        assert other.post('/invitations/accept',json={'token':i['token']}).status_code==410
        for path in ['/accounts','/transactions','/dashboard','/budgets','/goals','/recurring','/providers','/conversations','/proposals','/jobs','/members','/transactions/export']:
            assert other.get(b+path).status_code==404,path
        assert other.post(b+'/capture',json={'text':'ข้าว 50'}).status_code==404
        assert other.get(b+'/conversations/'+room+'/messages').status_code==404
        with SessionLocal() as db:
            assert not db.scalar(select(TelegramLink).where(TelegramLink.workspace_id==w,TelegramLink.user_id==uid))
            assert not db.scalar(select(LinkCode).where(LinkCode.workspace_id==w,LinkCode.user_id==uid))
        monkeypatch.setattr('app.ai.httpx.Client',lambda **kw:pytest.fail('revoked job must not call a model'))
        while run_once():pass
        with SessionLocal() as db:
            j=db.scalar(select(Job).where(Job.workspace_id==w,Job.user_id==uid));assert j.status=='failed' and j.error=='membership_revoked'
        # Reinvitation is explicit; private history retained, no ledger deleted.
        ii=invite(c,w,other.get('/auth/me').json()['email'])
        assert other.post('/invitations/accept',json={'token':ii['token']}).status_code==200
        assert other.get(b+'/conversations/'+room+'/messages').status_code==200
    finally:other.close()

def test_members_tenant_scope_caps_and_history(actor,monkeypatch):
    c,w,u=actor
    with SessionLocal.begin() as db:
        outsider=create_user(db,email(),PW);foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==outsider.id))
    assert c.get(f'/workspaces/{foreign}/members').status_code==404
    i=invite(c,w,email())
    assert c.post(f'/workspaces/{foreign}/invitations/{i["id"]}/revoke').status_code==404
    assert c.delete(f'/workspaces/{w}/members/{outsider.id}').status_code==404
    monkeypatch.setattr(members,'MAX_INVITES',1)
    assert c.post(f'/workspaces/{w}/invitations',json={'email':email()}).status_code==409
    monkeypatch.setattr(members,'MAX_INVITES',100)
    for _ in range(30):invite(c,w,email())
    result=c.get(f'/workspaces/{w}/membership-history?page=2').json();assert result['total']==31 and len(result['items'])==1
    monkeypatch.setattr(members,'MAX_MEMBERS',1)
    with client() as other:
        assert other.post('/auth/register-invite',json={'email':c.get(f'/workspaces/{w}/invitations').json()[0]['email'],'token':'x'*43,'password':PW}).status_code==410
        e=email();ii=invite(c,w,e)
        assert other.post('/auth/register-invite',json={'email':e,'token':ii['token'],'password':PW}).status_code==409
        with SessionLocal() as db:assert not db.scalar(select(User.id).where(User.email==e))

def test_pg_immutable_audit_and_owner_invariant(actor,pg_only):
    c,w,u=actor;invite(c,w,email())
    with pytest.raises(DBAPIError):
        with SessionLocal.begin() as db:db.execute(update(MembershipEvent).where(MembershipEvent.workspace_id==w).values(email='tampered@test.local'))
    with pytest.raises(DBAPIError):
        with SessionLocal.begin() as db:db.execute(delete(Membership).where(Membership.workspace_id==w))
    with pytest.raises(DBAPIError):
        with SessionLocal.begin() as db:db.execute(update(Membership).where(Membership.workspace_id==w).values(role='member'))

def test_pg_concurrent_owners_cannot_both_leave(actor,pg_only):
    c,w,u=actor;other,uid,_=recipient(c,w)
    c.post(f'/workspaces/{w}/members/{uid}/role',json={'role':'owner'})
    def leave(user):
        from fastapi import HTTPException
        try:
            with SessionLocal.begin() as db:members.remove(db,w,user,user,leaving=True)
            return 200
        except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(leave,[u.id,uid]))
    assert sorted(results)==[200,409]
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id==w,Membership.role=='owner'))==1
    other.close()

def test_pg_concurrent_accept_once(actor,pg_only):
    c,w,u=actor
    with SessionLocal.begin() as db:bob=create_user(db,email(),PW)
    i=invite(c,w,bob.email)
    def accept(_):
        with SessionLocal.begin() as db:return members.accept(db,db.get(User,bob.id),i['token'])
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(accept,range(2)))
    assert results==[{'workspace_id':w}]*2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id==w,Membership.user_id==bob.id))==1
        assert db.scalar(select(func.count()).select_from(MembershipEvent).where(MembershipEvent.workspace_id==w,MembershipEvent.action=='joined'))==1

def test_pg_removal_waits_for_worker_authorization_lock(actor,pg_only,monkeypatch):
    from threading import Event
    from concurrent.futures import TimeoutError
    from app import ai
    c,w,u=actor;other,uid,_=recipient(c,w)
    other.post(f'/workspaces/{w}/capture',json={'text':'ข้าว 50'})
    started,release=Event(),Event()
    original=ai.process_job
    def blocked(db,job):
        if job.workspace_id!=w:
            job.status='failed';job.error='test_cleanup';return
        original(db,job);started.set();assert release.wait(5)
    monkeypatch.setattr('app.worker.process_job',blocked)
    def worker():
        while run_once():
            if started.is_set():return
    def remove():
        with SessionLocal.begin() as db:members.remove(db,w,u.id,uid)
    with ThreadPoolExecutor(2) as pool:
        work=pool.submit(worker)
        try:
            assert started.wait(5)
            removal=pool.submit(remove)
            with pytest.raises(TimeoutError):removal.result(timeout=.1)
        finally:release.set()
        work.result(timeout=5);removal.result(timeout=5)
    assert other.get(f'/workspaces/{w}/accounts').status_code==404
    other.close()

def test_pg_concurrent_registration_email_unique_and_atomic(actor,pg_only):
    from fastapi import HTTPException
    from app.schemas import InviteRegister
    from threading import Barrier
    c,w,u=actor;e=email();second=c.post('/workspaces',json={'name':'another invite space'}).json()['id']
    codes=[invite(c,w,e),invite(c,second,e)];barrier=Barrier(2)
    def register(i):
        barrier.wait(timeout=5)
        try:
            with SessionLocal.begin() as db:members.register(db,InviteRegister(email=e,token=i['token'],password=PW))
            return 200
        except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(register,codes))==[200,409]
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==e))
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id==user.id))==2
        assert db.scalar(select(func.count()).select_from(Invitation).where(Invitation.email==e,Invitation.status=='accepted'))==1
