"""Conversation-first routing and scoped draft continuations, not phrase patches."""
import json,uuid
from types import SimpleNamespace
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Conversation,Provider,ChatAction,Entry,Message,now
from app.worker import run_once
from test_assistant_finance import assistant,tool
from test_chat_images import receipt
from test_chat_actions import count,say


def test_main_model_turn_never_uses_legacy_keyword_intent_or_read_shortcut(assistant,monkeypatch):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def forbidden(*a,**kw):raise AssertionError('Legacy intent intercepted a model conversation')
    monkeypatch.setattr('app.assistant_evidence.scope',forbidden)
    monkeypatch.setattr('app.assistant_questions.for_turn',forbidden)
    state['responses']=[{'content':'ได้ค่ะ เราคุยกันต่อเรื่องเดิมได้'}]
    assert 'เราคุยกันต่อ' in send('รายจ่ายเนอะ')['content']
    advertised={t['function']['name'] for t in state['calls'][0]['tools']}
    assert advertised=={'fetch_finance','lookup_workspace','prepare_transaction','load_toolkit'}
    assert len(state['calls'])==1


def test_receipt_unknown_caption_and_direction_correction_keep_same_draft(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='income',amount=6000,account_id=wallet,occurred_on='2026-10-14'))]
    upload=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'ช่วยจดจากสลิปนี้'}).json()
    assert run_once()
    aid=upload['attachment_id']
    with SessionLocal() as db:
        assert db.get(Conversation,cid).capture_context['ai_followup']['draft']['attachment_id']==aid
    def description(body):
        assert sum(isinstance(m['content'],list) for m in body['messages'])==1
        return tool('prepare_transaction',dict(intent='create',continue_draft=True,description='ค่าริดผ้า'))
    state['responses']=[description]
    send('ค่าริดผ้า')
    with SessionLocal() as db:
        draft=db.get(Conversation,cid).capture_context['ai_followup']['draft']
        assert draft['amount']==6000 and draft['description']=='ค่าริดผ้า' and draft['attachment_id']==aid
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,kind='expense',category_id=cat))]
    reply=send('รายจ่ายเนอะ')
    assert 'กรุณาตรวจสอบ' in reply['content'] and '฿60.00' in reply['content'] and 'ค้นคำ' not in reply['content']
    assert count(w)==0
    with SessionLocal() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.workspace_id==w,ChatAction.status=='pending'))
        assert action.payload['transaction']['kind']=='expense'
        assert action.payload['transaction']['occurred_on']=='2026-10-14'
        assert action.payload['attachment_id']==aid
    say(c,b,cid,'ยืนยัน')
    assert count(w)==1
    with SessionLocal() as db:
        entry=db.scalar(select(Entry).where(Entry.workspace_id==w))
        assert entry.amount==6000 and entry.kind=='expense'


def test_continuing_confirmable_single_draft_preserves_fields_and_clears_old_category(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    income=next(a['id'] for a in c.get(b+'/accounts').json() if a['kind']=='income')
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='income',description='บริการ',amount=6000,account_id=wallet,category_id=income))]
    assert 'กรุณาตรวจสอบ' in send('จดบริการ 60')['content']
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,kind='expense'))]
    response=send('อันนี้เป็นเงินออกจ้า')
    assert 'จัดเข้าหมวดไหน' in response['content'] and count(w)==0
    assert 'ทวนร่างใหม่' in say(c,b,cid,'ยืนยัน') and count(w)==0
    with SessionLocal() as db:
        draft=db.get(Conversation,cid).capture_context['ai_followup']['draft']
        assert draft['amount']==6000 and draft['kind']=='expense' and 'category_id' not in draft


def test_continuation_cannot_load_another_room_or_expired_partial_draft(assistant):
    from app.chat_dialogue import Suggestion,continuing
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    other=c.post(b+'/conversations',json={}).json()['id']
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='บริการ',amount=6000,account_id=wallet))]
    send('จดบริการ 60')
    with SessionLocal() as db:
        import pytest
        for room in (db.get(Conversation,other),db.get(Conversation,cid)):
            if room.id==cid:room.capture_context['ai_followup']['expires']=0
            with pytest.raises(ValueError,match='No current draft'):
                continuing(db,room,u.id,Suggestion(intent='create',continue_draft=True,category_id=cat))


def test_partial_draft_is_never_available_to_another_user(assistant):
    from app.chat_dialogue import Suggestion,continuing
    import pytest
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',amount=6000,account_id=wallet))]
    send('ช่วยจด 60')
    with SessionLocal() as db:
        with pytest.raises(ValueError,match='Conversation owner mismatch'):
            continuing(db,db.get(Conversation,cid),str(uuid.uuid4()),Suggestion(intent='create',continue_draft=True,description='อื่น'))


def test_free_question_after_image_keeps_receipt_for_an_unknown_caption(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    state['responses']=[{'content':'รายการนี้เป็นค่าอะไรคะ?'}]
    uploaded=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'จดให้หน่อย'}).json()
    assert run_once()
    def next_step(body):
        image=next(m for m in body['messages'] if isinstance(m['content'],list))
        assert uploaded['attachment_id'] in image['content'][0]['text']
        return tool('prepare_transaction',dict(intent='create',kind='expense',description='ค่าริดผ้า',amount=6000,account_id=wallet,category_id=cat,attachment_id=uploaded['attachment_id']))
    state['responses']=[next_step]
    assert '฿60.00' in send('ค่าริดผ้า')['content'] and count(w)==0


def test_receipt_focus_cannot_include_an_image_from_another_room(assistant):
    from app.assistant_images import selected_images
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    other=c.post(b+'/conversations',json={}).json()['id']
    aid=c.post(b+f'/conversations/{other}/images',files={'file':receipt()},data={'text':'อื่น'}).json()['attachment_id']
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        room.capture_context={'receipt_focus':{'attachment_id':aid,'expires':now()+900}}
    with SessionLocal() as db:
        job=SimpleNamespace(workspace_id=w,user_id=u.id,payload={'conversation_id':cid,'text':'ค่าริดผ้า'})
        assert selected_images([],job,db)==[]
