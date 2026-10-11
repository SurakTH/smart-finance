import json
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ChatAction,Message,Conversation,Job,message_time
from app.reporting import today
from app.assistant_contract import claims_review,UNPREPARED
from test_assistant_finance import assistant,tool
from test_chat_actions import count

PHANTOM='รายการที่รอการยืนยัน: อาหาร 35.60 + 59 + 14 + 30 รวม 138.60 บาท หากข้อมูลถูกต้อง พิมพ์ **ยืนยัน** เพื่อบันทึกได้เลยครับ'

def draft(wallet,cat):return tool('prepare_transaction',dict(intent='create',kind='expense',description='อาหาร',amount=13860,account_id=wallet,category_id=cat,occurred_on=today().isoformat()))

def test_phantom_review_is_repaired_to_real_draft_then_plain_confirm(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[{'content':PHANTOM},draft(wallet,cat)]
    value=send('ช่วยจดอาหาร 138.60 บาท เงินสด')
    assert 'กรุณาตรวจสอบ' in value['content'] and count(w)==0 and len(state['calls'])==2
    assert 'ข้อความก่อนหน้ายังไม่ได้สร้างร่างจริง' in state['calls'][1]['messages'][-1]['content']
    assert c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน','review_message_id':value['id']}).status_code==200
    assert count(w)==1
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert count(w)==1


def test_repeated_phantom_is_not_shown_as_a_review(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[{'content':PHANTOM},{'content':PHANTOM}]
    value=send('ช่วยจดอาหาร 138.60 บาท')
    assert value['content']==UNPREPARED and len(state['calls'])==2 and count(w)==0
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid))


def test_query_phantom_repairs_to_answer_without_creating_entries(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[{'content':PHANTOM},{'content':'รายงานนี้เป็นข้อมูลที่บันทึกอยู่แล้วค่ะ'}]
    value=send('เมื่อวานกินข้าวไปเท่าไร?')
    assert 'บันทึกอยู่แล้ว' in value['content'] and count(w)==0


def seed_legacy(db,w,cid,request):
    for role,text in [('user',request),('assistant',PHANTOM),('user','ยืนยัน'),('assistant','ยังไม่มีรายการให้ยืนยันค่ะ')]:
        db.add(Message(workspace_id=w,conversation_id=cid,role=role,content=text,created_at=message_time(db,w,cid)));db.flush()


def test_confirm_legacy_phantom_rebuilds_review_and_requires_fresh_confirmation(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:seed_legacy(db,w,cid,'ช่วยจดอาหาร 138.60 บาทจากเงินสด')
    state['responses']=[draft(wallet,cat)]
    value=send('ยืนยัน')
    assert 'กรุณาตรวจสอบ' in value['content'] and count(w)==0
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert count(w)==1


def test_legacy_report_confirmation_does_not_authorize_duplicate_draft(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:seed_legacy(db,w,cid,'เมื่อวานกินข้าวไปเท่าไร?')
    state['responses']=[draft(wallet,cat)]
    value=send('ยืนยัน')
    assert 'ยังไม่เตรียมรายการจากคำถามนี้' in value['content'] and count(w)==0


def test_lookup_nullable_optional_fields_and_inline_schema(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts','q':None,'month':'','cursor':'','kind':'','limit':None}]}),draft(wallet,cat)]
    value=send('ช่วยจดอาหาร 138.60 บาท')
    assert 'กรุณาตรวจสอบ' in value['content'] and count(w)==0
    schema=next(t for t in state['calls'][0]['tools'] if t['function']['name']=='lookup_workspace')['function']['parameters']
    assert '$ref' not in json.dumps(schema) and schema['properties']['queries']['items']['type']=='object'


def test_invalid_lookup_reports_field_without_input_or_unknown_key(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts','q':['PRIVATE'],'PRIVATE-secret':True}]}),{'content':'ขอตรวจรูปแบบใหม่ค่ะ'}]
    send('ดูบัญชีให้หน่อย')
    result=json.loads(state['calls'][1]['messages'][-1]['content'])
    assert result['error']=='invalid_lookup' and {'field':'queries.q','code':'string_type'} in result['issues']
    assert 'PRIVATE' not in json.dumps(result)
