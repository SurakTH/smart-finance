"""Separate visible replies from untrusted tool arguments and private reasoning."""
import json
import re
from dataclasses import dataclass

@dataclass
class AssistantReply:
    content: str
    draft: str | None = None
    tool_name: str | None = None
    call_id: str | None = None

def visible(text):
    return re.sub(r'<think\b[^>]*>.*?(?:</think>|$)','',text,flags=re.S|re.I).strip()

def completion_choice(choice):
    from .ai_errors import AIRequestError
    if choice.get("finish_reason")=="length":raise AIRequestError("output_limit")
    return completion(choice["message"])

def completion(message):
    if not isinstance(message,dict):raise ValueError('Invalid message')
    content=message.get('content') or ''
    if not isinstance(content,str) or len(content)>16000:raise ValueError('Invalid response')
    tools=message.get('tool_calls') or []
    if not isinstance(tools,list) or len(tools)>1:raise ValueError('Only one draft at a time')
    if not tools:
        if not visible(content):raise ValueError('Empty completion')
        return AssistantReply(visible(content))
    tool=tools[0]
    if not isinstance(tool,dict):raise ValueError('Invalid tool')
    function=tool.get('function',{})
    if not isinstance(function,dict):raise ValueError('Invalid function')
    if tool.get('type','function')!='function' or function.get('name') not in ('answer_finance_summary','load_toolkit','prepare_transaction','prepare_management_plan','query_finance','prepare_correction','lookup_workspace'):raise ValueError('Unknown tool')
    arguments=function.get('arguments')
    if not isinstance(arguments,str) or len(arguments)>16000:raise ValueError('Invalid arguments')
    identifier=tool.get('id') or 'call_sf_read'
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',identifier):raise ValueError('Invalid tool id')
    return AssistantReply('',arguments,function['name'],identifier)

def read_stream(response,job):
    from .chat_stream import publish
    import time
    text='';name='';arguments='';identifier='';tool_seen=False;finished=False;fields=[];size=0
    deadline=time.monotonic()+75
    for line in response.iter_lines():
        from .chat_stop import check
        check(job)
        size+=len(line.encode())+1
        if size>256000 or time.monotonic()>deadline:raise ValueError('Stream limit')
        if line.startswith('data:'):fields.append(line[5:].lstrip())
        elif line=='':
            if not fields:continue
            raw='\n'.join(fields);fields=[]
            if raw=='[DONE]':finished=True;break
            data=json.loads(raw)
            if not isinstance(data,dict) or 'error' in data:raise ValueError('Invalid stream')
            choices=data.get('choices',[])
            if not isinstance(choices,list):raise ValueError('Invalid choices')
            if not choices:continue
            choice=choices[0]
            if not isinstance(choice,dict):raise ValueError('Invalid choice')
            delta=choice.get('delta',{})
            if not isinstance(delta,dict):raise ValueError('Invalid delta')
            reason=choice.get('finish_reason')
            if reason is not None:
                if reason=='length':
                    from .ai_errors import AIRequestError
                    raise AIRequestError('output_limit')
                if reason not in ('stop','tool_calls'):raise ValueError('Incomplete completion')
                finished=True
            calls=delta.get('tool_calls') or []
            if not isinstance(calls,list) or len(calls)>1:raise ValueError('Too many tools')
            for call in calls:
                if not isinstance(call,dict):raise ValueError('Invalid tool')
                if call.get('index',0)!=0 or call.get('type','function')!='function':raise ValueError('Invalid tool')
                tool_seen=True
                if call.get('id'):
                    if not isinstance(call['id'],str):raise ValueError('Invalid tool id')
                    identifier+=call['id']
                    if len(identifier)>100:raise ValueError('Tool id limit')
                fn=call.get('function',{})
                if not isinstance(fn,dict):raise ValueError('Invalid function')
                n=fn.get('name','');a=fn.get('arguments','')
                if not isinstance(n,str) or not isinstance(a,str):raise ValueError('Invalid arguments')
                name+=n;arguments+=a
                if len(name)>100 or len(arguments)>16000:raise ValueError('Tool limit')
            part=delta.get('content')
            if part is not None:
                if not isinstance(part,str) or len(text)+len(part)>16000:raise ValueError('Content limit')
                text+=part
                shown=visible(text)
                if part and shown and not tool_seen:publish(job,'delta',text=shown,snapshot=True)
            # reasoning/reasoning_content/thoughts are intentionally neither stored nor published.
    if not finished:raise ValueError('Interrupted stream')
    message={'content':text}
    if tool_seen:message['tool_calls']=[{'type':'function','id':identifier or 'call_sf_read','function':{'name':name,'arguments':arguments}}]
    result=completion(message)
    if not result.content and result.draft is None:raise ValueError('Empty completion')
    return result
