import json,time
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Job,Account,Membership,AIUsage,ChatAction
from app.worker import run_once
from test_assistant_finance import assistant,tool
from test_balance_summary import opening
from test_chat_actions import setup
from test_chat_stop import pending,stop
from test_secretary import provider,transport,reply


def test_fabricated_balance_replaced_by_verified_value(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    opening(c,b,wallet,123456)
    state['responses']=[{'content':'ตอนนี้คุณมีเงิน 999,999 บาทค่ะ'}]
    content=send('ตอนนี้ฉันมีเงินเท่าไร?')['content']
    assert '999,999' not in content and '1,234.56' in content


def test_false_saved_claim_never_reaches_user_or_ledger(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[{'content':'บันทึกกาแฟ 80 บาทเรียบร้อยแล้วค่ะ'}]*2
    content=send('ช่วยจดกาแฟ 80 บาท')['content']
    assert 'เรียบร้อยแล้ว' not in content
    assert c.get(b+'/transaction-report').json()['total']==0


def test_scope_not_broadened_by_summary_tool(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000)
    assert c.post(b+'/accounts',json={'name':'เดินทางเฉพาะทดสอบ','kind':'expense'}).status_code==200
    state['responses']=[tool('answer_finance_summary',{'report':'monthly'})]
    content=send('เฉพาะหมวดเดินทางเฉพาะทดสอบเดือนนี้ใช้เท่าไร')['content']
    assert '80.00' not in content and ('0.00' in content or 'ระบุ' in content)


def test_duplicate_monthly_read_keeps_question_scope(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    opening(c,b,wallet,100000);post(8000)
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'balances'}]}),tool('query_finance',{'operation':'monthly_analysis'}),tool('query_finance',{'operation':'monthly_analysis'})]
    content=send('สรุปรายจ่ายเดือนนี้ให้หน่อย')['content']
    assert '80.00' in content and '920.00' not in content


def test_write_during_inference_is_fast_and_invalidates_result(actor,monkeypatch,pg_only):
    c,w,u,b,cid=setup(actor);provider(w)
    def handler(req):
        started=time.monotonic()
        response=c.post(b+'/accounts',json={'name':'บัญชีระหว่างรอ','kind':'asset'})
        assert response.status_code==200,response.text
        assert time.monotonic()-started<2
        # Another worker cannot execute the same job.
        assert run_once() is False
        with SessionLocal() as db:
            assert db.scalar(select(AIUsage.status).where(AIUsage.workspace_id==w))=='reserved'
        return reply('สวัสดีค่ะ')
    transport(monkeypatch,handler);jid=pending(c,b,cid,'สวัสดี')
    assert run_once()
    with SessionLocal() as db:
        job=db.get(Job,jid);assert job.status=='failed' and job.error=='context_changed'
        assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))
        assert db.scalar(select(AIUsage.status).where(AIUsage.workspace_id==w))=='success'


def test_membership_revoked_during_inference_discards_answer(actor,monkeypatch,pg_only):
    c,w,u,b,cid=setup(actor);provider(w)
    from app.bootstrap import create_user
    from uuid import uuid4
    with SessionLocal.begin() as db:
        successor=create_user(db,uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(user_id=successor.id,workspace_id=w,role='owner'))
    def handler(req):
        with SessionLocal.begin() as db:db.delete(db.get(Membership,(u.id,w)))
        return reply('ข้อมูลส่วนตัวที่ต้องไม่ส่งกลับ')
    transport(monkeypatch,handler);jid=pending(c,b,cid,'สวัสดี');assert run_once()
    with SessionLocal() as db:
        job=db.get(Job,jid);assert job.status=='failed' and job.error=='membership_revoked'


def test_delete_room_during_inference_does_not_recreate_it(actor,monkeypatch,pg_only):
    from app.models import Conversation
    c,w,u,b,cid=setup(actor);provider(w)
    def handler(req):
        response=c.delete(b+f'/conversations/{cid}')
        assert response.status_code in (200,204),response.text
        return reply('ห้ามกลับมา')
    transport(monkeypatch,handler);jid=pending(c,b,cid,'สวัสดี');assert run_once()
    with SessionLocal() as db:assert db.get(Conversation,cid) is None and db.get(Job,jid) is None


def test_crash_releases_claim_but_keeps_usage_reservation(actor,monkeypatch,pg_only):
    import pytest
    c,w,u,b,cid=setup(actor);provider(w)
    def crash(req):raise SystemExit('synthetic crash')
    transport(monkeypatch,crash);jid=pending(c,b,cid,'สวัสดี')
    with pytest.raises(SystemExit):run_once()
    with SessionLocal() as db:
        assert db.get(Job,jid).status=='pending'
        assert db.scalar(select(AIUsage.id).where(AIUsage.workspace_id==w))
    transport(monkeypatch,lambda req:reply('สวัสดีค่ะ'))
    assert run_once()
    with SessionLocal() as db:assert db.get(Job,jid).status=='done'


def test_unverified_stream_is_never_published(assistant,monkeypatch):
    import httpx
    from app import ai,chat_stream
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;events=[]
    from httpx._client import Client as real
    opening(c,b,wallet,10000)
    body='data: '+json.dumps({'choices':[{'delta':{'content':'คุณมีเงิน 999999 บาท'},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n'
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(lambda req:httpx.Response(200,headers={'content-type':'text/event-stream'},content=body)),**kw))
    monkeypatch.setattr(chat_stream,'publish',lambda job,kind,**kw:events.append((kind,kw)))
    content=send('ตอนนี้มีเงินเท่าไร')['content']
    assert '100.00' in content and '999999' not in content
    assert not any(kind=='delta' for kind,_ in events)


def test_lab_uses_guarded_result_not_number_presence():
    from app.ai_sandbox import Sandbox,query_finance
    lab=Sandbox('monthly')
    raw='ยอด 450 บาทไม่ถูกต้อง เดือนนี้ใช้จริง 999999 บาท'
    result=lab.finish(raw,{('query_finance',''):query_finance('{"operation":"monthly_analysis"}')})
    assert '450.00' in result and '999999' not in result


def test_other_workspace_can_run_while_first_waits(actor,monkeypatch,pg_only):
    from app.bootstrap import create_user
    from app.models import Conversation,Message
    from app.main import enqueue
    from uuid import uuid4
    c,w,u,b,cid=setup(actor);provider(w)
    with SessionLocal.begin() as db:
        other=create_user(db,uuid4().hex+'@test.local','secure-test-password')
        other_w=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
    provider(other_w)
    state={}
    def handler(req):
        if not state.get('nested'):
            state['nested']=True
            with SessionLocal.begin() as db:
                room=Conversation(workspace_id=other_w,user_id=other.id);db.add(room);db.flush()
                msg=Message(workspace_id=other_w,conversation_id=room.id,role='user',content='สวัสดี');db.add(msg);db.flush()
                job=enqueue(db,other_w,other.id,'chat',{'conversation_id':room.id,'text':'สวัสดี','user_message_id':msg.id});state['jid']=job.id
            assert run_once()
        return reply('สวัสดีค่ะ')
    transport(monkeypatch,handler);first=pending(c,b,cid,'สวัสดี');assert run_once()
    with SessionLocal() as db:
        assert db.get(Job,first).status=='done' and db.get(Job,state['jid']).status=='done'


def test_chat_intent_inside_tool_cannot_bypass_answer_gate(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',{'intent':'chat','reply':'บันทึกกาแฟ 80 บาทเรียบร้อยแล้วค่ะ'})]
    content=send('ช่วยจดกาแฟ 80 บาท')['content']
    assert 'เรียบร้อยแล้ว' not in content and c.get(b+'/transaction-report').json()['total']==0


def test_comparison_uses_two_verified_months_not_single_month(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000);state['responses']=[tool('answer_finance_summary',{'report':'monthly'})]
    result=send('เปรียบเทียบรายจ่ายเดือนนี้กับเดือนที่แล้ว')['content']
    assert '80.00' in result and 'เดือนก่อน' in result and 'เปรียบเทียบ' in result
