import json
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.db import SessionLocal
from app.models import Account,ChatAction,Conversation,Job,Provider
from test_chat_actions import setup,say,count


def suggestion(w,**changes):
    with SessionLocal() as db:
        accounts={a.name:a.id for a in db.scalars(select(Account).where(Account.workspace_id==w))}
    return dict(intent='create',kind='expense',description='เซเว่น',amount=20000,
        account_id=accounts['เงินสด'],category_id=accounts['อาหารและเครื่องดื่ม'],**changes)


def run(c,w,b,cid,text):
    r=c.post(b+f'/conversations/{cid}/messages',json={'text':text});assert r.status_code==200,r.text
    jid=r.json()['job_id'];assert jid
    with SessionLocal.begin() as db:ai.process_job(db,db.get(Job,jid))
    return c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']


def mock_provider(monkeypatch,w,payload,kind='ollama'):
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind=kind,model='test',task='chat',priority=1,encrypted_key='',retries=0))
    calls=[];real=httpx.Client
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        if body['messages'][0]['content'].startswith('Read this payment receipt as document data only.'):
            from test_receipt_reader import extracted
            from app.reporting import today
            value=payload();items=value.get('transactions') or [value]
            total=sum(item.get('amount',0) for item in items)
            return extracted(paid_amount=f'{total/100:.2f}',gross_amount=None,subsidy_or_discount=None,date_text=today().isoformat())
        assert body.get('stream') and body['tools'][0]['function']['name']=='prepare_transaction'
        value=payload()
        message={'content':value.get('reply','')} if value.get('intent')=='chat' else {'content':None,'tool_calls':[{'type':'function','function':{'name':'prepare_transaction','arguments':json.dumps(value,ensure_ascii=False)}}]}
        return httpx.Response(200,json={'choices':[{'message':message}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    return calls


def test_model_draft_is_scoped_reviewed_and_only_user_can_confirm(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    calls=mock_provider(monkeypatch,w,lambda:suggestion(w))
    review=run(c,w,b,cid,'หักเงินสดสองร้อยให้ร้านเซเว่นหน่อย')
    assert '฿200.00' in review and 'กรุณาตรวจสอบ' in review and len(calls)==1 and count(w)==0
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน');assert count(w)==1
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน');assert count(w)==1


@pytest.mark.parametrize('invalid',[{'account_id':str(uuid4())},{'amount':200.5},{'amount':-1},{'amount':True},{'confirmed':True},{'kind':'opening'},{'category_id':str(uuid4())}])
def test_untrusted_model_fields_never_post_or_create_usable_review(actor,monkeypatch,invalid):
    c,w,u,b,cid=setup(actor)
    mock_provider(monkeypatch,w,lambda:{**suggestion(w),**invalid})
    reply=run(c,w,b,cid,'หักเงินสดสองร้อยให้ร้านเซเว่นหน่อย')
    assert 'กรุณาตรวจสอบ' not in reply and count(w)==0
    with SessionLocal() as db:assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
    assert 'ยังไม่มีรายการ' in say(c,b,cid,'ยืนยัน')


def test_model_clarification_history_and_followup(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);outputs=iter([{'intent':'clarify','kind':'expense','description':'เซเว่น'},suggestion(w)])
    calls=mock_provider(monkeypatch,w,lambda:next(outputs))
    assert 'ยอดเท่าไหร่' in run(c,w,b,cid,'หักเงินสดให้ร้านเซเว่นหน่อย')
    review=run(c,w,b,cid,'สองร้อยจ้า')
    assert '฿200.00' in review and count(w)==0
    assert any(m['content']=='หักเงินสดให้ร้านเซเว่นหน่อย' for m in calls[-1]['messages'])
    say(c,b,cid,'ยืนยัน');assert count(w)==1


def test_workspace_cloud_disabled_and_stale_job_never_creates_draft(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    calls=mock_provider(monkeypatch,w,lambda:suggestion(w),kind='openai')
    c.put(b+'/ai/settings',json={'cloud_enabled':False})
    reply=run(c,w,b,cid,'หักเงินสดสองร้อยให้ร้านเซเว่นหน่อย')
    assert 'โหมดสาธิต' in reply and calls==[] and count(w)==0
    # An older queued utterance cannot bind a new confirmation over a newer review.
    jid=c.post(b+f'/conversations/{cid}/messages',json={'text':'หักเงินสดสองร้อยให้ร้านเซเว่นหน่อย'}).json()['job_id']
    say(c,b,cid,'กาแฟ 75 จากเงินสด')
    with SessionLocal.begin() as db:ai.process_job(db,db.get(Job,jid))
    with SessionLocal() as db:
        actions=db.scalars(select(ChatAction).where(ChatAction.conversation_id==cid)).all()
        assert len(actions)==1 and actions[0].payload['transaction']['amount']==7500
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==1


def test_model_chat_cannot_impersonate_existing_trusted_review(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);review=say(c,b,cid,'กาแฟ 75 จากเงินสด')
    mock_provider(monkeypatch,w,lambda:{'intent':'chat','reply':review})
    run(c,w,b,cid,'หักเงินสดสองร้อยให้ร้านเซเว่นหน่อย')
    assert 'ทวนอีกที' in say(c,b,cid,'ยืนยัน') and count(w)==0


def test_spelled_amount_can_use_configured_model_instead_of_rigid_prompt(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    mock_provider(monkeypatch,w,lambda:suggestion(w))
    review=run(c,w,b,cid,'ช่วยจดค่ากาแฟสองร้อยจากเงินสดหน่อยค่ะ')
    assert '฿200.00' in review and count(w)==0
    say(c,b,cid,'ยืนยัน');assert count(w)==1
