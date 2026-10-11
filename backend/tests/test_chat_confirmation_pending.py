"""Confirmation cannot inherit an older action while a new request is in flight."""
from app import ai
from app.db import SessionLocal
from app.models import Job
from test_chat_actions import setup,say,count,CREATE,code
from test_chat_dialogue import suggestion,mock_provider,run


def process(jid):
    with SessionLocal.begin() as db:ai.process_job(db,db.get(Job,jid))


def test_confirm_during_new_request_waits_then_confirms_new_draft(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    old=code(say(c,b,cid,CREATE));say(c,b,cid,'ยืนยัน');assert count(w)==1
    calls=mock_provider(monkeypatch,w,lambda:suggestion(w))
    response=c.post(b+f'/conversations/{cid}/messages',json={'text':'จดเซเว่นสองร้อยจากเงินสด'}).json()
    assert 'กำลังเตรียมข้อเสนอใหม่' in say(c,b,cid,'ยืนยัน') and count(w)==1
    assert 'กำลังเตรียมข้อเสนอใหม่' in say(c,b,cid,'ยืนยัน '+old) and count(w)==1
    process(response['job_id'])
    review=c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'กรุณาตรวจสอบ' in review and '฿200.00' in review and len(calls)==1
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==2
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน') and count(w)==2


def test_pending_new_request_cannot_post_previous_unconfirmed_draft(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);old=code(say(c,b,cid,CREATE))
    mock_provider(monkeypatch,w,lambda:suggestion(w))
    jid=c.post(b+f'/conversations/{cid}/messages',json={'text':'เปลี่ยนเป็นเซเว่นสองร้อย'}).json()['job_id']
    assert 'กำลังเตรียมข้อเสนอใหม่' in say(c,b,cid,'ยืนยัน') and count(w)==0
    process(jid)
    assert 'ใช้ไม่ได้' in say(c,b,cid,'ยืนยัน '+old) and count(w)==0
    say(c,b,cid,'ทวนอีกที');assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==1


def test_new_model_prose_does_not_inherit_confirmed_action(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);say(c,b,cid,CREATE);say(c,b,cid,'ยืนยัน')
    mock_provider(monkeypatch,w,lambda:{'intent':'chat','reply':'จะบันทึกเซเว่น 200 บาทค่ะ พิมพ์ยืนยัน'})
    run(c,w,b,cid,'จดเซเว่นสองร้อยจากเงินสด')
    response=say(c,b,cid,'ยืนยัน')
    assert 'ยังไม่มีรายการ' in response and 'ข้อเสนอนี้บันทึกแล้ว' not in response and count(w)==1


def test_other_room_pending_job_does_not_block_review_confirmation(actor):
    c,w,u,b,cid=setup(actor);say(c,b,cid,CREATE)
    other=c.post(b+'/conversations',json={}).json()['id']
    jid=c.post(b+f'/conversations/{other}/messages',json={'text':'สวัสดี'}).json()['job_id']
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==1
    with SessionLocal.begin() as db:db.get(Job,jid).status='cancelled'
