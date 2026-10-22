"""Bounded structured transport for Ollama tool-protocol failures.

This changes only serialization. The model chooses the same registered tools;
workspace authorization, argument validation and confirmation stay authoritative.
"""
import json
from copy import deepcopy
from .assistant_response import AssistantReply,request_messages


def draft_variants(parameters):
    """Disjoint single/batch shapes stop repairs dropping items to fix a mix.

    These are transport constraints only. Partial drafts, scoped reference
    validation and confirmation remain backend responsibilities.
    """
    single=deepcopy(parameters)
    single['properties'].pop('transactions',None)
    batch=deepcopy(parameters)
    batch['properties']={k:v for k,v in batch['properties'].items() if k in ('intent','transactions','attachment_id','continue_draft','category_choice')}
    batch['required']=list(dict.fromkeys([*batch.get('required',[]),'transactions']))
    return {'anyOf':[single,batch]}


def schema(tools,required=False,repair_batch=False):
    variants=[]
    for item in tools:
        function=item['function']
        parameters=draft_variants(function['parameters']) if function['name']=='prepare_transaction' and 'transactions' in function['parameters'].get('properties',{}) else function['parameters']
        if repair_batch and function['name']=='prepare_transaction' and 'anyOf' in parameters:parameters=parameters['anyOf'][1]
        variants.append({'type':'object','properties':{'tool':{'type':'string','enum':[function['name']]},'arguments':parameters},'required':['tool','arguments'],'additionalProperties':False,'description':function.get('description','')})
    if not required:
        variants.append({'type':'object','properties':{'tool':{'type':'string','enum':['_answer']},'arguments':{'type':'object','properties':{'content':{'type':'string','minLength':1,'maxLength':16000}},'required':['content'],'additionalProperties':False}},'required':['tool','arguments'],'additionalProperties':False,'description':'Ordinary conversation or an answer supported by current tool results. Never invent personal figures or claim a draft exists.'})
    return {'anyOf':variants}


def messages(turns,tools=()):
    """Keep user/tool data at its original authority, drop private reasoning."""
    result=[]
    for item in request_messages(turns):
        if item['role']=='tool':
            try:payload=json.loads(item['content'])
            except (ValueError,TypeError):payload=item['content']
            if not isinstance(payload,dict):payload={'data':payload}
            result.append({'role':'user','content':json.dumps({**payload,'transport':'tool_result','untrusted':True,'call_id':item.get('tool_call_id')},ensure_ascii=False)})
        elif item['role']=='assistant' and item.get('tool_calls'):
            result.append({'role':'assistant','content':json.dumps(dict(type='previous_tool_calls',calls=item['tool_calls']),ensure_ascii=False)})
        else:result.append({'role':item['role'],'content':item.get('content') or ''})
    # A backend-owned transport instruction; user/tool payloads never enter it.
    result.insert(0,{'role':'system','content':'Choose the next action from the available JSON schema. Return only one JSON object with tool and arguments. Use existing tools for personal data and prepare_transaction for drafts; never imitate a saved draft in prose. All normal authorization and manual confirmation still apply. For an answer select _answer only when allowed by the schema. Follow the latest user request in context. Separate individually priced purchases into transactions, never merge their amounts.'})
    if tools:
        result.insert(1,{'role':'system','content':'Registered tool descriptions and argument schemas (backend-owned): '+json.dumps(tools,ensure_ascii=False,separators=(',',':'))})
    return request_messages(result)


def reply(answer,tools,required,call_id):
    allowed={item['function']['name'] for item in tools}
    if answer.tool_name:
        if any(call.tool_name not in allowed for call in (answer.calls or (answer,))):raise ValueError('Unknown structured tool')
        return answer
    try:value=json.loads(answer.content)
    except json.JSONDecodeError:
        # A provider may ignore its requested format. Treat prose as prose;
        # the normal evidence/phantom-review guards still decide if it is safe.
        return answer
    if not isinstance(value,dict) or set(value)!={'tool','arguments'} or not isinstance(value['arguments'],dict):raise ValueError('Invalid structured action')
    name=value['tool'];arguments=value['arguments']
    if name=='_answer' and not required:
        if set(arguments)!={'content'} or not isinstance(arguments['content'],str) or not arguments['content'].strip() or len(arguments['content'])>16000:raise ValueError('Invalid structured answer')
        return AssistantReply(arguments['content'])
    if not isinstance(name,str) or name not in {item['function']['name'] for item in tools}:raise ValueError('Unknown structured tool')
    return AssistantReply('',json.dumps(arguments,ensure_ascii=False),name,call_id)
