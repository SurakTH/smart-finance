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
from .assistant_response import completion,completion_choice,read_stream
from .assistant_lookup import Lookup
from .assistant_finance import Read
from .chat_dialogue import Suggestion
from .ai_diagnostics import record
from .assistant_limits import REQUESTS

def today():
    # Synthetic expectations and tool date bounds must share one clock.
    from .reporting import today as report_today
    return report_today()

CASH='11111111-1111-4111-8111-111111111111'
FOOD='22222222-2222-4222-8222-222222222222'
CASES={'balance','monthly','transaction','followup','receipt','natural'}
REASONS={'passed','no_provider','image_disabled','wrong_tool','invalid_arguments','wrong_amount','answer_mismatch','no_tool','call_limit'}
PROMPTS={'natural':'ตั้งแต่เริ่มเดือนมาจนตอนนี้เหมือนเงินไหลไปกับคาเฟ่ ช่วยไล่ให้หน่อยได้มั้ย','balance':'ตอนนี้ฉันมีเงินเท่าไร?', 'monthly':'เดือนนี้ใช้ไปเท่าไร?', 'transaction':'ช่วยจดกาแฟ 80 บาทจากเงินสด หมวดอาหาร', 'followup':'เงินสด หมวดอาหาร', 'receipt':'ช่วยจดรายการในรูปจากเงินสด หมวดอาหาร'}

class TestFailed(ValueError):
    def __init__(self,reason,field=None):
        self.reason=reason
        fields=field if isinstance(field,list) else [field] if field else []
        self.issues=[dict(field=f,code='unsupported_filter') for f in fields]
        super().__init__(reason)

def fixture_image():
    image=Image.new('RGB',(500,190),'white');draw=ImageDraw.Draw(image)
    draw.text((30,25),'SMART FINANCE DEMO',fill='black',font_size=25)
    draw.text((30,70),'FOOD RECEIPT',fill='black',font_size=25)
    draw.text((30,120),'TOTAL THB 125.00',fill='black',font_size=30)
    out=io.BytesIO();image.save(out,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()

def context(case):
    messages=[{'role':'system','content':'คุณเป็นเลขาการเงินภาษาไทยในห้องทดสอบ ใช้ข้อมูลตัวอย่างจาก tools เท่านั้น ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์ ไม่ใช่บัญชีจริง วันนี้ '+today().isoformat()+'. ถามยอดปัจจุบันใช้ lookup_workspace balances สรุปเงินจาก assets_satang แยกหนี้และสุทธิ หน่วยสตางค์ แปลงเป็นบาท รายเดือนใช้ query_finance monthly_analysis ถ้าขอจด ใช้ prepare_transaction ข้อมูลครบ intent=create, kind=expense, amount เป็นจำนวนเต็มสตางค์, account_id, category_id, occurred_on ห้ามอ้างว่าบันทึกแล้ว ต้องทวนและรอผู้ใช้ยืนยัน ถามข้อมูลที่ขาดจาก tools ก่อน ห้ามเดา ID หรือจำนวนเงิน'}]
    if case=='natural':messages[0]['content']+=' สำหรับคำถามนี้เรียก fetch_finance ตามข้อมูลที่ต้องการ แล้วตอบเป็นภาษาไทยปกติจาก facts ไม่ต้องใช้แม่แบบคำตอบ ตัวเลขต้องตรงข้อมูลที่อ่าน ทุกข้อมูลเป็นตัวอย่างเท่านั้น'
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

class Sandbox:
    def __init__(self,case):
        from types import SimpleNamespace
        from .assistant_tools import catalog
        self.case=case;self.last_failure=None;self.semantic_used=False;self.room=SimpleNamespace(capture_context={})
        names={'lookup_workspace','query_finance','answer_finance_summary'} if case in ('balance','monthly') else {'lookup_workspace','prepare_transaction'}
        if case=='natural':names={'fetch_finance','understand_request','respond_finance','lookup_workspace'}
        from .assistant_tools import all_tools
        from .assistant_summary import tool as summary_tool
        # Explicit legacy protocol probes keep their own catalog; the primary
        # conversational agent exposes only its current read/draft tools.
        self.tools=[t for t in [*all_tools(),summary_tool()] if t['function']['name'] in names]
    def fetch(self,raw,job):
        from .assistant_data import parse_fetch,remember
        # Synthetic scenarios independently report all semantic mismatches.
        value=parse_fetch(raw,PROMPTS[self.case],check_scope=False)
        if value.resource not in ('summary','transactions'):raise TestFailed('wrong_tool','resource')
        for field in ('account_id','category_id','cursor','compare_period','bucket','group_by'):
            if getattr(value,field):raise TestFailed('invalid_arguments',field)
        if value.operation!='summary':raise TestFailed('invalid_arguments','operation')
        args=dict(intent='transactions' if value.resource=='transactions' else 'report',account=value.account,category=value.category,q=value.q,metric=value.metric,period=value.period.model_dump(mode='json') if value.period else ({'mode':'last_days','days':30} if value.resource=='transactions' else {'mode':'month_to_date'}))
        task,_,_=self.semantic_plan(json.dumps(args))
        result=self.semantic_prepare(job,task);remember(job,dict(job._semantic_evidence))
        return result
    def semantic_plan(self,raw):
        from .semantic_assistant import Plan,bounds
        from .assistant_scope import Scope
        value=Plan.model_validate_json(raw)
        if self.case!='natural':raise TestFailed('wrong_tool')
        problems=[]
        if value.intent not in ('report','transactions'):problems.append('intent')
        for field in ('account','category','reuse_previous_scope','source_message_id','compare_period','action'):
            if getattr(value,field):problems.append(field)
        # Literal search over synthetic records, with a distractor. Do not make
        # one exact spelling of coffee an undocumented tool argument contract.
        examples=[dict(description='คาเฟ่ กาแฟตัวอย่าง',amount=8000),dict(description='อาหารตัวอย่าง',amount=92000)]
        matches=[row for row in examples if value.q and value.q.strip().casefold() in row['description'].casefold()]
        if matches!=examples[:1]:problems.append('q')
        if value.metric not in (None,'expense'):problems.append('metric')
        try:
            start,end=bounds(value.period)
            if (start,end)!=(today().replace(day=1),today()):problems.append('period')
        except (ValueError,AttributeError):problems.append('period')
        if problems:raise TestFailed('invalid_arguments',problems)
        return Scope('period','',start=start,end=end,transaction_kind='expense',q=value.q.strip(),include_items=value.intent=='transactions'),None,None
    def semantic_prepare(self,job,task):
        self.semantic_used=True
        scope=f'ข้อมูลสังเคราะห์ · {task.start} ถึง {task.end} · ค้นคำ {task.q}'
        facts=dict(expense='80.00 บาท',count='1 รายการ',item_0_description='คาเฟ่ กาแฟตัวอย่าง',item_0_amount='80.00 บาท')
        self.semantic_fallback=scope+'\nรายจ่าย 80.00 บาท จาก 1 รายการ'
        job._semantic_evidence=dict(facts=facts,principal={'expense','count','item_0_amount'},scope=scope,fallback=self.semantic_fallback)
        return dict(source='synthetic_backend',scope=scope,facts=facts,notice='ตอบภาษาปกติ ตัวเลขทั้งหมดมาจาก facts ไม่ต้องใช้แม่แบบ')
    def lookup(self,raw):
        try:return lookup(raw)
        except (ValueError,TypeError) as error:return self.problem(error)
    def finance(self,raw):
        try:return query_finance(raw)
        except (ValueError,TypeError) as error:return self.problem(error)
    def problem(self,error):
        from .tool_arguments import feedback
        self.last_failure=error.reason if isinstance(error,TestFailed) else 'invalid_arguments'
        return dict(error=self.last_failure,**feedback(error))
    def validate(self,name,raw):
        try:
            if name!='prepare_transaction' or self.case not in ('transaction','followup','receipt'):raise TestFailed('wrong_tool')
            check_draft(raw,self.case)
        except (ValueError,TypeError) as error:return self.problem(error)
    def summary(self,raw):
        from .assistant_summary import parse,render
        value=parse(raw)
        if self.case not in ('balance','monthly') or value.report!=('balances' if self.case=='balance' else 'monthly'):raise TestFailed('wrong_tool')
        data=lookup(json.dumps({'queries':[{'resource':'balances'}]})) if self.case=='balance' else query_finance(json.dumps({'operation':'monthly_analysis','month':value.month}))
        return render(value,data)
    def finish(self,content,cache):
        from .assistant_summary import Summary,render
        if self.case=='natural':
            if self.semantic_used:return self.semantic_fallback
            raise TestFailed('no_tool')
        if self.case not in ('balance','monthly'):raise TestFailed('no_tool')
        for (name,_),result in reversed(list(cache.items())):
            if self.case=='monthly' and name=='query_finance':return render(Summary(report='monthly'),result)
            if self.case=='balance' and name=='lookup_workspace':
                rows=[r for r in result.get('results',[]) if r.get('resource')=='balances' and not r.get('summary',{}).get('scope',{}).get('q') and not r.get('summary',{}).get('scope',{}).get('kind')]
                if rows:return render(Summary(report='balances'),dict(results=rows))
        raise TestFailed('no_tool')

def evaluate(db,job,p,case,deadline,budget):
    from .assistant_runtime import converse
    try:url,headers,extensions=target(p)
    except Exception:raise AIRequestError('dns') from None
    try:
        from .ai_connections import credential
        encrypted=credential(p)
        if encrypted:headers['Authorization']='Bearer '+config.cipher().decrypt(encrypted.encode()).decode()
    except Exception:raise AIRequestError('key_invalid') from None
    sandbox=Sandbox(case)
    before=getattr(job,'_assistant_requests',0)
    with httpx.Client(trust_env=False,follow_redirects=False) as client:
        try:answer=converse(db,job,p,client,url,headers,extensions,context(case),deadline,[0],sandbox=sandbox)
        finally:budget[0]+=getattr(job,'_assistant_requests',0)-before
    if case in ('transaction','followup','receipt'):
        if answer.tool_name!='prepare_transaction':raise TestFailed(sandbox.last_failure or 'no_tool')
        check_draft(answer.draft,case)
    elif case=='natural':
        if not sandbox.semantic_used:raise TestFailed(sandbox.last_failure or 'no_tool')
        if not any((e.get('tool')=='respond_finance' or e.get('event')=='synthesis') and e.get('status')=='ok' for e in getattr(job,'_diagnostic_events',[])):raise TestFailed('answer_mismatch')
    elif not answer.content:raise TestFailed('answer_mismatch')

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
        if budget[0]>=REQUESTS or time.monotonic()>=deadline:break
    job._test_result=dict(case=case,status='skipped' if reason=='image_disabled' else 'failed',reason=reason,calls=budget[0],synthetic_only=True)
    record(job,'result',status=job._test_result['status']);job.status='done';job.error=None;job.payload={}
