import json
import uuid
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Account,Conversation,Entry,Membership,Goal,RecurringRule,GoalMovement
from app.assistant_lookup import read as lookup
from app.assistant_finance import read,analysis_snapshot
from app.reporting import today,monthly_report
from app.budgets import budget_report
from test_assistant_finance import assistant,tool,result

def look(db,room,**query):return lookup(db,room,json.dumps({'queries':[query]}))

def test_initial_context_does_not_dump_workspace_or_compute_dashboard(assistant,monkeypatch):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        db.add_all(Account(workspace_id=w,name='SECRET-account-'+str(i),kind='asset') for i in range(120))
    def fail(*a,**kw):raise AssertionError('Eager financial report')
    monkeypatch.setattr('app.ai.account_balances',fail)
    monkeypatch.setattr('app.finance_chat.answer_report',fail)
    state['responses']=[{'content':'สวัสดีค่ะ'}]
    send('สวัสดี ขอคุยด้วยหน่อย')
    body=state['calls'][0];system=' '.join(m['content'] for m in body['messages'] if m['role']=='system')
    assert 'SECRET-account' not in system and wallet not in system and cat not in system
    assert 'lookup_workspace' in {t['function']['name'] for t in body['tools']}
    assert len(system)<7000

def test_lookup_then_prepare_still_needs_human_confirmation(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def draft(body):
        rows=result(body)['results'];assert rows[0]['items'][0]['id']==wallet
        category=next(x for x in rows[1]['items'] if x['id']==cat)
        return tool('prepare_transaction',dict(intent='create',description='กาแฟ',kind='expense',amount=8000,account_id=wallet,category_id=category['id'],occurred_on=today().isoformat()))
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts'},{'resource':'categories','kind':'expense'}]}),draft]
    r=send('ช่วยจดกาแฟ 80 บาทให้หน่อย')
    assert 'กรุณาตรวจสอบ' in r['content'] and c.get(b+'/transaction-report').json()['expense']==0
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert c.get(b+'/transaction-report').json()['expense']==8000

def test_lookup_pages_and_literal_search(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        db.add_all(Account(workspace_id=w,name='page-'+str(i),kind='asset') for i in range(47));db.flush()
        room=db.get(Conversation,cid);ids=[];cursor=None
        while True:
            query={'resource':'accounts','q':'page-','limit':20}
            if cursor:query['cursor']=cursor
            page=look(db,room,**query)['results'][0];ids.extend(x['id'] for x in page['items']);cursor=page['next_cursor']
            assert len(page['items'])<=20
            if not page['has_more']:break
        assert len(ids)==len(set(ids))==47
        assert look(db,room,resource='accounts',q='%')['results'][0]['items']==[]
        assert look(db,room,resource='accounts',q='different',cursor=ids[0])['error']=='invalid_lookup'

@pytest.mark.parametrize('query',[
    {'resource':'accounts','limit':True},{'resource':'accounts','limit':21},
    {'resource':'accounts','workspace_id':str(uuid.uuid4())},
    {'resource':'accounts','sql':'SELECT password FROM users'},
    {'resource':'accounts','kind':'expense'}, {'resource':'budgets','month':'2026-99'},
    {'resource':'preferences','cursor':str(uuid.uuid4())},
])
def test_lookup_strict_validation(assistant,query):
    c,w,u,b,cid,*_=assistant
    with SessionLocal() as db:assert look(db,db.get(Conversation,cid),**query)['error']=='invalid_lookup'

def test_lookup_tenant_user_isolation_and_real_balances(assistant):
    from app.bootstrap import create_user
    from app.assistant_preferences import save,Preferences
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000)
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        foreign_w=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
        foreign=db.scalar(select(Account.id).where(Account.workspace_id==foreign_w,Account.kind=='asset'))
        db.add(Membership(workspace_id=w,user_id=other.id,role='member'));db.flush()
        save(db,w,other.id,Preferences(expense_account_id=wallet))
        room=db.get(Conversation,cid)
        assert look(db,room,resource='accounts',cursor=foreign)['error']=='invalid_lookup'
        rows=look(db,room,resource='balances')['results'][0]['items'];assert next(x for x in rows if x['id']==wallet)['balance_satang']==-8000
        assert look(db,room,resource='preferences')['results'][0]['expense_account_id'] is None
        assert not any(x['id']==foreign for x in rows)

def test_transaction_keyset_pages_ties_and_bad_anchor(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    ids=[post(description='page'+str(i)) for i in range(23)]
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);seen=[];cursor=None
        while True:
            query={'operation':'search_transactions','q':'page'}
            if cursor:query['cursor']=cursor
            data=read(db,room,json.dumps(query),'turn');seen.extend(x['id'] for x in data['items']);cursor=data['next_cursor']
            if not data['has_more']:break
        assert len(seen)==len(set(seen))==23 and set(seen)==set(ids)
        assert read(db,room,json.dumps(dict(operation='search_transactions',q='absent',cursor=ids[0])),'turn')['error']=='invalid_query'

def test_month_report_complete_totals_bounded_groups_and_freshness(assistant,monkeypatch):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;month=today().strftime('%Y-%m')
    post(500,on=(today().replace(day=1)-timedelta(days=1)).isoformat())
    for i in range(24):
        aid=c.post(b+'/accounts',json={'name':'category'+str(i),'kind':'expense'}).json()['id']
        assert c.post(b+'/transactions',json=dict(kind='expense',description='group',amount=1000+i,account_id=wallet,category_id=aid,occurred_on=today().isoformat(),idempotency_key=str(uuid.uuid4()))).status_code==200
        assert c.put(b+f'/budgets/{month}/{aid}',json={'amount':1000}).status_code==200
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);expected=monthly_report(db,w,month);budget=budget_report(db,w,month)
        monkeypatch.setattr('app.reporting.monthly_report',lambda *a:pytest.fail('dashboard read'))
        data=read(db,room,json.dumps(dict(operation='monthly_analysis',month=month)),'turn')
        assert data['expense']==expected['expense']==sum(1000+i for i in range(24))
        assert data['previous']['expense']==500 and data['category_count']==24
        assert len(data['categories'])==20 and len(data['budgets']['items'])==20
        assert data['budgets']['item_count']==24
        for key in ('planned','spent','remaining','over_count','unbudgeted_expense'):assert data['budgets'][key]==budget[key]
        before=analysis_snapshot(db,w,month)['fingerprint']
        # Modify a plan outside the displayed20: freshness must include it too.
        from app.models import Budget
        plans=db.scalars(select(Budget).where(Budget.workspace_id==w,Budget.month==month).order_by(Budget.category_id)).all()
        visible={item['category_id'] for item in data['budgets']['items']}
        next(p for p in plans if p.category_id not in visible).amount+=17;db.flush()
        assert analysis_snapshot(db,w,month)['fingerprint']!=before

def test_repeated_tool_read_cached_but_provider_rounds_remain_bounded(assistant,monkeypatch):
    import app.assistant_lookup as module
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;calls=[];original=module.read
    def track(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(module,'read',track)
    state['responses']=[tool('lookup_workspace',{'queries':[{'resource':'accounts'}]})]*3
    r=send('ช่วยดูบัญชีหน่อย')
    assert len(calls)==1 and len(state['calls'])==2 and 'เงินสด' in r['content']


def test_all_plan_lookups_and_followup_paging_context(assistant):
    from app.assistant_lookup import begin_turn as lookup_context
    from app.assistant_finance import begin_turn as finance_context
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;month=today().strftime('%Y-%m')
    assert c.put(b+f'/budgets/{month}/{cat}',json={'amount':20000}).status_code==200
    goal=c.post(b+'/goals',json=dict(name='vacation',target=100000,idempotency_key=str(uuid.uuid4())));assert goal.status_code==200
    rule=c.post(b+'/recurring',json=dict(description='internet',kind='expense',amount=50000,account_id=wallet,category_id=cat,frequency='monthly',start_on=today().isoformat(),idempotency_key=str(uuid.uuid4())));assert rule.status_code==200
    for i in range(12):post(description='page'+str(i))
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid)
        assert look(db,room,resource='goals',q='vacation')['results'][0]['items'][0]['saved']==0
        category_name=db.get(Account,cat).name
        plans=look(db,room,resource='budgets',q=category_name)['results'][0]
        assert plans['items'][0]['amount']==20000
        assert look(db,room,resource='recurring')['results'][0]['items'][0]['id']==rule.json()['id']
        data=read(db,room,json.dumps(dict(operation='search_transactions',q='page')),'turn')
        assert data['next_cursor'] in finance_context(room,'ดูต่อ','next')
        assert finance_context(room,'วันนี้เหนื่อย','next') is None
        db.add_all(Account(workspace_id=w,name='page-'+str(i),kind='asset') for i in range(12));db.flush()
        page=look(db,room,resource='accounts',q='page-')['results'][0]
        assert page['next_cursor'] in lookup_context(room,'ดูต่อ')
        assert lookup_context(room,'วันนี้เหนื่อย') is None
        context=dict(room.capture_context);context['lookup_pages'][0]['expires']=1;room.capture_context=context
        assert lookup_context(room,'ดูต่อ') is None


def test_receipt_context_skips_unrelated_chat_and_expired_images():
    from types import SimpleNamespace as Obj
    from app.assistant_images import selected_images
    from app.models import now
    image=Obj(role='user',attachment_id='receipt',created_at=now()*1000,content='ช่วยจดสลิป')
    previous=Obj(role='assistant',attachment_id=None,content='ใช้บัญชีไหนคะ?')
    job=Obj(payload={'text':'เงินสดจ้า'})
    assert selected_images([previous,image],job)==['receipt']
    job.payload['text']='สวัสดีค่ะ';assert selected_images([previous,image],job)==[]
    job.payload['text']='วันนี้เหนื่อยมาก';assert selected_images([previous,image],job)==[]
    job.payload['text']='เดือนนี้ใช้ไปเท่าไหร่';assert selected_images([previous,image],job)==[]
    job.payload['text']='รูปเมื่อกี้คืออะไร';assert selected_images([previous,image],job)==['receipt']
    image.created_at-=901000;assert selected_images([previous,image],job)==[]
