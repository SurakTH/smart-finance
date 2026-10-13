"""Bounded assistant turn runtime: request, read, repair, prepare, then answer.

All writes remain in the authenticated confirmation endpoint. Runtime validation
is pure; business validation and frozen review creation run after this returns.
"""
import json
import re
import time
import httpx
from .models import Conversation
from .ledger import get_scoped
from .ai_parameters import parameters
from .ai_usage import tracked_stream
from .ai_errors import ensure_response,AIRequestError
from .assistant_response import AssistantReply,completion,completion_choice,read_stream
from .ai_diagnostics import record
from .chat_stream import publish
from .chat_stop import check as check_stop
from .assistant_tools import catalog,Toolkit,validate_draft,canonical_read
from pydantic import ValidationError

def converse(db,job,p,client,url,headers,extensions,messages,deadline,read_budget,sandbox=None):
    from .assistant_finance import read
    room=sandbox.room if sandbox else get_scoped(db,Conversation,job.workspace_id,job.payload['conversation_id'])
    turns=list(messages)
    from . import assistant_evidence as evidence
    task=evidence.Scope('mutation' if sandbox.case in ('transaction','followup','receipt') else 'query','') if sandbox else evidence.scope(db,room,job.payload.get('text',''))
    job._suppress_preview=True
    def checked(answer):
        record(job,'synthesis',status='ok')
        return AssistantReply(sandbox.finish(answer.content,getattr(job,'_read_cache',{})) if sandbox else evidence.finish(db,room,job,task,answer.content,getattr(job,'_read_cache',{})))
    from .assistant_contract import claims_review,REPAIR,UNPREPARED
    repaired=False;repairs=0;stage='thinking';active=set(getattr(job,'_assistant_toolkits',[]))
    pending=(room.capture_context or {}).get('review_action_id')
    if pending:
        from .models import ChatAction
        action=db.get(ChatAction,pending)
        if action and action.workspace_id==room.workspace_id and action.conversation_id==room.id and action.status=='pending' and action.payload.get('type')=='management':active.add('management')
    def feedback(answer,result):
        turns.extend([{'role':'assistant','content':None,'tool_calls':[{'id':answer.call_id,'type':'function','function':{'name':answer.tool_name,'arguments':answer.draft}}]},{'role':'tool','tool_call_id':answer.call_id,'content':json.dumps(result,ensure_ascii=False)}])
    def invalid(answer,result):
        nonlocal repairs,stage
        stage='repairing'
        repairs+=1;record(job,'tool',tool=answer.tool_name,status='invalid',issues=result.get('issues',[]))
        publish(job,'progress',stage='repairing')
        feedback(answer,result)
    def request(final=False):
        check_stop(job,True)
        remaining=deadline-time.monotonic()
        if remaining<=0:raise AIRequestError('timeout')
        used=getattr(job,'_assistant_requests',0)
        if used>=8:raise AIRequestError('turn_limit')
        job._assistant_requests=used+1
        body={'model':p.model,'messages':turns,**parameters(p),'stream':True}
        if not final:body.update(tools=sandbox.tools if sandbox else catalog(active),tool_choice='auto')
        publish(job,'start')
        publish(job,'progress',stage='summarizing' if final else stage)
        with tracked_stream(db,job,p,client,'POST',url.rstrip('/')+'/chat/completions',headers=headers,extensions=extensions,json=body,timeout=httpx.Timeout(min(p.timeout_seconds,remaining),connect=5)) as response:
            ensure_response(response)
            if 'text/event-stream' in response.headers.get('content-type',''):answer=read_stream(response,job)
            else:
                raw=b''
                for chunk in response.iter_bytes():
                    raw+=chunk
                    if len(raw)>256000:raise ValueError('Response too large')
                answer=completion_choice(json.loads(raw)['choices'][0])
        return answer
    def finish():
        record(job,'synthesis',status='ok');publish(job,'progress',stage='summarizing')
        return AssistantReply(sandbox.finish('',getattr(job,'_read_cache',{})) if sandbox else evidence.grounded(db,room,job,task,getattr(job,'_read_cache',{})))
    for _ in range(7):
        answer=request()
        if not answer.tool_name and (claims_review(answer.content) or (task.kind=='mutation' and not re.search(r'ไหน|อะไร|เท่าไร|เท่าไหร่|\?',answer.content))):
            if repaired:return AssistantReply(UNPREPARED)
            repaired=True;record(job,'review_repair',status='invalid')
            turns.extend([{'role':'assistant','content':answer.content},{'role':'system','content':REPAIR}])
            continue
        if answer.tool_name=='interpret_request':
            if sandbox:raise ValueError('Unexpected sandbox interpreter')
            from .request_interpreter import interpret,NeedInfo,QUESTIONS
            try:
                interpreted,reply,kit=interpret(db,room,job,answer.draft)
            except NeedInfo as missing:
                from .request_interpreter import remember_clarification
                remember_clarification(db,room,job,missing.field)
                record(job,'tool',tool='interpret_request',status='invalid')
                return AssistantReply(QUESTIONS[missing.field])
            except (ValidationError,ValueError) as error:
                from .tool_arguments import issues
                invalid(answer,dict(error='invalid_arguments',issues=issues(error) if isinstance(error,ValidationError) else [],message='ส่งเจตนา วันที่ และตัวกรองตาม schema อ้างคำจากข้อความผู้ใช้เท่านั้น ห้ามใส่ tenant/user/SQL ถ้ากำกวมใช้ clarify'))
                if repairs>=2:return AssistantReply(QUESTIONS['intent'])
                continue
            record(job,'tool',tool='interpret_request',status='ok')
            if interpreted is not None:task=interpreted
            if reply is not None:
                return checked(AssistantReply(reply)) if interpreted and interpreted.kind=='conversation' else AssistantReply(reply)
            if task.kind!='mutation':
                publish(job,'progress',stage='summarizing')
                return AssistantReply(evidence.grounded(db,room,job,task,getattr(job,'_read_cache',{})))
            if kit:active.add(kit);job._assistant_toolkits=sorted(active)
            feedback(answer,dict(intent='mutation',toolkit=kit,message='ยังไม่ได้เปลี่ยนข้อมูล เตรียมร่างด้วยเครื่องมือที่มีและรอผู้ใช้ยืนยัน ห้ามยืนยันเอง'))
            continue
        if answer.tool_name=='answer_finance_summary':
            from .assistant_summary import answer as summary_answer
            try:
                from .assistant_summary import parse
                summary=parse(answer.draft)
                if not sandbox and not task.error:
                    # Model arguments cannot replace an independently resolved user scope.
                    if task.kind=='balance' and summary.report!='balances':raise ValueError('scope mismatch')
                    if task.kind in ('period','budget','comparison') and (summary.report!='monthly' or (summary.month and summary.month!=task.start.strftime('%Y-%m'))):raise ValueError('scope mismatch')
                content=sandbox.summary(answer.draft) if sandbox else evidence.grounded(db,room,job,task,getattr(job,'_read_cache',{}))
            except ValueError:
                invalid(answer,dict(error='invalid_arguments',message='เลือก report balances โดยไม่ใส่ month หรือ monthly พร้อมเดือน YYYY-MM ที่ถูกต้อง เว้น month เพื่อใช้เดือนนี้'))
                if repairs>=2:return AssistantReply('ยังอ่านรายงานตามเงื่อนไขนี้ไม่ได้ค่ะ ระบุเดือนที่ต้องการอีกครั้งได้ไหมคะ?')
                continue
            record(job,'tool',tool=answer.tool_name,status='ok')
            publish(job,'progress',stage='summarizing')
            return AssistantReply(content)
        if answer.tool_name=='load_toolkit' and sandbox:raise ValueError('Unexpected sandbox toolkit')
        if answer.tool_name=='load_toolkit':
            try:kit=Toolkit.model_validate_json(answer.draft).toolkit
            except ValidationError as error:
                from .tool_arguments import issues
                invalid(answer,dict(error='invalid_arguments',issues=issues(error),message='เลือก toolkit management หรือ corrections'))
                if repairs>=2:return AssistantReply('ฉันยังเลือกเครื่องมือสำหรับงานนี้ไม่สำเร็จค่ะ บอกงานที่ต้องการอีกครั้งได้เลย ยังไม่ได้เปลี่ยนข้อมูล')
                continue
            if kit in active:return finish()
            active.add(kit);job._assistant_toolkits=sorted(active)
            record(job,'tool',tool='load_toolkit',status='ok')
            feedback(answer,dict(available=True,toolkit=kit,message='เครื่องมือชุดนี้พร้อมในคำขอถัดไป ใช้เพื่อเตรียมร่างตามคำขอผู้ใช้เท่านั้น'))
            continue
        if answer.tool_name not in ('query_finance','lookup_workspace'):
            if answer.tool_name:
                publish(job,'progress',stage='checking_draft')
                problem=sandbox.validate(answer.tool_name,answer.draft) if sandbox else validate_draft(db,room,answer.tool_name,answer.draft)
                if problem:
                    invalid(answer,problem)
                    if repairs>=2:
                        prefix={'prepare_correction':'ยังเตรียมการแก้ไขไม่ได้','prepare_management_plan':'ยังเตรียมแผนนี้ไม่ได้'}.get(answer.tool_name,'ยังเตรียมรายการนี้ไม่ได้')
                        return AssistantReply(prefix+'ค่ะ ข้อมูลร่างยังไม่ครบหรือไม่ตรง ช่วยระบุบัญชี หมวด หรือรายละเอียดที่ต้องการอีกครั้งได้ไหมคะ? ยังไม่ได้เปลี่ยนข้อมูล')
                    continue
                if answer.tool_name=='prepare_transaction':
                    from .chat_dialogue import Suggestion
                    value=Suggestion.model_validate_json(answer.draft)
                    if value.intent=='chat':
                        if claims_review(value.reply or ''):return AssistantReply(UNPREPARED)
                        return checked(AssistantReply(value.reply or 'อยากให้ช่วยดูเรื่องไหนคะ?'))
                record(job,'tool',tool=answer.tool_name,status='ok')
            return answer if answer.tool_name else checked(answer)
        if read_budget[0]>=3:return finish()
        cache=getattr(job,'_read_cache',None)
        if cache is None:cache={};job._read_cache=cache
        key=canonical_read(answer.tool_name,answer.draft)
        if key is not None and key in cache:
            record(job,'tool',tool=answer.tool_name,status='cached')
            feedback(answer,cache[key])
            return finish()
        stage='lookup';publish(job,'progress',stage=stage)
        if answer.tool_name=='lookup_workspace':
            from .assistant_lookup import read as lookup
            result=sandbox.lookup(answer.draft) if sandbox else lookup(db,room,answer.draft)
        else:result=sandbox.finance(answer.draft) if sandbox else read(db,room,answer.draft,job.payload.get('user_message_id'))
        if result.get('error'):
            invalid(answer,result)
            if repairs>=2:return AssistantReply('ฉันยังค้นข้อมูลตามเงื่อนไขนี้ไม่สำเร็จค่ะ ช่วยระบุช่วงวันหรือชื่อบัญชีที่ต้องการอีกนิดได้ไหมคะ? ยังไม่ได้เปลี่ยนข้อมูล')
            continue
        read_budget[0]+=1
        if answer.tool_name=='query_finance':
            for old in list(cache):
                if old[0]=='query_finance':cache.pop(old)
            if json.loads(answer.draft).get('operation')=='search_transactions':active.add('corrections')
        if key is not None:cache[key]=result
        record(job,'tool',tool=answer.tool_name,status='invalid' if result.get('error') else 'ok',issues=result.get('issues',[]),resources=[r.get('resource') for r in result.get('results',[])]+([result.get('operation')] if result.get('operation') else []))
        if answer.tool_name=='lookup_workspace' and not sandbox:
            from .assistant_lookup import remember_pages
            remember_pages(room,answer.draft,result)
        from .finance_references import collect
        collect(job,result)
        turns.append({'role':'assistant','content':None,'tool_calls':[{'id':answer.call_id,'type':'function','function':{'name':answer.tool_name,'arguments':answer.draft}}]})
        turns.append({'role':'tool','tool_call_id':answer.call_id,'content':json.dumps(result,ensure_ascii=False)})
    return finish()

