import json
import uuid
from app.db import SessionLocal
from app.models import Account,Conversation,ChatAction
from sqlalchemy import select
from app.assistant_lookup import read
from app.reporting import today
from test_assistant_finance import assistant,tool,result


def opening(c,b,aid,amount):
    r=c.post(b+'/transactions',json=dict(kind='opening',description='ยอดตั้งต้น',amount=amount,account_id=aid,occurred_on=today().isoformat(),idempotency_key=str(uuid.uuid4())))
    assert r.status_code==200


def test_full_balance_summary_not_page_sum_and_filtered_scope(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    opening(c,b,wallet,100000)
    with SessionLocal.begin() as db:
        bank=Account(workspace_id=w,name='ธนาคาร',kind='asset');card=Account(workspace_id=w,name='บัตรเครดิต',kind='liability')
        db.add_all([bank,card]);db.flush();bankid,cardid=bank.id,card.id
        db.add_all(Account(workspace_id=w,name='กระเป๋า'+str(i),kind='asset') for i in range(30))
    opening(c,b,bankid,200000);opening(c,b,cardid,50000);post(10000)
    with SessionLocal() as db:
        room=db.get(Conversation,cid)
        def lookup(**kw):return read(db,room,json.dumps({'queries':[{'resource':'balances',**kw}]}))['results'][0]
        first=lookup(limit=1);assert len(first['items'])==1 and first['has_more']
        total=first['summary'];assert sum(x['balance_satang'] for x in first['items'])!=total['assets_satang'];assert total['assets_satang']==290000 and total['liabilities_satang']==50000 and total['net_satang']==240000
        assert total['account_count']==33 and total['complete']
        assert lookup(limit=1,cursor=first['next_cursor'])['summary']==total
        assert lookup(q='ธนาคาร')['summary']['assets_satang']==200000
        assert lookup(q='ไม่พบ')['summary']['account_count']==0
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'balances','limit':1}]})]*2
    reply=send('ตอนนี้ฉันมีเงินเท่าไร?')['content']
    assert '฿2,900.00' in reply and '฿500.00' in reply and '฿2,400.00' in reply
    assert len(state['calls'])==2 and not state['responses']
    assert c.get(b+'/transaction-report').json()['total']==4


def test_current_money_one_lookup_then_natural_answer(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;opening(c,b,wallet,123456)
    def answer(body):
        total=result(body)['results'][0]['summary'];assert total['assets_satang']==123456
        return {'content':'ตอนนี้เงินในบัญชีรวม 1,234.56 บาทค่ะ ไม่มีหนี้ในบัญชีที่บันทึกไว้'}
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'balances'}]}),answer]
    assert '1,234.56' in send('ตอนนี้ฉันมีเงินเท่าไร?')['content'] and len(state['calls'])==2


def test_duplicate_reads_final_text_call_uses_results_without_more_tools(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def final(body):
        assert 'tools' not in body and 'tool_choice' not in body
        outputs=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
        assert outputs[0]['results'][0]['items']
        return {'content':'มีบัญชีเงินสดอยู่ค่ะ'}
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts'}]})]*2+[final]
    assert 'เงินสด' in send('มีบัญชีอะไรบ้าง')['content'] and len(state['calls'])==2


def test_unique_read_limit_final_call_cannot_create_action(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts','q':q}]}) for q in ('a','b','c','d','e','f','g')]+[tool('prepare_transaction',dict(intent='create',kind='expense',amount=8000,description='กาแฟ',account_id=wallet,category_id=cat,occurred_on=today().isoformat()))]
    answer=send('มีบัญชีอะไรบ้าง')['content']
    assert 'ไม่พบรายการ' in answer and len(state['calls'])==7
    assert c.get(b+'/transaction-report').json()['total']==0
    with SessionLocal() as db:assert db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid)) is None


def test_balance_totals_include_transfers_card_payment_income_and_credit_expense(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    bank=c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'}).json()['id']
    card=c.post(b+'/accounts',json={'name':'บัตรเครดิต','kind':'liability'}).json()['id']
    opening(c,b,wallet,100000);opening(c,b,bank,200000);opening(c,b,card,50000)
    def entry(**kw):
        response=c.post(b+'/transactions',json=dict(description='ทดสอบยอด',occurred_on=today().isoformat(),idempotency_key=str(uuid.uuid4()),**kw))
        assert response.status_code==200
    entry(kind='transfer',amount=10000,account_id=wallet,other_account_id=bank)
    entry(kind='card_payment',amount=20000,account_id=bank,other_account_id=card)
    income=next(a['id'] for a in c.get(b+'/accounts').json() if a['kind']=='income')
    entry(kind='income',amount=40000,account_id=wallet,category_id=income)
    entry(kind='expense',amount=5000,account_id=card,category_id=cat)
    with SessionLocal() as db:
        total=read(db,db.get(Conversation,cid),json.dumps({'queries':[{'resource':'balances'}]}))['results'][0]['summary']
        assert (total['assets_satang'],total['liabilities_satang'],total['net_satang'])==(320000,35000,285000)


def test_balance_summary_is_scoped_and_continue_requeries_current_workspace(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;opening(c,b,wallet,10000)
    other=c.post('/workspaces',json={'name':'อีกพื้นที่'}).json()['id'];other_b='/workspaces/'+other
    foreign=next(a['id'] for a in c.get(other_b+'/accounts').json() if a['kind']=='asset')
    opening(c,other_b,foreign,9999900)
    read_tool=tool('lookup_workspace',{'queries':[{'resource':'balances'}]})
    state['responses']=[read_tool]*2
    first=send('ตอนนี้ฉันมีเงินเท่าไร?')['content'];assert '฿100.00' in first and '99,999' not in first
    post(2500);state['responses']=[read_tool]*2
    followup=send('ต่อ')['content'];assert '75.00' in followup and '99,999' not in followup
    assert len(state['calls'])==4
