import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app import main,config
from app.db import SessionLocal
from app.models import User,Membership,Session,Workspace

@pytest.fixture
def signup(monkeypatch):
    monkeypatch.setattr(main,'login_limit',lambda _:None)
    monkeypatch.setattr(config,'ALLOW_REGISTRATION',True)
    with TestClient(main.app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        yield client

def payload():
    return {'email':uuid.uuid4().hex+'@example.test','name':'  คนใหม่  ','password':'private-registration-password','confirm_password':'private-registration-password'}

def test_disabled_blocks_direct_signup(signup,monkeypatch):
    monkeypatch.setattr(config,'ALLOW_REGISTRATION',False)
    data=payload()
    assert signup.get('/auth/options').json()['allow_registration'] is False
    assert signup.post('/auth/register',json=data).status_code==403
    with SessionLocal() as db:assert db.scalar(select(User).where(User.email==data['email'])) is None
    assert signup.get('/auth/me').status_code==401

def test_signup_session_private_workspace_and_login(signup,actor):
    other,wid,_=actor
    data=payload();data['email']='  '+data['email'].upper()+'  '
    response=signup.post('/auth/register',json=data)
    assert response.status_code==201,response.text
    result=response.json();assert result['name']=='คนใหม่';assert result['email']==data['email'].strip().lower()
    cookie=response.headers['set-cookie'];assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    spaces=signup.get('/workspaces').json();assert len(spaces)==1 and spaces[0]['id']==result['workspace_id']
    own=spaces[0]['id'];assert own!=wid
    assert len(signup.get(f'/workspaces/{own}/accounts').json())==6
    assert signup.get(f'/workspaces/{own}/transactions').json()==[]
    assert signup.get(f'/workspaces/{wid}/accounts').status_code==404
    assert other.get(f'/workspaces/{own}/accounts').status_code==404
    with SessionLocal() as db:
        user=db.get(User,result['id']);assert user.password!=data['password']
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id==user.id))==1
    assert signup.post('/auth/logout').status_code==200
    assert signup.post('/auth/login',json={'email':result['email'],'password':data['password']}).status_code==200

def test_duplicate_email_no_extra_workspace(signup):
    data=payload();first=signup.post('/auth/register',json=data).json()
    with SessionLocal() as db:before=db.scalar(select(func.count()).select_from(Workspace))
    assert signup.post('/auth/register',json={**data,'email':data['email'].upper()}).status_code==409
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Workspace))==before
    assert signup.get('/auth/me').json()['id']==first['id']

@pytest.mark.parametrize('changes',[{'password':'short'},{'confirm_password':'different-password'},{'email':'bad-email'},{'name':'x'*101}])
def test_invalid_data_redacted_and_no_user(signup,changes):
    data=payload()|changes;r=signup.post('/auth/register',json=data)
    assert r.status_code==422
    assert data['password'] not in r.text and data['email'] not in r.text
    assert 'input' not in r.text
    with SessionLocal() as db:assert db.scalar(select(User).where(User.email==data['email'])) is None

def test_throttle_fail_closed(signup,monkeypatch):
    from fastapi import HTTPException
    seen=[]
    def limit(key):
        seen.append(key)
        if len(seen)==2:raise HTTPException(429,'กรุณาลองใหม่ภายหลัง')
    monkeypatch.setattr(main,'login_limit',limit)
    data=payload();assert signup.post('/auth/register',json=data).status_code==429
    assert seen==['register-ip:testclient','register-email:'+data['email']]
    with SessionLocal() as db:assert db.scalar(select(User).where(User.email==data['email'])) is None

def test_origin_guard(signup):
    assert signup.post('/auth/register',headers={'Origin':'https://other.invalid'},json=payload()).status_code==403
    with TestClient(main.app,base_url='https://testserver') as client:
        assert client.post('/auth/register',json=payload()).status_code==403

def test_session_failure_rolls_back_user_and_workspace(signup,monkeypatch):
    def fail_session(**kwargs):raise RuntimeError('simulated session failure')
    monkeypatch.setattr(main,'Session',fail_session)
    data=payload()
    with SessionLocal() as db:before=db.scalar(select(func.count()).select_from(Workspace))
    assert signup.post('/auth/register',json=data).status_code==500
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email==data['email'])) is None
        assert db.scalar(select(func.count()).select_from(Workspace))==before
