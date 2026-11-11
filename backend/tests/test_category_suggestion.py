"""Model-selected categories remain reviewable and survive wallet clarification."""
import json
import httpx
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account,ChatAction,Provider
from app.worker import run_once
from test_chat_actions import setup,say,count
from test_assistant_finance import assistant,tool
from test_receipt_reader import extracted,image,transport


@pytest.mark.parametrize('structured_recovery',[False,True])
def test_receipt_category_selected_before_wallet_is_preserved(actor,monkeypatch,structured_recovery):
    c,w,u,b,cid=setup(actor);calls=[]
    with SessionLocal.begin() as db:
        db.add(Account(workspace_id=w,name='ธนาคาร',kind='asset'))
        db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    if structured_recovery:
        output=[httpx.Response(200,json={'choices':[{'message':{'content':'ใช้บัญชีไหนคะ?'}}]}),
            httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(dict(action='prepare',kind='expense',description='กาแฟ',account=None,category='อาหารและเครื่องดื่ม',other_account=None),ensure_ascii=False)}}]})]
    else:
        output=[httpx.Response(200,json={'choices':[{'message':tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',category='อาหารและเครื่องดื่ม'))}]})]
    transport(monkeypatch,[extracted(paid_amount='75.00',gross_amount=None,subsidy_or_discount=None),*output],calls)
    c.post(b+f'/conversations/{cid}/images',files={'file':image()},data={'text':'ค่ากาแฟ ช่วยจดให้หน่อย'})
    while run_once():pass
    question=c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'ใช้บัญชีไหน' in question
    review=say(c,b,cid,'เงินสด')
    assert 'กรุณาตรวจสอบ' in review and 'อาหารและเครื่องดื่ม' in review and '฿75.00' in review
    assert 'จัดเข้าหมวดไหน' not in review
    assert len(calls)==(3 if structured_recovery else 2)
    with SessionLocal() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.status=='pending'))
        category=db.get(Account,action.payload['transaction']['category_id'])
        assert category.workspace_id==w and category.kind=='expense' and category.name=='อาหารและเครื่องดื่ม'
    assert count(w)==0
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==1


def test_receipt_decision_preserves_user_category_choice_over_saved_rule(actor,monkeypatch):
    from app.assistant_preferences import save,Preferences
    c,w,u,b,cid=setup(actor);calls=[]
    with SessionLocal.begin() as db:
        wallet=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.kind=='asset'))
        category=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='อาหารและเครื่องดื่ม'))
        save(db,w,u.id,Preferences(expense_account_id=wallet,rules=[dict(keyword='กาแฟ',category_id=category)]))
        db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    output=[extracted(paid_amount='75.00',gross_amount=None,subsidy_or_discount=None),
            httpx.Response(200,json={'choices':[{'message':{'content':'ใช้หมวดไหนคะ?'}}]}),
            httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(dict(action='prepare',kind='expense',description='กาแฟ',account='เงินสด',category=None,category_choice='ask',other_account=None),ensure_ascii=False)}}]})]
    transport(monkeypatch,output,calls)
    uploaded=c.post(b+f'/conversations/{cid}/images',files={'file':image()},data={'text':'ค่ากาแฟเงินสด จดให้หน่อย แต่หมวดฉันเลือกเอง'}).json()
    while run_once():pass
    question=c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'จัดเข้าหมวดไหน' in question and 'อาหารและเครื่องดื่ม' in question and count(w)==0
    assert 'category_choice' in calls[-1]['response_format']['json_schema']['schema']['properties']
    review=say(c,b,cid,'อาหารและเครื่องดื่ม')
    assert 'กรุณาตรวจสอบ' in review and '฿75.00' in review
    with SessionLocal() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.status=='pending'))
        assert action.payload['attachment_id']==uploaded['attachment_id']
    assert len(calls)==3 and count(w)==0



def test_receipt_read_survives_failed_followup_inference(actor,monkeypatch):
    from app.models import Conversation
    c,w,u,b,cid=setup(actor);calls=[]
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    transport(monkeypatch,[extracted(paid_amount='75.00',gross_amount=None,subsidy_or_discount=None),
        httpx.Response(503,json={'error':'synthetic unavailable'})],calls)
    uploaded=c.post(b+f'/conversations/{cid}/images',files={'file':image()},
        data={'text':'จดค่ากาแฟจากสลิปนี้'}).json()
    while run_once():pass
    reply=c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert '75.00 บาท' in reply and 'ยังเตรียมร่างไม่เสร็จ' in reply and 'ไม่ต้องส่งรูปซ้ำ' in reply
    with SessionLocal() as db:
        context=db.get(Conversation,cid).capture_context
        assert context['receipt_reading']['attachment_id']==uploaded['attachment_id']
        assert not db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid))
    assert count(w)==0 and 'ยังไม่มีรายการให้ยืนยัน' in say(c,b,cid,'ยืนยัน')


@pytest.mark.parametrize('choice,manual,expect_call',[(1,False,True),(0,False,True),(24,False,True),(1,True,False)])
def test_partial_amount_gets_only_a_scoped_category_suggestion(assistant,choice,manual,expect_call):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',
        description='มื้อเที่ยง',category_choice='ask' if manual else 'auto'))]
    assert 'ยอดเท่าไหร่' in send('มื้อเที่ยง ช่วยจดหน่อย')['content']
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,amount=7000,account_id=wallet))]
    if expect_call:
        def classify(body):
            assert body['response_format']['json_schema']['name']=='draft_category'
            assert body['max_tokens']<=512 and len(body['messages'])==2 and 'tools' not in body
            data=json.loads(body['messages'][-1]['content'])
            assert data['description']=='มื้อเที่ยง'
            assert data['categories'][0]['name']=='อาหารและเครื่องดื่ม'
            assert all('id' not in option for option in data['categories'])
            return {'content':json.dumps({'choice':choice})}
        state['responses'].append(classify)
    result=send('70 บาท เงินสด')['content']
    if expect_call and choice==1:
        assert '฿70.00' in result and 'หมวด: อาหารและเครื่องดื่ม' in result
    else:
        assert 'จัดเข้าหมวดไหน' in result
    assert len(state['calls'])==2+expect_call and count(w)==0


def test_partial_category_uses_saved_rule_without_extra_request(assistant):
    from app.assistant_preferences import Preferences,save
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        preferred=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='เดินทาง'))
        save(db,w,u.id,Preferences(rules=[{'keyword':'มื้อเที่ยง','category_id':preferred}]))
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='มื้อเที่ยง'))]
    assert 'ยอดเท่าไหร่' in send('มื้อเที่ยง ช่วยจดหน่อย')['content']
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,amount=7000,account_id=wallet))]
    assert 'หมวด: เดินทาง' in send('70 บาท เงินสด')['content']
    assert len(state['calls'])==2 and count(w)==0


@pytest.mark.parametrize('use_existing',[True,False])
@pytest.mark.parametrize('repeats_description',[True,False])
def test_sparse_new_draft_only_recovers_when_model_identifies_same_purchase(assistant,use_existing,repeats_description):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='ข้าวเที่ยง'))]
    assert 'ยอดเท่าไหร่' in send('ช่วยจดข้าวเที่ยงหน่อย')['content']
    def decision(body):
        assert json.loads(body['messages'][-1]['content'])['link_required'] is True
        return {'content':json.dumps({'choice':1 if use_existing else 0,'use_existing':use_existing})}
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=False,kind='expense',amount=7000,account_id=wallet,
        **({'description':'ข้าวเที่ยง'} if repeats_description else {}))),decision]
    reply=send('ทั้งหมด 70 บาท เงินสด' if use_existing else 'จดอีกอย่าง 70 บาท เงินสด')['content']
    if use_existing:
        assert 'กรุณาตรวจสอบ' in reply and 'ข้าวเที่ยง' in reply and '฿70.00' in reply
    else:
        question='จัดเข้าหมวดไหน' if repeats_description else 'รายการนี้เป็นค่าอะไร'
        assert question in reply and 'กรุณาตรวจสอบ' not in reply
    assert len(state['calls'])==3 and count(w)==0


@pytest.mark.parametrize('keep_category',[True,False])
def test_amount_followup_checks_new_deferral_before_erasing_known_category(assistant,keep_category):
    c,w,u,b,cid,wallet,_,state,post,send=assistant
    with SessionLocal() as db:
        cat=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='อาหารและเครื่องดื่ม'))
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='ข้าวเที่ยง',category_id=cat))]
    assert 'ยอดเท่าไหร่' in send('ช่วยจดข้าวเที่ยงหน่อย')['content']
    def decision(body):
        data=json.loads(body['messages'][-1]['content'])
        assert data['review_deferral'] and not data['categories']
        return {'content':json.dumps({'choice':0,'keep_category':keep_category})}
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,amount=7000,account_id=wallet,category_choice='ask'))]
    if not keep_category:state['responses'].append(decision)
    result=send('ทั้งหมด 70 บาท ใช้เงินสด' if keep_category else '70 บาท เงินสด แต่หมวดขอเลือกเอง')['content']
    assert ('หมวด: อาหารและเครื่องดื่ม' if keep_category else 'จัดเข้าหมวดไหน') in result
    assert len(state['calls'])==(2 if keep_category else 3) and count(w)==0


def test_rice_draft_ignores_model_amount_without_user_source(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',
        description='กินข้าวเมื่อกี้',amount=8000,account_id=wallet,category_choice='ask'))]
    reply=send('กินข้าวเมื่อกี้ ช่วยจดหน่อย')['content']
    assert 'ยอดเท่าไหร่' in reply and '80.00' not in reply
    with SessionLocal() as db:
        from app.models import Conversation
        pending=db.get(Conversation,cid).capture_context['ai_followup']
        assert pending['field']=='amount' and not pending['draft'].get('amount')
    assert count(w)==0


def test_spoken_baht_is_not_discarded_by_negative_source_check(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',
        description='กาแฟ',amount=8000,account_id=wallet,category_id=cat))]
    assert '฿80.00' in send('จดค่ากาแฟแปดสิบบาทให้หน่อย')['content']
    assert count(w)==0


def test_category_lookup_cannot_supply_missing_user_amount(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[
        tool('lookup_workspace',{'queries':[{'resource':'categories'}]}),
        tool('prepare_transaction',dict(intent='create',kind='expense',
            description='ข้าวเที่ยง',amount=8000,account_id=wallet,category_id=cat)),
    ]
    assert 'ยอดเท่าไหร่' in send('ช่วยจดข้าวเที่ยงให้หน่อย')['content']
    assert count(w)==0


def test_amount_only_reply_does_not_replace_known_category(assistant):
    c,w,u,b,cid,wallet,_,state,post,send=assistant
    with SessionLocal() as db:
        travel=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='เดินทาง'))
        other=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='อื่น ๆ'))
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='ค่าแท็กซี่',category_id=travel))]
    assert 'ยอดเท่าไหร่' in send('ค่าแท็กซี่ ช่วยจดหน่อย')['content']
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,amount=9500,account_id=wallet,category_id=other))]
    reply=send('ทั้งหมด 95 บาท ใช้เงินสด')['content']
    assert 'หมวด: เดินทาง' in reply and '฿95.00' in reply
    assert len(state['calls'])==2 and count(w)==0


@pytest.mark.parametrize('manual',[False,True])
@pytest.mark.parametrize('needs_link',[False,True])
def test_amount_reply_checks_original_request_before_overriding_model_deferral(assistant,manual,needs_link):
    from app.models import Conversation,Message
    c,w,u,b,cid,wallet,_,state,post,send=assistant
    text='ค่าข้าว ช่วยจดหน่อย'+(' แต่หมวดเดี๋ยวเลือกเอง' if manual else '')
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',
        description='ค่าข้าว',category_choice='ask'))]
    assert 'ยอดเท่าไหร่' in send(text)['content']
    with SessionLocal() as db:
        source=db.get(Conversation,cid).capture_context['ai_followup']['source_message_id']
        assert db.get(Message,source).content==text
    def decision(body):
        data=json.loads(body['messages'][-1]['content'])
        assert data['original_request']==text and data['user_reply']=='70 บาท จ่ายเงินสด'
        schema=body['response_format']['json_schema']['schema']
        assert schema['required']==['action']
        assert ('link_only' in schema['properties']['action']['enum'])==needs_link
        action=('link_only' if needs_link else 'ask') if manual else 'category_1'
        return {'content':json.dumps({'action':action})}
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=not needs_link,
        amount=7000,account_id=wallet,**({'description':'ค่าข้าว'} if needs_link else {}))),decision]
    reply=send('70 บาท จ่ายเงินสด')['content']
    assert ('จัดเข้าหมวดไหน' if manual else 'หมวด: อาหารและเครื่องดื่ม') in reply
    if manual:
        with SessionLocal() as db:
            assert db.get(Conversation,cid).capture_context['ai_followup']['source_message_id']==source
    assert count(w)==0


def test_deferral_source_from_other_room_is_not_read_by_model(assistant):
    from app.models import Conversation,Message
    c,w,u,b,cid,wallet,_,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='ค่าข้าว',category_choice='ask'))]
    assert 'ยอดเท่าไหร่' in send('ค่าข้าว ช่วยจดหน่อย')['content']
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        other=Conversation(workspace_id=w,user_id=u.id);db.add(other);db.flush()
        secret=Message(workspace_id=w,conversation_id=other.id,role='user',content='ข้อความจากอีกห้อง')
        db.add(secret);db.flush()
        room.capture_context={**room.capture_context,'ai_followup':{
            **room.capture_context['ai_followup'],'source_message_id':secret.id}}
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,
        amount=7000,account_id=wallet))]
    assert 'จัดเข้าหมวดไหน' in send('70 บาท จ่ายเงินสด')['content']
    assert len(state['calls'])==2 and count(w)==0


def test_deferral_review_does_not_skip_intervening_user_message(assistant):
    c,w,u,b,cid,wallet,_,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',
        description='ค่าข้าว',category_choice='ask'))]
    assert 'ยอดเท่าไหร่' in send('ค่าข้าว ช่วยจดหน่อย')['content']
    state['responses']=[{'content':'ได้ค่ะ'}]
    assert 'ได้ค่ะ' in send('หมวดเดี๋ยวฉันเลือกเองนะ')['content']
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,
        amount=7000,account_id=wallet))]
    assert 'จัดเข้าหมวดไหน' in send('70 บาท จ่ายเงินสด')['content']
    assert len(state['calls'])==3 and count(w)==0


@pytest.mark.parametrize('promise',[
    'ผมจะสร้างร่างรายการใหม่ให้ก่อนนะครับ แจ้งยอดเงินและวันที่ด้วยครับ',
    'รับทราบครับ จดรายการค่าแท็กซี่ให้เลย (คิดเป็นเงินเท่าไหร่คะ?)',
    'ผมจะร่างรายการไว้ก่อนนะครับ รบกวนคุณแจ้งยอดเงินบาทที่ใช้ไป',
])
def test_promised_partial_draft_requires_a_real_draft_before_asking(assistant,promise):
    from app.models import Conversation
    c,w,u,b,cid,wallet,_,state,post,send=assistant
    with SessionLocal() as db:
        travel=db.scalar(select(Account.id).where(Account.workspace_id==w,Account.name=='เดินทาง'))
    state['responses']=[
        {'content':promise},
        tool('prepare_transaction',dict(intent='create',kind='expense',
            description='ค่าแท็กซี่',category_id=travel)),
    ]
    assert 'ยอดเท่าไหร่' in send('ค่าแท็กซี่ขากลับ ช่วยลงให้หน่อย')['content']
    with SessionLocal() as db:
        pending=db.get(Conversation,cid).capture_context['ai_followup']
        assert pending['field']=='amount' and pending['draft']['category_id']==travel
        assert pending['source_message_id']
    assert len(state['calls'])==2 and count(w)==0
