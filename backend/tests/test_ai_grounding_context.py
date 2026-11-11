"""Audit regressions: meaning, date scope, bounded reads and receipt provenance."""
import json,uuid
from types import SimpleNamespace
from datetime import date
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Conversation,Provider,ChatAction,Message,now
from app.assistant_data import natural,remember,parse_fetch,CalendarConflict,read
from app.assistant_grounding import render
from app.worker import run_once
from test_assistant_finance import assistant,tool,result
from test_chat_actions import say,count,code
from test_chat_images import receipt


def evidence(facts):
    job=SimpleNamespace(user_id='user',workspace_id='workspace',payload={'conversation_id':'room'})
    remember(job,dict(facts=facts,scope='ช่วงทดสอบ',fallback='ข้อมูลจริง'))
    return job


@pytest.mark.parametrize('reply',['รายรับ 80 บาท รายจ่าย 1,000 บาท','รายรับ: **80 บาท**\nรายจ่าย: **1,000 บาท**','| รายรับ | รายจ่าย |\n| --- | --- |\n| 80 | 1,000 |'])
def test_swapped_metrics_rejected(reply):
    job=evidence(dict(income='1,000.00 บาท',expense='80.00 บาท',count='2 รายการ'))
    with pytest.raises(ValueError):natural(job,reply)


@pytest.mark.parametrize('reply',['เงินสด 1,000 บาท ธนาคาร 80 บาท ยอดสุทธิ 1,080 บาท','| บัญชี | ยอด |\n| --- | --- |\n| เงินสด | 1,000 |\n| ธนาคาร | 80 |\nยอดสุทธิ 1,080 บาท'])
def test_swapped_account_balances_rejected(reply):
    job=evidence(dict(net='1,080.00 บาท',account_0_name='เงินสด',account_0_balance='80.00 บาท',account_1_name='ธนาคาร',account_1_balance='1,000.00 บาท'))
    with pytest.raises(ValueError):natural(job,reply)


def test_valid_metrics_and_account_table_still_work():
    job=evidence(dict(income='1,000.00 บาท',expense='80.00 บาท'))
    assert '1,000' in natural(job,'| รายรับ | รายจ่าย |\n| --- | --- |\n| 1,000 | 80 |')


def test_decrease_magnitude_allowed_but_wrong_direction_rejected():
    job=evidence(dict(amount='100.00 บาท',previous_amount='150.00 บาท',delta='-50.00 บาท',change_percent='-33.33%'))
    assert 'ลดลง 50' in natural(job,'ใช้ไป 100 บาท ลดลง 50 บาท หรือ 33.33% ค่ะ')
    with pytest.raises(ValueError):natural(job,'ใช้ไป 100 บาท เพิ่มขึ้น 50 บาท หรือ 33.33%')


def test_all_turn_evidence_and_stable_dataset_ids_retained():
    job=evidence(dict(net='12,000.00 บาท'))
    original=job._direct_evidence['datasets'][0]
    for amount in (100,200,300,400,500):remember(job,dict(facts={'amount':f'{amount}.00 บาท'},scope='ช่วงทดสอบ',fallback='ข้อมูลจริง'))
    assert len(job._direct_evidence['datasets'])==6
    assert '12,000' in natural(job,'ยอดสุทธิ 12,000 บาท ยอดรวมช่วงล่าสุด 500 บาท')
    remember(job,original)
    assert job._direct_evidence['latest']==0 and len(job._direct_evidence['datasets'])==6
    reply=render(job,json.dumps(dict(reports=[dict(dataset_id=1,facts=['net'])])))
    assert 'ยอดสุทธิ' in reply and '12,000' in reply


def test_explicit_date_conflict_and_multiperiod_request(monkeypatch):
    monkeypatch.setattr('app.reporting.today',lambda:date(2026,10,14))
    monkeypatch.setattr('app.semantic_assistant.today',lambda:date(2026,10,14))
    with pytest.raises(CalendarConflict):parse_fetch(json.dumps(dict(resource='summary',period='เดือนนี้')),'เมื่อวานใช้ไปเท่าไหร่')
    assert parse_fetch(json.dumps(dict(resource='summary',period='month to date')),'เดือนนี้ใช้ไปเท่าไหร่').period.mode=='month_to_date'
    assert parse_fetch(json.dumps(dict(resource='summary',period='เดือนนี้')),'เทียบเมื่อวานกับเดือนนี้').period.mode=='current_month'


def test_renderer_owns_labels_signs_and_rejects_unbound_money():
    job=evidence(dict(amount='100.00 บาท',previous_amount='150.00 บาท',delta='-50.00 บาท',change_percent='-33.33%'))
    text=render(job,json.dumps(dict(intro='ดูให้แล้วค่ะ',reports=[dict(dataset_id=1,facts=['amount','delta','change_percent'])],advice='ลองดูหมวดที่ใช้บ่อยประกอบได้ค่ะ')))
    assert 'ยอดรวม: **100.00 บาท**' in text and 'ลดลง: **50.00 บาท**' in text and '33.33%' in text
    for data in (dict(reports=[dict(dataset_id=1,facts=['made_up'])]),dict(reports=[dict(dataset_id=2,facts=['amount'])]),dict(intro='รายรับ 999 บาท',reports=[dict(dataset_id=1,facts=['amount'])])):
        with pytest.raises(ValueError):render(job,json.dumps(data))
    job.user_id='another-user'
    from app.ai_fence import Invalidated
    with pytest.raises(Invalidated):render(job,json.dumps(dict(reports=[dict(dataset_id=1,facts=['amount'])])))


def test_real_render_tool_two_calls_with_sql_data_and_no_writes(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000)
    state['responses']=[tool('fetch_finance',dict(resource='summary',metric='expense')),lambda body:tool('render_finance',dict(intro='ดูให้แล้วค่ะ',reports=[dict(dataset_id=result(body)['dataset_id'],facts=['expense','count'])]))]
    text=send('เดือนนี้ใช้ไปเท่าไหร่')['content']
    assert 'รายจ่าย: **80.00 บาท**' in text and '1 รายการ' in text and len(state['calls'])==2
    assert count(w)==1


def test_identical_normalized_fetch_reuses_aggregate_and_detects_loop(assistant,monkeypatch):
    from app import assistant_data
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000)
    real=assistant_data.prepare;computations=[]
    def counted(*args,**kwargs):computations.append(1);return real(*args,**kwargs)
    monkeypatch.setattr(assistant_data,'prepare',counted)
    repeat=tool('fetch_finance',dict(resource='summary',period='month to date',metric='expense'))
    state['responses']=[repeat,repeat,repeat]
    assert '80.00' in send('เดือนนี้ใช้ไปเท่าไหร่')['content']
    assert len(computations)==1 and len(state['calls'])==3
    assert result(state['calls'][2])['cached'] is True


def test_preferences_reply_and_names_remain_private_and_natural(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    pref=c.get(b+'/ai/preferences').json();pref.update(enabled=True,expense_account_id=wallet)
    assert c.put(b+'/ai/preferences',json=pref).status_code==200
    state['responses']=[tool('lookup_workspace',dict(queries=[dict(resource='preferences')])),{'content':'บัญชีเริ่มต้นรายจ่ายของคุณคือเงินสดค่ะ'}]
    assert 'คือเงินสด' in send('ตั้งบัญชีเริ่มต้นไว้ที่ไหน')['content']
    assert result(state['calls'][1])['results'][0]['expense_account']['name']=='เงินสด'
    assert count(w)==0


def test_plain_cancel_after_report_but_confirmation_stays_bound(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    draft=tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account_id=wallet,category_id=cat))
    state['responses']=[draft];review=send('ช่วยจดกาแฟ 80 บาท')['content'];old_code=code(review)
    state['responses']=[tool('fetch_finance',dict(resource='summary',metric='expense')),{'content':'ใช้ไป 0 บาทค่ะ'}]
    send('เดือนนี้ใช้ไปเท่าไหร่')
    assert 'ทวนอีกที' in say(c,b,cid,'ยืนยัน') and count(w)==0
    assert 'ยกเลิกข้อเสนอ' in say(c,b,cid,'ยกเลิก') and count(w)==0
    state['responses']=[draft];send('ช่วยจดกาแฟ 80 บาท')
    assert 'ยกเลิกแล้ว' in say(c,b,cid,'ยกเลิก '+old_code)
    with SessionLocal() as db:assert len(db.scalars(select(ChatAction).where(ChatAction.conversation_id==cid,ChatAction.status=='pending')).all())==1


def test_partial_receipt_no_pixels_on_unrelated_read_and_can_be_cancelled(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    state['responses']=[tool('prepare_transaction',dict(intent='create',amount=6000))]
    uploaded=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'ช่วยจดจากรูปนี้'}).json();assert run_once()
    state['calls'].clear()
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='เมื่อวาน',metric='expense')),{'content':'ใช้ไป 0 บาทค่ะ'}]
    assert '0 บาท' in send('เมื่อวานใช้ไปเท่าไหร่')['content']
    assert all(not any(isinstance(m['content'],list) for m in body['messages']) for body in state['calls'])
    with SessionLocal() as db:assert db.get(Conversation,cid).capture_context['ai_followup']['draft']['attachment_id']==uploaded['attachment_id']
    assert 'ยกเลิกร่าง' in say(c,b,cid,'ยกเลิก') and count(w)==0


def test_search_labels_and_workspace_name_never_enter_system_role(assistant):
    from app.models import Workspace
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    marker='UNTRUSTED-AUDIT-LABEL';post(8000,marker)
    with SessionLocal.begin() as db:db.get(Workspace,w).name='UNTRUSTED-WORKSPACE-NAME'
    state['responses']=[tool('fetch_finance',dict(resource='transactions',metric='expense')),{'content':'พบรายจ่าย 80 บาทค่ะ'}];send('ขอดูรายการล่าสุด')
    state['responses']=[{'content':'อยากให้แก้รายละเอียดเป็นอะไรคะ?'}];send('ช่วยแก้รายการเมื่อกี้หน่อย')
    systems=' '.join(m['content'] for m in state['calls'][-1]['messages'] if m['role']=='system')
    users=' '.join(str(m['content']) for m in state['calls'][-1]['messages'] if m['role']=='user')
    assert marker not in systems and 'UNTRUSTED-WORKSPACE-NAME' not in systems
    assert marker in users and 'UNTRUSTED-WORKSPACE-NAME' in users
    assert count(w)==1


def test_compact_history_budget_preserves_sources_and_older_task_outcomes(assistant):
    from app.chat_context import history_and_notes
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='SOURCE-TASK',amount=8000,account_id=wallet,category_id=cat))];send('ช่วยจดกาแฟ 80 บาท');say(c,b,cid,'ยกเลิก')
    with SessionLocal.begin() as db:
        action=db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid));action.created_at=1
        for i in range(30):db.add(Message(workspace_id=w,conversation_id=cid,role='user' if i%2==0 else 'assistant',content='topic '+str(i)+' '+('ก'*1200),created_at=now()*1000+1000+i))
    with SessionLocal() as db:
        old,_=history_and_notes(db,w,cid);recent,notes=history_and_notes(db,w,cid,compact=True)
        assert len(recent)<len(old) and sum(min(len(m.content),4000) for m in recent)<=12000
        note=json.loads(notes);assert all(item['message_id'] for item in note['items'])
        assert note['task_outcomes'][0]['status']=='cancelled' and note['task_outcomes'][0]['description']=='SOURCE-TASK'
        assert '8000' not in notes and 'ไม่ใช่ยอดเงินจริง' in notes


def test_supporting_date_cannot_replace_requested_date(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='last week',purpose='context',metric='expense')),
        tool('render_finance',dict(reports=[dict(dataset_id=1,facts=['expense'])])),
        tool('render_finance',dict(reports=[dict(dataset_id=1,facts=['expense'])]))]
    text=send('เมื่อวานใช้ไปเท่าไหร่')['content']
    assert 'ยังไม่มีข้อมูลตรงช่วงที่ถาม' in text and '0.00' not in text and count(w)==0


def test_context_and_requested_dates_are_both_rendered_with_correct_labels(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='last week',purpose='context',metric='expense')),
        tool('fetch_finance',dict(resource='summary',period='เมื่อวาน',metric='expense')),
        tool('render_finance',dict(reports=[dict(dataset_id=2,facts=['expense']),dict(dataset_id=1,facts=['expense'])]))]
    text=send('เมื่อวานใช้เยอะไหม')['content']
    assert 'ข้อมูลประกอบ' in text and 'รายจ่าย: **0.00 บาท**' in text and len(state['calls'])==3 and count(w)==0


def test_receipt_inspection_cannot_load_another_rooms_pixels(assistant):
    from app.assistant_images import inspect
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    other=c.post(b+'/conversations',json={}).json()['id'];state['responses']=[{'content':'ได้รับรูปค่ะ'}]
    aid=c.post(b+f'/conversations/{other}/images',files={'file':receipt()},data={'text':'รูปทดสอบ'}).json()['attachment_id'];assert run_once()
    with SessionLocal() as db:
        job=SimpleNamespace(workspace_id=w,user_id=u.id,payload={'conversation_id':cid},_receipt_id=aid)
        with pytest.raises(ValueError,match='No scoped receipt'):inspect(db,db.get(Conversation,cid),job,SimpleNamespace(supports_images=True))


def test_initial_tool_schema_has_a_regression_budget_without_losing_constraints():
    from app.assistant_tools import catalog
    tools=catalog(set());encoded=json.dumps(tools,ensure_ascii=False).encode()
    assert len(encoded)<9000  # Baseline before compaction was 11,041 bytes.
    names={t['function']['name']:t['function']['parameters'] for t in tools}
    assert set(names)=={'fetch_finance','lookup_workspace','prepare_transaction','load_toolkit'}
    assert names['fetch_finance']['additionalProperties'] is False
    assert 'intent' in names['prepare_transaction']['required']


def test_supporting_reads_do_not_replace_followup_scope_and_cache_is_room_bound(assistant):
    from app.ai_fence import Invalidated
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    other=c.post(b+'/conversations',json={}).json()['id']
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        message=Message(workspace_id=w,conversation_id=cid,role='user',content='เมื่อวานใช้เยอะไหม');db.add(message);db.flush()
        job=SimpleNamespace(workspace_id=w,user_id=u.id,payload={'conversation_id':cid,'user_message_id':message.id,'text':message.content})
        primary=dict(resource='summary',period='เมื่อวาน',metric='expense')
        first=read(db,room,job,json.dumps(primary));scope=dict(room.capture_context['verified_scope'])
        read(db,room,job,json.dumps(dict(resource='summary',period='last week',purpose='context',metric='expense')))
        assert room.capture_context['verified_scope']==scope
        assert read(db,room,job,json.dumps(primary))['dataset_id']==first['dataset_id'] and job._last_fetch_cached
        other_message=Message(workspace_id=w,conversation_id=other,role='user',content='เมื่อวานใช้เยอะไหม');db.add(other_message);db.flush()
        forged=SimpleNamespace(workspace_id=w,user_id=u.id,payload={'conversation_id':other,'user_message_id':other_message.id,'text':other_message.content},_fetch_cache=job._fetch_cache,_fetch_cache_actor=job._fetch_cache_actor)
        with pytest.raises(Invalidated):read(db,db.get(Conversation,other),forged,json.dumps(primary))


def test_default_renderer_keeps_requested_transaction_breakdown(assistant,monkeypatch):
    monkeypatch.setattr('app.reporting.today',lambda:date(2026,10,14))
    monkeypatch.setattr('app.semantic_assistant.today',lambda:date(2026,10,14))
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-13');post(12000,'ข้าว','2026-10-13')
    state['responses']=[
        tool('fetch_finance',dict(resource='transactions',period='เมื่อวาน',metric='expense')),
        tool('render_finance',{}),
    ]
    text=send('เมื่อวานจ่ายอะไรบ้าง')['content']
    assert 'รายจ่าย 200.00 บาท' in text and 'รายรับ' not in text
    assert 'กาแฟ · 80.00 บาท' in text and 'ข้าว · 120.00 บาท' in text
    assert len(state['calls'])==2 and count(w)==2


def test_default_renderer_excludes_supporting_only_results():
    job=evidence(dict(expense='80.00 บาท'))
    from app.assistant_data import remember
    remember(job,dict(scope='ข้อมูลประกอบ',facts={'expense':'999.00 บาท'},
                      fallback='999.00 บาท',purpose='context'))
    assert render(job,'{}')==job._direct_evidence['datasets'][0]['fallback']
    with pytest.raises(ValueError):render(job,'{"intro":"จ่ายไป 999 บาท"}')
    job._direct_evidence['datasets'].pop(0)
    with pytest.raises(ValueError,match='missing answering scope'):render(job,'{}')


def test_invalid_presentation_does_not_spend_another_model_call(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000)
    state['responses']=[
        tool('fetch_finance',dict(resource='summary',metric='expense')),
        tool('render_finance',dict(intro='รายจ่าย 999 บาท',reports=[dict(dataset_id=1,facts=['expense'])])),
    ]
    text=send('เดือนนี้ใช้ไปเท่าไหร่')['content']
    assert '80.00 บาท' in text and '999' not in text
    assert len(state['calls'])==2 and count(w)==1
