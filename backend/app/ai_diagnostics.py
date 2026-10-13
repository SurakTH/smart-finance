"""Owner-visible metadata only. No prompts, arguments, URLs, replies or secrets."""
import time
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict
from typing import Literal
from sqlalchemy import select,update,or_,and_
from .models import Job,Provider,now
from .db import get_db
from .security import owner,login_limit

router=APIRouter(prefix='/workspaces/{wid}/ai',dependencies=[Depends(owner)])
EVENTS={'request','tool','provider_error','fallback','synthesis','result','review_repair'}
TOOLS={'understand_request','respond_finance','interpret_request','answer_finance_summary','load_toolkit','lookup_workspace','query_finance','prepare_transaction','prepare_correction','prepare_management_plan'}
RESOURCES={'accounts','categories','balances','budgets','goals','recurring','preferences','monthly_analysis','search_transactions'}
STATUSES={'ok','failed','invalid','cached','limited','passed','skipped'}

def record(job,event,**values):
    if not isinstance(event,str) or event not in EVENTS:return
    item={'event':event}
    for key,value in values.items():
        if key=='provider_id':
            try:item[key]=str(UUID(value))
            except (ValueError,TypeError,AttributeError):pass
        elif key in ('duration_ms','input_tokens','output_tokens','attempt') and type(value) is int:item[key]=max(0,min(value,1_000_000_000))
        elif key=='tool' and isinstance(value,str) and value in TOOLS:item[key]=value
        elif key=='status' and isinstance(value,str) and value in STATUSES:item[key]=value
        elif key=='estimated' and type(value) is bool:item[key]=value
        elif key=='resources' and isinstance(value,list):item[key]=[x for x in value if isinstance(x,str) and x in RESOURCES][:3]
        elif key=='issues':
            from .tool_arguments import valid_issues
            item[key]=valid_issues(value)
        elif key=='error':
            from .ai_errors import MESSAGES
            if isinstance(value,str) and value in MESSAGES:item[key]=value
    items=getattr(job,'_diagnostic_events',[])
    if len(items)<40:items.append(item)
    job._diagnostic_events=items

def finish(db,job):
    events=getattr(job,'_diagnostic_events',[])
    if not events and job.task not in ('chat','ai_test','extract'):return
    data=dict(version=1,events=events,status=job.status,duration_ms=int((time.monotonic()-getattr(job,'_diagnostic_started',time.monotonic()))*1000))
    if job.task=='ai_test':data['test']=getattr(job,'_test_result',{'status':'failed','reason':'processing_failed'})
    job.diagnostics=data
    job.diagnostics_expires=now()+30*86400

def serialize(job):
    data=job.diagnostics if job.diagnostics_expires and job.diagnostics_expires>now() else {}
    if job.task=='ai_test' and job.status=='pending':data={'test':dict(case=job.payload.get('case','balance'),status='pending',reason='',calls=0)}
    return dict(id=job.id,task=job.task,status=job.status,created_at=job.created_at,diagnostics=data)

@router.get('/diagnostics')
def history(wid:str,db=Depends(get_db,scope='function')):
    # Index on workspace/order keeps the inspection bounded even with years of jobs.
    cutoff=(now()-30*86400)*1000
    rows=db.scalars(select(Job).where(Job.workspace_id==wid,Job.created_at>=cutoff,or_(Job.diagnostics_expires>now(),and_(Job.task=='ai_test',Job.status=='pending'))).order_by(Job.created_at.desc(),Job.id.desc()).limit(50))
    return {'items':[serialize(j) for j in rows],'retention_days':30}

@router.get('/diagnostics/{jid}')
def detail(wid:str,jid:str,db=Depends(get_db,scope='function')):
    job=db.get(Job,jid)
    if not job or job.workspace_id!=wid:raise HTTPException(404,'ไม่พบผลตรวจในพื้นที่นี้')
    return serialize(job)

class TestInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    case:Literal['balance','monthly','transaction','followup','receipt','natural']
    provider_id:UUID|None=None

@router.post('/tests')
def start(wid:str,data:TestInput,member=Depends(owner),db=Depends(get_db,scope='function')):
    login_limit('ai-sandbox:'+wid)
    if db.scalar(select(Job.id).where(Job.workspace_id==wid,Job.task=='ai_test',Job.status=='pending').limit(1)):raise HTTPException(409,'มีการทดสอบกำลังทำงานอยู่ รอผลก่อนเริ่มใหม่')
    from .ai_settings import settings
    options=settings(db,wid)
    providers=list(db.scalars(select(Provider).where(Provider.workspace_id==wid,Provider.task=='chat',Provider.enabled.is_(True))))
    if data.provider_id:providers=[p for p in providers if p.id==str(data.provider_id)]
    providers=[p for p in providers if p.kind=='ollama' or options['cloud_enabled']]
    if not providers:raise HTTPException(422,'ไม่มีโมเดลแชทที่เปิดใช้และตรงการอนุญาต Cloud AI ในพื้นที่นี้')
    from .main import enqueue
    job=enqueue(db,wid,member.user_id,'ai_test',dict(case=data.case,provider_id=str(data.provider_id) if data.provider_id else None))
    return {'job_id':job.id}

@router.delete('/diagnostics')
def clear(wid:str,db=Depends(get_db,scope='function')):
    db.execute(update(Job).where(Job.workspace_id==wid,Job.status!='pending',Job.diagnostics_expires.is_not(None)).values(diagnostics={},diagnostics_expires=None))
    return {'ok':True}

def cleanup(db):
    # Clear metadata, retaining durable job and accounting records.
    rows=db.scalars(select(Job).where(Job.diagnostics_expires<now()).limit(200))
    for job in rows:job.diagnostics={};job.diagnostics_expires=None
