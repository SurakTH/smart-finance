"""Small-model transport quirks must not weaken scoped reads or confirmation."""
import json
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from app.assistant_response import completion,read_stream,assistant_message
from app.assistant_context import reference_context
from app.chat_dialogue import named_references
from app.db import SessionLocal
from app.models import Account,Workspace,ChatAction
from test_assistant_finance import assistant,tool


def calls(*items):
    return {'tool_calls':[{**tool(name,args)['tool_calls'][0],'id':'read_'+str(i)} for i,(name,args) in enumerate(items)]}


def sse(frames):
    return httpx.Response(200,headers={'content-type':'text/event-stream'},text=''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n')


def test_interleaved_stream_keeps_each_tool_and_private_continuation_separate():
    frames=[{'choices':[{'delta':{'reasoning_content':'PRIVATE','tool_calls':[
        {'index':1,'id':'second','function':{'name':'lookup_','arguments':'{"queries":'}},
        {'index':0,'id':'first','function':{'name':'fetch_','arguments':'{"resource":'}}]}}]},
        {'choices':[{'delta':{'tool_calls':[
            {'index':0,'function':{'name':'finance','arguments':'"balances"}'}},
            {'index':1,'function':{'name':'workspace','arguments':'[{"resource":"accounts"}]}'}}]},'finish_reason':'tool_calls'}]}]
    answer=read_stream(sse(frames),SimpleNamespace(payload={}))
    assert [c.tool_name for c in answer.calls]==['fetch_finance','lookup_workspace']
    assert [c.call_id for c in answer.calls]==['first','second']
    assert json.loads(answer.calls[1].draft)['queries'][0]['resource']=='accounts'
    assert answer.continuation['reasoning_content']=='PRIVATE'
    assert 'PRIVATE' not in repr(answer) and not answer.content
    assert len(assistant_message(answer)['tool_calls'])==2


@pytest.mark.parametrize('mutation',[
    lambda c:c*4,
    lambda c:[c[0],c[0]],
    lambda c:[c[0],{**c[1],'function':{'name':'confirm','arguments':'{}'}}],
])
def test_batch_limits_and_unknown_tools_fail_closed(mutation):
    data=calls(('fetch_finance',{'resource':'balances'}),('lookup_workspace',{'queries':[{'resource':'accounts'}]}))
    with pytest.raises(ValueError):completion({'tool_calls':mutation(data['tool_calls'])})


def test_read_batch_executes_sequentially_and_returns_every_call_result(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[calls(('lookup_workspace',{'queries':[{'resource':'accounts'}]}),('lookup_workspace',{'queries':[{'resource':'categories'}]})),tool('prepare_transaction',{'intent':'create','kind':'expense','description':'กาแฟ','amount':8000,'account_id':wallet,'category_id':cat})]
    reply=send('จดกาแฟ80เงินสด')
    assert 'กรุณาตรวจสอบ' in reply['content']
    assert c.get(b+'/transaction-report').json()['total']==0
    messages=state['calls'][1]['messages']
    assert [m['tool_call_id'] for m in messages if m['role']=='tool']==['read_0','read_1']
    assert len([m for m in messages if m.get('tool_calls')])==1
    assert state['calls'][0]['stream_options']=={'include_usage':True}
    c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    assert c.get(b+'/transaction-report').json()['total']==1


def test_mixed_prepare_batch_is_not_executed_before_repair(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    draft={'intent':'create','kind':'expense','description':'กาแฟ','amount':8000,'account_id':wallet,'category_id':cat}
    def repaired(body):
        results=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
        assert len(results)==2 and all(r['error']=='sequential_required' for r in results)
        with SessionLocal() as db:assert not db.scalar(select(ChatAction.id).where(ChatAction.workspace_id==w))
        return tool('prepare_transaction',draft)
    state['responses']=[calls(('prepare_transaction',draft),('lookup_workspace',{'queries':[{'resource':'accounts'}]})),repaired]
    assert 'กรุณาตรวจสอบ' in send('จดกาแฟ80')['content']
    assert c.get(b+'/transaction-report').json()['total']==0


def test_names_are_scoped_exact_and_must_agree_with_explicit_ids(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    from app.models import Conversation
    with SessionLocal.begin() as db:
        room=db.get(Conversation,cid);account=db.get(Account,wallet);category=db.get(Account,cat)
        raw=json.dumps({'intent':'create','kind':'expense','account':account.name,'category':category.name})
        value=json.loads(named_references(db,room,raw))
        assert value['account_id']==wallet and value['category_id']==cat and 'account' not in value
        foreign=Workspace(name='Other tenant');db.add(foreign);db.flush()
        other=Account(workspace_id=foreign.id,name='Foreign unique name',kind='asset');db.add(other);db.flush()
        for data in [{'account':'Foreign unique name'},{'account':account.name,'account_id':other.id}]:
            with pytest.raises(ValueError):named_references(db,room,json.dumps({'intent':'create',**data}))
        duplicate=Account(workspace_id=w,name=account.name,kind='liability');db.add(duplicate);db.flush()
        with pytest.raises(ValueError):named_references(db,room,json.dumps({'intent':'create','account':account.name}))


def test_named_draft_correction_still_requires_one_confirmation(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    accounts=c.get(b+'/accounts').json();a=next(x['name'] for x in accounts if x['id']==wallet);k=next(x['name'] for x in accounts if x['id']==cat)
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account=a,category=k))]
    assert '฿80.00' in send('จดกาแฟ80')['content']
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,amount=8500))]
    assert '฿85.00' in send('เอาเป็น85นะ')['content']
    assert c.get(b+'/transaction-report').json()['total']==0
    for _ in range(2):c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    report=c.get(b+'/transaction-report').json()
    assert report['total']==1 and report['expense']==8500


def test_reference_context_is_bounded_untrusted_and_has_no_balances(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    with SessionLocal.begin() as db:
        foreign=Workspace(name='Other tenant');db.add(foreign);db.flush()
        db.add(Account(workspace_id=foreign.id,name='NEVER-LEAK',kind='asset'))
        db.add_all(Account(workspace_id=w,name='Asset '+str(i),kind='asset') for i in range(30));db.flush()
        value=json.loads(reference_context(db,w))
        assert value['untrusted'] and value['has_more'] and len(value['items'])==20
        assert all(set(r)=={'name','kind'} for r in value['items'])
        assert 'NEVER-LEAK' not in json.dumps(value)


def test_repair_does_not_prefill_a_rejected_financial_answer(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    from app.reporting import today
    from datetime import timedelta
    post(23500,on=(today()-timedelta(days=1)).isoformat())
    def strict_server(body):
        assert body['messages'][-1]['role']=='user'
        if 'response_format' in body:
            assert body['response_format']['json_schema']['name']=='assistant_action'
            assert '_answer' not in json.dumps(body['response_format'])
            assert 'tools' not in body
        else:assert body['tool_choice']=='required'
        assert '45 บาท' not in json.dumps(body,ensure_ascii=False)
        return tool('fetch_finance',{'resource':'summary','period':'เมื่อวาน','metric':'expense'})
    state['responses']=[{'content':'เมื่อวานใช้ไป45 บาทค่ะ'},strict_server,{'content':'เมื่อวานใช้ไป235 บาทค่ะ'}]
    reply=send('เมื่อวานใช้ไปเท่าไหร่')
    assert '235 บาท' in reply['content'] and 'API' not in reply['content']
    assert len(state['calls'])==3


def test_parallel_new_drafts_become_one_atomic_review(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    first=dict(intent='create',kind='expense',description='ข้าว',amount=5500,account_id=wallet,category_id=cat)
    second={**first,'description':'น้ำ','amount':2000}
    state['responses']=[calls(('prepare_transaction',first),('prepare_transaction',second))]
    reply=send('จดข้าว55กับน้ำ20')
    assert '2 รายการ' in reply['content'] and '฿55.00' in reply['content'] and '฿20.00' in reply['content']
    assert c.get(b+'/transaction-report').json()['total']==0
    for _ in range(2):c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน'})
    report=c.get(b+'/transaction-report').json()
    assert report['total']==2 and report['expense']==7500


def test_parallel_draft_error_keeps_all_call_ids_and_private_protocol_state(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    first=dict(intent='create',kind='expense',description='ข้าว',amount='5500',account_id=wallet,category_id=cat)
    second={**first,'description':'น้ำ','amount':2000}
    batch=calls(('prepare_transaction',first),('prepare_transaction',second));batch['reasoning_content']='PRIVATE batch'
    def fixed(body):
        messages=body['messages']
        assert [m['tool_call_id'] for m in messages if m['role']=='tool']==['read_0','read_1']
        assert next(m for m in messages if m.get('tool_calls'))['reasoning_content']=='PRIVATE batch'
        return tool('prepare_transaction',{'intent':'create','transactions':[{**first,'amount':5500},second]})
    state['responses']=[batch,fixed]
    assert '2 รายการ' in send('จดข้าว55กับน้ำ20')['content']
    assert c.get(b+'/transaction-report').json()['total']==0


def test_advertised_draft_schema_is_inline_and_only_prepares_drafts():
    from app.assistant_tools import catalog
    tools=catalog({'management','grounded_answer','corrections'})
    assert '$ref' not in json.dumps(tools) and '$defs' not in json.dumps(tools)
    schema=next(t['function']['parameters'] for t in tools if t['function']['name']=='prepare_transaction')
    assert schema['properties']['intent']['enum']==['create'] and 'reply' not in schema['properties']
    item=schema['properties']['transactions']['items']
    assert item['additionalProperties'] is False and item['properties']['amount']['exclusiveMinimum']==0


@pytest.mark.parametrize('text,execution',[
    ('ฉันสามารถช่วยค้นรายการที่บันทึกแล้ว และเตรียมร่างใหม่ให้ตรวจได้ค่ะ',False),
    ('แก้ไขรายการที่ยังไม่ได้บันทึก และดูข้อมูลที่บันทึกแล้ว',False),
    ('ยังไม่ได้บันทึกก่อนหน้านี้ แต่ตอนนี้บันทึกเรียบร้อยแล้ว',True),
    ('ฉันบันทึกให้เรียบร้อยแล้ว',True),
    ('บันทึกค่ากาแฟสำเร็จ',True),
])
def test_capability_and_negation_are_not_execution_receipts(text,execution):
    from app.semantic_assistant import claims_execution
    assert claims_execution(text) is execution
