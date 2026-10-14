"""Bounded assistant turn runtime: request, read, repair, prepare, then answer.

All writes remain in the authenticated confirmation endpoint. Runtime validation
is pure; business validation and frozen review creation run after this returns.
"""
import json
import re
import time
import httpx
from fastapi import HTTPException
from .models import Conversation
from .ledger import get_scoped
from .ai_parameters import parameters
from .ai_usage import tracked_stream
from .ai_errors import ensure_response,AIRequestError
from .assistant_response import AssistantReply,completion,completion_choice,read_stream,assistant_message,request_messages,MAX_RESPONSE_BYTES
from .ai_diagnostics import record
from .chat_stream import publish
from .chat_stop import check as check_stop
from .assistant_tools import catalog,Toolkit,validate_draft,canonical_read
from pydantic import ValidationError

def converse(db,job,p,client,url,headers,extensions,messages,deadline,read_budget,sandbox=None):
    from .assistant_finance import read
    room=sandbox.room if sandbox else get_scoped(db,Conversation,job.workspace_id,job.payload['conversation_id'])
    if not sandbox:
        from .assistant_data import authorize
        authorize(db,job,room)
    turns=list(messages)
    from . import assistant_evidence as evidence
    task=evidence.Scope('mutation' if sandbox.case in ('transaction','followup','receipt') else 'query','') if sandbox else evidence.scope(db,room,job.payload.get('text',''))
    job._suppress_preview=True
    from .assistant_questions import for_turn,remember
    clear_question=None if sandbox or job.payload.get('attachment_id') else for_turn(db,room,job)
    def recovered():
        if not clear_question:return None
        record(job,'synthesis',status='ok')
        remember(room,job,clear_question)
        if clear_question.question:return AssistantReply(clear_question.question)
        content=evidence.grounded(db,room,job,clear_question.scope(db,room),{})
        if (room.capture_context or {}).get('verified_scope'):
            room.capture_context={**room.capture_context,'verified_scope':{**room.capture_context['verified_scope'],'source_user_message_id':job.payload.get('user_message_id'),'read_kind':'period','include_items':clear_question.include_items}}
        return AssistantReply(content)
    if clear_question:
        check_stop(job,True)
        return recovered()
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
        turns.extend([assistant_message(answer),{'role':'tool','tool_call_id':answer.call_id,'content':json.dumps(result,ensure_ascii=False)}])
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
        body={'model':p.model,'messages':request_messages(turns),**parameters(p),'stream':True}
        if not final:body.update(tools=sandbox.tools if sandbox else catalog(active),tool_choice='auto',parallel_tool_calls=False)
        publish(job,'start')
        publish(job,'progress',stage='summarizing' if final else stage)
        with tracked_stream(db,job,p,client,'POST',url.rstrip('/')+'/chat/completions',headers=headers,extensions=extensions,json=body,timeout=httpx.Timeout(min(p.timeout_seconds,remaining),connect=5)) as response:
            ensure_response(response)
            if 'text/event-stream' in response.headers.get('content-type',''):answer=read_stream(response,job)
            else:
                raw=b''
                for chunk in response.iter_bytes():
                    raw+=chunk
                    if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('Response too large')
                answer=completion_choice(json.loads(raw)['choices'][0])
        return answer
    def finish():
        record(job,'synthesis',status='ok');publish(job,'progress',stage='summarizing')
        if getattr(job,'_direct_finance_read',False) and getattr(job,'_direct_evidence',None):
            from .assistant_data import fallback
            return AssistantReply(fallback(job))
        return AssistantReply(sandbox.finish('',getattr(job,'_read_cache',{})) if sandbox else evidence.grounded(db,room,job,task,getattr(job,'_read_cache',{})))
    for _ in range(7):
        try:answer=request()
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as error:
            # A failed language-model continuation does not invalidate a completed
            # authorized ledger read. Keep its exact scoped report and references.
            # Lab must still expose the provider failure; it is not a fallback test.
            check_stop(job,True)
            if sandbox:raise
            direct=getattr(job,'_direct_finance_read',False) and getattr(job,'_direct_evidence',None)
            from .assistant_data import identity
            cache=getattr(job,'_read_cache',{})
            cached=bool(cache) and getattr(job,'_read_cache_actor',None)==identity(job)
            if not direct and not cached:raise
            from .ai_errors import diagnose
            record(job,'provider_error',provider_id=p.id,error=diagnose(error),status='failed')
            record(job,'synthesis',status='limited',error=diagnose(error))
            if direct:return finish()
            if task.kind=='mutation':return AssistantReply('ฉันอ่านข้อมูลที่เกี่ยวข้องได้แล้ว แต่ยังเตรียมร่างไม่สำเร็จค่ะ ยังไม่ได้บันทึกหรือแก้ข้อมูล')
            from .assistant_balance_reply import fallback as balance_fallback
            content=balance_fallback(cache) or evidence.grounded(db,room,job,evidence.Scope('query',''),cache)
            return AssistantReply(content)
        if not answer.tool_name and claims_review(answer.content):
            if repaired:return AssistantReply(UNPREPARED)
            repaired=True;record(job,'review_repair',status='invalid')
            turns.extend([assistant_message(answer),{'role':'system','content':REPAIR}])
            continue
        if not answer.tool_name and getattr(job,'_direct_evidence',None) and (getattr(job,'_direct_finance_read',False) or task.error or task.kind in ('query','conversation')):
            from .assistant_data import natural,fallback
            try:content=natural(job,answer.content)
            except ValueError:
                repairs+=1;record(job,'synthesis',status='invalid');publish(job,'progress',stage='repairing')
                if repairs>=2:return AssistantReply(fallback(job))
                turns.extend([assistant_message(answer),{'role':'system','content':'ปรับคำตอบให้ตรงข้อมูลที่อ่านจริง บอกผลที่ผู้ใช้ถามพร้อมยอดรวมที่เกี่ยวข้องก่อนเสนอคำถามต่อ อย่าตอบแค่ชวนคุย ตอบภาษาปกติได้ ไม่ต้องใช้แม่แบบ อย่าใส่ตัวเลขที่ไม่มีในข้อมูล และอย่าอ้างว่าได้บันทึก/แก้ไขข้อมูล ถ้าข้อมูลไม่พอเรียกเครื่องมืออ่านเพิ่ม'}])
                continue
            record(job,'synthesis',status='ok')
            return AssistantReply(content)
        if not answer.tool_name and task.kind=='mutation' and not re.search(r'ไหน|อะไร|เท่าไร|เท่าไหร่|\?',answer.content):
            if repaired:return AssistantReply(UNPREPARED)
            repaired=True;record(job,'review_repair',status='invalid')
            turns.extend([assistant_message(answer),{'role':'system','content':REPAIR}])
            continue
        if answer.tool_name and answer.tool_name not in ('respond_finance','understand_request'):
            job.__dict__.pop('_semantic_evidence',None)
        if answer.tool_name=='fetch_finance':
            from .assistant_data import read as fetch,fallback
            if read_budget[0]>=3:return AssistantReply(fallback(job)) if getattr(job,'_direct_evidence',None) else finish()
            from .request_interpreter import NeedInfo
            try:result=sandbox.fetch(answer.draft,job) if sandbox else fetch(db,room,job,answer.draft)
            except (ValidationError,ValueError,HTTPException,NeedInfo) as error:
                from .tool_arguments import feedback as argument_feedback
                from .assistant_calendar import argument_help
                if sandbox:sandbox.problem(error)
                invalid(answer,dict(error='invalid_arguments',**argument_help(),**argument_feedback(error)))
                if repairs>=2:return AssistantReply(fallback(job)) if getattr(job,'_direct_evidence',None) else AssistantReply('ฉันยังค้นข้อมูลส่วนนี้ไม่สำเร็จค่ะ อยากให้ดูบัญชีหรือช่วงไหนเป็นพิเศษคะ?')
                continue
            job._direct_finance_read=True
            record(job,'tool',tool=answer.tool_name,status='ok',resources=[json.loads(answer.draft)['resource']]);read_budget[0]+=1
            if result.get('items') is not None:active.add('corrections')
            feedback(answer,result)
            continue
        if answer.tool_name=='respond_finance':
            from .semantic_assistant import respond
            try:
                if getattr(job,'_direct_evidence',None):
                    from .assistant_data import natural
                    from .semantic_assistant import Answer
                    content=natural(job,Answer.model_validate_json(answer.draft).text)
                else:content=respond(job,answer.draft)
            except (ValidationError,ValueError):
                invalid(answer,dict(error='invalid_arguments',message='ตอบภาษาปกติได้ แต่ตัวเลขต้องตรงข้อมูลที่อ่าน ไม่อ้างผลบันทึกหรือแก้ไขที่ไม่ได้ทำ ตรวจข้อมูลหรืออ่านเพิ่มเองก่อนตอบ'))
                if repairs>=2:return finish() if getattr(job,'_direct_evidence',None) else AssistantReply(getattr(job,'_semantic_evidence',{}).get('fallback') or evidence.UNVERIFIED)
                continue
            record(job,'tool',tool=answer.tool_name,status='ok')
            return AssistantReply(content)
        if answer.tool_name=='understand_request':
            if not sandbox:authorize(db,job,room)
            from .semantic_assistant import plan,prepare,clarification,general_reply
            job.__dict__.pop('_semantic_evidence',None)
            from .request_interpreter import NeedInfo,QUESTIONS
            try:
                interpreted,reply,kit=sandbox.semantic_plan(answer.draft) if sandbox else plan(db,room,job,answer.draft)
                if interpreted is not None:task=interpreted
                if reply is not None:
                    if task.kind=='conversation' and interpreted is not None:return AssistantReply(general_reply(reply,job.payload.get("text","")))
                    record(job,'tool',tool=answer.tool_name,status='ok')
                    return AssistantReply(reply)
                if task.kind=='mutation':
                    if kit:active.add(kit);job._assistant_toolkits=sorted(active)
                    feedback(answer,dict(intent='mutation',toolkit=kit,message='เตรียมร่างด้วย tools ที่มี รอยืนยันจากผู้ใช้เท่านั้น'))
                    continue
                if read_budget[0]>=3:return finish()
                result=sandbox.semantic_prepare(job,task) if sandbox else prepare(db,room,job,task)
                from .assistant_data import remember
                remember(job,dict(job._semantic_evidence));job._direct_finance_read=True
            except NeedInfo as missing:
                result=dict(error='missing_or_ambiguous',issues=[dict(field=missing.field,code='unknown_reference')],
                    message='ตรวจข้อความและบริบทแล้วแก้แผนก่อน ถ้าเป็นชื่อใช้ lookup_workspace ค้นชื่อจริง ถ้ากำกวมจริงใช้ clarify พร้อม question ธรรมชาติเฉพาะจุด ห้ามสั่งผู้ใช้กรอก format')
                invalid(answer,result)
                if repairs>=2:return AssistantReply(clarification(db,room,missing.field))
                continue
            except (ValidationError,ValueError,HTTPException) as error:
                from .tool_arguments import feedback as argument_feedback
                from .assistant_calendar import argument_help
                if sandbox:sandbox.problem(error)
                invalid(answer,dict(error='invalid_arguments',**argument_help(),**argument_feedback(error)))
                if repairs>=2:return AssistantReply(clarification(db,room,'intent'))
                continue
            record(job,'tool',tool=answer.tool_name,status='ok')
            read_budget[0]+=1
            active.add('conversation_answer')
            feedback(answer,result)
            continue
        if answer.tool_name=='interpret_request':
            if not sandbox:authorize(db,job,room)
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
            if not sandbox:authorize(db,job,room)
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
        if cache is None:
            from .assistant_data import identity
            cache={};job._read_cache=cache;job._read_cache_actor=identity(job)
        key=canonical_read(answer.tool_name,answer.draft)
        if key is not None and key in cache:
            record(job,'tool',tool=answer.tool_name,status='cached')
            feedback(answer,cache[key])
            return finish()
        stage='lookup';publish(job,'progress',stage=stage)
        if not sandbox:
            from .assistant_data import authorize
            authorize(db,job,room)
        if answer.tool_name=='lookup_workspace':
            from .assistant_lookup import read as lookup
            result=sandbox.lookup(answer.draft) if sandbox else lookup(db,room,answer.draft)
        else:result=sandbox.finance(answer.draft) if sandbox else read(db,room,answer.draft,job.payload.get('user_message_id'))
        if result.get('error'):
            invalid(answer,result)
            if repairs>=2:return AssistantReply('ฉันยังค้นข้อมูลตามเงื่อนไขนี้ไม่สำเร็จค่ะ ช่วยระบุช่วงวันหรือชื่อบัญชีที่ต้องการอีกนิดได้ไหมคะ? ยังไม่ได้เปลี่ยนข้อมูล')
            continue
        from .assistant_data import remember_lookup
        if answer.tool_name=='lookup_workspace':remember_lookup(job,result)
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
        feedback(answer,result)
    return finish()

