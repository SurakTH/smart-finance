"""Bounded assistant turn runtime: request, read, repair, prepare, then answer.

All writes remain in the authenticated confirmation endpoint. Runtime validation
is pure; business validation and frozen review creation run after this returns.
"""
import json
import re
import time
import httpx
from fastapi import HTTPException
from .models import Conversation,Message
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
from .assistant_limits import REQUESTS,READS

def converse(db,job,p,client,url,headers,extensions,messages,deadline,read_budget,sandbox=None):
    from .assistant_finance import read
    room=sandbox.room if sandbox else get_scoped(db,Conversation,job.workspace_id,job.payload['conversation_id'])
    if not sandbox:
        from .assistant_data import authorize
        authorize(db,job,room)
    from sqlalchemy import select
    room_has_image=True if sandbox else bool(db.scalar(select(Message.id).where(Message.workspace_id==room.workspace_id,Message.conversation_id==room.id,Message.role=='user',Message.attachment_id.is_not(None)).limit(1)))
    turns=list(messages)
    from . import assistant_evidence as evidence
    # The model owns intent and topic selection. Legacy keyword scopes are only
    # used by explicit legacy tools, never to route or replace a model turn.
    task=evidence.Scope(('mutation' if sandbox.case in ('transaction','followup','receipt') else 'query') if sandbox else 'conversation','')
    job._suppress_preview=True
    def checked(answer):
        record(job,'synthesis',status='ok')
        if sandbox:return AssistantReply(sandbox.finish(answer.content,getattr(job,'_read_cache',{})))
        if getattr(job,'_read_cache',None):return AssistantReply(evidence.finish(db,room,job,task,answer.content,job._read_cache))
        from .semantic_assistant import general_reply
        return AssistantReply(general_reply(answer.content,job.payload.get('text','')))
    from .assistant_contract import claims_review,promises_partial_draft,PARTIAL_REPAIR,REPAIR,UNPREPARED
    receipt_planned=False;capture_checked=False;repair_base=None;reference_ids=False;repaired=False;repairs=0;stage='thinking';active=set(getattr(job,'_assistant_toolkits',[]))
    from .receipt_reader import current as receipt_current
    receipt_document=(getattr(job,'_receipt_reading',None) or {}).get('document') or receipt_current(room,getattr(job,'_receipt_id',None))
    if receipt_document and receipt_document.get('is_receipt'):active.add('receipt_answer')
    pending=(room.capture_context or {}).get('review_action_id')
    if pending:
        from .models import ChatAction
        action=db.get(ChatAction,pending)
        if action and action.workspace_id==room.workspace_id and action.conversation_id==room.id and action.status=='pending' and action.payload.get('type')=='management':active.add('management')
    queued=[];batched_ids=set();merged_batches={};require_tool=False;structured=False;repair_batch=False
    def feedback(answer,result):
        batch=merged_batches.pop(answer.call_id,None)
        if batch:
            turns.append(assistant_message(batch))
            for call in batch.calls:turns.append({'role':'tool','tool_call_id':call.call_id,'content':json.dumps(result,ensure_ascii=False)})
            return
        if answer.call_id not in batched_ids:turns.append(assistant_message(answer))
        turns.append({'role':'tool','tool_call_id':answer.call_id,'content':json.dumps(result,ensure_ascii=False)})
    def invalid(answer,result):
        nonlocal repairs,stage,require_tool,repair_base,repair_batch
        stage='repairing'
        if answer.tool_name=='fetch_finance' and result.get('error')=='balance_filters':require_tool=True
        if answer.tool_name=='prepare_transaction':
            require_tool=True
            try:
                items=json.loads(answer.draft).get('transactions')
                if isinstance(items,list) and 2<=len(items)<=10:repair_batch=True
            except (ValueError,AttributeError,TypeError):pass
            if not sandbox:
                from .assistant_tools import repair_seed
                repair_base=repair_seed(db,room,answer.draft,result) or repair_base
        repairs+=1;record(job,'tool',tool=answer.tool_name,status='invalid',issues=result.get('issues',[]))
        publish(job,'progress',stage='repairing')
        feedback(answer,result)
    def request(final=False):
        nonlocal structured
        check_stop(job,True)
        remaining=deadline-time.monotonic()
        if remaining<=0:raise AIRequestError('timeout')
        used=getattr(job,'_assistant_requests',0)
        if used>=REQUESTS:raise AIRequestError('turn_limit')
        job._assistant_requests=used+1
        body={'model':p.model,'messages':request_messages(turns),**parameters(p),'stream':True}
        if p.kind=='ollama':body['stream_options']={'include_usage':True}
        tools=sandbox.tools if sandbox else catalog(active)
        if not sandbox and not reference_ids:
            from .assistant_tools import name_first_tools
            tools=name_first_tools(tools)
        if not sandbox and not room_has_image:
            from .assistant_tools import without_image_fields
            tools=without_image_fields(tools)
        if not final and p.kind=='ollama' and not sandbox and require_tool:structured=True
        if not final and structured:
            from .assistant_protocol import messages as protocol_messages,schema as protocol_schema
            body['messages']=protocol_messages(turns,tools)
            body['response_format']={'type':'json_schema','json_schema':{'name':'assistant_action','strict':True,'schema':protocol_schema(tools,require_tool,repair_batch)}}
        elif not final:body.update(tools=tools,tool_choice='required' if require_tool else 'auto',parallel_tool_calls=False)
        publish(job,'start')
        publish(job,'progress',stage='summarizing' if final else stage)
        try:
            with tracked_stream(db,job,p,client,'POST',url.rstrip('/')+'/chat/completions',headers=headers,extensions=extensions,json=body,timeout=httpx.Timeout(min(p.timeout_seconds,remaining),connect=5)) as response:
                ensure_response(response)
                if 'text/event-stream' in response.headers.get('content-type',''):answer=read_stream(response,job)
                else:
                    raw=b''
                    for chunk in response.iter_bytes():
                        raw+=chunk
                        if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('Response too large')
                    answer=completion_choice(json.loads(raw)['choices'][0])
        except (ValueError,KeyError,TypeError,IndexError) as error:
            from .ai_usage import BudgetExceeded
            eligible=not isinstance(error,(AIRequestError,BudgetExceeded)) or (isinstance(error,AIRequestError) and (error.http_status==500 or error.code=='invalid_response'))
            if not eligible or final or structured or p.kind!='ollama' or sandbox or getattr(job,'_direct_evidence',None) or getattr(job,'_read_cache',None):raise
            structured=True
            record(job,'fallback',provider_id=p.id,status='limited',error=getattr(error,'code','invalid_response'))
            return request(final)
        if not final and structured:
            from .assistant_protocol import reply as protocol_reply
            answer=protocol_reply(answer,tools,require_tool,'structured_'+str(job._assistant_requests))
        return answer
    def finish():
        record(job,'synthesis',status='ok');publish(job,'progress',stage='summarizing')
        if getattr(job,'_direct_finance_read',False) and getattr(job,'_direct_evidence',None):
            from .assistant_data import fallback
            return AssistantReply(fallback(job))
        cache=getattr(job,'_read_cache',{})
        from .assistant_balance_reply import fallback as balance_fallback
        latest_balance=balance_fallback(dict([list(cache.items())[-1]])) if cache else None
        return AssistantReply(sandbox.finish('',cache) if sandbox else latest_balance or evidence.grounded(db,room,job,task,cache))
    for _ in range(REQUESTS*3):
        try:
            if queued:answer=queued.pop(0)
            else:
                batched_ids.clear()
                merged_batches.clear()
                answer=request()
            if answer.calls:
                batch=answer
                if all(c.tool_name=='prepare_transaction' for c in batch.calls):
                    from .assistant_tools import merge_transaction_calls
                    try:
                        answer=AssistantReply('',merge_transaction_calls(batch.calls),'prepare_transaction',batch.calls[0].call_id)
                        merged_batches[answer.call_id]=batch
                    except (ValueError,ValidationError):answer=batch
                if answer is not batch:pass
                elif any(c.tool_name not in ('lookup_workspace','fetch_finance') for c in batch.calls):
                    turns.append(assistant_message(batch))
                    batched_ids.update(c.call_id for c in batch.calls)
                    for call in answer.calls:
                        feedback(call,dict(error='sequential_required',message='Read-only calls may be batched. Prepare exactly one draft after reading its references; do not combine prepare with other calls.'))
                    repairs+=1
                    if repairs>=2:return finish()
                    continue
                else:
                    turns.append(assistant_message(batch))
                    batched_ids.update(c.call_id for c in batch.calls)
                    queued.extend(batch.calls)
                    answer=queued.pop(0)
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
        if not answer.tool_name and not receipt_planned and p.kind=='ollama' and job.payload.get('attachment_id') and receipt_document and receipt_document.get('is_receipt'):
            # A small model can ask for an already uploaded image or a choice
            # without creating a real partial draft. Resolve the receipt intent
            # once through the bounded structured adapter, not keyword routing.
            from .receipt_reader import plan as receipt_plan,explain
            receipt_planned=True
            decision=receipt_plan(db,room,job,p,client,url,headers,extensions,receipt_document,deadline)
            if decision.action=='answer':return AssistantReply(explain(receipt_document))
            if decision.action=='prepare':
                draft=decision.model_dump(mode='json',exclude_none=True,exclude={'action'})
                draft.update(intent='create',attachment_id=job.payload['attachment_id'])
                answer=AssistantReply('',json.dumps(draft,ensure_ascii=False),'prepare_transaction','receipt_plan_'+str(job._assistant_requests))
        partial_promise=not sandbox and not answer.tool_name and promises_partial_draft(answer.content)
        if not answer.tool_name and (claims_review(answer.content) or partial_promise):
            if repaired:return AssistantReply(UNPREPARED)
            repaired=True;require_tool=True;record(job,'review_repair',status='invalid')
            turns.append({'role':'system','content':PARTIAL_REPAIR if partial_promise else REPAIR})
            continue
        if not sandbox and not answer.tool_name and not getattr(job,'_direct_evidence',None) and not getattr(job,'_read_cache',None):
            from .semantic_assistant import general_reply
            if general_reply(answer.content,job.payload.get('text',''))==evidence.UNVERIFIED:
                repairs+=1
                if repairs>=2:return AssistantReply(evidence.UNVERIFIED)
                # The answer claimed personalized figures without a read. Let
                # the model choose the right tool, but require evidence now.
                require_tool=True
                turns.append({'role':'system','content':'ตัวเลขการเงินนี้ยังไม่มีหลักฐานจาก tools ถ้าเป็นข้อมูลของผู้ใช้ ให้เลือกเรียก fetch_finance/lookup_workspace ที่ตรงเจตนาเองก่อนตอบ ห้ามเดายอด ไม่ต้องให้ผู้ใช้เปลี่ยนรูปแบบคำพูด หากเป็นข้อมูลจากรูปที่ต้องบันทึกให้ prepare_transaction เพื่อเก็บร่าง'})
                turns.append({'role':'user','content':'[Backend evidence check] คำตอบที่ยังไม่ได้ส่งให้ผู้ใช้ไม่มีข้อมูลจากเครื่องมือรองรับ โปรดเรียกเครื่องมือที่ตรงกับคำขอล่าสุดและบริบทก่อนตอบ ห้ามใช้ยอดในข้อความเก่ามาแทนการอ่านช่วงใหม่'})
                continue
        if not answer.tool_name and getattr(job,'_direct_evidence',None) and (getattr(job,'_direct_finance_read',False) or task.error or task.kind in ('query','conversation')):
            from .assistant_data import natural,fallback
            try:content=natural(job,answer.content)
            except ValueError:
                repairs+=1;record(job,'synthesis',status='invalid');publish(job,'progress',stage='repairing')
                if repairs>=2:return AssistantReply(fallback(job))
                turns.append({'role':'system','content':'ปรับคำตอบให้ตรงข้อมูลที่อ่านจริง บอกผลที่ผู้ใช้ถามพร้อมยอดรวมที่เกี่ยวข้องก่อนเสนอคำถามต่อ อย่าตอบแค่ชวนคุย ตอบภาษาปกติได้ ไม่ต้องใช้แม่แบบ อย่าใส่ตัวเลขที่ไม่มีในข้อมูล และอย่าอ้างว่าได้บันทึก/แก้ไขข้อมูล ถ้าข้อมูลไม่พอเรียกเครื่องมืออ่านเพิ่ม'})
                continue
            record(job,'synthesis',status='ok')
            return AssistantReply(content)
        if not answer.tool_name and task.kind=='mutation' and not re.search(r'ไหน|อะไร|เท่าไร|เท่าไหร่|\?',answer.content):
            if repaired:return AssistantReply(UNPREPARED)
            repaired=True;require_tool=True;record(job,'review_repair',status='invalid')
            turns.append({'role':'system','content':REPAIR})
            continue
        if answer.tool_name and answer.tool_name not in ('respond_finance','understand_request'):
            require_tool=False
            job.__dict__.pop('_semantic_evidence',None)
        if answer.tool_name=='render_receipt':
            from .receipt_reader import explain
            try:
                if not receipt_document or json.loads(answer.draft)!={}:raise ValueError('No receipt in scope')
                content=explain(receipt_document)
            except (ValueError,TypeError):
                invalid(answer,dict(error='invalid_arguments',message='render_receipt takes no arguments and requires a receipt in this room.'))
                if repairs>=2:return finish()
                continue
            record(job,'tool',tool='render_receipt',status='ok')
            return AssistantReply(content)
        if answer.tool_name=='render_finance':
            from .assistant_grounding import render
            try:
                if sandbox:raise ValueError('Unexpected sandbox renderer')
                content=render(job,answer.draft)
            except (ValueError,ValidationError) as error:
                from .tool_arguments import feedback as argument_feedback
                datasets=(getattr(job,'_direct_evidence',None) or {}).get('datasets',[])
                if not sandbox and any(d.get('purpose','answer')=='answer' for d in datasets):
                    # The model already chose to show the report. Bad formatting
                    # cannot invalidate an authorized read or justify another call.
                    check_stop(job,True)
                    record(job,'tool',tool='render_finance',status='invalid',issues=argument_feedback(error).get('issues',[]))
                    record(job,'synthesis',status='limited')
                    from .assistant_data import fallback
                    return AssistantReply(fallback(job))
                invalid(answer,dict(error='invalid_arguments',issues=argument_feedback(error)['issues'],
                    message='Read an answering dataset first. Use {} to show the verified report.'))
                if repairs>=2:return finish()
                continue
            record(job,'tool',tool='render_finance',status='ok')
            record(job,'synthesis',status='ok')
            return AssistantReply(content)
        if answer.tool_name=='fetch_finance':
            from .assistant_data import read as fetch,fallback
            if read_budget[0]>=READS:return AssistantReply(fallback(job)) if getattr(job,'_direct_evidence',None) else finish()
            from .request_interpreter import NeedInfo
            try:result=sandbox.fetch(answer.draft,job) if sandbox else fetch(db,room,job,answer.draft)
            except (ValidationError,ValueError,HTTPException,NeedInfo) as error:
                from .tool_arguments import feedback as argument_feedback
                from .assistant_calendar import argument_help
                from .assistant_data import BalanceFilterConflict
                if sandbox:sandbox.problem(error)
                invalid(answer,dict(error='balance_filters' if isinstance(error,BalanceFilterConflict) else 'invalid_arguments',**argument_help(),**argument_feedback(error)))
                if repairs>=2:return AssistantReply(fallback(job)) if getattr(job,'_direct_evidence',None) else AssistantReply('ฉันยังค้นข้อมูลส่วนนี้ไม่สำเร็จค่ะ อยากให้ดูบัญชีหรือช่วงไหนเป็นพิเศษคะ?')
                continue
            job._direct_finance_read=True
            active.add('grounded_answer')
            if not sandbox and getattr(job,'_last_fetch_cached',False):
                counts=getattr(job,'_fetch_repeats',{});key=job._last_fetch_key;counts[key]=counts.get(key,0)+1;job._fetch_repeats=counts
                record(job,'tool',tool=answer.tool_name,status='cached')
                if counts[key]>=2:return finish()
                feedback(answer,dict(cached=True,dataset_id=result['dataset_id'],message='Already read in this turn. Use earlier facts to answer or continue the requested draft; do not fetch the same data again.'))
                continue
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
                if read_budget[0]>=READS:return finish()
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
            # Legacy tool compatibility only; not advertised to the primary agent.
            if not sandbox:task=evidence.scope(db,room,job.payload.get('text',''))
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
            if kit=='receipt':
                from .assistant_images import inspect
                try:image=inspect(db,room,job,p)
                except ValueError:
                    invalid(answer,dict(error='invalid_arguments',message='No authorized available receipt, or this provider cannot read images. Continue using extracted room draft; ask only for genuinely missing details.'))
                    if repairs>=2:return finish()
                    continue
                feedback(answer,dict(available=True,attachment_id=image['attachment_id'],untrusted=True))
                if 'receipt' not in active:turns.append(image['message'])
                else:return finish()
                active.add('receipt');record(job,'tool',tool='load_toolkit',status='ok')
                continue
            if kit in active:return finish()
            active.add(kit);job._assistant_toolkits=sorted(active)
            record(job,'tool',tool='load_toolkit',status='ok')
            feedback(answer,dict(available=True,toolkit=kit,message='เครื่องมือชุดนี้พร้อมในคำขอถัดไป ใช้เพื่อเตรียมร่างตามคำขอผู้ใช้เท่านั้น'))
            continue
        if answer.tool_name not in ('query_finance','lookup_workspace'):
            if answer.tool_name:
                publish(job,'progress',stage='checking_draft')
                if answer.tool_name=='prepare_transaction' and not sandbox:
                    from .chat_dialogue import named_references
                    try:
                        if repair_base:
                            from .assistant_tools import merge_repair
                            answer.draft=merge_repair(answer.draft,repair_base)
                        answer.draft=named_references(db,room,answer.draft)
                    except ValidationError as error:
                        from .tool_arguments import issues
                        invalid(answer,dict(error='invalid_arguments',issues=issues(error),message='Fix these fields using the tool schema. Never ask the user for JSON or satang.'))
                        if repairs>=2:return AssistantReply(UNPREPARED)
                        continue
                    except ValueError as error:
                        from .tool_arguments import feedback as argument_feedback
                        invalid(answer,{**argument_feedback(error),'error':'invalid_reference','message':'Use existing names only. If unknown/ambiguous or user wants to choose, omit that reference and resubmit the remaining partial draft to retain it. Do not replace the draft with a prose question.'})
                        if repairs>=2:return AssistantReply('ฉันยังจับคู่บัญชีหรือหมวดนี้ไม่ได้ค่ะ ช่วยระบุชื่อที่ต้องการอีกนิด ยังไม่ได้บันทึกข้อมูล')
                        continue
                problem=sandbox.validate(answer.tool_name,answer.draft) if sandbox else validate_draft(db,room,answer.tool_name,answer.draft)
                if problem:
                    invalid(answer,problem)
                    if repairs>=2:
                        if problem.get('error')=='invalid_source':
                            if any(issue.get('code')=='unknown_reference' for issue in problem.get('issues',[])):
                                return AssistantReply('ไม่พบรูปนี้ในบทสนทนาของคุณค่ะ ยังไม่ได้บันทึก')
                            return AssistantReply('แหล่งรูปของร่างยังไม่ตรงกันค่ะ ยังไม่ได้บันทึกข้อมูล กรุณาเลือกหรือส่งรูปที่ต้องการอีกครั้ง')
                        prefix={'prepare_correction':'ยังเตรียมการแก้ไขไม่ได้','prepare_management_plan':'ยังเตรียมแผนนี้ไม่ได้'}.get(answer.tool_name,'ยังเตรียมรายการนี้ไม่ได้')
                        return AssistantReply(prefix+'ค่ะ ข้อมูลร่างยังไม่ครบหรือไม่ตรง ช่วยระบุบัญชี หมวด หรือรายละเอียดที่ต้องการอีกครั้งได้ไหมคะ? ยังไม่ได้เปลี่ยนข้อมูล')
                    continue
                if answer.tool_name=='prepare_transaction':
                    from .chat_dialogue import Suggestion
                    value=Suggestion.model_validate_json(answer.draft)
                    if p.kind=='ollama' and not sandbox:
                        from .assistant_amount_source import without_unsourced_amounts
                        grounded=without_unsourced_amounts(db,room,job,value)
                        if grounded is not value:
                            value=grounded
                            answer.draft=value.model_dump_json(exclude_unset=True,exclude_none=True)
                    if (p.kind=='ollama' and not sandbox and not capture_checked and value.intent!='chat'
                        and value.amount is None and value.transactions is None and not value.continue_draft
                        and not job.payload.get('attachment_id')
                        and re.search(r'(?:[0-9๐-๙][0-9๐-๙,.]*\s*(?:บาท|THB)|฿\s*[0-9๐-๙])',job.payload.get('text',''),re.I)):
                        # Presence of currency text only triggers model review. It
                        # never parses/inserts an amount or decides user intent.
                        capture_checked=True
                        invalid(answer,dict(error='check_missing_amount',issues=[dict(field='amount',code='missing')],message='The user message contains currency amounts but the draft omitted amount. Reread the actual request and current draft once. Include the stated transaction amount in satang if present; leave it absent if the numbers are not the requested amount. Never guess from dates or account numbers. Resubmit the draft, not prose.'))
                        continue
                    if p.kind=='ollama' and not sandbox:
                        from .assistant_draft_completion import complete_draft
                        patch=complete_draft(db,room,job,p,client,url,headers,extensions,value,deadline)
                        if patch:
                            proposed=json.dumps({**json.loads(answer.draft),**patch})
                            if not validate_draft(db,room,answer.tool_name,proposed):
                                answer.draft=proposed
                    if value.intent=='chat':
                        if claims_review(value.reply or ''):return AssistantReply(UNPREPARED)
                        return checked(AssistantReply(value.reply or 'อยากให้ช่วยดูเรื่องไหนคะ?'))
                record(job,'tool',tool=answer.tool_name,status='ok')
            return answer if answer.tool_name else checked(answer)
        if read_budget[0]>=READS:return finish()
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
        else:
            # Retired read protocol can still complete old in-flight jobs.
            if not sandbox:task=evidence.scope(db,room,job.payload.get('text',''))
            result=sandbox.finance(answer.draft) if sandbox else read(db,room,answer.draft,job.payload.get('user_message_id'))
        if result.get('error'):
            invalid(answer,result)
            if repairs>=2:return AssistantReply('ฉันยังค้นข้อมูลตามเงื่อนไขนี้ไม่สำเร็จค่ะ ช่วยระบุช่วงวันหรือชื่อบัญชีที่ต้องการอีกนิดได้ไหมคะ? ยังไม่ได้เปลี่ยนข้อมูล')
            continue
        from .assistant_data import remember_lookup
        if answer.tool_name=='lookup_workspace':
            reference_ids=True
            bindings=remember_lookup(job,result)
            if bindings:
                result={**result,**bindings}
                from .assistant_data import quantity
                if any(quantity(k) for k in bindings['facts']):active.add('grounded_answer')
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

