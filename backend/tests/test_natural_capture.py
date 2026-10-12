import re
import uuid
import pytest
from sqlalchemy import select,delete
from app.db import SessionLocal
from app.models import Account,Conversation,Entry,Message,TelegramLink,Job
from app.bot import text_capture
from test_chat_actions import setup,say,code,count

@pytest.fixture(autouse=True)
def clean_pending(actor):
 yield
 with SessionLocal.begin() as db:db.execute(delete(Job).where(Job.workspace_id==actor[1],Job.status=='pending'))

@pytest.mark.parametrize('text,expected',[('เมื่อกี้จ่ายค่ากาแฟ 75 จากเงินสด','฿75.00'),('กินข้าว 80.50 เมื่อวาน','฿80.50'),('รับเงินเดือน 30,000 บาท','฿30,000.00'),('แท็กซี่ 120 บาท','฿120.00')])
def test_natural_review_requires_confirmation(actor,text,expected):
 c,w,u,b,cid=setup(actor)
 review=say(c,b,cid,text);assert expected in review,review
 if text.startswith('รับเงินเดือน'):assert 'รายรับ · เงินเดือน\n' in review
 assert count(w)==0
 assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน '+code(review));assert count(w)==1

def test_missing_account_category_followup_and_expiry(actor):
 c,w,u,b,cid=setup(actor)
 c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'})
 assert 'ใช้บัญชีไหน' in say(c,b,cid,'กาแฟ 75 บาท')
 review=say(c,b,cid,'เงินสด');assert '฿75.00' in review and 'หมวด: อาหารและเครื่องดื่ม' in review
 assert count(w)==0
 assert 'จัดเข้าหมวดไหน' in say(c,b,cid,'จ่ายค่าหนังสือ 300 จากเงินสด')
 review=say(c,b,cid,'หมวด อื่น ๆ');assert '฿300.00' in review and 'หมวด: อื่น ๆ' in review
 assert 'ใช้บัญชีไหน' in say(c,b,cid,'กาแฟ 90 บาท')
 with SessionLocal.begin() as db:
  room=db.get(Conversation,cid);room.capture_context={'pending':{'text':'กาแฟ 90 บาท','expires':0}}
 assert 'ยืนยัน ' not in say(c,b,cid,'เงินสด');assert count(w)==0

def test_natural_transfer_card_and_latest_correction(actor):
 c,w,u,b,cid=setup(actor)
 c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'});c.post(b+'/accounts',json={'name':'บัตรเครดิต','kind':'liability'})
 review=say(c,b,cid,'โอน 500 จากเงินสด ไปธนาคาร');assert 'ปลายทาง: ธนาคาร' in review,review
 say(c,b,cid,'ยืนยัน '+code(review));assert count(w)==1
 review=say(c,b,cid,'แก้รายการล่าสุดเป็น 450 บาท');assert 'ก่อนแก้ไข' in review and '฿450.00' in review
 say(c,b,cid,'ยืนยัน '+code(review));assert count(w)==3
 review=say(c,b,cid,'จ่ายบัตร 200 จากเงินสด ไปบัตรเครดิต');assert 'จ่ายบัตร' in review and 'ปลายทาง: บัตรเครดิต' in review
 assert count(w)==3
 other=c.post(b+'/conversations',json={}).json()['id']
 assert 'ยังไม่มีรายการที่ยืนยันผ่านห้องนี้' in say(c,b,other,'แก้ยอดล่าสุดเป็น 90 บาท')

@pytest.mark.parametrize('text',['กาแฟ -75 บาท','กาแฟ 75.001 บาท','กาแฟ 75 หรือ 90 บาท','กาแฟ 75 และข้าว 90 บาท','กาแฟประมาณ 75 บาท','กาแฟ 75 วันที่ 2026-02-30'])
def test_ambiguous_or_invalid_does_not_create_action(actor,text):
 c,w,u,b,cid=setup(actor);reply=say(c,b,cid,text)
 assert 'ยังไม่บันทึก' in reply and count(w)==0
 assert not re.search(r'\nยืนยัน [A-F0-9]{8}\n',reply)

def test_telegram_same_review_confirm_dedup_and_user_scope(actor):
 c,w,u,b,cid=setup(actor);tid=int(uuid.uuid4().hex[:12],16)
 with SessionLocal.begin() as db:db.add(TelegramLink(telegram_id=str(tid),workspace_id=w,user_id=u.id))
 def send(mid,text):
  with SessionLocal.begin() as db:return text_capture(db,tid,mid,text)
 review=send(1,'กาแฟ 75 จากเงินสด');key=code(review);assert count(w)==0
 assert send(1,'กาแฟ 75 จากเงินสด')==review
 assert 'บันทึกรายการเรียบร้อย' in send(2,'ยืนยัน '+key);assert count(w)==1
 assert 'บันทึกรายการเรียบร้อย' in send(2,'ยืนยัน '+key);assert count(w)==1
 assert 'ไม่มีการบันทึกซ้ำ' in send(3,'ยืนยัน '+key)
 assert 'ไม่พบรหัส' in say(c,b,cid,'ยืนยัน '+key)
 with SessionLocal.begin() as db:
  assert text_capture(db,tid+1,1,'ยืนยัน '+key)=='กรุณาเชื่อมต่อจากเว็บก่อน'
 assert count(w)==1


def test_keyset_history_tied_timestamps_and_tenant_scope(actor):
 c,w,u,b,cid=setup(actor)
 with SessionLocal.begin() as db:
  for i in range(130):db.add(Message(workspace_id=w,conversation_id=cid,role='user',content=str(i),created_at=12345))
 path=b+f'/conversations/{cid}/messages/page'
 page=c.get(path).json();assert len(page['items'])==50 and page['has_older'] and not page['has_newer']
 second=c.get(path+'?before='+page['items'][0]['id']).json();assert len(second['items'])==50 and second['has_older']
 third=c.get(path+'?before='+second['items'][0]['id']).json();assert len(third['items'])==30 and not third['has_older']
 ids=[x['id'] for p in (third,second,page) for x in p['items']];assert len(set(ids))==130
 newer=c.get(path+'?after='+third['items'][-1]['id']).json();assert len(newer['items'])==50 and newer['has_newer']
 assert c.get(path+'?before='+page['items'][0]['id']+'&after='+ids[0]).status_code==422
 other=c.post(b+'/conversations',json={}).json()['id']
 assert c.get(b+f'/conversations/{other}/messages/page?before='+ids[0]).status_code==404


def test_cancel_followup_and_report_question_never_become_drafts(actor):
 c,w,u,b,cid=setup(actor)
 c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'})
 assert 'ใช้บัญชีไหน' in say(c,b,cid,'กาแฟ 75 บาท')
 assert 'ยกเลิกข้อมูลที่กำลังกรอก' in say(c,b,cid,'ยกเลิกการกรอก')
 with SessionLocal() as db:assert 'pending' not in (db.get(Conversation,cid).capture_context or {})
 say(c,b,cid,'ช่วยบอกว่าเดือนนี้ใช้ไป 500 บาทหรือยัง')
 from app.models import ChatAction
 with SessionLocal() as db:assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
 assert count(w)==0


def test_casual_followups_amount_and_pending_correction(actor):
 c,w,u,b,cid=setup(actor)
 c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'})
 assert 'ยอดเท่าไหร่' in say(c,b,cid,'ช่วยจดค่ากาแฟให้หน่อย')
 assert 'ใช้บัญชีไหน' in say(c,b,cid,'75 บาทค่ะ')
 review=say(c,b,cid,'เงินสดจ้า');assert '฿75.00' in review
 review=say(c,b,cid,'จริง ๆ 90 บาท');assert '฿90.00' in review and count(w)==0
 assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน');assert count(w)==1
 assert c.get(b+'/transactions').json()[0]['amount']==9000
 assert 'จัดเข้าหมวดไหน' in say(c,b,cid,'ซื้อหนังสือ 300 จากเงินสด')
 assert 'หมวด: อื่น ๆ' in say(c,b,cid,'อื่น ๆ ค่ะ')
 assert 'ยกเลิกข้อเสนอ' in say(c,b,cid,'ยกเลิก');assert count(w)==1


def test_telegram_bare_confirmation_and_cancel(actor):
 c,w,u,b,cid=setup(actor);tid=int(uuid.uuid4().hex[:12],16)
 with SessionLocal.begin() as db:db.add(TelegramLink(telegram_id=str(tid),workspace_id=w,user_id=u.id))
 def send(mid,text):
  with SessionLocal.begin() as db:return text_capture(db,tid,mid,text)
 assert 'กรุณาตรวจสอบ' in send(1,'กาแฟ 75 จากเงินสดจ้า')
 assert 'บันทึกรายการเรียบร้อย' in send(2,'ยืนยัน');assert count(w)==1
 assert 'บันทึกรายการเรียบร้อย' in send(2,'ยืนยัน');assert count(w)==1
 assert 'ไม่มีการบันทึกซ้ำ' in send(3,'ยืนยัน')
 send(4,'กาแฟ 90 จากเงินสด')
 assert 'ยกเลิกข้อเสนอ' in send(5,'ยกเลิก');assert count(w)==1


@pytest.mark.parametrize('text',['ช่วยอธิบายค่าใช้จ่ายให้หน่อย','กาแฟ 75 แพงไหม','สมมติซื้อกาแฟ 75 บาท','ขอตัวอย่างการโอนเงิน 200 บาท'])
def test_casual_questions_and_examples_are_not_capture_commands(actor,text):
 from app.chat_actions import handle
 from app.chat_dialogue import eligible
 c,w,u,b,cid=setup(actor)
 with SessionLocal.begin() as db:
  room=db.get(Conversation,cid)
  assert handle(db,room,u.id,text) is None
  assert not eligible(room,text)
 assert count(w)==0


def test_telegram_missing_details_use_shared_chat_model_when_configured(actor,monkeypatch):
 from app.models import Provider
 c,w,u,b,cid=setup(actor);tid=int(uuid.uuid4().hex[:12],16)
 c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'})
 with SessionLocal.begin() as db:
  db.add(TelegramLink(telegram_id=str(tid),workspace_id=w,user_id=u.id))
  db.add(Provider(workspace_id=w,kind='ollama',model='test',task='chat',priority=1,encrypted_key=''))
 from app.telegram_chat import ACK
 from app import ai
 from app.assistant_response import AssistantReply
 import json
 monkeypatch.setattr(ai,'call_model',lambda db,job:(AssistantReply('',draft=json.dumps({'intent':'clarify','kind':'expense','amount':7500,'description':'กาแฟ','reply':'ใช้บัญชีไหนคะ?'})),False))
 with SessionLocal.begin() as db:reply=text_capture(db,tid,1,'กาแฟ 75 บาท')
 assert reply==ACK
 with SessionLocal.begin() as db:
  job=db.scalar(select(Job).where(Job.workspace_id==w,Job.status=='pending'))
  assert job.task=='chat' and job.payload['routing']=='workspace'
  room=job.payload['conversation_id'];jid=job.id;ai.process_job(db,job)
 with SessionLocal() as db:
  reply=db.scalars(select(Message).where(Message.conversation_id==room,Message.role=='assistant')).first()
  assert 'บัญชี' in reply.content
 assert count(w)==0
 with SessionLocal.begin() as db:db.delete(db.get(Job,jid))
