"""Per-request accounting, no prompts/keys stored. All prices are user-supplied USD."""
import json
from contextlib import contextmanager
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,func,case,Integer
from .db import get_db,SessionLocal
from .models import AIUsage,AIUsagePolicy,Provider,Workspace,uid
from .security import owner
from .reporting import today

router=APIRouter(prefix='/workspaces/{wid}/ai/usage',dependencies=[Depends(owner)])
class Price(BaseModel):
    model_config=ConfigDict(extra='forbid')
    input:int=Field(ge=0,le=1_000_000_000,strict=True)
    output:int=Field(ge=0,le=1_000_000_000,strict=True)
class Policy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    monthly_limit:int=Field(default=0,ge=0,le=1_000_000_000_000,strict=True)
    prices:dict[UUID,Price]=Field(default_factory=dict,max_length=30)

def policy(db,wid):
    row=db.get(AIUsagePolicy,wid)
    return dict(monthly_limit=row.monthly_limit,prices=row.prices) if row else dict(monthly_limit=0,prices={})
@router.put('/policy')
def save_policy(wid:str,data:Policy,db=Depends(get_db,scope='function')):
    db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    providers=set(db.scalars(select(Provider.id).where(Provider.workspace_id==wid)))
    if not {str(k) for k in data.prices}<=providers:raise HTTPException(422,'โมเดลไม่ตรงกับพื้นที่')
    row=db.get(AIUsagePolicy,wid)
    if not row:row=AIUsagePolicy(workspace_id=wid);db.add(row)
    row.monthly_limit=data.monthly_limit;row.prices={str(k):v.model_dump() for k,v in data.prices.items()}
    # Fill only previously unpriced requests for the same model. Existing snapshots stay fixed.
    models={p.id:p.model for p in db.scalars(select(Provider).where(Provider.workspace_id==wid))}
    for event in db.scalars(select(AIUsage).where(AIUsage.workspace_id==wid,AIUsage.cost.is_(None))):
        price=row.prices.get(event.provider_id)
        if price and models.get(event.provider_id)==event.model:
            event.cost=cost(event.input_tokens,event.output_tokens,price);event.estimated=True
    db.flush()
    return policy(db,wid)
@router.get('')
def report(wid:str,month:str|None=Query(None,pattern=r'^\d{4}-\d{2}$'),db=Depends(get_db,scope='function')):
    from .reporting import month_bounds
    month=month or today().strftime('%Y-%m');month_bounds(month)
    groups=db.execute(select(AIUsage.provider_id,AIUsage.model,AIUsage.task,func.count(),func.sum(AIUsage.input_tokens),func.sum(AIUsage.output_tokens),func.sum(AIUsage.cost),func.sum(func.cast(AIUsage.estimated, Integer)),func.sum(case((AIUsage.cost.is_(None),1),else_=0)),func.sum(case((AIUsage.status=='failed',1),else_=0))).where(AIUsage.workspace_id==wid,AIUsage.month==month).group_by(AIUsage.provider_id,AIUsage.model,AIUsage.task)).all()
    items=[dict(provider_id=p,model=m,task=t,requests=n,input_tokens=i,output_tokens=o,cost=c or 0,estimated_requests=e,unpriced_requests=u,failed_requests=f) for p,m,t,n,i,o,c,e,u,f in groups]
    return dict(month=month,policy=policy(db,wid),items=items,requests=sum(r['requests'] for r in items),cost=sum(r['cost'] for r in items),unpriced_requests=sum(r['unpriced_requests'] for r in items))

class BudgetExceeded(ValueError):pass

def cost(i,o,price):return (i*price['input']+o*price['output']+999999)//1000000

def reserve(db,job,p,body):
    workspace=db.scalar(select(Workspace).where(Workspace.id==job.workspace_id).with_for_update())
    if hasattr(job,'_baseline_epoch'):
        from .models import Membership
        from .ai_fence import Invalidated
        if not workspace or workspace.archived_at is not None or not db.get(Membership,(job.user_id,job.workspace_id)):raise Invalidated('membership_revoked')
        if workspace.ai_epoch!=job._baseline_epoch:raise Invalidated('context_changed')
    options=policy(db,job.workspace_id);price=options['prices'].get(p.id)
    if p.kind=='ollama':price=dict(input=0,output=0)
    # UTF-8 byte count is a conservative text estimate, not an exact tokenizer.
    # Images reserve 16k tokens each; vendor tokenization/billing can differ.
    def estimate(value):
        if isinstance(value,dict):
            if value.get('type')=='image_url':return 16384
            return sum(len(str(k).encode())+estimate(v) for k,v in value.items())
        if isinstance(value,list):return sum(estimate(v)+8 for v in value)
        return len(str(value).encode())+8
    i=estimate(body);o=p.max_tokens;charge=cost(i,o,price) if price else None
    month=today().strftime('%Y-%m')
    used=db.scalar(select(func.coalesce(func.sum(AIUsage.cost),0)).where(AIUsage.workspace_id==job.workspace_id,AIUsage.month==month))
    if options['monthly_limit'] and p.kind!='ollama':
        unknown=db.scalar(select(AIUsage.id).where(AIUsage.workspace_id==job.workspace_id,AIUsage.month==month,AIUsage.cost.is_(None)).limit(1))
        if charge is None or unknown or used+charge>options['monthly_limit']:
            job._budget_blocked=True;raise BudgetExceeded('AI budget reached or price unknown')
    row=AIUsage(id=uid(),workspace_id=job.workspace_id,provider_id=p.id,model=p.model,task=job.task,month=month,input_tokens=i,output_tokens=o,cost=charge,estimated=True,status='reserved')
    db.add(row);db.flush()
    return row,price

def tokens(value):
    if not isinstance(value,dict):return None
    i=value.get('prompt_tokens');o=value.get('completion_tokens')
    if type(i) is int and type(o) is int and 0<=i<=100_000_000 and 0<=o<=100_000_000:return i,o
    return None

class Meter:
    def __init__(self,response):self.response=response;self.usage=None;self.raw=b''
    def __getattr__(self,name):return getattr(self.response,name)
    def iter_lines(self):
        for line in self.response.iter_lines():
            if line.startswith('data:'):
                try:self.usage=tokens(json.loads(line[5:]).get('usage')) or self.usage
                except (ValueError,AttributeError):pass
            yield line
    def iter_bytes(self):
        for chunk in self.response.iter_bytes():
            if len(self.raw)+len(chunk)<=256000:self.raw+=chunk
            yield chunk
        try:self.usage=tokens(json.loads(self.raw).get('usage')) or self.usage
        except (ValueError,AttributeError):pass

@contextmanager
def tracked_stream(db,job,p,client,*args,**kwargs):
    import time
    started=time.monotonic()
    # Commit the reservation before network I/O; crashes conservatively retain it.
    with SessionLocal.begin() as billing:
        row,price=reserve(billing,job,p,kwargs.get('json',{}))
    meter=None;ok=False;failure=None;details={}
    try:
        with client.stream(*args,**kwargs) as response:
            from .chat_stop import watch
            guard=watch(job,response)
            try:
                meter=Meter(response);yield meter;ok=True
            finally:guard.set()
    except Exception as error:
        from .ai_errors import diagnose,metadata
        failure=diagnose(error)
        details=metadata(error)
        raise
    finally:
        row.status='success' if ok else 'failed'
        if meter and meter.usage:
            row.input_tokens,row.output_tokens=meter.usage;row.estimated=False
            row.cost=cost(*meter.usage,price) if price else None
        # Preserve accounting when worker rolls back invalid model output.
        event={key:getattr(row,key) for key in ('id','workspace_id','provider_id','model','task','month','input_tokens','output_tokens','cost','estimated','status','created_at')}
        job._usage_events=getattr(job,'_usage_events',[])+[event]
        from .ai_diagnostics import record
        record(job,'request',provider_id=p.id,status='ok' if ok else 'failed',error=failure,**details,duration_ms=int((time.monotonic()-started)*1000),input_tokens=row.input_tokens,output_tokens=row.output_tokens,estimated=row.estimated)
        with SessionLocal.begin() as billing:
            current=billing.get(AIUsage,row.id)
            if current:
                for key in ('status','input_tokens','output_tokens','estimated','cost'):setattr(current,key,getattr(row,key))

def recover(db,job):
    for event in getattr(job,'_usage_events',[]):
        if not db.get(AIUsage,event['id']):db.add(AIUsage(**event))
