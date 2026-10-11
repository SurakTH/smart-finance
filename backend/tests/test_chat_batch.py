"""Batch review is one trusted boundary; provider outputs cannot post money."""
import time
import pytest
from sqlalchemy import select,func
from app import ai,ledger
from app.db import SessionLocal
from app.models import ChatAction,Entry,Line,Message,Proposal
from test_chat_actions import setup,say,count,CREATE
from test_chat_dialogue import suggestion,mock_provider,run


def batch(w,**changes):
    first=suggestion(w)
    return {'intent':'create','transactions':[first,{**first,'description':'กาแฟ','amount':7500}],**changes}


def test_one_model_call_batch_edit_remove_plain_confirm_replay(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    calls=mock_provider(monkeypatch,w,lambda:batch(w))
    review=run(c,w,b,cid,'จดเซเว่นสองร้อยกับกาแฟ75เงินสดให้หน่อย')
    assert '2 รายการ' in review and '฿200.00' in review and '฿75.00' in review and count(w)==0
    assert '฿80.00' in say(c,b,cid,'แก้ยอดรายการที่ 2 เป็น 80 บาท')
    assert 'เท่าไหร่' in say(c,b,cid,'จริงๆ 90')
    assert '1 รายการ' in say(c,b,cid,'ลบรายการที่ 1')
    assert 'ทั้งชุด 1 รายการ' in say(c,b,cid,'ยืนยัน') and count(w)==1
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน') and count(w)==1 and len(calls)==1
    with SessionLocal() as db:
        assert db.scalar(select(Entry.amount).where(Entry.workspace_id==w))==8000
        assert db.scalar(select(func.sum(Line.signed_amount)).where(Line.workspace_id==w))==0


@pytest.mark.parametrize('change',[{'amount':True},{'amount':-1},{'account_id':'00000000-0000-0000-0000-000000000000'},{'intent':'chat'},{'confirmed':True}])
def test_entire_batch_rejected_if_any_item_invalid(actor,monkeypatch,change):
    c,w,u,b,cid=setup(actor);value=batch(w);value['transactions'][1].update(change)
    mock_provider(monkeypatch,w,lambda:value)
    assert 'กรุณาตรวจสอบ' not in run(c,w,b,cid,'จดหลายรายการเงินสดให้หน่อย') and count(w)==0
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid))


def test_batch_limit_and_mixed_single_fields_rejected(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);value=batch(w);value['transactions']*=6
    mock_provider(monkeypatch,w,lambda:value)
    assert 'กรุณาตรวจสอบ' not in run(c,w,b,cid,'จด12รายการ')
    value['transactions']=value['transactions'][:2];value['amount']=100
    assert 'กรุณาตรวจสอบ' not in run(c,w,b,cid,'จดสองรายการ') and count(w)==0


def test_duplicate_warning_and_new_duplicate_invalidates_confirmation(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    say(c,b,cid,CREATE);say(c,b,cid,'ยืนยัน')
    review=say(c,b,cid,CREATE)
    assert 'อาจซ้ำ' in review
    say(c,b,cid,'ยกเลิก')
    value=batch(w);value['transactions'][1]=value['transactions'][0].copy()
    mock_provider(monkeypatch,w,lambda:value)
    review=run(c,w,b,cid,'จดเซเว่นสองรายการ')
    assert 'ซ้ำกับรายการที่ 1' in review
    with SessionLocal.begin() as db:
        from app.schemas import TransactionInput
        from uuid import uuid4
        from app.reporting import today
        ledger.post(db,w,u.id,TransactionInput(**{k:v for k,v in suggestion(w).items() if k!='intent'},occurred_on=today(),idempotency_key=uuid4()))
    assert 'ข้อมูลเปลี่ยน' in say(c,b,cid,'ยืนยัน') and count(w)==2


def test_batch_failure_rolls_back_every_post(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    mock_provider(monkeypatch,w,lambda:batch(w));run(c,w,b,cid,'จดสองรายการ')
    original=ledger.post;calls=[]
    def fail_second(*args,**kwargs):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('synthetic posting failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(ledger,'post',fail_second)
    response=c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert response.status_code==500
    assert count(w)==0
    with SessionLocal() as db:
        assert db.scalar(select(ChatAction.status).where(ChatAction.conversation_id==cid))=='pending'
        assert db.scalar(select(func.count()).select_from(Line).where(Line.workspace_id==w))==0
    monkeypatch.setattr(ledger,'post',original)
    assert 'ทั้งชุด 2 รายการ' in say(c,b,cid,'ยืนยัน') and count(w)==2


def test_image_batch_evidence_one_call_and_repeated_image_blocked(actor,monkeypatch):
    from app.models import Job,Provider
    from test_chat_images import receipt
    c,w,u,b,cid=setup(actor)
    calls=mock_provider(monkeypatch,w,lambda:batch(w))
    with SessionLocal.begin() as db:
        provider=db.scalar(select(Provider).where(Provider.workspace_id==w));provider.supports_images=True
    result=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'จดสองรายการจากรูปนี้ใช้เงินสด'}).json()
    with SessionLocal.begin() as db:ai.process_job(db,db.get(Job,result['job_id']))
    review=c.get(b+f'/conversations/{cid}/messages').json()[-1]
    assert review['attachment_id']==result['attachment_id'] and '2 รายการ' in review['content'] and count(w)==0
    assert len(calls)==1
    say(c,b,cid,'ยืนยัน');assert count(w)==2
    with SessionLocal() as db:
        proposals=db.scalars(select(Proposal).where(Proposal.workspace_id==w)).all()
        assert len(proposals)==2 and all(p.attachment_id==result['attachment_id'] and p.status=='confirmed' for p in proposals)
    other=c.post(b+'/conversations',json={}).json()['id']
    result=c.post(b+f'/conversations/{other}/images',files={'file':receipt()},data={'text':'จดรูปเดิม'}).json()
    with SessionLocal.begin() as db:ai.process_job(db,db.get(Job,result['job_id']))
    assert 'ไม่สร้างรายการซ้ำ' in c.get(b+f'/conversations/{other}/messages').json()[-1]['content'] and count(w)==2


def test_duplicate_checks_ignore_other_workspaces(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    other=c.post('/workspaces',json={'name':'different tenant'}).json()['id'];base=f'/workspaces/{other}'
    room=c.post(base+'/conversations',json={}).json()['id']
    say(c,base,room,CREATE);say(c,base,room,'ยืนยัน')
    review=say(c,b,cid,CREATE)
    assert 'อาจซ้ำ' not in review


def test_prompt_text_budget_and_unique_images(actor,monkeypatch):
    from app.models import Job,Provider
    from test_chat_images import receipt
    c,w,u,b,cid=setup(actor)
    calls=mock_provider(monkeypatch,w,lambda:{'intent':'chat','reply':'สวัสดีค่ะ'})
    with SessionLocal.begin() as db:
        db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    image=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()}).json()
    with SessionLocal.begin() as db:
        job=db.get(Job,image['job_id']);job.status='cancelled'
        for i in range(20):db.add(Message(workspace_id=w,conversation_id=cid,role='user',content='ข้อมูล '+str(i)+' ก'*2000,attachment_id=image['attachment_id'],created_at=int(time.time()*1000)-1000+i))
    run(c,w,b,cid,'สวัสดีค่ะ')
    messages=calls[0]['messages'];turns=[m for m in messages if m['role']!='system']
    images=[part for m in turns if isinstance(m['content'],list) for part in m['content'] if part['type']=='image_url']
    assert len(images)==1 and len(turns)<=7
    assert sum(len(m['content']) for m in turns if isinstance(m['content'],str))<=24000


def test_explicit_batch_needs_no_model_even_when_provider_configured(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    mock_provider(monkeypatch,w,lambda:(_ for _ in ()).throw(AssertionError('Unnecessary AI call')))
    command='บันทึกรายจ่าย กาแฟ 75 บาท บัญชี เงินสด หมวด อาหารและเครื่องดื่ม\nบันทึกรายจ่าย ข้าว 80 บาท บัญชี เงินสด หมวด อาหารและเครื่องดื่ม'
    assert '2 รายการ' in say(c,b,cid,command) and count(w)==0
    assert 'ทั้งชุด 2 รายการ' in say(c,b,cid,'ยืนยัน') and count(w)==2
