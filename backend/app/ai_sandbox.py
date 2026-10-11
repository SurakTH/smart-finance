"""Synthetic-only evaluation. This module never resolves drafts or reads a ledger."""
import base64
import io
import json
import re
import time
import httpx
from PIL import Image,ImageDraw
from pydantic import ValidationError
from sqlalchemy import select
from . import config
from .models import Provider
from .ai_settings import settings,target
from .ai_parameters import parameters
from .ai_usage import tracked_stream
from .ai_errors import ensure_response,diagnose,AIRequestError
from .assistant_response import completion,read_stream
from .assistant_lookup import Lookup
from .assistant_finance import Read
from .chat_dialogue import Suggestion
from .ai_diagnostics import record
from .reporting import today

CASH='11111111-1111-4111-8111-111111111111'
FOOD='22222222-2222-4222-8222-222222222222'
CASES={'balance','monthly','transaction','followup','receipt'}
REASONS={'passed','no_provider','image_disabled','wrong_tool','invalid_arguments','wrong_amount','answer_mismatch','no_tool','call_limit'}
PROMPTS={'balance':'ตอนนี้ฉันมีเงินเท่าไร?', 'monthly':'เดือนนี้ใช้ไปเท่าไร?', 'transaction':'ช่วยจดกาแฟ 80 บาทจากเงินสด หมวดอาหาร', 'followup':'เงินสด หมวดอาหาร', 'receipt':'ช่วยจดรายการในรูปจากเงินสด หมวดอาหาร'}

class TestFailed(ValueError):
    def __init__(self,reason):self.reason=reason;super().__init__(reason)

def fixture_image():
    image=Image.new('RGB',(500,190),'white');draw=ImageDraw.Draw(image)
    draw.text((30,25),'SMART FINANCE DEMO',fill='black',font_size=25)
    draw.text((30,70),'FOOD RECEIPT',fill='black',font_size=25)
    draw.text((30,120),'TOTAL THB 125.00',fill='black',font_size=30)
    out=io.BytesIO();image.save(out,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()

def context(case):
    messages=[{'role':'system','content':'คุณเป็นเลขาการเงินภาษาไทยในห้องทดสอบ ใช้ข้อมูลตัวอย่างจาก tools เท่านั้น ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์ ไม่ใช่บัญชีจริง วันนี้ '+today().isoformat()+'. ถามยอดปัจจุบันใช้ lookup_workspace balances สรุปเงินจาก assets_satang แยกหนี้และสุทธิ หน่วยสตางค์ แปลงเป็นบาท รายเดือนใช้ query_finance monthly_analysis ถ้าขอจด ใช้ prepare_transaction ข้อมูลครบ intent=create, kind=expense, amount เป็นจำนวนเต็มสตางค์, account_id, category_id, occurred_on ห้ามอ้างว่าบันทึกแล้ว ต้องทวนและรอผู้ใช้ยืนยัน ถามข้อมูลที่ขาดจาก tools ก่อน ห้ามเดา ID หรือจำนวนเงิน'}]
    if case=='followup':messages.extend([{'role':'user','content':'ช่วยจดกาแฟ 80 บาทให้หน่อย'},{'role':'assistant','content':'ใช้บัญชีไหนและหมวดอะไรคะ?'}])
    content=PROMPTS[case]
    if case=='receipt':content=[{'type':'text','text':content},{'type':'image_url','image_url':{'url':fixture_image()}}]
    return messages+[{'role':'user','content':content}]

def lookup(raw):
    values=Lookup.model_validate_json(raw);results=[]
    for query in values.queries:
        if query.cursor or (query.month and query.resource!='budgets') or (query.kind and query.resource not in ('accounts','categories','balances')):raise TestFailed('invalid_arguments')
        if query.resource=='preferences':
            results.append(dict(resource='preferences',enabled=True,expense_account_id=CASH,income_account_id=CASH,rules=[dict(keyword='กาแฟ',category_id=FOOD)],has_more=False));continue
        if query.resource not in ('accounts','categories','balances'):
            results.append(dict(resource=query.resource,items=[],returned=0,has_more=False,next_cursor=None));continue
        items=[dict(id=CASH,name='เงินสด',kind='asset',balance_satang=123456),dict(id='33333333-3333-4333-8333-333333333333',name='บัตรตัวอย่าง',kind='liability',balance_satang=23456)] if query.resource!='categories' else [dict(id=FOOD,name='อาหาร',kind='expense')]
        if query.kind:
            if query.kind not in (('income','expense') if query.resource=='categories' else ('asset','liability')):raise TestFailed('invalid_arguments')
            items=[x for x in items if x['kind']==query.kind]
        if query.q:items=[x for x in items if query.q.strip().casefold() in x['name'].casefold()]
        row=dict(resource=query.resource,items=items[:query.limit],returned=len(items[:query.limit]),has_more=False,next_cursor=None)
        if query.resource=='balances':
            assets=sum(x['balance_satang'] for x in items if x['kind']=='asset');debt=sum(x['balance_satang'] for x in items if x['kind']=='liability')
            row['summary']=dict(assets_satang=assets,liabilities_satang=debt,net_satang=assets-debt,account_count=len(items),complete=True,scope={'q':query.q.strip(),'kind':query.kind})
        results.append(row)
    return dict(source='workspace_backend',unit='THB_satang',results=results)

def query_finance(raw):
    value=Read.model_validate_json(raw)
    if value.operation!='monthly_analysis':raise TestFailed('wrong_tool')
    if value.month and value.month!=today().strftime('%Y-%m'):raise TestFailed('invalid_arguments')
    if value.account_id or value.category_id or value.cursor or value.q or value.start or value.end or value.kind or value.amount:raise TestFailed('invalid_arguments')
    return dict(source='ledger_backend',unit='THB_satang',month=today().strftime('%Y-%m'),income=200000,expense=45000,net=155000,count=3,categories=[dict(id=FOOD,name='อาหาร',amount=45000)],budgets={'items':[]})

def check_draft(raw,case):
    value=Suggestion.model_validate_json(raw)
    if value.transactions:
        if len(value.transactions)!=1 or any(getattr(value,k) is not None for k in ('kind','description','amount','account_id','category_id','occurred_on')):raise TestFailed('invalid_arguments')
        value=value.transactions[0]
    if value.intent!='create' or value.kind!='expense' or str(value.account_id)!=CASH or str(value.category_id)!=FOOD or not value.description or value.occurred_on not in (None,today()):raise TestFailed('invalid_arguments')
    if value.amount!=(12500 if case=='receipt' else 8000):raise TestFailed('wrong_amount')
    return True

def evaluate(db,job,p,case,deadline,budget):
    from .ai import assistant_tools
    try:url,headers,extensions=target(p)
    except Exception:raise AIRequestError('dns') from None
    try:
        if p.encrypted_key:headers['Authorization']='Bearer '+config.cipher().decrypt(p.encrypted_key.encode()).decode()
    except Exception:raise AIRequestError('key_invalid') from None
    messages=context(case);seen=set();reads=0;last_failure=None;repaired=False
    names={'lookup_workspace','query_finance'} if case in ('balance','monthly') else {'lookup_workspace','prepare_transaction'}
    tools=[t for t in assistant_tools() if t['function']['name'] in names]
    def feedback(answer,error):
        nonlocal last_failure,repaired
        reason=error.reason if isinstance(error,TestFailed) else 'invalid_arguments'
        from .tool_arguments import issues
        fields=issues(error) if isinstance(error,ValidationError) else []
        record(job,'tool',tool=answer.tool_name,status='invalid',issues=fields)
        last_failure=reason
        if repaired:raise TestFailed(reason)
        repaired=True
        result=dict(error=reason,issues=fields,message='แก้คำสั่งตาม schema และโจทย์เดิม เว้นช่องที่ไม่ใช้ ค้น ID ด้วย lookup_workspace; จำนวนเป็นสตางค์ ห้ามเดา ID หรือจำนวนจากคำตอบตัวเอง')
        messages.extend([{'role':'assistant','content':None,'tool_calls':[{'id':answer.call_id,'type':'function','function':{'name':answer.tool_name,'arguments':answer.draft}}]},{'role':'tool','tool_call_id':answer.call_id,'content':json.dumps(result,ensure_ascii=False)}])
    for _ in range(4):
        if budget[0]>=8 or time.monotonic()>=deadline:raise TestFailed('call_limit')
        budget[0]+=1
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=httpx.Timeout(min(p.timeout_seconds,max(1,deadline-time.monotonic())),connect=5)) as client:
            body=dict(model=p.model,messages=messages,tools=tools,tool_choice='auto',stream=True,**parameters(p))
            with tracked_stream(db,job,p,client,'POST',url.rstrip('/')+'/chat/completions',headers=headers,extensions=extensions,json=body) as response:
                ensure_response(response)
                if 'text/event-stream' in response.headers.get('content-type',''):answer=read_stream(response,job)
                else:
                    raw=b''
                    for chunk in response.iter_bytes():
                        raw+=chunk
                        if len(raw)>256000:raise TestFailed('invalid_arguments')
                    answer=completion(json.loads(raw)['choices'][0]['message'])
        name=answer.tool_name
        if not name:
            if case not in ('balance','monthly'):raise TestFailed('no_tool')
            required='lookup_workspace' if case=='balance' else 'query_finance'
            if required not in seen:raise TestFailed('no_tool')
            numbers=re.findall(r'\d+(?:\.\d+)?',answer.content.replace(',',''))
            if ('1234.56' if case=='balance' else '450') not in numbers and (case!='monthly' or '450.00' not in numbers):raise TestFailed('answer_mismatch')
            return
        if name=='prepare_transaction' and case in ('transaction','followup','receipt'):
            try:check_draft(answer.draft,case)
            except (ValueError,TypeError) as error:
                feedback(answer,error);continue
            record(job,'tool',tool=name,status='ok');return
        if name not in ('lookup_workspace','query_finance') or reads>=3:
            record(job,'tool',tool=name,status='invalid');raise TestFailed('wrong_tool')
        try:
            result=lookup(answer.draft) if name=='lookup_workspace' else query_finance(answer.draft)
            if case=='balance' and not any(x.get('resource')=='balances' for x in result.get('results',[])):
                pass  # ID discovery is allowed, but a balance read is still required.
            elif name=='lookup_workspace' and any(x.get('resource')=='balances' and not x.get('summary',{}).get('scope',{}).get('q') and x.get('summary',{}).get('scope',{}).get('kind') in (None,'asset') for x in result.get('results',[])):seen.add(name)
            elif name=='query_finance':seen.add(name)
        except (ValueError,TypeError) as error:
            feedback(answer,error);continue
        reads+=1;record(job,'tool',tool=name,status='ok',resources=[x.get('resource') for x in result.get('results',[])]+(['monthly_analysis'] if name=='query_finance' else []))
        messages.extend([{'role':'assistant','content':None,'tool_calls':[{'id':answer.call_id,'type':'function','function':{'name':name,'arguments':answer.draft}}]},{'role':'tool','tool_call_id':answer.call_id,'content':json.dumps(result,ensure_ascii=False)}])
    raise TestFailed(last_failure or 'call_limit')

def run(db,job):
    case=job.payload['case'];selected=job.payload.get('provider_id');options=settings(db,job.workspace_id)
    rows=db.scalars(select(Provider).where(Provider.workspace_id==job.workspace_id,Provider.task=='chat',Provider.enabled.is_(True)).order_by(Provider.priority,Provider.id)).all()
    rows=[p for p in rows if (not selected or p.id==selected) and (p.kind=='ollama' or options['cloud_enabled'])][:options['max_attempted_providers']]
    reason='no_provider';deadline=time.monotonic()+90;budget=[0]
    for index,p in enumerate(rows):
        if case=='receipt' and not p.supports_images:reason='image_disabled';continue
        if index:record(job,'fallback',provider_id=p.id,status='ok')
        try:evaluate(db,job,p,case,deadline,budget)
        except TestFailed as error:reason=error.reason
        except Exception as error:reason=diagnose(error)
        else:
            job._test_result=dict(case=case,status='passed',reason='passed',provider_id=p.id,calls=budget[0],synthetic_only=True)
            record(job,'result',status='passed',provider_id=p.id);job.status='done';job.error=None;job.payload={};return
        record(job,'provider_error',provider_id=p.id,error=reason,status='failed')
        if budget[0]>=8 or time.monotonic()>=deadline:break
    job._test_result=dict(case=case,status='skipped' if reason=='image_disabled' else 'failed',reason=reason,calls=budget[0],synthetic_only=True)
    record(job,'result',status=job._test_result['status']);job.status='done';job.error=None;job.payload={}
