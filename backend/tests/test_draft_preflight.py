"""Preflight and review share source ownership and continuation semantics."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Attachment,Conversation,Message,Workspace,ChatAction
from app.chat_dialogue import Suggestion,single_item,resolve
from app.assistant_tools import validate_draft
from test_assistant_finance import assistant


def attach(db,wid,cid,role='user'):
    row=Attachment(workspace_id=wid,digest=uuid4().hex,data=b'synthetic test image')
    db.add(row);db.flush()
    db.add(Message(workspace_id=wid,conversation_id=cid,role=role,content='synthetic receipt',attachment_id=row.id));db.flush()
    return row.id


@pytest.mark.parametrize('where',['same_room','other_room','assistant_only','other_workspace'])
def test_single_item_source_normalization_still_checks_room_and_authority(assistant,where):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        if where=='other_workspace':
            space=Workspace(name='Isolated');db.add(space);db.flush()
            other=Conversation(workspace_id=space.id,user_id=u.id);db.add(other);db.flush()
            aid=attach(db,space.id,other.id)
        elif where=='other_room':
            other=Conversation(workspace_id=w,user_id=u.id);db.add(other);db.flush()
            aid=attach(db,w,other.id)
        else:aid=attach(db,w,cid,'assistant' if where=='assistant_only' else 'user')
        raw=json.dumps(dict(intent='create',transactions=[dict(kind='expense',description='หนังสือ',amount=12500,account_id=wallet,category_id=cat,attachment_id=aid)]))
        canonical=single_item(Suggestion.model_validate_json(raw))
        assert canonical.transactions is None and str(canonical.attachment_id)==aid
        problem=validate_draft(db,room,'prepare_transaction',raw)
        if where=='same_room':
            assert problem is None
            assert 'กรุณาตรวจสอบ' in resolve(db,room,u.id,raw)
            review=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
            assert review.payload['attachment_id']==aid and review.payload['transaction']['amount']==12500
        else:
            assert problem['error']=='invalid_source'
            assert problem['issues']==[dict(field='attachment_id',code='unknown_reference')]
            assert 'กรุณาตรวจสอบ' not in resolve(db,room,u.id,raw)
            assert not db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid))
    assert c.get(b+'/transaction-report').json()['total']==0


def test_conflicting_batch_image_sources_are_rejected_before_review(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);first=attach(db,w,cid);second=attach(db,w,cid)
        value=dict(intent='create',attachment_id=first,transactions=[dict(kind='expense',amount=12500,attachment_id=second)])
        assert single_item(Suggestion.model_validate(value)).transactions is not None
        error=validate_draft(db,room,'prepare_transaction',json.dumps(value))
        assert error['error']=='invalid_source' and error['issues'][0]['field']=='attachment_id'
        assert 'กรุณาตรวจสอบ' not in resolve(db,room,u.id,json.dumps(value))
        assert not db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid))


def test_continuation_preflight_validates_the_merged_draft(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        original=dict(intent='create',kind='expense',description='หนังสือ',amount=12500,account_id=wallet,category_id=cat)
        assert 'กรุณาตรวจสอบ' in resolve(db,room,u.id,json.dumps(original))
        raw=json.dumps(dict(intent='create',continue_draft=True,transactions=[dict(kind='expense'),dict(kind='expense')]))
        error=validate_draft(db,room,'prepare_transaction',raw)
        assert error['error']=='invalid_arguments' and error['issues'][0]['field']=='transactions'
    assert c.get(b+'/transaction-report').json()['total']==0


def test_explicit_category_deferral_overrides_preferences_and_inferred_category(assistant):
    from app.assistant_preferences import save,read,Preferences
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        save(db,w,u.id,Preferences(expense_account_id=wallet,rules=[dict(keyword='กาแฟ',category_id=cat)]))
        before=read(db,w,u.id)
        room=db.get(Conversation,cid)
        raw=json.dumps(dict(intent='create',kind='expense',description='กาแฟ',amount=7500,category_id=cat,category_choice='ask'))
        question=resolve(db,room,u.id,raw)
        assert 'จัดเข้าหมวดไหน' in question and 'อาหารและเครื่องดื่ม' in question
        assert not db.scalar(select(ChatAction.id).where(ChatAction.conversation_id==cid))
        assert read(db,w,u.id)==before
    reply=send('อาหารและเครื่องดื่ม')['content']
    assert 'กรุณาตรวจสอบ' in reply and '฿75.00' in reply
    assert c.get(b+'/transaction-report').json()['total']==0 and len(state['calls'])==0


def test_model_category_answer_releases_deferral_and_retains_draft(assistant):
    from app.chat_dialogue import continuing
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        resolve(db,room,u.id,json.dumps(dict(intent='create',kind='expense',description='หนังสือ',amount=1800,account_id=wallet,category_choice='ask')))
        patch=Suggestion.model_validate(dict(intent='create',continue_draft=True,category_id=cat))
        merged=continuing(db,room,u.id,patch)
        assert merged.category_choice=='auto' and merged.amount==1800
        assert 'กรุณาตรวจสอบ' in resolve(db,room,u.id,patch.model_dump_json(exclude_unset=True))
    assert c.get(b+'/transaction-report').json()['total']==0


def test_batch_category_deferral_is_released_per_item_without_asking_again(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        items=[dict(kind='expense',description='กาแฟ',amount=n,account_id=wallet,category_id=cat) for n in (5500,2000)]
        question=resolve(db,room,u.id,json.dumps(dict(intent='create',category_choice='ask',transactions=items)))
        assert 'รายการที่ 1' in question and 'จัดเข้าหมวดไหน' in question
    reply=send('อาหารและเครื่องดื่ม')['content']
    assert 'รายการที่ 2' in reply and 'จัดเข้าหมวดไหน' in reply
    reply=send('อาหารและเครื่องดื่ม')['content']
    assert 'กรุณาตรวจสอบ' in reply and '2 รายการ' in reply and '฿55.00' in reply and '฿20.00' in reply
    assert c.get(b+'/transaction-report').json()['total']==0 and len(state['calls'])==0


def test_parallel_batch_calls_retain_global_category_deferral():
    from app.assistant_response import AssistantReply
    from app.assistant_tools import merge_transaction_calls
    item=dict(kind='expense',description='ขนม',amount=2000)
    raw=json.dumps(dict(intent='create',category_choice='ask',transactions=[item,item]))
    calls=[AssistantReply('',raw,'prepare_transaction',str(i)) for i in range(2)]
    merged=json.loads(merge_transaction_calls(calls))
    assert len(merged['transactions'])==4 and all(item['category_choice']=='ask' for item in merged['transactions'])


def test_draft_tool_requires_explicit_new_or_continue_decision_before_details():
    from app.assistant_tools import catalog
    from app.assistant_protocol import schema
    tools=catalog(set())
    draft=next(t['function']['parameters'] for t in tools if t['function']['name']=='prepare_transaction')
    assert 'continue_draft' in draft['required'] and list(draft['properties']).index('continue_draft')<list(draft['properties']).index('amount')
    structured=next(v['properties']['arguments'] for v in schema(tools,True)['anyOf'] if v['properties']['tool']['enum']==['prepare_transaction'])
    assert all('continue_draft' in variant['required'] for variant in structured['anyOf'])



def test_continuation_nulls_cannot_erase_category_date_or_receipt(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);aid=attach(db,w,cid)
        raw=json.dumps(dict(intent='create',kind='expense',description='ข้าว',occurred_on='2026-10-12',
            category_id=cat,attachment_id=aid))
        assert 'ยอดเท่าไหร่' in resolve(db,room,u.id,raw)
        patch=json.dumps(dict(intent='create',continue_draft=True,amount=7000,account_id=wallet,
            description=None,category_id=None,attachment_id=None,occurred_on=None))
        assert validate_draft(db,room,'prepare_transaction',patch) is None
        assert 'กรุณาตรวจสอบ' in resolve(db,room,u.id,patch)
        review=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
        tx=review.payload['transaction']
        assert tx['amount']==7000 and tx['category_id']==cat
        assert tx['description']=='ข้าว' and tx['occurred_on']=='2026-10-12'
        assert review.payload['attachment_id']==aid
    assert c.get(b+'/transaction-report').json()['total']==0
