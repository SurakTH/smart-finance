import json
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from app import ai
from app.db import SessionLocal
from app.models import Account,ChatAction,Conversation,Job,Provider,Proposal
from app.worker import run_once
from app.assistant_response import read_stream,completion
from app.ai_parameters import parameters
from test_chat_actions import setup,say,count
from test_chat_dialogue import suggestion
from test_chat_images import receipt


def provider(w,**values):
    with SessionLocal.begin() as db:
        p=Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0,**values)
        db.add(p);db.flush();return p.id


def transport(monkeypatch,handler):
    real=httpx.Client
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))


def reply(text):return httpx.Response(200,json={'choices':[{'message':{'content':text}}]})
def draft(value):return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'type':'function','function':{'name':'prepare_transaction','arguments':json.dumps(value)}}]}}]})


def test_normal_chat_uses_model_for_every_utterance_without_turning_examples_into_actions(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w);calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        assert body['tools'][0]['function']['name']=='prepare_transaction'
        return reply('คุยได้เลยค่ะ วันนี้เป็นยังไงบ้าง?') if len(calls)==1 else reply(json.dumps(suggestion(w)))
    transport(monkeypatch,handler)
    say(c,b,cid,'วันนี้รู้สึกเหนื่อยจัง');assert run_once()
    assert 'วันนี้เป็นยังไง' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    say(c,b,cid,'ขอตัวอย่างข้อมูลค่าอาหาร 200');assert run_once()
    assert len(calls)==2 and any(m['content']=='วันนี้รู้สึกเหนื่อยจัง' for m in calls[-1]['messages'])
    with SessionLocal() as db:assert not db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid))
    assert count(w)==0


def test_common_capture_uses_real_model_instead_of_regex_when_configured(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w);calls=[]
    def handler(req):calls.append(json.loads(req.content));return draft(suggestion(w))
    transport(monkeypatch,handler)
    r=c.post(b+f'/conversations/{cid}/messages',json={'text':'กาแฟ 200 จากเงินสด'})
    assert r.json()['job_id'] and count(w)==0
    assert run_once() and len(calls)==1
    assert 'กรุณาตรวจสอบ' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'บันทึกรายการเรียบร้อย' in say(c,b,cid,'ยืนยัน') and count(w)==1


def test_image_asks_then_uses_caption_followup_and_keeps_evidence(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w,reasoning_effort='high');calls=[]
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        assert body['reasoning_effort']=='high' and 'temperature' not in body
        images=[m for m in body['messages'] if isinstance(m.get('content'),list)]
        assert len(images)==1
        if len(calls)==1:return reply('เห็นยอดในสลิปแล้วค่ะ ใช้บัญชีไหนคะ?')
        value=suggestion(w);value['attachment_id']=images[0]['content'][0]['text'].split('attachment_id=')[1].split(';')[0]
        return draft(value)
    transport(monkeypatch,handler)
    uploaded=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'มื้อเที่ยง ช่วยจดให้หน่อย'}).json()
    assert run_once();assert 'ใช้บัญชีไหน' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    say(c,b,cid,'เงินสดจ้า');assert run_once()
    reviewed=c.get(b+f'/conversations/{cid}/messages').json()[-1]
    assert reviewed['attachment_id']==uploaded['attachment_id'] and '฿200.00' in reviewed['content'] and count(w)==0
    assert c.get(b+'/proposals').json()==[]
    say(c,b,cid,'ยืนยัน');assert count(w)==1
    assert c.get(b+'/proposals').json()[0]['status']=='confirmed'
    assert 'ไม่มีการบันทึกซ้ำ' in say(c,b,cid,'ยืนยัน') and count(w)==1


def test_question_cannot_become_draft_even_if_model_calls_tool(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w)
    transport(monkeypatch,lambda req:draft(suggestion(w)))
    say(c,b,cid,'กาแฟ 200 แพงไหม');assert run_once()
    assert 'ยังไม่เตรียมรายการจากคำถาม' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'ยังไม่มีรายการ' in say(c,b,cid,'ยืนยัน') and count(w)==0


def test_vision_routes_skip_text_only_provider_before_applying_fallback_cap(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w)
    with SessionLocal.begin() as db:
        db.add(Provider(workspace_id=w,kind='ollama',model='text-only',task='chat',supports_images=False,priority=0))
    calls=[]
    def handler(req):calls.append(json.loads(req.content)['model']);return reply('ในรูปเป็นใบเสร็จค่ะ')
    transport(monkeypatch,handler)
    c.put(b+'/ai/settings',json={'max_attempted_providers':1})
    c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'รูปนี้คืออะไร'})
    assert run_once() and calls==['vision'] and count(w)==0


def test_tool_arguments_and_reasoning_never_stream_and_partial_tools_never_commit(monkeypatch):
    events=[];monkeypatch.setattr('app.chat_stream.publish',lambda job,kind,**kw:events.append((kind,kw)))
    job=SimpleNamespace(payload={})
    parts=[{'choices':[{'delta':{'reasoning':'private internal content'}}]},
        {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'prepare_','arguments':'{"intent":'}}]}}]},
        {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'name':'transaction','arguments':'"create"}'}}]},'finish_reason':'tool_calls'}]}]
    data=''.join('data: '+json.dumps(p)+'\n\n' for p in parts)+'data: [DONE]\n\n'
    response=httpx.Response(200,text=data)
    result=read_stream(response,job)
    assert result.draft=='{"intent":"create"}' and events==[]
    with pytest.raises(ValueError):read_stream(httpx.Response(200,text='data: '+json.dumps(parts[1])+'\n\n'),job)
    with pytest.raises(ValueError):completion({'tool_calls':[{'function':{'name':'confirm','arguments':'{}'}}]})
    with pytest.raises(ValueError):completion({'tool_calls':[{},{}]})


@pytest.mark.parametrize('kind,effort,expected',[
 ('openai','high',{'reasoning_effort':'high','max_completion_tokens':1500}),
 ('gemini','low',{'reasoning_effort':'low','max_tokens':1500}),
 ('openrouter','none',{'reasoning':{'effort':'none','exclude':False},'max_tokens':1500}),
 ('compatible','medium',{'reasoning_effort':'medium','max_tokens':1500}),
 ('ollama','none',{'reasoning_effort':'none','max_tokens':1500}),
 ('groq','high',{'reasoning_effort':'high','max_completion_tokens':1500,'include_reasoning':False}),
])
def test_thinking_adapter_maps_selected_setting_without_temperature(kind,effort,expected):
    assert parameters(SimpleNamespace(kind=kind,model='openai/gpt-oss-20b',reasoning_effort=effort,max_tokens=1500,temperature=50))==expected


def test_model_settings_persist_and_reject_known_unsupported_thinking(actor):
    c,w,u,b,cid=setup(actor)
    payload={'kind':'ollama','model':'vision','task':'chat','supports_images':True,'reasoning_effort':'high'}
    r=c.post(b+'/providers',json=payload);assert r.status_code==200,r.text
    pid=r.json()['id'];assert r.json()['reasoning_effort']=='high' and r.json()['supports_images']
    assert c.get(b+'/providers').json()[0]['reasoning_effort']=='high'
    assert c.put(b+'/providers/'+pid,json={**payload,'reasoning_effort':'none'}).json()['reasoning_effort']=='none'
    assert c.put(b+'/providers/'+pid,json={**payload,'reasoning_effort':'invented'}).status_code==422
    assert c.put(b+'/providers/'+pid,json={**payload,'kind':'gemini','model':'gemini-3-pro','reasoning_effort':'none'}).status_code==422
    assert c.put(b+'/providers/'+pid,json={**payload,'kind':'groq','model':'openai/gpt-oss-20b','reasoning_effort':'none'}).status_code==422


def test_model_cannot_attach_evidence_from_another_room(actor,monkeypatch):
    c,w,u,b,cid=setup(actor);provider(w)
    other=c.post(b+'/conversations',json={}).json()['id']
    aid=c.post(b+f'/conversations/{other}/images',files={'file':receipt()}).json()['attachment_id']
    with SessionLocal.begin() as db:
        jobs=db.scalars(select(Job).where(Job.workspace_id==w)).all()
        for job in jobs:job.status='done';job.payload={}
    transport(monkeypatch,lambda req:draft({**suggestion(w),'attachment_id':aid}))
    say(c,b,cid,'จดอาหารสองร้อย');assert run_once()
    assert 'ไม่พบรูปนี้ในบทสนทนา' in c.get(b+f'/conversations/{cid}/messages').json()[-1]['content']
    assert 'ยังไม่มีรายการ' in say(c,b,cid,'ยืนยัน') and count(w)==0


def test_image_confirmation_failure_rolls_back_money_and_evidence(actor,monkeypatch):
    from app import chat_actions
    from fastapi import HTTPException
    c,w,u,b,cid=setup(actor);provider(w)
    transport(monkeypatch,lambda req:draft(suggestion(w)))
    c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'จดมื้อกลางวัน'})
    assert run_once()
    visible=c.get(b+f'/conversations/{cid}/messages').json()[-1]['id']
    real=chat_actions.post
    def interrupted(*args,**kw):real(*args,**kw);raise HTTPException(409,'ลองใหม่')
    monkeypatch.setattr(chat_actions,'post',interrupted)
    r=c.post(b+f'/conversations/{cid}/messages',json={'text':'ยืนยัน','review_message_id':visible})
    assert r.status_code==409 and count(w)==0 and c.get(b+'/proposals').json()==[]
    with SessionLocal() as db:assert db.scalar(select(ChatAction).where(ChatAction.conversation_id==cid)).status=='pending'


def test_default_thinking_omits_effort_and_uses_reasoning_model_token_limit():
    p=SimpleNamespace(kind='openai',model='o3',reasoning_effort='default',max_tokens=1200,temperature=20)
    assert parameters(p)=={'max_completion_tokens':1200}


def test_inbox_cannot_confirm_receipt_already_saved_from_chat(actor,monkeypatch):
    from app.schemas import TransactionInput
    c,w,u,b,cid=setup(actor);provider(w)
    transport(monkeypatch,lambda req:draft(suggestion(w)))
    result=c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'จดค่าอาหาร'}).json()
    with SessionLocal.begin() as db:
        pending=Proposal(workspace_id=w,description='ข้อเสนอเก่าจาก Inbox',attachment_id=result['attachment_id'],amount=20000)
        db.add(pending);db.flush();pid=pending.id
    assert run_once();say(c,b,cid,'ยืนยัน');assert count(w)==1
    tx={k:v for k,v in suggestion(w).items() if k!='intent'}
    from uuid import uuid4
    from app.reporting import today
    tx.update(occurred_on=today().isoformat(),idempotency_key=str(uuid4()))
    r=c.post(b+'/proposals/'+pid+'/confirm',json=tx)
    assert r.status_code==409 and count(w)==1


def test_streamed_read_tool_preserves_fragmented_call_id_without_exposing_arguments(monkeypatch):
    events=[];monkeypatch.setattr('app.chat_stream.publish',lambda *a,**kw:events.append(kw))
    parts=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call_','function':{'name':'query_','arguments':'{"operation":'}}]}}]},
           {'choices':[{'delta':{'reasoning_content':'private','tool_calls':[{'index':0,'id':'finance123','function':{'name':'finance','arguments':'"monthly_analysis"}'}}]},'finish_reason':'tool_calls'}]}]
    response=httpx.Response(200,text=''.join('data: '+json.dumps(p)+'\n\n' for p in parts)+'data: [DONE]\n\n')
    reply=read_stream(response,SimpleNamespace(payload={}))
    assert reply.call_id=='call_finance123' and reply.tool_name=='query_finance'
    assert json.loads(reply.draft)=={'operation':'monthly_analysis'} and events==[]
