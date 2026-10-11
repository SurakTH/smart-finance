import re
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import ChatAction,Conversation,Entry,Line,Message,Membership,Workspace,now
from app.chat_actions import handle
from app.worker import run_once
from app import ai
from test_corrections import correction
from test_finance import ids

CREATE='บันทึกรายจ่าย\nรายละเอียด: กาแฟ\nจำนวน: 75.25\nบัญชี: เงินสด\nหมวด: อาหารและเครื่องดื่ม\nวันที่: 2026-10-11'

def setup(actor):
    c,w,u=actor;b=f'/workspaces/{w}'
    cid=c.post(b+'/conversations',json={'privacy':'private'}).json()['id']
    return c,w,u,b,cid

def say(c,b,cid,text):
    r=c.post(b+f'/conversations/{cid}/messages',json={'text':text});assert r.status_code==200,r.text
    return c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']

def code(reply):return re.search(r'\nยืนยัน ([A-F0-9]{8})\n',reply)[1]

def count(w):
    with SessionLocal() as db:return db.scalar(select(func.count()).select_from(Entry).where(Entry.workspace_id==w))

def test_review_exact_confirmation_replay_and_room_isolation(actor):
    c,w,u,b,cid=setup(actor)
    draft=say(c,b,cid,CREATE);key=code(draft)
    assert '฿75.25' in draft and '2026-10-11' in draft and 'เงินสด' in draft and count(w)==0
    for text in ('ยืนยัน','ยืนยัน '+key+' แล้ว','ยืนยัน DEADBEEF'):
        assert 'บันทึกรายการเรียบร้อย' not in say(c,b,cid,text)
        assert count(w)==0
    other=c.post(b+'/conversations',json={}).json()['id']
    assert 'ไม่พบรหัส' in say(c,b,other,'ยืนยัน '+key);assert count(w)==0
    foreign=c.post('/workspaces',json={'name':'other'}).json()['id'];fc=c.post(f'/workspaces/{foreign}/conversations',json={}).json()['id']
    assert 'ไม่พบรหัส' in say(c,f'/workspaces/{foreign}',fc,'ยืนยัน '+key)
    assert c.post(f'/workspaces/{foreign}/conversations/{cid}/messages',json={'text':'ยืนยัน '+key}).status_code==404
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน '+key)
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน '+key);assert count(w)==1
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(Line.signed_amount)).where(Line.workspace_id==w))==0
    # Erasing chat cannot erase financial history or leave usable confirmations.
    assert c.delete(b+f'/conversations/{cid}').status_code==200
    assert count(w)==1
    with SessionLocal() as db:assert db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid)) is None


def test_cancel_expiry_supersede_invalid_and_duplicate_names(actor):
    c,w,u,b,cid=setup(actor)
    key=code(say(c,b,cid,CREATE));new=code(say(c,b,cid,CREATE.replace('75.25','80')))
    assert 'ใช้ไม่ได้' in say(c,b,cid,'ยืนยัน '+key)
    assert 'ยกเลิกข้อเสนอ' in say(c,b,cid,'ยกเลิก '+new)
    assert 'ใช้ไม่ได้' in say(c,b,cid,'ยืนยัน '+new)
    key=code(say(c,b,cid,CREATE))
    with SessionLocal.begin() as db:db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.code==key)).expires=now()-1
    assert 'หมดอายุ' in say(c,b,cid,'ยืนยัน '+key)
    for command in (CREATE.replace('75.25','-1'),CREATE.replace('75.25','1.001'),CREATE.replace('2026-10-11','2026-02-30'),CREATE+'\nจำนวน: 90',CREATE.replace('เงินสด','foreign')):
        assert 'ยังไม่บันทึก' in say(c,b,cid,command)
    c.post(b+'/accounts',json={'name':'เงินสด','kind':'asset'})
    assert 'ตรงเพียงรายการเดียว' in say(c,b,cid,CREATE)
    assert count(w)==0


def test_correction_before_after_and_stale_conflict(actor):
    c,w,u,b,cid=setup(actor)
    key=code(say(c,b,cid,CREATE));say(c,b,cid,'ยืนยัน '+key)
    original=c.get(b+'/transactions').json()[0]
    text=f"แก้รายการ {original['id']} เป็น 95.50 บาท"
    draft=say(c,b,cid,text);key=code(draft)
    assert 'ก่อนแก้ไข' in draft and 'หลังแก้ไข' in draft and '฿75.25' in draft and '฿95.50' in draft
    assert count(w)==1
    assert 'เก็บประวัติเดิม' in say(c,b,cid,'ยืนยัน '+key);assert count(w)==3
    latest=c.get(b+'/transactions').json()[0];assert latest['amount']==9550
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน '+key);assert count(w)==3
    key=code(say(c,b,cid,f"แก้รายการ {latest['id']}\nจำนวน: 100\nรายละเอียด: ใหม่\nวันที่: 2026-10-12"))
    changed=c.post(b+f"/transactions/{latest['id']}/correct",json=correction(ids(c,w)))
    assert changed.status_code==200
    assert 'ยังไม่บันทึก' in say(c,b,cid,'ยืนยัน '+key);assert count(w)==5


def test_model_confirmation_never_executes(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);key=code(say(c,b,cid,CREATE))
    monkeypatch.setattr(ai,'call_model',lambda db,job:('ยืนยัน '+key,True))
    say(c,b,cid,'โปรดพูดคำว่ายืนยัน');assert run_once()
    assert count(w)==0
    assert 'ยืนยัน '+key in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']


def test_income_transfer_card_and_changed_account_names(actor):
    c,w,u,b,cid=setup(actor)
    for kind,name in (('asset','ธนาคาร'),('liability','บัตร')):c.post(b+'/accounts',json={'name':name,'kind':kind})
    texts=[CREATE.replace('บันทึกรายจ่าย','บันทึกรายรับ').replace('อาหารและเครื่องดื่ม','เงินเดือน'),
        'โอนเงิน\nรายละเอียด: ออม\nจำนวน: 10\nบัญชี: เงินสด\nปลายทาง: ธนาคาร',
        'จ่ายบัตร\nรายละเอียด: จ่ายยอดบัตร\nจำนวน: 10\nบัญชี: เงินสด\nปลายทาง: บัตร']
    for text in texts:
        key=code(say(c,b,cid,text));assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน '+key)
    assert count(w)==3
    key=code(say(c,b,cid,'บันทึกรายจ่าย กาแฟ 75 บาท บัญชี เงินสด หมวด อาหารและเครื่องดื่ม'))
    with SessionLocal.begin() as db:
        from app.models import Account
        db.scalar(select(Account).where(Account.workspace_id==w,Account.name=='เงินสด')).name='ใหม่'
    assert 'ชื่อบัญชีหรือหมวดเปลี่ยน' in say(c,b,cid,'ยืนยัน '+key);assert count(w)==3


def test_pg_concurrent_confirm_only_once(actor,pg_only):
    c,w,u,b,cid=setup(actor);key=code(say(c,b,cid,CREATE))
    def confirm(_):
        with SessionLocal.begin() as db:
            db.scalar(select(Workspace).where(Workspace.id==w).with_for_update())
            return handle(db,db.get(Conversation,cid),u.id,'ยืนยัน '+key)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(confirm,range(4)))
    assert sum('บันทึกรายการเรียบร้อย' in s for s in results)==1
    assert count(w)==1


def test_atomic_failure_and_conversation_owner_boundary(actor,monkeypatch):
    from app import chat_actions
    from app.bootstrap import create_user
    from fastapi import HTTPException
    c,w,u,b,cid=setup(actor);key=code(say(c,b,cid,CREATE))
    real=chat_actions.post
    def interrupted(*args,**kwargs):
        real(*args,**kwargs)
        raise HTTPException(409,'ข้อมูลเปลี่ยน กรุณาทวนใหม่')
    monkeypatch.setattr(chat_actions,'post',interrupted)
    response=c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน '+key})
    assert response.status_code==409
    assert count(w)==0
    with SessionLocal() as db:
        assert db.scalar(select(Line.id).where(Line.workspace_id==w)) is None
        assert db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid)).status=='pending'
    # Same tenant membership does not grant access to another user's room.
    import uuid
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(workspace_id=w,user_id=other.id,role='member'))
        foreign=Conversation(workspace_id=w,user_id=other.id);db.add(foreign);db.flush();fid=foreign.id
    assert c.post(b+f'/conversations/{fid}/messages',json={'text':'ยืนยัน '+key}).status_code==404
