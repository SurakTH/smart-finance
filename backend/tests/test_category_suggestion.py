"""Model-selected categories remain reviewable and survive wallet clarification."""
import json
import httpx
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account,ChatAction,Provider
from app.worker import run_once
from test_chat_actions import setup,say,count
from test_assistant_finance import tool
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
