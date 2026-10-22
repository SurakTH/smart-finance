import json
import pytest
from app.assistant_protocol import messages,schema,reply
from app.assistant_response import AssistantReply
from test_assistant_finance import assistant,tool

TOOLS=[{'function':{'name':'prepare_transaction','parameters':{'type':'object'},'description':'Draft only'}}]


def test_structured_drafts_separate_batch_shape_without_changing_native_catalog():
    from app.assistant_tools import catalog
    tools=catalog(set())
    original=json.dumps(tools,sort_keys=True)
    variants=schema(tools,True)['anyOf']
    draft=next(v for v in variants if v['properties']['tool']['enum']==['prepare_transaction'])
    single,batch=draft['properties']['arguments']['anyOf']
    assert 'transactions' not in single['properties']
    assert set(batch['properties'])=={'intent','transactions','attachment_id','continue_draft'}
    assert 'transactions' in batch['required']
    assert single['additionalProperties'] is False and batch['additionalProperties'] is False
    assert batch['properties']['transactions']['items']['properties']['amount']['type']=='integer'
    assert json.dumps(tools,sort_keys=True)==original


def test_transport_keeps_untrusted_data_out_of_system_and_private_state():
    result=messages([{'role':'system','content':'backend'}, {'role':'user','content':'USER_MARKER'}, {'role':'assistant','content':'','reasoning_content':'PRIVATE_MARKER','tool_calls':[{'id':'x','function':{'name':'prepare_transaction','arguments':'{}'}}]}, {'role':'tool','tool_call_id':'x','content':'TOOL_MARKER'}])
    assert 'USER_MARKER' not in result[0]['content'] and 'TOOL_MARKER' not in result[0]['content']
    assert 'PRIVATE_MARKER' not in json.dumps(result)
    assert result[-1]['role']=='user' and 'TOOL_MARKER' in result[-1]['content']


def test_required_transport_cannot_answer_or_call_confirmation():
    assert '_answer' not in json.dumps(schema(TOOLS,True))
    for name in ('_answer','confirm','delete_workspace'):
        with pytest.raises(ValueError):reply(AssistantReply(json.dumps({'tool':name,'arguments':{}})),TOOLS,True,'x')
    value=reply(AssistantReply(json.dumps({'tool':'prepare_transaction','arguments':{'amount':1800}})),TOOLS,True,'x')
    assert value.tool_name=='prepare_transaction' and json.loads(value.draft)['amount']==1800


def test_native_call_in_structured_mode_still_requires_same_tool_allowlist():
    value=AssistantReply('','{}','prepare_transaction','native')
    assert reply(value,TOOLS,True,'x') is value
    with pytest.raises(ValueError):reply(AssistantReply('','{}','confirm','native'),TOOLS,True,'x')


def test_ollama_server_tool_error_recovers_same_provider_to_review(assistant):
    import httpx
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def recovery(body):
        assert 'tools' not in body and body['response_format']['json_schema']['name']=='assistant_action'
        return {'content':json.dumps({'tool':'prepare_transaction','arguments':dict(intent='create',kind='expense',description='ค่าซักผ้า',amount=6000,account_id=wallet,category_id=cat)})}
    state['responses']=[httpx.Response(500,json={'error':'synthetic tool parser error'}),recovery]
    result=send('ช่วยจดค่าซักผ้า60บาทเงินสด')
    assert 'กรุณาตรวจสอบ' in result['content'] and '฿60.00' in result['content']
    assert c.get(b+'/transaction-report').json()['total']==0
    assert len(state['calls'])==2 and len({body['model'] for body in state['calls']})==1


def test_repeated_ollama_error_does_not_loop_or_post(assistant):
    import httpx
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[httpx.Response(500),httpx.Response(500)]
    send('จดค่าซักผ้า60บาทเงินสด')
    assert len(state['calls'])==2 and c.get(b+'/transaction-report').json()['total']==0


def test_ungrounded_followup_requires_structured_read_not_old_figures(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    post(7500)
    def recovery(body):
        assert 'tools' not in body and '_answer' not in json.dumps(body['response_format'])
        return {'content':json.dumps({'tool':'fetch_finance','arguments':{'resource':'summary','metric':'expense','period':'วันนี้'}})}
    state['responses']=[{'content':'วันนี้ใช้ไป 999 บาท'},recovery,{'content':json.dumps({'tool':'_answer','arguments':{'content':'ใช้ไป75บาท'}})}]
    result=send('วันนี้ใช้ไปเท่าไหร่')
    assert '75' in result['content'] and '999' not in result['content']
    assert c.get(b+'/transaction-report').json()['total']==1


def test_stated_amount_omitted_by_model_is_rechecked_not_parsed_by_backend(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def recovery(body):
        assert body['response_format']['json_schema']['name']=='assistant_action'
        assert 'Registered tool descriptions' in body['messages'][0]['content']
        return {'content':json.dumps({'tool':'prepare_transaction','arguments':dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account_id=wallet,category_id=cat)})}
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',account_id=wallet,category_id=cat)),recovery]
    value=send('จดกาแฟ80บาทจากเงินสด')
    assert '฿80.00' in value['content'] and 'ยอดเท่าไหร่' not in value['content']
    assert len(state['calls'])==2 and c.get(b+'/transaction-report').json()['total']==0


def test_category_reference_error_retains_partial_draft_before_asking(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    value=dict(intent='create',kind='expense',description='กาแฟ',amount=7500,account_id=wallet)
    state['responses']=[tool('prepare_transaction',dict(**value,category='ฉันเลือกเอง')),{'content':json.dumps({'tool':'prepare_transaction','arguments':{'intent':'create','category':None,'continue_draft':True}})}]
    answer=send('จดกาแฟ75บาทเงินสด หมวดฉันเลือกเอง')
    assert 'จัดเข้าหมวดไหน' in answer['content']
    from app.db import SessionLocal
    from app.models import Conversation
    with SessionLocal() as db:
        draft=db.get(Conversation,cid).capture_context['ai_followup']['draft']
        assert draft['amount']==7500 and draft['account_id']==wallet
    assert c.get(b+'/transaction-report').json()['total']==0


def test_no_image_tool_schema_cannot_suggest_image_provenance(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def model(body):
        item=next(t for t in body['tools'] if t['function']['name']=='prepare_transaction')
        assert 'attachment_id' not in item['function']['parameters']['properties']
        return tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account_id=wallet,category_id=cat))
    state['responses']=[model]
    assert 'กรุณาตรวจสอบ' in send('จดกาแฟ80บาทเงินสด')['content']


def test_invalid_native_tool_json_recovers_without_changing_model(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[{'tool_calls':[{'id':'bad','type':'function','function':{'name':'prepare_transaction','arguments':'{bad json'}}]}, {'content':json.dumps({'tool':'prepare_transaction','arguments':dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account_id=wallet,category_id=cat)})}]
    result=send('จดกาแฟ80บาทเงินสด')
    assert '฿80.00' in result['content'] and c.get(b+'/transaction-report').json()['total']==0
    assert len(state['calls'])==2


def test_nonexistent_continuation_is_repaired_before_draft_resolution(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    value=dict(intent='create',kind='expense',description='กาแฟ',amount=7500,account_id=wallet,category_id=cat)
    state['responses']=[tool('prepare_transaction',dict(**value,continue_draft=True)),{'content':json.dumps({'tool':'prepare_transaction','arguments':{'intent':'create','continue_draft':False}})}]
    answer=send('จดกาแฟ75บาทเงินสด')
    assert '฿75.00' in answer['content'] and 'กรุณาตรวจสอบ' in answer['content']
    assert c.get(b+'/transaction-report').json()['total']==0


def test_balance_filter_conflict_explains_fields_and_repairs_same_read(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def recovery(body):
        assert 'tools' not in body and '_answer' not in json.dumps(body['response_format'])
        feedback=json.loads(body['messages'][-1]['content'])
        assert {v['field'] for v in feedback['issues']}=={'period','metric'}
        assert 'accumulated wallet balance' in feedback['message']
        return {'content':json.dumps({'tool':'fetch_finance','arguments':{'resource':'balances','account_id':wallet}})}
    state['responses']=[tool('fetch_finance',dict(resource='balances',period='วันนี้',metric='expense',account_id=wallet)),recovery,{'content':json.dumps({'tool':'_answer','arguments':{'content':'ยอดสุทธิ 0.00 บาท'}})}]
    answer=send('ตอนนี้ฉันมีเงินเท่าไร')
    assert '0.00' in answer['content'] and 'ไม่สำเร็จ' not in answer['content']
    assert len(state['calls'])==3 and c.get(b+'/transaction-report').json()['total']==0


def test_mixed_batch_repair_keeps_array_and_confirms_all_items_once(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    items=[dict(kind='expense',description=name,amount=amount,account_id=wallet,category_id=cat) for name,amount in [('ข้าว',5500),('น้ำ',2000)]]
    def recovery(body):
        variants=body['response_format']['json_schema']['schema']['anyOf']
        arguments=next(v['properties']['arguments'] for v in variants if v['properties']['tool']['enum']==['prepare_transaction'])
        assert 'transactions' in arguments['required'] and 'amount' not in arguments['properties']
        assert 'Keep its separate items' in body['messages'][-1]['content']
        return {'content':json.dumps({'tool':'prepare_transaction','arguments':dict(intent='create',transactions=items)})}
    state['responses']=[tool('prepare_transaction',dict(intent='create',amount=7500,transactions=items)),recovery]
    answer=send('จดข้าว55บาทกับน้ำ20บาท จ่ายเงินสด')
    assert '2 รายการ' in answer['content'] and '฿55.00' in answer['content'] and '฿20.00' in answer['content']
    assert c.get(b+'/transaction-report').json()['total']==0
    send('ยืนยัน');send('ยืนยัน')
    report=c.get(b+'/transaction-report').json()
    assert report['total']==2 and report['expense']==7500


def test_reference_ids_are_advertised_only_after_scoped_lookup(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    def initial(body):
        draft_tool=next(t for t in body['tools'] if t['function']['name']=='prepare_transaction')
        props=draft_tool['function']['parameters']['properties']
        assert 'account' in props and 'category' in props
        assert not {'account_id','category_id','other_account_id'}&props.keys()
        return tool('lookup_workspace',{'queries':[{'resource':'accounts'}]})
    def after_lookup(body):
        draft_tool=next(t for t in body['tools'] if t['function']['name']=='prepare_transaction')
        assert 'account_id' in draft_tool['function']['parameters']['properties']
        return tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=8000,account_id=wallet,category_id=cat))
    state['responses']=[initial,after_lookup]
    assert '฿80.00' in send('จดกาแฟ80บาทเงินสด')['content']
    assert c.get(b+'/transaction-report').json()['total']==0


def test_one_item_array_patch_continues_single_review_without_losing_details(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=8500,account_id=wallet,category_id=cat,occurred_on='2026-10-20'))]
    send('จดกาแฟ85บาทเงินสด วันที่20ตุลา')
    state['responses']=[tool('prepare_transaction',dict(intent='create',continue_draft=True,transactions=[dict(kind='expense')]))]
    reply=send('รายจ่ายนะ')['content']
    assert 'กรุณาตรวจสอบ' in reply and '฿85.00' in reply and '2026-10-20' in reply
    assert c.get(b+'/transaction-report').json()['total']==0


def test_one_item_patch_does_not_insert_null_image_or_clear_continuation():
    from app.chat_dialogue import Suggestion,single_item
    result=single_item(Suggestion.model_validate(dict(intent='create',continue_draft=True,transactions=[dict(kind='expense')])))
    assert result.continue_draft and result.transactions is None and 'attachment_id' not in result.model_fields_set
