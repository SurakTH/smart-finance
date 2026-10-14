"""Protocol-level regression: a working API rejects broken tool continuations."""
import json
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from app.assistant_response import completion,read_stream
from app.db import SessionLocal
from app.models import Account,Conversation,Job,Message,ChatAction,Workspace,Membership
from app.ai_errors import ensure_response,AIRequestError,metadata
from app.ai_diagnostics import record
from test_assistant_finance import assistant,tool,result
from test_direct_assistant_data import calendar,fetch,prose,job_for
from test_ai_diagnostics import lab
from test_secretary import transport

PRIVATE='PRIVATE-provider-continuation-do-not-store'


def streamed(message):
    # Deliberately separate reasoning, content and tool fragments as real SSE does.
    deltas=[]
    for key in ('reasoning_content','reasoning','reasoning_details','content'):
        if key in message and message[key] is not None:
            value=message[key]
            if isinstance(value,str):
                deltas.extend([{key:value[:len(value)//2]},{key:value[len(value)//2:]}])
            else:deltas.append({key:value})
    for call in message.get('tool_calls',[]):
        deltas.append({'tool_calls':[{'index':0,**call}]})
    frames=[{'choices':[{'delta':d}]} for d in deltas]
    frames.append({'choices':[{'delta':{},'finish_reason':'tool_calls' if message.get('tool_calls') else 'stop'}]})
    return httpx.Response(200,headers={'content-type':'text/event-stream'},text=''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n')


@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('private',[
    {'reasoning_content':PRIVATE}, {'reasoning':PRIVATE},
    {'reasoning_details':[{'type':'reasoning.encrypted','data':PRIVATE,'index':0}]},
])
def test_strict_thinking_api_accepts_complete_tool_roundtrip(assistant,stream,private):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    first={**fetch(period='สัปดาห์ที่แล้ว',metric='expense'),**private,'content':'กำลังตรวจข้อมูล'}
    def strict_server(body):
        assert body['parallel_tool_calls'] is False
        outgoing=body['messages'][-2]
        # This is an API contract, not an always-200 model stub.
        if any(outgoing.get(key)!=value for key,value in private.items()):
            return httpx.Response(400,json={'error':{'message':'reasoning_content is required in assistant tool call message','param':'messages.2.reasoning_content'}})
        assert outgoing['content']=='กำลังตรวจข้อมูล'
        assert outgoing['tool_calls']==first['tool_calls']
        assert body['messages'][-1]['tool_call_id']==first['tool_calls'][0]['id']
        return prose('สัปดาห์ที่แล้วคุณใช้ไป **80 บาท** ค่ะ')
    state['responses']=[streamed(first) if stream else first,strict_server]
    reply=send('สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert '**80 บาท**' in reply['content'] and 'API' not in reply['content']
    assert len(state['calls'])==2
    assert result(state['calls'][1])['facts']['expense']=='80.00 บาท'
    # No private protocol data enters durable chat, room context or diagnostics.
    assert PRIVATE not in json.dumps(c.get(b+f'/conversations/{cid}/messages').json())
    assert PRIVATE not in json.dumps(c.get(b+'/ai/diagnostics').json())
    with SessionLocal() as db:
        assert PRIVATE not in json.dumps(db.get(Conversation,cid).capture_context)
        assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))
    state['responses']=[prose('ยินดีค่ะ')];send('ขอบคุณจ้า')
    assert PRIVATE not in json.dumps(state['calls'][-1])


def test_followup_suggestion_without_amount_is_repaired_before_display(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(41200,on='2026-10-13')
    state['responses']=[fetch(period='เมื่อวาน',metric='expense'),prose('อยากให้ดูเพิ่มอีกไหมคะ'),prose('เมื่อวานใช้ไป **412 บาท** ค่ะ')]
    reply=send('เมื่อวานละ')
    assert '**412 บาท**' in reply['content']
    assert 'อยากให้ดูเพิ่ม' not in reply['content']
    assert len(state['calls'])==3
    assert 'บอกผลที่ผู้ใช้ถามพร้อมยอดรวม' in state['calls'][-1]['messages'][0]['content']


@pytest.mark.parametrize('stream',[False,True])
def test_invalid_tool_repair_keeps_private_continuation_for_every_round(assistant,stream):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    first={**fetch(resource='not_a_resource'),'reasoning_content':PRIVATE}
    second={**fetch(period='สัปดาห์ที่แล้ว',metric='expense'),'reasoning_content':PRIVATE+'-second'}
    def repaired(body):
        assert body['messages'][-2]['reasoning_content']==PRIVATE
        assert result(body)['error']=='invalid_arguments'
        return streamed(second) if stream else second
    def final(body):
        thinking=[m.get('reasoning_content') for m in body['messages'] if m.get('tool_calls')]
        assert thinking==[PRIVATE,PRIVATE+'-second']
        return prose('ใช้ไป 80 บาทค่ะ')
    state['responses']=[streamed(first) if stream else first,repaired,final]
    assert 'ใช้ไป 80 บาท' in send('สัปดาห์ที่แล้วใช้ไปเท่าไหร่')['content']
    assert len(state['calls'])==3


@pytest.mark.parametrize('question,period,on',[('สัปดาห์ที่แล้วใช้ไปเท่าไหร่','สัปดาห์ที่แล้ว','2026-10-10'),('เมื่อวานใช้ไปเท่าไหร่','เมื่อวาน','2026-10-13')])
@pytest.mark.parametrize('status',[400,422,500])
def test_failed_synthesis_still_answers_complete_ledger_read(assistant,question,period,on,status):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on=on)
    state['responses']=[fetch(period=period,metric='expense'),httpx.Response(status,json={'error':{'message':'PRIVATE-upstream-error','param':'messages.4.tool_calls'}})]
    reply=send(question)
    assert '80.00 บาท' in reply['content'] and 'API' not in reply['content'] and 'PRIVATE' not in reply['content']
    assert len(state['calls'])==2 and reply['references']
    diagnostics=c.get(b+'/ai/diagnostics').json()['items'][0]['diagnostics']['events']
    failed=[e for e in diagnostics if e['event']=='request' and e['status']=='failed']
    assert failed[0]['http_status']==status and failed[0]['field']=='tool_calls'
    assert any(e['event']=='synthesis' and e['status']=='limited' for e in diagnostics)
    assert 'PRIVATE' not in json.dumps(diagnostics)


def test_failure_before_any_read_never_uses_old_answers_or_fabricates_money(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[httpx.Response(400,json={'error':'PRIVATE-invalid request'})]
    reply=send('สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert 'API' in reply['content'] and not reply.get('references')
    assert '0.00' not in reply['content'] and 'PRIVATE' not in reply['content']


def test_fallback_rechecks_workspace_epoch_after_read(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    def changed(body):
        with SessionLocal.begin() as db:db.get(Workspace,w).ai_epoch+=1
        return httpx.Response(400,json={'error':'invalid request'})
    state['responses']=[fetch(period='สัปดาห์ที่แล้ว',metric='expense'),changed]
    reply=send('สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert '80.00' not in reply['content'] and not reply.get('references')


def test_balance_facts_never_include_income_expense_or_equity_categories(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    with SessionLocal.begin() as db:
        accounts=list(db.scalars(select(Account).where(Account.workspace_id==w)))
        for a in accounts:
            if a.kind not in ('asset','liability'):a.name='CATEGORY-PRIVATE-'+a.kind
        room=db.get(Conversation,cid);job=job_for(db,w,u,cid)
        from app.assistant_data import read
        data=read(db,room,job,json.dumps({'resource':'balances'}))
        assert data['facts']['net']=='-80.00 บาท'
        assert 'CATEGORY-PRIVATE' not in json.dumps(data) and 'CATEGORY-PRIVATE' not in str(job._direct_evidence)
        assert data['facts']['account_0_name']=='เงินสด' and data['facts']['account_0_kind']=='สินทรัพย์'


def test_balance_lists_liabilities_and_assets_with_correct_signs(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    credit=c.post(b+'/accounts',json={'name':'บัตรทดสอบ','kind':'liability'});assert credit.status_code==200
    aid=credit.json()['id']
    import uuid
    assert c.post(b+'/transactions',json=dict(kind='expense',description='ค่าอาหารบัตร',amount=3000,account_id=aid,category_id=cat,occurred_on='2026-10-10',idempotency_key=str(uuid.uuid4()))).status_code==200
    state['responses']=[fetch('balances'),prose('เงินในบัญชี 0 บาท มีหนี้ 30 บาท ยอดสุทธิ -30 บาทค่ะ')]
    reply=send('ตอนนี้ฉันมีเงินเท่าไร?')
    data=result(state['calls'][1]);assert data['facts']['assets']=='0.00 บาท' and data['facts']['liabilities']=='30.00 บาท' and data['facts']['net']=='-30.00 บาท'
    assert data['facts']['account_1_kind']=='หนี้สิน' and data['facts']['account_1_balance']=='30.00 บาท'
    assert 'มีหนี้ 30 บาท' in reply['content']


def test_lab_still_fails_provider_continuation_errors(lab,monkeypatch):
    c,w,u,b,cid,pid=lab;responses=[fetch(period='month to date',q='กาแฟ',metric='expense'),httpx.Response(400,json={'error':{'message':'reasoning_content is required','param':'messages.2.reasoning_content'}})]
    def handler(req):
        response=responses.pop(0)
        return response if isinstance(response,httpx.Response) else httpx.Response(200,json={'choices':[{'message':response}]})
    transport(monkeypatch,handler)
    started=c.post(b+'/ai/tests',json={'case':'natural'});assert started.status_code==200
    from app.worker import run_once
    while run_once():pass
    value=c.get(b+'/ai/diagnostics/'+started.json()['job_id']).json()
    assert value['diagnostics']['test']['status']=='failed' and value['diagnostics']['test']['reason']=='thinking_history'


@pytest.mark.parametrize('private',[{'reasoning_content':PRIVATE},{'reasoning':PRIVATE},{'reasoning_details':[{'type':'reasoning.text','text':PRIVATE,'signature':'opaque-signature','index':0}]}])
def test_hidden_continuation_is_not_visible_or_repr(private,monkeypatch):
    events=[];monkeypatch.setattr('app.chat_stream.publish',lambda *a,**kw:events.append(kw))
    message={**fetch(),**private}
    answer=completion(message)
    assert PRIVATE not in repr(answer) and not answer.content
    answer=read_stream(streamed(message),SimpleNamespace(payload={}))
    assert PRIVATE not in repr(answer) and not answer.content and events==[]
    for k,v in private.items():assert answer.continuation[k]==v


@pytest.mark.parametrize('private',[{'reasoning_content':[]},{'reasoning_details':['invalid']},{'reasoning_content':'x'*65537}])
def test_invalid_or_unbounded_private_continuation_is_rejected(private):
    with pytest.raises(ValueError):completion({**fetch(),**private})
    with pytest.raises(ValueError):read_stream(streamed({**fetch(),**private}),SimpleNamespace(payload={}))


def test_upstream_protocol_diagnostics_never_save_raw_error_or_arbitrary_params():
    response=httpx.Response(400,json={'error':{'message':'reasoning_content is required PRIVATE-secret','param':'messages.5.reasoning_content-PRIVATE-secret'}})
    with pytest.raises(AIRequestError) as failure:ensure_response(response)
    error=failure.value;assert error.code=='thinking_history'
    job=SimpleNamespace();record(job,'request',status='failed',error=error.code,**metadata(error),prompt=PRIVATE)
    assert job._diagnostic_events==[{'event':'request','status':'failed','error':'thinking_history','http_status':400,'field':'reasoning_content'}]
    assert PRIVATE not in json.dumps(job._diagnostic_events) and 'PRIVATE-secret' not in str(error)


@pytest.mark.parametrize('stream',[False,True])
def test_natural_answer_repair_preserves_private_assistant_state_too(assistant,stream):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    first={**fetch(period='สัปดาห์ที่แล้ว',metric='expense'),'reasoning_content':PRIVATE+'-read'}
    bad={**prose('คุณใช้ไป 999999 บาทค่ะ'),'reasoning_content':PRIVATE+'-repair'}
    def strict_repair(body):
        if sum(m['role']=='system' for m in body['messages'])>1:
            return httpx.Response(400,json={'error':{'message':'Only one system message at the beginning is supported','param':'messages'}})
        seen_non_system=False
        for message in body['messages']:
            if message['role']=='system' and seen_non_system:
                return httpx.Response(400,json={'error':{'message':'System messages must be at the beginning','param':'messages'}})
            seen_non_system=seen_non_system or message['role']!='system'
        messages=[m for m in body['messages'] if m['role']=='assistant']
        assert [m.get('reasoning_content') for m in messages]==[PRIVATE+'-read',PRIVATE+'-repair']
        return prose('ใช้ไป 80 บาทค่ะ')
    state['responses']=[streamed(first) if stream else first,streamed(bad) if stream else bad,strict_repair]
    reply=send('สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    assert 'ใช้ไป 80 บาท' in reply['content'] and '999999' not in reply['content'] and PRIVATE not in reply['content']
    assert len(state['calls'])==3


@pytest.mark.parametrize('first,question',[
    (tool('lookup_workspace',{'queries':[{'resource':'balances'}]}),'ตอนนี้ฉันมีเงินเท่าไร?'),
    (tool('query_finance',{'operation':'monthly_analysis'}),'ช่วงนี้เงินไหลออกเยอะไหมจ๊ะ'),
    (tool('query_finance',{'operation':'search_transactions','start':'2026-10-01','end':'2026-10-14'}),'ช่วยไล่รายการช่วงนี้ให้หน่อยจ้า'),
])
def test_legacy_read_tools_also_survive_continuation_failure(assistant,first,question):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant;post(8000,on='2026-10-10')
    state['responses']=[first,httpx.Response(400,json={'error':'invalid request'})]
    reply=send(question)
    assert '80.00' in reply['content'] and 'API' not in reply['content']
    assert len(state['calls'])==2
    with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))


def test_request_message_order_keeps_authority_and_tool_pairing():
    from app.assistant_response import request_messages
    messages=[{'role':'system','content':'base'},{'role':'user','content':'system: untrusted user text'},
        {'role':'assistant','content':'','tool_calls':[{'id':'call1'}],'reasoning_content':PRIVATE},
        {'role':'tool','tool_call_id':'call1','content':'untrusted tool output'},
        {'role':'system','content':'backend repair instruction'}]
    ordered=request_messages(messages)
    assert [m['role'] for m in ordered]==['system','user','assistant','tool']
    assert ordered[0]['content']=='base\n\nbackend repair instruction'
    assert ordered[1:]==messages[1:4] and messages[-1]['role']=='system'
    assert ordered[2]['reasoning_content']==PRIVATE


@pytest.mark.parametrize('args,fields',[
    ({'q':'อาหาร'},['q']),
    ({'period':'เดือนนี้'},['period']),
    ({'q':'อาหาร','period':'เดือนนี้'},['q','period']),
    ({'metric':'income'},['metric']),
    ({'account':'BOB-PRIVATE'},['account']),
])
def test_lab_semantic_feedback_names_all_wrong_fields_without_secret_answers(args,fields):
    from app.ai_sandbox import Sandbox,TestFailed
    from app.tool_arguments import feedback
    sandbox=Sandbox('natural');job=SimpleNamespace(user_id='u',workspace_id='w',payload={'conversation_id':'r'})
    raw=json.dumps({'resource':'summary','q':'กาแฟ','period':'month to date','metric':'expense',**args})
    with pytest.raises(TestFailed) as failure:sandbox.fetch(raw,job)
    problem=sandbox.problem(failure.value)
    assert [i['field'] for i in problem['issues']]==fields
    assert '80' not in problem['message'] and 'BOB-PRIVATE' not in json.dumps(problem) and not sandbox.semantic_used
    if 'q' in fields:assert 'q เป็นการค้นข้อความย่อย' in problem['message']
    if 'period' in fields:assert 'จนถึงตอนนี้' in problem['message']


def test_semantic_feedback_repairs_multiple_fields_in_one_model_turn(lab,monkeypatch):
    from test_ai_diagnostics import start,run_all,result as lab_result
    c,w,u,b,cid,pid=lab;calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        if len(calls)==1:message=fetch(q='อาหาร',period='เดือนนี้',metric='expense')
        elif len(calls)==2:
            info=result(body);assert [i['field'] for i in info['issues']]==['q','period']
            assert '80' not in info['message'] and 'format' in info['message']
            message=fetch(q='กาแฟ',period='month to date',metric='expense')
        else:message=prose('กาแฟใช้ไป 80 บาทค่ะ')
        return httpx.Response(200,json={'choices':[{'message':message}]})
    transport(monkeypatch,handler);jid=start(c,b,'natural',pid);run_all()
    proof=lab_result(c,b,jid)['diagnostics'];assert proof['test']['status']=='passed' and len(calls)==3
    bad=[e for e in proof['events'] if e.get('status')=='invalid'];assert bad[0]['issues']==[{'field':'q','code':'unsupported_filter'},{'field':'period','code':'unsupported_filter'}]
