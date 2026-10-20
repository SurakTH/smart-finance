"""Owner-managed, workspace-scoped reusable AI credentials."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select,update
from sqlalchemy.orm import Session
from .db import get_db
from .models import AIConnection, Provider, Workspace
from .schemas import ProviderInput
from .ledger import get_scoped


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    kind: str = Field(pattern='^(gemini|openrouter|groq|openai|compatible|ollama)$')
    endpoint: str = Field(default='',max_length=500)
    api_key: str = Field(default='',max_length=500)
    clear_key: bool = False


def credential(p):
    connection=getattr(p,'connection',None)
    if getattr(p,'connection_id',None):
        if not connection or connection.workspace_id!=p.workspace_id:
            raise ValueError('Connection unavailable')
        return connection.encrypted_key
    return p.encrypted_key


def public(c,models=0):
    return dict(id=c.id,name=c.name,kind=c.kind,endpoint=c.endpoint,has_key=bool(c.encrypted_key),models=models)


def attach(db,wid,p,data):
    if not data.connection_id:return False
    c=get_scoped(db,AIConnection,wid,data.connection_id)
    if data.api_key or data.clear_key:raise HTTPException(422,'แก้คีย์ที่การเชื่อมต่อ เพื่อใช้กับทุกโมเดลร่วมกัน')
    p.connection_id=c.id;p.connection=c;p.kind=c.kind;p.endpoint=c.endpoint;p.encrypted_key=''
    for key,value in data.model_dump(exclude={'connection_id','api_key','clear_key','kind','endpoint'}).items():setattr(p,key,value)
    from .ai_parameters import validate
    validate(c.kind,data.model,data.reasoning_effort)
    return True


def install(router):
    # Router already enforces owner membership and archived-workspace checks.
    from .ai_settings import lock, apply

    @router.get('/ai/connections')
    def listing(wid:str,db:Session=Depends(get_db,scope='function')):
        connections=db.scalars(select(AIConnection).where(AIConnection.workspace_id==wid).order_by(AIConnection.name,AIConnection.id)).all()
        providers=db.scalars(select(Provider).where(Provider.workspace_id==wid)).all()
        return [public(c,sum(p.connection_id==c.id for p in providers)) for c in connections]

    def save(db,wid,data,c=None):
        # Reuse existing URL, key and provider policy validation; credentials never
        # pass through a model response or get copied into linked model records.
        sample=Provider(workspace_id=wid,kind=c.kind if c else data.kind,endpoint=c.endpoint if c else '',encrypted_key=c.encrypted_key if c else '')
        apply(sample,ProviderInput(kind=data.kind,model='connection',task='chat',name=data.name,endpoint=data.endpoint,api_key=data.api_key,clear_key=data.clear_key),creating=c is None)
        destination_changed=c is not None and (c.kind!=sample.kind or c.endpoint!=sample.endpoint)
        if c is None:c=AIConnection(workspace_id=wid);db.add(c)
        c.name=data.name.strip()
        if not c.name:raise HTTPException(422,'กรุณาตั้งชื่อการเชื่อมต่อ')
        c.kind=sample.kind;c.endpoint=sample.endpoint;c.encrypted_key=sample.encrypted_key
        db.flush()
        linked=db.scalars(select(Provider).where(Provider.workspace_id==wid,Provider.connection_id==c.id)).all()
        for p in linked:
            from .ai_parameters import validate
            validate(c.kind,p.model,p.reasoning_effort)
            p.kind=c.kind;p.endpoint=c.endpoint;p.encrypted_key=''
        if destination_changed:
            from .models import AIUsagePolicy
            policy=db.get(AIUsagePolicy,wid)
            if policy:
                ids={p.id for p in linked}
                policy.prices={k:v for k,v in policy.prices.items() if k not in ids}
        # A shared key-only rotation no longer changes a Provider row. Invalidate
        # in-flight AI contexts just as the legacy provider trigger did.
        db.execute(update(Workspace).where(Workspace.id==wid).values(ai_epoch=Workspace.ai_epoch+1))
        db.flush()
        return public(c,len(linked))

    @router.post('/ai/connections')
    def create(wid:str,data:ConnectionInput,db:Session=Depends(get_db,scope='function')):
        lock(db,wid)
        if len(db.scalars(select(AIConnection.id).where(AIConnection.workspace_id==wid)).all())>=30:raise HTTPException(422,'เพิ่มได้สูงสุด 30 การเชื่อมต่อ')
        return save(db,wid,data)

    @router.put('/ai/connections/{cid}')
    def edit(wid:str,cid:str,data:ConnectionInput,db:Session=Depends(get_db,scope='function')):
        lock(db,wid)
        return save(db,wid,data,get_scoped(db,AIConnection,wid,cid))

    @router.delete('/ai/connections/{cid}')
    def remove(wid:str,cid:str,db:Session=Depends(get_db,scope='function')):
        lock(db,wid);c=get_scoped(db,AIConnection,wid,cid)
        if db.scalar(select(Provider.id).where(Provider.workspace_id==wid,Provider.connection_id==cid).limit(1)):raise HTTPException(409,'ยังมีโมเดลใช้การเชื่อมต่อนี้ ย้ายหรือลบโมเดลก่อน')
        db.delete(c)
        db.execute(update(Workspace).where(Workspace.id==wid).values(ai_epoch=Workspace.ai_epoch+1))
        return {'ok':True}
