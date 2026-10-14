"""Date words are model transport, never a required user command format."""
import asyncio,json
from datetime import date
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.assistant_calendar import normalize,hint,date_only
from app.assistant_data import Fetch,parse_fetch,tool as fetch_tool
from app.semantic_assistant import bounds,tools as semantic_tools
from app.db import SessionLocal
from app.models import Conversation,ChatAction,Message
from test_assistant_finance import assistant,tool,result
from test_telegram_assistant import channel,Sender

@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    from app import semantic_assistant,reporting,finance_chat,request_interpreter,assistant_finance
    for module in (semantic_assistant,reporting,finance_chat,request_interpreter,assistant_finance):monkeypatch.setattr(module,'today',lambda:date(2026,10,14))

@pytest.mark.parametrize('value,start,end',[
 ('สัปดาห์ที่แล้ว','2026-10-05','2026-10-11'),('last week','2026-10-05','2026-10-11'),
 ({'mode':'Last-Week'},'2026-10-05','2026-10-11'),({'mode':'lastweek'},'2026-10-05','2026-10-11'),
 ({'mode':'previous week'},'2026-10-05','2026-10-11'),({'mode':'relative','value':'สัปดาห์ที่แล้ว'},'2026-10-05','2026-10-11'),
 ('เมื่อวาน','2026-10-13','2026-10-13'),('วันที่ 13/10','2026-10-13','2026-10-13'),
 ('๑๓/๑๐/๒๕๖๙','2026-10-13','2026-10-13'),('2569-10-13','2026-10-13','2026-10-13'),
 ('2026-10','2026-10-01','2026-10-31'),('month-to-date','2026-10-01','2026-10-14'),
 ('this month so far','2026-10-01','2026-10-14'),('ตั้งแต่เริ่มเดือนมาจนตอนนี้','2026-10-01','2026-10-14'),
 ('ตั้งแต่ต้นเดือน ถึง วันนี้','2026-10-01','2026-10-14'),
 ('last 7 days','2026-10-08','2026-10-14'),('ย้อนหลัง 7 วัน','2026-10-08','2026-10-14'),
 ({'mode':'last_7_days'},'2026-10-08','2026-10-14'),('week to date','2026-10-12','2026-10-14'),
 ({'mode':'date','start':'13/10'},'2026-10-13','2026-10-13'),
 ({'mode':'custom_range','start':'2026-10-01','end':'2026-10-13'},'2026-10-01','2026-10-13'),
 ('1/10 ถึง 13/10','2026-10-01','2026-10-13'),
])
def test_transport_styles_resolve_exact_backend_dates(value,start,end):
    actual=bounds(Fetch(resource='summary',period=value).period)
    assert tuple(str(x) for x in actual)==(start,end)


@pytest.mark.parametrize('value',[
 'วันที่ 31/2','13/10/69','anything','วันอาทิตย์','last 0 days','last 367 days',
 {'mode':'yesterday','start':'2026-10-13','end':'2026-10-13'},
 {'mode':'last_7_days','days':30}, {'mode':'range','start':'2026-10-14','end':'2026-10-01'},
 {'mode':'relative','value':'last_week','workspace_id':'foreign'},
 {'mode':'range','start':'2020-01-01','end':'2026-10-14'},
])
def test_ambiguous_conflicting_unbounded_or_authority_periods_stay_rejected(value):
    with pytest.raises((ValueError,ValidationError)):bounds(Fetch(resource='summary',period=value).period)


@pytest.mark.parametrize('text,mode',[
 ('สัปดาห์ที่แล้วใช้ไปเท่าไหร่','previous_week'),('สัปดาห์ที่แล้ว','previous_week'),
 ('เมื่อวานละ','yesterday'),('วันที่ 13/10 ละ','range'),
 ('ตั้งแต่เริ่มเดือนมาจนตอนนี้เหมือนเงินไหลไปกับคาเฟ่ ช่วยไล่ให้หน่อยได้มั้ย','month_to_date'),
 ('ช่วยดูรายจ่าย 1/10 ถึง 13/10 หน่อย','range'),
])
def test_hint_finds_one_date_without_parsing_finance_intent(text,mode):assert hint(text)['mode']==mode


@pytest.mark.parametrize('text',['เดือนนี้กับเดือนก่อน','เมื่อวานกับวันนี้','13/10 และ 14/10','เรื่องเดิมน่ะ','วันอาทิตย์ละ'])
def test_conflicting_or_missing_calendar_hint_never_guesses(text):assert hint(text) is None


def test_advertised_tools_have_plain_date_words_and_flat_range_objects():
    for value in [fetch_tool(),semantic_tools()[0]]:
        params=value['function']['parameters'];period=params['properties']['period']
        assert period['anyOf'][0]['type']=='string' and '"mode":' not in json.dumps(period)
        assert period['anyOf'][1]['required']==['start','end'] and not period['anyOf'][1]['additionalProperties']
        assert 'Window' not in params.get('$defs',{})


def test_calendar_recovery_uses_original_user_date_not_a_default_month():
    value=parse_fetch(json.dumps({'resource':'summary','period':{'mode':'made_up_enum'}}),'สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert tuple(str(d) for d in bounds(value.period))==('2026-10-05','2026-10-11')


@pytest.mark.parametrize('extra',[
 {'workspace_id':'foreign'}, {'user_id':'foreign'}, {'sql':'SELECT * FROM entries'},
 {'account_id':'not-a-uuid'}, {'period':{'mode':'nonsense','user_id':'foreign'}},
 {'compare_period':{'mode':'nonsense'}},
 {'period':{'mode':'relative','value':{'user_id':'foreign'}}},
 {'period':[{'workspace_id':'foreign'}]},
])
def test_date_recovery_never_erases_other_validation_or_authority_errors(extra):
    data={'resource':'summary','period':{'mode':'made_up_enum'}};data.update(extra)
    with pytest.raises(ValidationError):parse_fetch(json.dumps(data),'เมื่อวานใช้ไปเท่าไหร่')


def test_unknown_calendar_without_a_clear_user_date_gets_actionable_repair(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    def corrected(body):
        feedback=result(body);assert feedback['error']=='invalid_arguments'
        assert 'previous_week' in feedback['calendar']['accepted_modes']
        assert 'สัปดาห์ที่แล้ว' in feedback['calendar']['examples']
        assert 'invented period.mode' in feedback['calendar']['message']
        return tool('fetch_finance',{'resource':'summary','period':'last week','metric':'expense'})
    state['responses']=[tool('fetch_finance',{'resource':'summary','period':{'mode':'wrong_calendar'}}),corrected,{'content':'รอบก่อนใช้ไป 80 บาทค่ะ'}]
    assert 'รอบก่อนใช้ไป 80 บาท' in send('รอบก่อนเงินหายไปเยอะไหมจ๊ะ')['content']
    assert len(state['calls'])==3


def test_exact_user_conversation_no_repeated_date_questions_or_wrong_month(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(12000,'อาหารอาทิตย์ก่อน','2026-10-10');post(8000,'กาแฟเมื่อวาน','2026-10-13');post(900000,'นอกช่วง','2026-09-10')
    state['responses']=[tool('fetch_finance',{'resource':'summary','period':{'mode':'broken_provider_enum'},'metric':'expense'}),{'content':'สัปดาห์ก่อนใช้ไป 120.00 บาทค่ะ'}]
    first=send('สัปดาห์ที่แล้วใช้ไปเท่าไหร่')['content']
    assert '120.00' in first and '2026-10-05' in first and len(state['calls'])==2
    for text,amount,start in [('สัปดาห์ที่แล้ว',120,'2026-10-05'),('เมื่อวานละ',80,'2026-10-13'),('วันที่ 13/10 ละ',80,'2026-10-13')]:
        state['responses']=[tool('fetch_finance',{'resource':'summary','period':{'mode':'broken_provider_enum'}}),{'content':f'ช่วงนี้ใช้ไป {amount} บาทค่ะ'}]
        answer=send(text)['content'];assert f'ใช้ไป {amount} บาท' in answer and start in answer
        assert 'อยากให้ดูบัญชีหรือช่วงไหน' not in answer and '9,000' not in answer
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


@pytest.mark.parametrize('missing',[False,True])
def test_date_only_followup_inherits_owned_adjacent_filters_without_model_flag(assistant,missing):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-13');post(92000,'อาหาร','2026-10-13');post(20000,'กาแฟ','2026-10-10')
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='last week',q='กาแฟ',account_id=wallet,metric='expense')),{'content':'กาแฟรอบก่อนใช้ไป 200 บาทค่ะ'}]
    send('ลองดูคาเฟ่ของกระเป๋าเงินสดรอบก่อนให้หน่อย')
    arguments={'resource':'summary'} if missing else dict(resource='summary',period={'mode':'unsupported_enum'})
    state['responses']=[tool('fetch_finance',arguments),{'content':'ส่วนเมื่อวานกาแฟใช้ไป 80 บาทค่ะ'}]
    answer=send('เมื่อวานละ');assert 'ใช้ไป 80 บาท' in answer['content'] and 'ค้นคำ กาแฟ' in answer['content']
    assert all(r['filters'].get('q')=='กาแฟ' for r in answer['references'])
    assert result(state['calls'][-1])['facts']['expense']=='80.00 บาท'


@pytest.mark.parametrize('change',['expired','intervening'])
def test_calendar_followup_does_not_inherit_stale_or_interrupted_filters(assistant,change):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,'กาแฟ','2026-10-13');post(92000,'อาหาร','2026-10-13')
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='last week',q='กาแฟ')),{'content':'รอบก่อนรายจ่าย 0 บาท ยังไม่พบรายการค่ะ'}]
    send('ลองดูคาเฟ่รอบก่อนให้หน่อยจ้า')
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        if change=='expired':room.capture_context={**room.capture_context,'verified_scope':{**room.capture_context['verified_scope'],'expires':0}}
        else:db.add(Message(workspace_id=w,conversation_id=cid,role='user',content='พักเรื่องนี้ก่อนนะ'))
    state['responses']=[tool('fetch_finance',dict(resource='summary',period='เมื่อวาน')),{'content':'เมื่อวานใช้ไป 1,000 บาทค่ะ'}]
    assert '1,000 บาท' in send('เมื่อวานละ')['content'] and 'ค้นคำ กาแฟ' not in result(state['calls'][-1])['scope']


def test_telegram_plain_spending_question_recovers_malformed_calendar_mode(channel):
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[tool('fetch_finance',{'resource':'summary','period':{'mode':'broken_provider_enum'},'metric':'expense'}),{'content':'อาทิตย์ก่อนใช้ไป 0 บาทค่ะ'}]
    capture(1,'สัปดาห์ที่แล้วใช้ไปเท่าไหร่');process();bot=Sender()
    assert asyncio.run(deliver_once(bot)) and '2026-10-05' in bot.sent[0][1] and '2026-10-11' in bot.sent[0][1]
    assert len(state['calls'])==2


@pytest.mark.parametrize('query',['กาแฟ','คาเฟ่'])
def test_lab_invalid_period_mode_is_recovered_from_synthetic_prompt_only(actor,monkeypatch,query):
    import httpx
    from app import ai
    from app.models import Account,Provider
    from test_ai_diagnostics import run_all,counts,start,result as report
    c,w,u=actor;b=f'/workspaces/{w}'
    monkeypatch.setattr('app.ai_diagnostics.login_limit',lambda _:None)
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='ollama',model='calendar-lab',task='chat',retries=0))
        db.scalar(select(Account).where(Account.workspace_id==w,Account.kind=='asset')).name='PRIVATE-real-ledger'
    replies=[tool('fetch_finance',dict(resource='summary',period={'mode':'model_invented_mode'},q=query,metric='expense')),{'content':'คาเฟ่ตัวอย่างใช้ไป 80 บาท จาก 1 รายการค่ะ'}];real=httpx.Client;calls=[]
    def handler(req):
        calls.append(json.loads(req.content));assert 'PRIVATE-real-ledger' not in req.content.decode() and w not in req.content.decode()
        return httpx.Response(200,json={'choices':[{'message':replies.pop(0)}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    before=counts(w);jid=start(c,b,'natural');run_all();out=report(c,b,jid)['diagnostics']['test']
    assert out['status']=='passed' and out['calls']==2 and out['synthetic_only'] and counts(w)==before


@pytest.mark.parametrize('query',['','ตัวอย่าง','อาหาร','missing'])
def test_lab_calendar_repair_does_not_turn_an_incorrect_subject_into_a_pass(query):
    from app.ai_sandbox import Sandbox,TestFailed
    from types import SimpleNamespace
    sandbox=Sandbox('natural');job=SimpleNamespace(user_id='a',workspace_id='w',payload={'conversation_id':'c'})
    with pytest.raises(TestFailed):sandbox.fetch(json.dumps(dict(resource='summary',period={'mode':'model_invented_mode'},q=query)),job)


def test_calendar_recovery_still_rejects_another_users_account(assistant):
    from test_direct_assistant_data import bob
    from app.models import Account
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;other,foreign=bob()
    with SessionLocal() as db:aid=db.scalar(select(Account.id).where(Account.workspace_id==foreign,Account.kind=='asset'))
    state['responses']=[tool('fetch_finance',dict(resource='summary',period={'mode':'wrong_mode'},account_id=aid))]*2
    answer=send('ช่วยดูเงินกระเป๋าที่ใช้เมื่อวานให้ทีจ้า')['content']
    assert '0.00 บาท' not in answer and len(state['calls'])==2
    feedback=json.dumps(result(state['calls'][1]));assert aid not in feedback and foreign not in feedback


@pytest.mark.parametrize('period',[None,{'mode':'custom'},{'mode':'month'},{'mode':'last_days'},{'mode':'range','start':'2020-01-01','end':'2026-10-14'}])
def test_missing_or_incomplete_model_period_uses_clear_user_date_not_default_month(period):
    value=parse_fetch(json.dumps(dict(resource='summary',period=period)),'สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert tuple(str(d) for d in bounds(value.period))==('2026-10-05','2026-10-11')


def test_a_valid_explicit_model_range_can_still_fetch_additional_context():
    value=parse_fetch(json.dumps(dict(resource='summary',period='last week')),'เมื่อวานฉันใช้เยอะไหม')
    assert tuple(str(d) for d in bounds(value.period))==('2026-10-05','2026-10-11')
