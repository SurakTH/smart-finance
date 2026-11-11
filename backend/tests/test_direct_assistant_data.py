"""Natural prose, autonomous scoped reads, and explicit cross-user denial."""
import asyncio,json,uuid
from types import SimpleNamespace
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import SessionLocal
from app.main import app
from app.models import Account,Conversation,Message,Membership,ChatAction,Job,AssistantPreference
from app.bootstrap import create_user
from app.assistant_data import read,natural,remember,authorize,Fetch
from app.ai_fence import Invalidated
from test_assistant_finance import assistant,tool,result
from test_telegram_assistant import channel,Sender

@pytest.fixture(autouse=True)
def calendar(monkeypatch):
    from app import semantic_assistant,reporting,finance_chat,request_interpreter,assistant_finance
    for module in (semantic_assistant,reporting,finance_chat,request_interpreter,assistant_finance):monkeypatch.setattr(module,'today',lambda:date(2026,10,14))

def fetch(resource='summary',**kw):return tool('fetch_finance',dict(resource=resource,**kw))
def prose(text):return dict(content=text)

def job_for(db,w,u,cid):
    message=Message(workspace_id=w,conversation_id=cid,role='user',content='ช่วยดูภาพรวมให้หน่อยจ้า')
    db.add(message);db.flush()
    return SimpleNamespace(workspace_id=w,user_id=u.id,payload=dict(conversation_id=cid,user_message_id=message.id,text=message.content))

def bob():
    with SessionLocal.begin() as db:
        user=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        wid=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
    return user,wid


def test_direct_fetch_then_ordinary_prose_no_planning_or_answer_schema(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');post(99900,'คนละช่วง','2026-10-01')
    state['responses']=[fetch(period='last_week',metric='expense'),prose('ดูให้แล้วค่ะ อาทิตย์ก่อนคุณจ่ายไป **80 บาท** จาก 1 รายการ')]
    text=send('อาทิตย์ก่อนกระเป๋าฉันโดนไปหนักแค่ไหนจ๊ะ')['content']
    assert 'จ่ายไป **80 บาท**' in text and '2026-10-05 ถึง 2026-10-11' in text
    assert len(state['calls'])==2 and result(state['calls'][1])['facts']['expense']=='80.00 บาท'
    assert '999.00' not in text and 'format' not in text
    assert 'fetch_finance' in {t['function']['name'] for t in state['calls'][0]['tools']}
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


def test_model_combines_several_needed_reads_and_keeps_evidence(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-10');c.put(b+f'/budgets/2026-10/{cat}',json={'amount':10000})
    state['responses']=[fetch('balances'),fetch(metric='expense'),fetch('budgets'),prose('ยอดสุทธิตอนนี้ -80 บาทค่ะ เดือนนี้จ่ายไป 80 บาท งบที่วางไว้ 100 บาท ยังเหลือ 20 บาท')]
    reply=send('ช่วยดูทั้งเงินที่เหลือกับงบให้หน่อย ฉันยังพอไหวมั้ย')
    assert 'ยังเหลือ 20 บาท' in reply['content'] and len(state['calls'])==4
    assert any(r['type']=='balance' for r in reply['references'])
    assert any(r['type']=='summary' for r in reply['references'])


def test_model_can_fetch_items_without_user_writing_dates_or_account_ids(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,'กาแฟ','2026-10-10')
    state['responses']=[fetch('transactions',q='กาแฟ'),prose('เจอค่ากาแฟ 80 บาทค่ะ')]
    reply=send('ลองไล่คาเฟ่ที่แวะช่วงนี้ให้ทีจ้า')
    assert 'เจอค่ากาแฟ 80 บาท' in reply['content']
    data=result(state['calls'][1]);assert data['total']==1 and data['items'][0]['id']
    assert data['scope'].startswith('2026-09-15 ถึง 2026-10-14')
    assert any(r['type']=='entry' for r in reply['references'])
    assert 'prepare_correction' in {t['function']['name'] for t in state['calls'][1]['tools']}


@pytest.mark.parametrize('invalid',['ยอดใช้ไป 980 บาทค่ะ','ยอดใช้ไป 1 บาทค่ะ','ยอดใช้ไป 999999 บาทค่ะ','บันทึกเรียบร้อยแล้วค่ะ 80 บาท','รวมหนึ่งล้านบาทค่ะ'])
def test_bad_figures_or_fake_write_receipts_are_repaired_internally(assistant,invalid):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    state['responses']=[fetch(metric='expense'),prose(invalid),prose('คุณใช้ไป 80 บาท จาก 1 รายการค่ะ')]
    reply=send('ดูเงินที่โดนไปตั้งแต่ต้นเดือนให้ที')['content']
    assert invalid not in reply and 'คุณใช้ไป 80 บาท' in reply and len(state['calls'])==3


def test_repeated_bad_prose_uses_complete_real_report(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    state['responses']=[fetch(metric='expense'),prose('999999 บาท'),prose('999999 บาท')]
    reply=send('ต้นเดือนถึงตอนนี้ฉันหมดไปเยอะไหม')['content']
    assert '80.00 บาท' in reply and '999999' not in reply and 'รูปแบบ' not in reply


def test_lookup_names_then_direct_read_then_normal_prose(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts'}]}),fetch(account_id=wallet,metric='expense'),prose('กระเป๋าเงินสดของคุณใช้ไป 80 บาทค่ะ')]
    assert 'กระเป๋าเงินสดของคุณใช้ไป 80 บาท' in send('กระเป๋าที่ใช้ประจำเดือนนี้โดนไปเท่าไหร่แล้วจ๊ะ')['content']
    assert len(state['calls'])==3


def test_lookup_goals_supports_ordinary_answer_without_answer_tool(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    assert c.post(b+'/goals',json={'name':'เที่ยวญี่ปุ่น','target':3000000,'idempotency_key':str(uuid.uuid4())}).status_code==200
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'goals'}]}),prose('คุณตั้งเป้าเที่ยวญี่ปุ่นไว้ 30,000 บาท ตอนนี้สะสมได้ 0 บาทค่ะ')]
    assert 'ตั้งเป้าเที่ยวญี่ปุ่นไว้ 30,000 บาท' in send('เรื่องเที่ยวที่แพลนไว้ไปถึงไหนแล้วจ๊ะ')['content']


def test_transaction_pagination_keeps_current_page_and_complete_totals(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    ids=[post(8000,'คาเฟ่'+chr(65+i),'2026-10-10') for i in range(12)]
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);job=job_for(db,w,u,cid)
        first=read(db,room,job,json.dumps({'resource':'transactions','period':'mtd','q':'คาเฟ่'}))
        second=read(db,room,job,json.dumps({'resource':'transactions','period':'mtd','q':'คาเฟ่','cursor':first['next_cursor']}))
        assert len(first['items'])==10 and first['has_more'] and len(second['items'])==2
        assert set(i['id'] for i in first['items']).isdisjoint(i['id'] for i in second['items'])
        assert second['total']==12 and second['facts']['expense']=='960.00 บาท'
        assert second['facts']['item_0_description']==second['items'][0]['description']
        assert 'item_2_description' not in second['facts']
        ctx=room.capture_context['finance_search'];assert {i['id'] for i in ctx['items']}=={i['id'] for i in second['items']}
        assert set(ids)=={r['filters']['entry_id'] for r in job._finance_refs if r['type']=='entry'}


@pytest.mark.parametrize('authority',['workspace_id','user_id','conversation_id','sql','confirm'])
def test_model_cannot_select_another_user_tenant_chat_or_sql(assistant,authority):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[fetch(**{authority:str(uuid.uuid4())})]*2
    reply=send('ช่วยดูเงินในกระเป๋าหน่อยจ้า')['content']
    assert '0.00 บาท' not in reply and len(state['calls'])==2


@pytest.mark.parametrize('by_id',[True,False])
def test_foreign_users_account_and_data_never_reach_model(assistant,by_id):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;other,foreign=bob()
    with SessionLocal.begin() as db:
        account=db.scalar(select(Account).where(Account.workspace_id==foreign,Account.kind=='asset'))
        account.name='BOB-SECRET-wallet';aid=account.id
    state['responses']=[fetch(**({'account_id':aid} if by_id else {'account':'BOB-SECRET-wallet'}))]*2
    reply=send('ช่วยสรุปกระเป๋าฉันรอบนี้ให้ที')['content']
    assert 'BOB-SECRET' not in reply and '0.00 บาท' not in reply
    feedback=json.dumps(result(state['calls'][1]));assert 'BOB-SECRET' not in feedback and aid not in feedback
    assert c.get(f'/workspaces/{foreign}/transactions').status_code in (403,404)


def test_same_account_names_two_users_return_only_their_own_ledger(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10');other,foreign=bob()
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        assert client.post('/auth/login',json={'email':other.email,'password':'secure-test-password'}).status_code==200
        accounts=client.get(f'/workspaces/{foreign}/accounts').json()
        aid=next(a['id'] for a in accounts if a['kind']=='asset');category=next(a['id'] for a in accounts if a['kind']=='expense')
        assert client.post(f'/workspaces/{foreign}/transactions',json=dict(kind='expense',description='BOB-SECRET-purchase',amount=9999900,account_id=aid,category_id=category,occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()))).status_code==200
        theirs=client.post(f'/workspaces/{foreign}/conversations',json={}).json()['id']
    with SessionLocal.begin() as db:
        a_job=job_for(db,w,u,cid);a=read(db,db.get(Conversation,cid),a_job,json.dumps({'resource':'summary','account':'เงินสด'}))
        b_job=job_for(db,foreign,other,theirs);bdata=read(db,db.get(Conversation,theirs),b_job,json.dumps({'resource':'summary','account':'เงินสด'}))
        assert a['facts']['expense']=='80.00 บาท' and bdata['facts']['expense']=='99,999.00 บาท'
        assert foreign not in json.dumps(a) and 'BOB-SECRET' not in json.dumps(a)
        b_job._direct_evidence=a_job._direct_evidence
        with pytest.raises(Invalidated):natural(b_job,'80 บาท')


def test_invited_shared_ledger_still_works_but_rooms_and_preferences_are_private(assistant):
    from app.assistant_lookup import read as lookup
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10');other,foreign=bob()
    with SessionLocal.begin() as db:db.add(Membership(user_id=other.id,workspace_id=w,role='member'))
    with SessionLocal.begin() as db:
        room=Conversation(workspace_id=w,user_id=other.id);db.add(room);db.flush()
        db.add(AssistantPreference(user_id=other.id,workspace_id=w,values=dict(enabled=True,rules=[{'keyword':'BOB-PRIVATE-rule','category_id':cat}])))
        own=db.get(Conversation,cid);job=job_for(db,w,u,cid)
        # Even an invited member cannot use another member's private room.
        with pytest.raises(Invalidated):authorize(db,job,room)
        forged=SimpleNamespace(workspace_id=w,user_id=u.id,payload={'conversation_id':room.id})
        with pytest.raises(Invalidated):authorize(db,forged)
        assert 'BOB-PRIVATE' not in json.dumps(lookup(db,own,json.dumps({'queries':[{'resource':'preferences'}]})))
        theirjob=job_for(db,w,other,room.id)
        assert read(db,room,theirjob,json.dumps({'resource':'summary'}))['facts']['expense']=='80.00 บาท'
    assert c.get(b+f'/conversations/{room.id}/messages').status_code==404


@pytest.mark.parametrize('reader',[fetch(),tool('understand_request',{'intent':'report','period':{'mode':'current_month'}}),tool('lookup_workspace',{'queries':[{'resource':'balances'}]})])
def test_membership_removed_before_tool_read_blocks_data_delivery(assistant,pg_only,reader):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;other,foreign=bob()
    with SessionLocal.begin() as db:db.add(Membership(user_id=other.id,workspace_id=w,role='owner'))
    def revoke(body):
        with SessionLocal.begin() as db:db.delete(db.get(Membership,(u.id,w)))
        return reader
    state['responses']=[revoke]
    from test_chat_actions import say
    from app.worker import run_once
    say(c,b,cid,'ช่วยดูภาพรวมตั้งแต่เริ่มรอบนี้ที')
    while run_once():pass
    assert c.get(b+f'/conversations/{cid}/messages').status_code in (403,404)
    assert len(state['calls'])==1
    with SessionLocal() as db:
        assert db.scalar(select(Job).where(Job.workspace_id==w)).error=='membership_revoked'
        assert not db.scalar(select(Message.id).where(Message.conversation_id==cid,Message.role=='assistant'))


def test_telegram_direct_fetch_can_answer_in_normal_prose(channel):
    from app.telegram_chat import deliver_once
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[fetch(metric='expense'),prose('ตรวจให้แล้วค่ะ รอบนี้ใช้ไป 0 บาท')]
    capture(1,'รอบนี้เงินไหลไปเยอะไหมจ๊ะ');process();bot=Sender()
    assert asyncio.run(deliver_once(bot)) and 'รอบนี้ใช้ไป 0 บาท' in bot.sent[0][1]


def test_internal_dates_accept_common_model_aliases_without_user_format():
    assert Fetch(resource='summary',period='this month').period.mode=='current_month'
    assert Fetch(resource='summary',period={'start':'2026-10-01','end':'2026-10-14'}).period.mode=='range'


def test_numbered_lists_and_thai_digits_are_plain_prose_not_special_slots():
    job=SimpleNamespace(user_id='a',workspace_id='w',payload={'conversation_id':'r'})
    remember(job,dict(facts={'expense':'80.00 บาท','count':'1 รายการ'},scope='เดือนนี้',fallback='80 บาท'))
    assert '๘๐ บาท' in natural(job,'1. ใช้ไป ๘๐ บาท\n2. ลองลดของไม่จำเป็นค่ะ')
    with pytest.raises(ValueError):natural(job,'1 บาท')
    with pytest.raises(ValueError):natural(job,'980.00 บาท')


def test_lab_direct_tool_and_plain_prose_use_only_synthetic_data(actor,monkeypatch):
    import httpx
    from app import ai
    from app.models import Provider
    from test_ai_diagnostics import run_all,counts,start,result as report_result
    c,w,u=actor;b=f'/workspaces/{w}'
    monkeypatch.setattr('app.ai_diagnostics.login_limit',lambda _:None)
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='ollama',model='direct-lab',task='chat',retries=0))
        db.scalar(select(Account).where(Account.workspace_id==w,Account.kind=='asset')).name='PRIVATE-real-account'
    replies=[fetch(q='กาแฟ',metric='expense'),prose('คาเฟ่ตัวอย่างใช้ไป 80 บาท จาก 1 รายการค่ะ')]
    real=httpx.Client;calls=[]
    def handler(req):
        calls.append(json.loads(req.content))
        assert 'PRIVATE-real-account' not in req.content.decode() and w not in req.content.decode()
        return httpx.Response(200,json={'choices':[{'message':replies.pop(0)}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    before=counts(w);jid=start(c,b,'natural');run_all();report=report_result(c,b,jid)['diagnostics']['test']
    assert report['status']=='passed' and report['synthetic_only'] and report['calls']==2
    assert counts(w)==before and len(calls)==2


def test_direct_transfer_reports_do_not_present_movement_as_expense(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    other=c.post(b+'/accounts',json={'name':'ออมทรัพย์','kind':'asset'}).json()['id']
    assert c.post(b+'/transactions',json=dict(kind='transfer',description='ย้ายเงิน',amount=8000,account_id=wallet,other_account_id=other,occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()))).status_code==200
    state['responses']=[fetch(metric='transfer'),prose('มีการโอนย้ายระหว่างบัญชี 80 บาท จาก 1 รายการค่ะ ไม่ใช่รายจ่ายเพิ่ม')]
    reply=send('รอบนี้ฉันย้ายเงินในกระเป๋าไปบ้างยังจ๊ะ')['content']
    data=result(state['calls'][1]);assert data['facts']['amount']=='80.00 บาท' and 'expense' not in data['facts']
    assert 'โอนย้ายระหว่างบัญชี 80 บาท' in reply


@pytest.mark.parametrize('direct',[True,False])
def test_read_then_phantom_review_is_repaired_to_real_draft_and_manual_confirm(assistant,direct):
    from test_chat_actions import say
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    initial=fetch('balances') if direct else tool('lookup_workspace',{'queries':[{'resource':'accounts'},{'resource':'categories'}]})
    state['responses']=[initial,prose('รายการรอยืนยัน กาแฟ 80 บาท พิมพ์ ยืนยัน'),tool('prepare_transaction',dict(intent='create',kind='expense',amount=8000,description='กาแฟ',account_id=wallet,category_id=cat,occurred_on='2026-10-14'))]
    review=send('เมื่อเช้าซดกาแฟแปดสิบ ช่วยจัดให้ทีจ้า')
    assert 'กรุณาตรวจสอบ' in review['content'] and c.get(b+'/transactions').json()==[]
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน')
    assert len(c.get(b+'/transactions').json())==1


def test_scoped_explicit_id_survives_duplicate_account_names(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    with SessionLocal.begin() as db:
        duplicate=Account(workspace_id=w,name='เงินสด',kind='asset');db.add(duplicate);db.flush();aid=duplicate.id
    assert c.post(b+'/transactions',json=dict(kind='expense',description='กระเป๋าอีกใบ',amount=9000,account_id=aid,category_id=cat,occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()))).status_code==200
    state['responses']=[fetch(account_id=wallet,metric='expense'),prose('กระเป๋านี้ใช้ไป 80 บาทค่ะ')]
    assert 'กระเป๋านี้ใช้ไป 80 บาท' in send('ดูเฉพาะกระเป๋าที่ฉันเลือกให้หน่อยจ้า')['content']
    assert result(state['calls'][1])['facts']['expense']=='80.00 บาท'


@pytest.mark.parametrize('label,claim',[
    ('999999 บาท','ใช้ไป 999999 บาทค่ะ'),('1','เหลือ 1 บาทค่ะ'),
    ('คาเฟ่ 1234','คาเฟ่ 1234 บาทค่ะ'),('ราคา 900 บาท','ใช้ไป 900 บาทค่ะ'),
])
def test_untrusted_names_and_descriptions_cannot_supply_amount_evidence(label,claim):
    job=SimpleNamespace(user_id='a',workspace_id='w',payload={'conversation_id':'r'})
    remember(job,dict(facts={'expense':'80.00 บาท','item_0_description':label,'account_0_name':label},scope='เดือนนี้',fallback='80 บาท'))
    with pytest.raises(ValueError):natural(job,claim)


def test_money_cannot_be_presented_as_an_unverified_daily_or_per_item_average():
    job=SimpleNamespace(user_id='a',workspace_id='w',payload={'conversation_id':'r'})
    remember(job,dict(facts={'expense':'80.00 บาท','count':'1 รายการ'},scope='เดือนนี้',fallback='80 บาท'))
    with pytest.raises(ValueError):natural(job,'เฉลี่ย 80.00 บาท/วันค่ะ')
    with pytest.raises(ValueError):natural(job,'เฉลี่ย 80.00 บาท/รายการค่ะ')
    assert '80.00 บาท' in natural(job,'ใช้ไป 80.00 บาทค่ะ')


def test_suggestions_and_item_figures_cannot_replace_latest_requested_total():
    job=SimpleNamespace(user_id='a',workspace_id='w',payload={'conversation_id':'r'})
    remember(job,dict(facts={'expense':'80.00 บาท'},scope='สัปดาห์ก่อน',fallback='80 บาท'))
    remember(job,dict(facts={'expense':'412.00 บาท','count':'4 รายการ','item_0_amount':'248.00 บาท'},scope='เมื่อวาน',fallback='412 บาท'))
    for text in ('อยากให้ดูเพิ่มอีกไหมคะ', 'เมื่อวานมี 4 รายการค่ะ', 'รายการแรก 248 บาทค่ะ', 'สัปดาห์ก่อนใช้ 80 บาทค่ะ'):
        with pytest.raises(ValueError,match='missing requested total'):natural(job,text)
    assert '412 บาท' in natural(job,'เมื่อวานใช้ไป **412 บาท** ค่ะ')


def test_balance_answer_must_include_net_instead_of_only_zero_debt():
    job=SimpleNamespace(user_id='a',workspace_id='w',payload={'conversation_id':'r'})
    remember(job,dict(facts={'net':'800.00 บาท','assets':'900.00 บาท','liabilities':'100.00 บาท'},scope='ยอดปัจจุบัน',fallback='800 บาท'))
    with pytest.raises(ValueError,match='missing requested total'):natural(job,'มีสินทรัพย์ 900 บาท หนี้ 100 บาทค่ะ')
    assert '฿800' in natural(job,'ยอดสุทธิ **฿800** ค่ะ')


def test_same_period_alias_keeps_scoped_dates_for_followup_breakdown(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'เมื่อวาน','2026-10-13');post(190000,'วันอื่น','2026-10-01')
    state['responses']=[fetch(period='เมื่อวาน',metric='expense'),tool('render_finance',{})]
    assert '80.00 บาท' in send('เมื่อวานใช้ไปเท่าไหร่')['content']
    state['responses']=[fetch('analytics',period='same as previous',operation='ranking',group_by='account'),tool('render_finance',{})]
    text=send('แยกตามบัญชีให้หน่อย')['content']
    assert '2026-10-13 ถึง 2026-10-13' in text and 'เงินสด' in text
    assert '80.00 บาท' in text and '1,900.00' not in text


def test_same_period_without_previous_read_does_not_default_to_month(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(8000,'กาแฟ','2026-10-13')
    state['responses']=[fetch(period='same period',metric='expense')]*2
    reply=send('ดูช่วงเดิมให้หน่อย')
    assert '80.00' not in reply['content'] and not reply['references']
