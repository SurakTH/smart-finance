from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app import main
from app.db import SessionLocal
from app.models import User,Session
from app.security import verify,digest

def test_profile_private_persisted_validated(actor):
    client,wid,user=actor
    assert client.get('/auth/me').json()['name']==''
    result=client.put('/auth/profile',json={'name':'  ชื่อของฉัน  ','user_id':'someone-else'})
    assert result.status_code==200 and result.json()['name']=='ชื่อของฉัน'
    assert 'password' not in result.json()
    assert client.get('/auth/me').json()['email']==user.email
    for value in ('   ','x'*101,'bad\nname'):
        assert client.put('/auth/profile',json={'name':value}).status_code==422
    with SessionLocal() as db: assert db.get(User,user.id).name=='ชื่อของฉัน'
    with TestClient(main.app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as anonymous:
        assert anonymous.put('/auth/profile',json={'name':'other'}).status_code==401

def test_password_revoke_rotate_login(actor):
    client,wid,user=actor
    other=TestClient(main.app,base_url='https://testserver',headers={'X-SF-Request':'1'})
    assert other.post('/auth/login',json={'email':user.email,'password':'secure-test-password'}).status_code==200
    old=client.cookies.get('sf_session')
    data={'current_password':'secure-test-password','new_password':'different-secret-password','confirm_password':'different-secret-password'}
    for body,status in ((dict(data,current_password='wrong'),400),(dict(data,confirm_password='not-matching-password'),422),(dict(data,new_password='secure-test-password',confirm_password='secure-test-password'),422),(dict(data,new_password='short'),422),(dict(data,new_password=' '*12,confirm_password=' '*12),422)):
        assert client.post('/auth/password',json=body).status_code==status
        assert other.get('/auth/me').status_code==200
    response=client.post('/auth/password',json=data)
    assert response.status_code==200 and response.json()=={'ok':True}
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    assert client.cookies.get('sf_session')!=old
    assert client.get('/auth/me').status_code==200
    assert other.get('/auth/me').status_code==401
    with SessionLocal() as db:
        assert verify(data['new_password'],db.get(User,user.id).password)
        assert db.get(Session,digest(old)) is None
        assert db.scalar(select(func.count()).select_from(Session).where(Session.user_id==user.id))==1
    assert other.post('/auth/login',json={'email':user.email,'password':'secure-test-password'}).status_code==401
    assert other.post('/auth/login',json={'email':user.email,'password':data['new_password']}).status_code==200
    other.close()

def test_password_throttle_csrf_and_session_recheck(actor,monkeypatch):
    client,wid,user=actor
    seen=[]
    monkeypatch.setattr(main,'login_limit',lambda identity:seen.append(identity))
    data={'current_password':'wrong','new_password':'different-secret-password','confirm_password':'different-secret-password'}
    assert client.post('/auth/password',json=data).status_code==400
    assert seen==['password-change:'+user.id]
    assert client.post('/auth/password',json=data,headers={'Origin':'https://evil.invalid'}).status_code==403
    with SessionLocal.begin() as db:
        account=db.get(User,user.id)
        session=db.get(Session,digest(client.cookies.get('sf_session')))
        db.delete(session);db.flush()
        from fastapi import HTTPException
        import pytest
        class Request:
            cookies={'sf_session':client.cookies.get('sf_session')}
        with pytest.raises(HTTPException) as e: main.locked_account(db,account,Request())
        assert e.value.status_code==401

def test_profile_does_not_modify_other_user(actor):
    from app.bootstrap import create_user
    import uuid
    client,wid,user=actor
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','other-private-password')
        other.name='ชื่อคนอื่น'
        oid=other.id
    assert client.put('/auth/profile',json={'name':'ชื่อใหม่ของฉัน','id':oid}).status_code==200
    with SessionLocal() as db:
        assert db.get(User,oid).name=='ชื่อคนอื่น'
        assert verify('other-private-password',db.get(User,oid).password)

def test_concurrent_password_change_revokes_waiting_session(actor,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client,wid,user=actor
    token=client.cookies.get('sf_session');barrier=Barrier(2)
    def change(index):
        with TestClient(main.app,base_url='https://testserver',headers={'X-SF-Request':'1','Cookie':'sf_session='+token}) as c:
            password='new-private-password-'+str(index)
            barrier.wait()
            return c.post('/auth/password',json={'current_password':'secure-test-password','new_password':password,'confirm_password':password}).status_code
    with ThreadPoolExecutor(2) as pool: assert sorted(pool.map(change,range(2)))==[200,401]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Session).where(Session.user_id==user.id))==1
