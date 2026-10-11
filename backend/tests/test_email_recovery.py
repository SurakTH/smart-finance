import json,secrets
from urllib.parse import urlsplit,parse_qs
import pytest
from sqlalchemy import select
from app import config,email_recovery,main
from app.db import SessionLocal
from app.models import User,EmailToken,Session,now
from app.security import digest,verify

@pytest.fixture
def mailbox(actor,monkeypatch):
    monkeypatch.setattr(config,'MAIL_ENABLED',True)
    monkeypatch.setattr(config,'SMTP_HOST','smtp.test.local')
    monkeypatch.setattr(config,'SMTP_FROM','finance@test.local')
    monkeypatch.setattr(config,'SMTP_SECURITY','starttls')
    from cryptography.fernet import Fernet
    monkeypatch.setenv('ENCRYPTION_KEY',Fernet.generate_key().decode())
    sent=[];monkeypatch.setattr(email_recovery,'send',sent.append)
    issued_users=set()
    real_issue=email_recovery.issue
    def tracked_issue(db,user,purpose):
        issued_users.add(user.id)
        return real_issue(db,user,purpose)
    monkeypatch.setattr(email_recovery,'issue',tracked_issue)
    yield actor,sent
    from sqlalchemy import delete
    with SessionLocal.begin() as db:
        db.execute(delete(EmailToken).where(EmailToken.user_id.in_(issued_users)))

def latest(user,purpose):
    with SessionLocal() as db:
        row=db.scalar(select(EmailToken).where(EmailToken.user_id==user.id,EmailToken.purpose==purpose,EmailToken.used.is_(False)))
        payload=json.loads(config.cipher().decrypt(row.encrypted_payload.encode()))
        raw=parse_qs(urlsplit(payload['url']).fragment)['token'][0]
        assert urlsplit(payload['url']).query==''
        assert raw not in row.encrypted_payload and row.token_hash==digest(raw)
        return raw

def body(token):return {'token':token,'password':'new-secure-password','confirm_password':'new-secure-password'}

def test_generic_disabled(actor,monkeypatch):
    client,wid,user=actor;monkeypatch.setattr(config,'MAIL_ENABLED',False)
    a=client.post('/auth/forgot-password',json={'email':user.email})
    b=client.post('/auth/forgot-password',json={'email':'absent@test.local'})
    assert a.status_code==b.status_code==200 and a.json()==b.json()
    with SessionLocal() as db:assert not db.scalar(select(EmailToken).where(EmailToken.user_id==user.id))
    assert client.post('/auth/request-verification').status_code==503

def test_reset_revoke_replay(mailbox):
    (client,wid,user),sent=mailbox
    client.post('/auth/login',json={'email':user.email,'password':'secure-test-password'})
    a=client.post('/auth/forgot-password',json={'email':user.email})
    assert a.json()==client.post('/auth/forgot-password',json={'email':'absent@test.local'}).json()
    raw=latest(user,'reset');assert email_recovery.deliver_once() and len(sent)==1
    assert client.post('/auth/reset-password',json=body(raw)).status_code==200
    assert client.get('/auth/me').status_code==401
    assert client.post('/auth/reset-password',json=body(raw)).status_code==400
    with SessionLocal() as db:
        assert not db.scalar(select(Session).where(Session.user_id==user.id))
        u=db.get(User,user.id);assert verify('new-secure-password',u.password) and u.email_verified_at
        row=db.get(EmailToken,digest(raw));assert row.used and row.encrypted_payload is None
    assert client.post('/auth/login',json={'email':user.email,'password':'secure-test-password'}).status_code==401
    assert client.post('/auth/login',json={'email':user.email,'password':'new-secure-password'}).status_code==200

def test_expiry_supersede(mailbox):
    (client,wid,user),sent=mailbox
    client.post('/auth/forgot-password',json={'email':user.email});old=latest(user,'reset')
    client.post('/auth/forgot-password',json={'email':user.email});raw=latest(user,'reset')
    assert old!=raw and client.post('/auth/reset-password',json=body(old)).status_code==400
    with SessionLocal.begin() as db:db.get(EmailToken,digest(raw)).expires=now()-1
    assert client.post('/auth/reset-password',json=body(raw)).status_code==400
    email_recovery.deliver_once();assert not sent

def test_verify_purpose_replay(mailbox):
    (client,wid,user),sent=mailbox
    assert client.get('/auth/email-status').json()=={'verified':False,'delivery_enabled':True}
    assert client.post('/auth/request-verification').status_code==200
    raw=latest(user,'verify')
    assert client.post('/auth/reset-password',json=body(raw)).status_code==400
    assert client.get('/auth/email-status').json()['verified'] is False
    assert client.post('/auth/verify-email',json={'token':raw}).status_code==200
    assert client.get('/auth/email-status').json()['verified'] is True
    assert client.post('/auth/verify-email',json={'token':raw}).status_code==400
    assert client.get('/auth/me').status_code==200

def test_password_change_cancels_link(mailbox):
    (client,wid,user),sent=mailbox
    client.post('/auth/forgot-password',json={'email':user.email});raw=latest(user,'reset')
    assert client.post('/auth/password',json={'current_password':'secure-test-password','new_password':'changed-password-123','confirm_password':'changed-password-123'}).status_code==200
    assert client.post('/auth/reset-password',json=body(raw)).status_code==400
    email_recovery.deliver_once();assert not sent

def test_validation_redacted(actor):
    client,wid,user=actor;marker='secret-marker'
    for path,data in [('/auth/reset-password',{'token':marker,'password':marker,'confirm_password':marker}),('/auth/verify-email',{'token':marker}),('/auth/forgot-password',{'email':marker})]:
        r=client.post(path,json=data);assert r.status_code==422 and marker not in r.text

def test_rate_limits(actor,monkeypatch):
    client,wid,user=actor;calls=[];monkeypatch.setattr(main,'login_limit',calls.append)
    client.post('/auth/forgot-password',json={'email':user.email})
    client.post('/auth/request-verification')
    client.post('/auth/verify-email',json={'token':secrets.token_urlsafe(48)})
    client.post('/auth/reset-password',json=body(secrets.token_urlsafe(48)))
    assert {x.split(':')[0] for x in calls}=={'reset-ip','reset-email','verify-user','verify-consume','reset-consume'}

def test_worker_retry_scrub(mailbox,monkeypatch):
    (client,wid,user),sent=mailbox
    client.post('/auth/forgot-password',json={'email':user.email});raw=latest(user,'reset')
    def fail(payload):raise RuntimeError('private credential never stored')
    monkeypatch.setattr(email_recovery,'send',fail)
    for i in range(3):
        with SessionLocal.begin() as db:db.get(EmailToken,digest(raw)).next_attempt=0
        assert email_recovery.deliver_once()
    with SessionLocal() as db:
        row=db.get(EmailToken,digest(raw));assert row.attempts==3 and row.delivery=='failed' and row.encrypted_payload is None

def test_registration_verification(mailbox,monkeypatch):
    (client,wid,user),sent=mailbox;monkeypatch.setattr(config,'ALLOW_REGISTRATION',True)
    email=secrets.token_hex(16)+'@test.local'
    r=client.post('/auth/register',json={'email':email,'name':'New','password':'secure-test-password','confirm_password':'secure-test-password'})
    assert r.status_code==201
    with SessionLocal() as db:
        u=db.scalar(select(User).where(User.email==email));assert db.scalar(select(EmailToken).where(EmailToken.user_id==u.id,EmailToken.purpose=='verify'))

def test_smtp_tls_transport(monkeypatch):
    calls=[]
    class SMTP:
        def __init__(self,*args,**kw):calls.append(('connect',kw['timeout']))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):calls.append(('ehlo',))
        def starttls(self,**kw):assert kw['context'].check_hostname;calls.append(('tls',))
        def login(self,*args):calls.append(('login',))
        def send_message(self,message):
            assert message['To']=='owner@test.local'
            assert '#token=' in message.get_content()
            calls.append(('send',))
    monkeypatch.setattr(config,'SMTP_SECURITY','starttls')
    monkeypatch.setattr(config,'SMTP_USERNAME','test-user')
    monkeypatch.setattr(config,'SMTP_PASSWORD','test-only-password')
    monkeypatch.setattr(config,'SMTP_FROM','finance@test.local')
    monkeypatch.setattr(email_recovery.smtplib,'SMTP',SMTP)
    email_recovery.send({'email':'owner@test.local','purpose':'reset','url':'https://test.local/reset-password#token=synthetic'})
    assert calls==[('connect',10),('ehlo',),('tls',),('ehlo',),('login',),('send',)]

def test_mismatch_does_not_consume(mailbox):
    (client,wid,user),sent=mailbox
    client.post('/auth/forgot-password',json={'email':user.email});raw=latest(user,'reset')
    bad=body(raw);bad['confirm_password']='different-password'
    assert client.post('/auth/reset-password',json=bad).status_code==422
    assert client.post('/auth/reset-password',json=body(raw)).status_code==200


def test_concurrent_one_use_postgres(mailbox,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    (client,wid,user),sent=mailbox
    client.post('/auth/request-verification');raw=latest(user,'verify')
    def consume():
        try:
            with SessionLocal.begin() as db:
                account=email_recovery.consume(db,raw,'verify')
                account.email_verified_at=now()
            return 'ok'
        except HTTPException as error:
            assert error.status_code==400
            return 'used'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _:consume(),range(2)))==['ok','used']


def test_cleanup_expired_mail_even_when_disabled(mailbox,monkeypatch):
    from app.worker import cleanup_once
    (client,wid,user),sent=mailbox
    client.post('/auth/forgot-password',json={'email':user.email});raw=latest(user,'reset')
    with SessionLocal.begin() as db:db.get(EmailToken,digest(raw)).expires=now()-1
    monkeypatch.setattr(config,'MAIL_ENABLED',False)
    cleanup_once()
    with SessionLocal() as db:
        row=db.get(EmailToken,digest(raw));assert row.encrypted_payload is None and row.used
