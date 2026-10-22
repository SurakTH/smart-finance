"""Reference answers retain the real draft; they never post financial data."""
import json
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account,Conversation,ChatAction,now
from app.chat_dialogue import resolve,answer_clarification
from test_chat_actions import setup,say,count


def partial(w,**patch):
    return dict(intent='create',kind='expense',description='ค่าหนังสือ',amount=1800,occurred_on='2026-10-20',**patch)


def start(w,u,cid,data):
    with SessionLocal.begin() as db:
        return resolve(db,db.get(Conversation,cid),u.id,json.dumps(data))


def test_exact_account_then_category_retains_amount_date_and_requires_confirm(actor):
    c,w,u,b,cid=setup(actor)
    with SessionLocal.begin() as db:db.add(Account(workspace_id=w,name='กระเป๋าสำรอง',kind='asset'))
    question=start(w,u,cid,partial(w))
    assert 'เงินสด' in question and 'กระเป๋าสำรอง' in question
    response=c.post(b+f'/conversations/{cid}/messages',json={'text':'เงินสด'})
    assert response.json()['job_id'] is None
    question=c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'จัดเข้าหมวดไหน' in question and 'อาหารและเครื่องดื่ม' in question
    assert 'เงินเดือน' not in question
    review=say(c,b,cid,'อาหารและเครื่องดื่ม')
    assert '฿18.00' in review and '2026-10-20' in review and 'เงินสด' in review
    assert count(w)==0
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน')
    assert count(w)==1
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน')


def test_unique_wallet_is_preserved_while_asking_category(actor):
    c,w,u,b,cid=setup(actor)
    start(w,u,cid,partial(w))
    with SessionLocal() as db:
        pending=db.get(Conversation,cid).capture_context['ai_followup']
        assert pending['field']=='category_id'
        assert pending['draft']['account_id']
    assert '฿18.00' in say(c,b,cid,'อาหารและเครื่องดื่ม')
    assert count(w)==0


def test_unrelated_negative_ambiguous_expired_and_foreign_answers_are_not_selected(actor):
    c,w,u,b,cid=setup(actor)
    start(w,u,cid,partial(w))
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        for text in ('ไม่เอาอาหารและเครื่องดื่ม','อาหารและเครื่องดื่มได้ไหม','เงินเดือน','ยอดเงินเท่าไหร่'):
            assert answer_clarification(db,room,u.id,text) is None
        assert answer_clarification(db,room,'someone-else','อาหารและเครื่องดื่ม') is None
        db.add(Account(workspace_id=w,name='อาหารและเครื่องดื่ม',kind='expense'));db.flush()
        assert answer_clarification(db,room,u.id,'อาหารและเครื่องดื่ม') is None
        context=dict(room.capture_context);context['ai_followup']={**context['ai_followup'],'expires':now()-1};room.capture_context=context
        assert answer_clarification(db,room,u.id,'อาหารและเครื่องดื่ม') is None
    assert count(w)==0


def test_destination_choices_exclude_source_and_wrong_kind(actor):
    c,w,u,b,cid=setup(actor)
    with SessionLocal.begin() as db:
        cash=db.scalar(select(Account).where(Account.workspace_id==w,Account.name=='เงินสด'))
        db.add(Account(workspace_id=w,name='ธนาคารปลายทาง',kind='asset'))
        data=partial(w);data.update(kind='transfer',account_id=cash.id)
    question=start(w,u,cid,data)
    assert 'ธนาคารปลายทาง' in question and 'เงินสด' not in question
    review=say(c,b,cid,'ธนาคารปลายทาง')
    assert '฿18.00' in review and count(w)==0


def test_batch_reference_answer_fills_only_asked_item(actor):
    c,w,u,b,cid=setup(actor)
    with SessionLocal() as db:
        cash=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='เงินสด'))
        food=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='อาหารและเครื่องดื่ม'))
    first=partial(w,account_id=cash,category_id=food)
    second=partial(w,account_id=cash);second['amount']=7500
    question=start(w,u,cid,dict(intent='create',transactions=[first,second]))
    assert 'รายการที่ 2' in question and 'อาหารและเครื่องดื่ม' in question
    review=say(c,b,cid,'อาหารและเครื่องดื่ม')
    assert '฿18.00' in review and '฿75.00' in review
    with SessionLocal() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.status=='pending'))
        assert len(action.payload['items'])==2
    assert count(w)==0


def test_receipt_answers_keep_image_paid_total_date_and_do_not_reinvoke_model(actor,monkeypatch):
    import httpx
    from app.models import Provider,Message
    from app.worker import run_once
    from test_receipt_reader import image,extracted,transport
    from test_assistant_finance import tool
    c,w,u,b,cid=setup(actor);calls=[]
    with SessionLocal.begin() as db:
        db.add(Account(workspace_id=w,name='ธนาคารทดสอบ',kind='asset'))
        db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    initial=tool('prepare_transaction',{'intent':'create','kind':'expense','description':'ค่าหนังสือ'})
    transport(monkeypatch,[extracted(paid_amount='18.00',gross_amount='45.00',subsidy_or_discount='27.00'),httpx.Response(200,json={'choices':[{'message':initial}]})],calls)
    result=c.post(b+f'/conversations/{cid}/images',files={'file':image()},data={'text':'จดค่าหนังสือ'}).json()
    while run_once():pass
    assert 'เงินสด' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'จัดเข้าหมวดไหน' in say(c,b,cid,'เงินสด')
    assert '฿18.00' in say(c,b,cid,'อาหารและเครื่องดื่ม')
    assert len(calls)==2 and count(w)==0
    with SessionLocal() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.status=='pending'))
        assert action.payload['attachment_id']==result['attachment_id']
        assert action.payload['transaction']['occurred_on']=='2026-10-20'
        assert action.payload['receipt']['paid_satang']==1800
        assert action.payload['receipt']['subsidy_satang']==2700
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน')
    assert count(w)==1


def test_cancelled_draft_cannot_consume_later_reference_reply(actor):
    c,w,u,b,cid=setup(actor)
    start(w,u,cid,partial(w))
    assert 'ยกเลิกร่าง' in say(c,b,cid,'ยกเลิก')
    with SessionLocal() as db:
        assert answer_clarification(db,db.get(Conversation,cid),u.id,'อาหารและเครื่องดื่ม') is None
    assert count(w)==0
