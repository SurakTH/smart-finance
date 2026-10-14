"""User language is interpreted by a model; only backend facts reach numbers."""
import asyncio,json,uuid
from datetime import date
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account,ChatAction,Conversation,Job,Message
from app.semantic_assistant import Window,bounds
from test_assistant_finance import assistant,tool
from test_telegram_assistant import channel,Sender

@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    from app import semantic_assistant,reporting,request_interpreter,finance_chat
    for module in (semantic_assistant,reporting,request_interpreter,finance_chat):monkeypatch.setattr(module,'today',lambda:date(2026,10,14))


def plan(intent='report',**kw):return tool('understand_request',dict(intent=intent,**kw))
def answer(text='ดูให้แล้วค่ะ ช่วงนี้ใช้ไป **{{expense}}** จาก {{count}}'):return tool('respond_finance',dict(text=text))


def test_unlisted_language_and_date_paraphrase_are_not_rejected_by_legacy_grammar(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-10')
    state['responses']=[plan('transactions',period={'mode':'month_to_date'},q='กาแฟ',metric='expense'),
        answer('คาเฟ่นี่เองค่ะ รวม **{{expense}}** จาก {{count}} เช่น {{item_0_description}} {{item_0_amount}}')]
    content=send('ตั้งแต่เปิดเดือนมาจนตอนนี้เหมือนเงินไหลไปกับคาเฟ่ ช่วยไล่ให้หน่อยได้มั้ย')['content']
    assert '80.00 บาท' in content and '1,000.00' not in content and '2026-10-14' in content
    assert 'คาเฟ่นี่เอง' in content and 'กรอก' not in content and len(state['calls'])==2
    data=json.loads(state['calls'][1]['messages'][-1]['content'])
    assert data['facts']['expense']=='80.00 บาท' and 'income' not in data['facts']
    assert all('กาแฟ'==r['filters']['q'] for r in c.get(b+f'/conversations/{cid}/messages').json()[-1]['references'])


def test_model_can_resolve_canonical_account_from_a_nickname(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan(period={'mode':'current_month'},account='เงินสด',metric='expense'),answer()]
    content=send('เดือนนี้กระเป๋าที่พกออกบ้านโดนไปแค่ไหนแล้ว')['content']
    assert 'บัญชี เงินสด' in content and '80.00 บาท' in content


def test_model_resolves_natural_date_range_without_demanding_iso_from_user(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-04');post(99999,'นอกช่วง','2026-10-10')
    state['responses']=[plan(period={'mode':'range','start':'2026-10-01','end':'2026-10-04'},metric='expense'),answer()]
    content=send('ขอดูเงินที่จ่ายตั้งแต่วันที่หนึ่งถึงวันที่สี่ตุลาหน่อยจ้า')['content']
    assert '2026-10-01 ถึง 2026-10-04' in content and '80.00 บาท' in content and '999.99' not in content


def test_internal_schema_error_is_repaired_without_asking_user_to_reformat(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan(period={'mode':'unsupported_period'}),plan(period={'mode':'previous_week'},metric='expense'),answer('อาทิตย์ก่อนใช้ไป {{expense}} ค่ะ')]
    content=send('อาทิตย์ก่อนเงินหายไปกับอะไรหนักๆบ้างอะ')['content']
    assert '80.00 บาท' in content and 'อาทิตย์ก่อนใช้ไป' in content and len(state['calls'])==3
    assert json.loads(state['calls'][1]['messages'][-1]['content'])['error']=='invalid_arguments'


def test_missing_date_is_repaired_from_context_before_user_is_asked_again(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan(metric='expense'),plan(period={'mode':'month_to_date'},metric='expense'),answer()]
    content=send('ตั้งแต่เริ่มเดือนมานี่เงินโดนไปเท่าไรแล้วอะ')['content']
    assert '2026-10-01 ถึง 2026-10-14' in content and '0.00 บาท' in content
    assert 'ช่วงไหน' not in content and len(state['calls'])==3


def test_elliptical_followup_uses_validated_previous_scope_then_can_clear_filters(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(92000,'อาหาร','2026-10-10')
    state['responses']=[plan(period={'mode':'current_month'},q='กาแฟ',metric='expense'),answer()]
    assert '80.00' in send('อยากรู้กาแฟในรอบเดือนนี้จัง')['content']
    state['responses']=[plan(reuse_previous_scope=True),answer('เรื่องเดิมยอด {{expense}} ค่ะ')]
    assert '80.00' in send('เออแล้วมันหนักเท่าไหร่นะ')['content']
    state['responses']=[plan(reuse_previous_scope=True,clear_filters=True,metric='expense'),answer()]
    content=send('อันนี้เอาทุกอย่างรวมกันเลยนะ ไม่เฉพาะกาแฟแล้ว')['content']
    assert '1,000.00 บาท' in content and 'ค้นคำ กาแฟ' not in content


def test_genuine_ambiguity_gets_a_specific_natural_question(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('clarify',question='หมายถึงอาทิตย์ที่ผ่านมาหรืออาทิตย์ที่จะถึงคะ?')]
    assert send('ขอดูวันอาทิตย์แบบอันนั้นอะ')['content']=='หมายถึงอาทิตย์ที่ผ่านมาหรืออาทิตย์ที่จะถึงคะ?'


@pytest.mark.parametrize('bad',[
    'คุณใช้ไป 999999 บาทค่ะ','รวม {{made_up_amount}} ค่ะ',
    'บันทึกเรียบร้อยแล้วค่ะ {{expense}}','รวมหนึ่งล้านบาทค่ะ {{expense}}',
])
def test_unverified_narrative_is_repaired_to_backend_fact_slots(assistant,bad):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan(period={'mode':'current_month'},metric='expense'),answer(bad),answer()]
    content=send('รอบเดือนนี้เงินโดนไปเยอะมั้ยนะ')['content']
    assert '80.00 บาท' in content and '999999' not in content and 'ล้านบาท' not in content and 'บันทึกเรียบร้อย' not in content
    assert len(state['calls'])==3
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


def test_repeated_invalid_narrative_falls_back_to_real_report_not_format_request(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan(period={'mode':'current_month'},metric='expense'),answer('ยอด 999999 ค่ะ'),answer('ยอด 999999 ค่ะ')]
    content=send('รอบเดือนนี้เงินโดนไปเยอะมั้ยนะ')['content']
    assert '80.00' in content and '999999' not in content and 'format' not in content


def test_conceptual_financial_conversation_is_allowed_without_forcing_a_report(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('conversation',reply='ลองเริ่มจากแยกค่าใช้จ่ายจำเป็นกับสิ่งที่อยากซื้อ แล้วค่อยตั้งงบที่ทำไหวค่ะ')]
    content=send('เริ่มจัดการเงินยังไงแบบไม่เครียดดีอะ')['content']
    assert 'แยกค่าใช้จ่ายจำเป็น' in content and 'ตรวจสอบได้พอ' not in content


@pytest.mark.parametrize('extra',[
    {'workspace_id':str(uuid.uuid4())},{'user_id':str(uuid.uuid4())},{'sql':'SELECT * FROM entries'},
    {'intent':'confirm'}, {'period':{'mode':'range','start':'2020-01-01','end':'2026-10-14'}},
])
def test_model_cannot_choose_authority_sql_confirmation_or_unbounded_read(assistant,extra):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    raw=dict(intent='report',period={'mode':'current_month'},metric='expense');raw.update(extra)
    state['responses']=[tool('understand_request',raw)]*2
    content=send('รอบเดือนนี้เงินโดนไปเยอะมั้ยนะ')['content']
    assert '0.00 บาท' not in content
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


def test_other_workspace_account_is_not_resolved_or_exposed(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    foreign=c.post('/workspaces',json={'name':'อื่น'}).json()['id']
    c.post(f'/workspaces/{foreign}/accounts',json={'name':'บัญชีลับต่างพื้นที่','kind':'asset'})
    state['responses']=[plan(period={'mode':'current_month'},account='บัญชีลับต่างพื้นที่')]*2
    content=send('กระเป๋าฉันรอบเดือนนี้เป็นไงบ้าง')['content']
    assert 'บัญชีลับต่างพื้นที่' not in content and '0.00' not in content


@pytest.mark.parametrize('operation,options,text',[
    ('average',{},'เฉลี่ยเล่นๆแล้วแต่ละวันเงินโดนไปเท่าไหร่จ๊ะ'),
    ('ranking',{'group_by':'description'},'มีตัวไหนดูดเงินสุดๆช่วงนี้บ้าง'),
    ('trend',{'bucket':'week'},'ลองดูว่าต้นเดือนมาทิศทางจ่ายเป็นไงที'),
    ('compare',{'compare_period':{'mode':'previous_month'}},'เดือนรอบนี้กับรอบก่อนต่างกันหนักไหม'),
])
def test_semantic_analytics_uses_same_complete_sql_without_residual_word_gate(assistant,operation,options,text):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan('analytics',period={'mode':'current_month'},operation=operation,metric='expense',**options),answer('ยอดที่ดูคือ {{amount}} ค่ะ')]
    content=send(text)['content'];assert '80.00 บาท' in content and len(state['calls'])==2


def test_semantic_budget_can_explain_remaining_actual_plan(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');assert c.put(b+f'/budgets/2026-10/{cat}',json={'amount':10000}).status_code==200
    state['responses']=[plan('budget',period={'mode':'current_month'}),answer('วงเงินที่วางไว้ {{planned}} ตอนนี้ใช้ {{spent}} ยังเหลือ {{remaining}} ค่ะ')]
    content=send('งบที่ตั้งไว้รอบนี้เหลือช่องหายใจมั้ยนะ')['content']
    assert '100.00 บาท' in content and '80.00 บาท' in content and '20.00 บาท' in content


def test_semantic_writes_only_select_draft_tools_and_require_plain_confirmation(assistant):
    from test_chat_actions import say
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('mutation',action='transaction'),tool('prepare_transaction',dict(intent='create',kind='expense',amount=8000,description='กาแฟ',account_id=wallet,category_id=cat,occurred_on='2026-10-14'))]
    content=send('เมื่อเช้าซดกาแฟแปดสิบ ลืมจดอีกละ ช่วยจัดให้ที')['content']
    assert 'กรุณาตรวจสอบ' in content and c.get(b+'/transactions').json()==[]
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน')
    assert len(c.get(b+'/transactions').json())==1


def test_telegram_can_use_same_natural_answer_and_fact_slots(channel):
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[plan(period={'mode':'month_to_date'},metric='expense'),answer('ตรวจให้แล้วค่ะ ใช้ไป {{expense}}')]
    capture(1,'ตั้งแต่เริ่มรอบนี้ถึงตอนนี้เงินไปแค่ไหนละ');process()
    bot=Sender();assert asyncio.run(deliver_once(bot))
    assert 'ตรวจให้แล้วค่ะ ใช้ไป 0.00 บาท' in bot.sent[0][1]


def test_context_change_during_natural_synthesis_discards_the_answer(assistant,pg_only):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def changed(body):
        assert c.post(b+'/accounts',json={'name':'เปลี่ยนตอนสรุป','kind':'asset'}).status_code==200
        return answer()
    state['responses']=[plan(period={'mode':'current_month'},metric='expense'),changed]
    send('รอบเดือนนี้เงินโดนไปเยอะมั้ยนะ')
    with SessionLocal() as db:
        job=db.scalar(select(Job).where(Job.workspace_id==w));assert job.error=='context_changed'
        assert not db.scalar(select(Message.id).where(Message.conversation_id==cid,Message.role=='assistant'))



@pytest.mark.parametrize('reply',['999999','คุณมีเงินสามสิบบาทค่ะ'])
def test_conversation_cannot_bypass_personal_finance_facts_with_numbers(assistant,reply):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan('conversation',reply=reply)]
    content=send('ตอนนี้ฉันมีเงินเท่าไร')['content']
    assert reply not in content and 'ตรวจสอบได้พอ' in content


def test_verified_past_spending_is_not_mistaken_for_an_assistant_write_receipt(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan(period={'mode':'current_month'},metric='expense'),answer('คุณจ่ายไปแล้ว {{expense}} ค่ะ ถ้าอยากลด ลองดูรายการที่กินบ่อยกันได้')]
    content=send('รอบเดือนนี้เงินโดนไปเยอะมั้ยนะ')['content']
    assert 'คุณจ่ายไปแล้ว 80.00 บาท' in content and 'ต้องมีร่าง' not in content



def test_primary_catalog_prefers_semantics_and_defers_answer_schema_until_facts(assistant):
    from app.assistant_tools import catalog
    names=lambda active:{t['function']['name'] for t in catalog(active)}
    assert 'fetch_finance' in names(set()) and 'understand_request' not in names(set()) and 'interpret_request' not in names(set())
    assert 'respond_finance' not in names(set()) and 'respond_finance' in names({'conversation_answer'})
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[plan(period={'mode':'current_month'},metric='expense'),answer()]
    send('รอบเดือนนี้เงินโดนไปเยอะมั้ยนะ')
    assert 'respond_finance' not in {t['function']['name'] for t in state['calls'][0]['tools']}
    assert 'respond_finance' in {t['function']['name'] for t in state['calls'][1]['tools']}



def test_lab_natural_case_uses_new_runtime_without_real_finance_data(actor,monkeypatch):
    import httpx
    from app import ai
    from app.models import Provider
    from test_ai_diagnostics import run_all,counts,start,result
    c,w,u=actor;b=f'/workspaces/{w}'
    monkeypatch.setattr('app.ai_diagnostics.login_limit',lambda _:None)
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='ollama',model='semantic-lab',task='chat',retries=0))
        db.scalar(select(Account).where(Account.workspace_id==w,Account.kind=='asset')).name='PRIVATE-real-account'
    replies=[plan(period={'mode':'month_to_date'},q='กาแฟ',metric='expense'),answer('คาเฟ่ตัวอย่างใช้ไป {{expense}} จาก {{count}} ค่ะ')]
    real=httpx.Client;calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        assert 'PRIVATE-real-account' not in req.content.decode() and w not in req.content.decode()
        return httpx.Response(200,json={'choices':[{'message':replies.pop(0)}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    before=counts(w);jid=start(c,b,'natural');run_all();report=result(c,b,jid)['diagnostics']['test']
    assert report['status']=='passed' and report['synthetic_only'] and report['calls']==2
    assert counts(w)==before and len(calls)==2



def test_followup_current_balance_keeps_account_but_not_spending_filters(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10')
    state['responses']=[plan(period={'mode':'current_month'},account='เงินสด',q='กาแฟ',metric='expense'),answer()]
    send('กระเป๋าเงินสดเฉพาะกาแฟรอบนี้โดนไปเท่าไหร่')
    state['responses']=[plan('balances',reuse_previous_scope=True),answer('ส่วนบัญชีนี้ยอดปัจจุบัน {{assets}} ค่ะ')]
    content=send('แล้วตัวบัญชีนี้ตอนนี้เหลือจริงๆเท่าไหร่')['content']
    assert 'ยอดสะสมปัจจุบัน' in content and '-80.00 บาท' in content and 'ค้นคำ กาแฟ' not in content
