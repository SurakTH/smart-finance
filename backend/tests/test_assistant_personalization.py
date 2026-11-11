import json,uuid
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.db import SessionLocal
from app.models import Account,AssistantPreference,AIUsage,Job,Membership,Message,Provider,Conversation,now
from app.assistant_preferences import defaults,read
from app.ai_usage import reserve,policy,BudgetExceeded
from app.worker import run_once
from test_chat_actions import setup,say,count,CREATE
from test_secretary import transport,provider,reply,draft
from test_chat_dialogue import suggestion
from app.reporting import today


def pref(c,b,**patch):
    current=c.get(b+'/ai/preferences').json();current.update(patch)
    r=c.put(b+'/ai/preferences',json=current);assert r.status_code==200,r.text
    return r.json()

def test_memory_review_plain_confirm_and_no_money_cross_confirmation(actor):
    c,w,u,b,cid=setup(actor)
    say(c,b,cid,CREATE)
    r=say(c,b,cid,'จำไว้ว่า กาแฟลงหมวดเดินทาง')
    assert 'ทวนความจำ' in r and c.get(b+'/ai/preferences').json()['rules']==[]
    assert 'จำความชอบนี้แล้ว' in say(c,b,cid,'ยืนยัน') and count(w)==0
    assert 'ยังไม่มีรายการ' in say(c,b,cid,'ยืนยัน') and count(w)==0
    rules=c.get(b+'/ai/preferences').json()['rules'];assert rules[0]['keyword']=='กาแฟ'
    say(c,b,cid,'จำไว้ว่า ใช้บัญชีเงินสดเป็นหลัก');say(c,b,cid,'ยกเลิก')
    assert not c.get(b+'/ai/preferences').json()['expense_account_id']


def test_memory_settings_version_disable_clear_foreign_ids(actor):
    c,w,u,b,cid=setup(actor);accounts=c.get(b+'/accounts').json();aid=next(a['id'] for a in accounts if a['kind']=='asset')
    first=c.get(b+'/ai/preferences').json();saved=pref(c,b,expense_account_id=aid)
    assert c.put(b+'/ai/preferences',json=first).status_code==409
    assert c.put(b+'/ai/preferences',json={**saved,'expense_account_id':str(uuid.uuid4())}).status_code==422
    assert c.put(b+'/ai/preferences',json={**saved,'rules':[{'keyword':'\n','category_id':aid}]}).status_code==422
    pref(c,b,enabled=False);assert 'ความจำปิด' in say(c,b,cid,'จำไว้ว่า ใช้บัญชีเงินสดเป็นหลัก')
    erased=c.delete(b+'/ai/preferences').json();assert not erased['enabled'] and not erased['expense_account_id'] and not erased['rules']


def test_memory_tenant_and_personal_isolation(actor):
    c,w,u,b,cid=setup(actor);aid=next(a['id'] for a in c.get(b+'/accounts').json() if a['kind']=='asset');pref(c,b,expense_account_id=aid)
    other=c.post('/workspaces',json={'name':'other'}).json()['id']
    assert c.get(f'/workspaces/{other}/ai/preferences').json()['expense_account_id'] is None
    from app.bootstrap import create_user
    with SessionLocal.begin() as db:
        friend=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password');db.add(Membership(user_id=friend.id,workspace_id=w,role='member'))
        assert read(db,w,friend.id)['expense_account_id'] is None
    c.post('/auth/logout');assert c.post('/auth/login',json={'email':friend.email,'password':'secure-test-password'}).status_code==200
    assert c.get(b+'/ai/preferences').json()['rules']==[]
    assert c.get(b+'/ai/usage').status_code==403
    assert c.get(f'/workspaces/{other}/ai/preferences').status_code==404


def test_defaults_cross_room_and_explicit_override_ask_only_missing(actor):
    c,w,u,b,cid=setup(actor);accounts=c.get(b+'/accounts').json();cash=next(a['id'] for a in accounts if a['kind']=='asset');travel=next(a['id'] for a in accounts if a['name']=='เดินทาง')
    bank=c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'}).json()['id']
    pref(c,b,expense_account_id=bank,rules=[{'keyword':'กาแฟ','category_id':travel}])
    second=c.post(b+'/conversations',json={}).json()['id']
    review=say(c,b,second,'กาแฟ 80');assert 'ธนาคาร' in review and 'เดินทาง' in review and '฿80.00' in review and count(w)==0
    review=say(c,b,second,'กาแฟ 90 จากเงินสด หมวด อาหารและเครื่องดื่ม');assert 'เงินสด' in review and 'อาหารและเครื่องดื่ม' in review
    assert 'ยอดเท่าไหร่' in say(c,b,cid,'ซื้อกาแฟ')
    review=say(c,b,cid,'85');assert 'ธนาคาร' in review and 'เดินทาง' in review and '฿85.00' in review
    say(c,b,cid,'ยืนยัน');assert count(w)==1


def test_conflicting_rules_do_not_guess_category(actor):
    c,w,u,b,cid=setup(actor);rows=c.get(b+'/accounts').json();cats=[a for a in rows if a['kind']=='expense']
    pref(c,b,rules=[{'keyword':'กาแฟ','category_id':cats[0]['id']},{'keyword':'ร้าน','category_id':cats[1]['id']}])
    with SessionLocal() as db:assert defaults(db,w,u.id,'expense','กาแฟร้าน')[1] is None
    assert 'ความชอบที่ตั้งไว้ตรงหลายหมวด' in say(c,b,cid,'ซื้อกาแฟร้าน 80')


def test_ai_prompt_personal_defaults_fill_omissions_without_autopost(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w);s=suggestion(w);pref(c,b,expense_account_id=s['account_id'],rules=[{'keyword':'กาแฟ','category_id':s['category_id']}]);calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        value={**s,'description':'กาแฟ','account_id':None,'category_id':None}
        return draft(value)
    transport(monkeypatch,handler)
    say(c,b,cid,'ช่วยจดกาแฟ 200');assert run_once()
    assert not any(s['account_id'] in str(m['content']) for m in calls[0]['messages'] if m['role']=='system')
    assert 'กรุณาตรวจสอบ' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content'] and count(w)==0


def test_memory_expiry_new_turn_and_image_cannot_confirm_old_review(actor,monkeypatch):
    c,w,u,b,cid=setup(actor)
    say(c,b,cid,'จำไว้ว่า ใช้บัญชีเงินสดเป็นหลัก')
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);ctx=dict(room.capture_context);ctx['preference_review']={**ctx['preference_review'],'expires':now()-1};room.capture_context=ctx
    assert 'หมดอายุ' in say(c,b,cid,'ยืนยัน')
    say(c,b,cid,'จำไว้ว่า ใช้บัญชีเงินสดเป็นหลัก');say(c,b,cid,'กาแฟ 80');say(c,b,cid,'ยืนยัน')
    assert not c.get(b+'/ai/preferences').json()['expense_account_id'] and count(w)==1


def cloud(c,w,b,**values):
    c.put(b+'/ai/settings',json={'cloud_enabled':True})
    with SessionLocal.begin() as db:
        p=Provider(workspace_id=w,kind='compatible',endpoint='https://api.example.com/v1',model='test-model',task='chat',retries=0,**values);db.add(p);db.flush();return p.id

@pytest.mark.parametrize("output_budget",[1200,0])
def test_usage_actual_and_estimated_no_sensitive_data(actor,monkeypatch,output_budget):
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b,max_tokens=output_budget)
    monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}))
    assert c.put(b+'/ai/usage/policy',json={'prices':{pid:{'input':1000000,'output':2000000}}}).status_code==200
    responses=[httpx.Response(200,json={'choices':[{'message':{'content':'สวัสดี'}}],'usage':{'prompt_tokens':100,'completion_tokens':50}}),reply('ยินดีค่ะ')]
    transport(monkeypatch,lambda req:responses.pop(0))
    say(c,b,cid,'สวัสดี');assert run_once();say(c,b,cid,'คุยต่อ');assert run_once()
    report=c.get(b+'/ai/usage').json();assert report['requests']==2 and report['items'][0]['estimated_requests']==1
    with SessionLocal() as db:
        rows=db.scalars(select(AIUsage).where(AIUsage.workspace_id==w).order_by(AIUsage.created_at,AIUsage.id)).all();real=next(r for r in rows if not r.estimated)
        assert real.cost==200 and real.input_tokens==100 and real.output_tokens==50
        assert 'สวัสดี' not in str(report) and 'encrypted_key' not in str(report)


def test_budget_blocks_cloud_before_network_but_local_fallback_runs(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b,priority=0);provider(w,priority=1)
    c.put(b+'/ai/usage/policy',json={'monthly_limit':1,'prices':{pid:{'input':1000000,'output':1000000}}})
    monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}));calls=[]
    def handler(req):calls.append(json.loads(req.content)['model']);return reply('ใช้ local ค่ะ')
    transport(monkeypatch,handler);say(c,b,cid,'สวัสดี');assert run_once();assert calls==['vision']
    report=c.get(b+'/ai/usage').json();assert report['requests']==1 and report['cost']==0


@pytest.mark.parametrize('scenario',['missing_price','unknown_previous','exhausted'])
def test_budget_blocks_unpriced_or_exhausted_and_no_money(actor,monkeypatch,scenario):
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b);monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}));calls=[]
    transport(monkeypatch,lambda req:(calls.append(1) or reply('ok')))
    prices={} if scenario=='missing_price' else {pid:{'input':1000000,'output':1000000}}
    if scenario=='unknown_previous':
        with SessionLocal.begin() as db:db.add(AIUsage(workspace_id=w,provider_id=pid,model='past',task='chat',month=today().strftime('%Y-%m'),input_tokens=1,output_tokens=1,cost=None,status='success'))
    c.put(b+'/ai/usage/policy',json={'monthly_limit':1 if scenario=='exhausted' else 1000000,'prices':prices})
    say(c,b,cid,'คุยเล่น');assert run_once();assert calls==[] and count(w)==0
    assert 'วงเงิน AI' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']


def test_retries_and_provider_failure_are_counted(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);pid=provider(w)
    with SessionLocal.begin() as db:db.get(Provider,pid).retries=1
    transport(monkeypatch,lambda req:httpx.Response(503,json={'error':'secret provider body'}))
    say(c,b,cid,'สวัสดี');assert run_once()
    report=c.get(b+'/ai/usage').json();assert report['requests']==2 and report['items'][0]['failed_requests']==2
    assert 'secret provider body' not in str(report)


def test_stream_usage_and_failed_job_accounting_survive_savepoint(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w)
    sse='data: '+json.dumps({'choices':[{'delta':{'content':'สวัสดี'},'finish_reason':'stop'}]})+'\n\ndata: '+json.dumps({'choices':[],'usage':{'prompt_tokens':15,'completion_tokens':7}})+'\n\ndata: [DONE]\n\n'
    transport(monkeypatch,lambda req:httpx.Response(200,text=sse,headers={'content-type':'text/event-stream'}))
    original=ai.message_time
    monkeypatch.setattr(ai,'message_time',lambda *a:(_ for _ in ()).throw(ValueError('simulate failed history write')))
    say(c,b,cid,'สวัสดี');assert run_once()
    report=c.get(b+'/ai/usage').json();assert report['requests']==1 and report['items'][0]['input_tokens']==15 and report['items'][0]['estimated_requests']==0
    monkeypatch.setattr(ai,'message_time',original)


def test_evidence_from_real_report_and_history_pagination(actor):
    c,w,u,b,cid=setup(actor);say(c,b,cid,CREATE);say(c,b,cid,'ยืนยัน')
    say(c,b,cid,'2026-10-01 ถึง 2026-10-31 ใช้เท่าไหร่ มีอะไรบ้าง');assert run_once()
    message=c.get(b+f'/conversations/{cid}/messages').json()[-1]
    refs=message['references'];assert refs[0]['type']=='summary' and refs[0]['expense']==7525
    entry=next(r for r in refs if r['type']=='entry');assert entry['amount']==7525
    filters=refs[0]['filters'];report=c.get(b+'/transaction-report',params=filters).json();assert report['expense']==7525
    paged=c.get(b+f'/conversations/{cid}/messages/page').json()['items'][-1];assert paged['references']==refs


def test_reprice_unknown_and_changing_model_clears_route_price(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b)
    monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}))
    transport(monkeypatch,lambda req:reply('สวัสดี'))
    say(c,b,cid,'สวัสดี');assert run_once();assert c.get(b+'/ai/usage').json()['unpriced_requests']==1
    c.put(b+'/ai/usage/policy',json={'monthly_limit':1000000,'prices':{pid:{'input':1000000,'output':1000000}}})
    report=c.get(b+'/ai/usage').json();assert report['unpriced_requests']==0 and report['cost']>0
    row=next(p for p in c.get(b+'/providers').json() if p['id']==pid)
    row.pop('id');row.pop('has_key');row['model']='different-model'
    assert c.put(b+'/providers/'+pid,json=row).status_code==200
    assert pid not in c.get(b+'/ai/usage').json()['policy']['prices']
    assert c.get(b+'/ai/usage').json()['cost']==report['cost']


def test_budget_serializes_concurrent_reservations(actor,pg_only):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b)
    c.put(b+'/ai/usage/policy',json={'monthly_limit':100,'prices':{pid:{'input':1000000,'output':1000000}}})
    with SessionLocal.begin() as db:db.get(Provider,pid).max_tokens=64
    def attempt():
        with SessionLocal.begin() as db:
            try:reserve(db,SimpleNamespace(workspace_id=w,task='chat'),db.get(Provider,pid),{});return True
            except BudgetExceeded:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==[False,True]


def test_probe_counts_failures_and_respects_budget(actor,monkeypatch):
    from app import ai_settings
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b)
    monkeypatch.setattr(ai_settings,'login_limit',lambda _:None)
    monkeypatch.setattr(ai_settings,'target',lambda p:('https://api.example.com/v1',{},{}))
    transport(monkeypatch,lambda req:httpx.Response(503,json={'error':'private-response'}))
    assert c.post(b+'/providers/'+pid+'/test').status_code==422
    report=c.get(b+'/ai/usage').json();assert report['requests']==1 and report['items'][0]['failed_requests']==1
    c.put(b+'/ai/usage/policy',json={'monthly_limit':1,'prices':{pid:{'input':1000000,'output':1000000}}})
    assert c.post(b+'/providers/'+pid+'/test').status_code==422
    assert c.get(b+'/ai/usage').json()['requests']==1


def test_model_default_unknown_usage_is_not_free_or_repriced_as_zero(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b,max_tokens=0)
    monkeypatch.setattr(ai,'target',lambda p:('https://api.example.com/v1',{},{}))
    transport(monkeypatch,lambda req:reply('ยินดีค่ะ'))
    prices={pid:{'input':1000000,'output':2000000}}
    c.put(b+'/ai/usage/policy',json={'prices':prices})
    say(c,b,cid,'สวัสดี');assert run_once()
    assert c.get(b+'/ai/usage').json()['unpriced_requests']==1
    c.put(b+'/ai/usage/policy',json={'prices':prices})
    assert c.get(b+'/ai/usage').json()['unpriced_requests']==1
    with SessionLocal() as db:
        row=db.scalar(select(AIUsage).where(AIUsage.workspace_id==w))
        assert row.estimated and row.cost is None


def test_model_default_with_capped_cloud_budget_is_blocked_before_network(actor):
    c,w,u,b,cid=setup(actor);pid=cloud(c,w,b,max_tokens=0)
    c.put(b+'/ai/usage/policy',json={'monthly_limit':1000000,'prices':{pid:{'input':1,'output':1}}})
    with SessionLocal.begin() as db:
        with pytest.raises(BudgetExceeded):reserve(db,SimpleNamespace(workspace_id=w,task='chat'),db.get(Provider,pid),{})
