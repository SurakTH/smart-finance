"""A waiting provider must not block authenticated reads of committed state."""
import time
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Workspace
from app.worker import run_once
from test_chat_actions import setup
from test_chat_stop import pending
from test_secretary import provider,transport,reply


def test_workspace_reads_complete_while_worker_waits_for_ai(actor,monkeypatch,pg_only):
    c,w,u,b,cid=setup(actor);provider(w)
    def handler(req):
        # Provider has not even returned headers; worker holds Workspace FOR UPDATE.
        paths=['/accounts','/transactions','/proposals','/dashboard','/conversations','/jobs',
               f'/conversations/{cid}/messages/page','/ai/settings','/providers','/ai/preferences','/ai/usage']
        for path in paths:
            started=time.monotonic();result=c.get(b+path)
            assert result.status_code==200,(path,result.status_code)
            assert time.monotonic()-started<2,path
        assert any(j['status']=='pending' and j['conversation_id']==cid for j in c.get(b+'/jobs').json())
        assert c.get(b+f'/conversations/{cid}/messages/page').json()['items'][-1]['role']=='user'
        return reply('รอ AI ได้โดยหน้าเว็บยังเปิดดูข้อมูลค่ะ')
    transport(monkeypatch,handler);pending(c,b,cid,'สวัสดี คุยกับฉันหน่อย')
    while run_once():pass
    assert 'หน้าเว็บยังเปิดดูข้อมูล' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']


def test_read_snapshot_still_denies_archived_workspace_and_removed_membership(actor):
    from app.models import Membership
    c,w,u,b,cid=setup(actor)
    with SessionLocal.begin() as db:db.get(Workspace,w).archived_at=1
    assert c.get(b+'/accounts').status_code==404
    from app.bootstrap import create_user
    from uuid import uuid4
    with SessionLocal.begin() as db:
        db.get(Workspace,w).archived_at=None
        successor=create_user(db,uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(user_id=successor.id,workspace_id=w,role='owner'))
        db.delete(db.get(Membership,(u.id,w)))
    assert c.get(b+'/accounts').status_code==404
    assert c.get(b+f'/conversations/{cid}/messages/page').status_code==404


def test_mutations_still_take_workspace_authorization_lock(actor,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.exc import OperationalError
    c,w,u,b,cid=setup(actor)
    # Hold the authorization dependency alone, then independently probe its lock.
    from app.security import workspace_member
    from starlette.requests import Request
    with SessionLocal.begin() as db:
        workspace_member(w,Request({'type':'http','method':'POST'}),u,db)
        def locked():
            with SessionLocal() as other:
                try:other.scalar(select(Workspace.id).where(Workspace.id==w).with_for_update(nowait=True))
                except OperationalError:return True
                return False
        with ThreadPoolExecutor(max_workers=1) as pool:assert pool.submit(locked).result(timeout=3)
