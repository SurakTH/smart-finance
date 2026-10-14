"""Tool catalog and pure preflight checks. No posting or draft mutation here."""
import json
from pydantic import BaseModel,ConfigDict,ValidationError
from typing import Literal
from sqlalchemy import select
from .models import Account
from .tool_arguments import issues

class Toolkit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    toolkit:Literal['management','corrections']


def all_tools():
    from .chat_dialogue import tool
    from .assistant_management import tool as management
    from .assistant_finance import tools
    from .assistant_lookup import tool as lookup
    from .request_interpreter import tool as interpret_tool
    from .semantic_assistant import tools as semantic_tools
    from .assistant_data import tool as fetch_tool
    return [tool(),management(),*tools(),lookup(),interpret_tool(),*semantic_tools(),fetch_tool()]


def catalog(active):
    names={'prepare_transaction','lookup_workspace','fetch_finance'}
    if 'conversation_answer' in active:names.add('respond_finance')
    if 'management' in active:names.add('prepare_management_plan')
    if 'corrections' in active:names.add('prepare_correction')
    result=[tool for tool in all_tools() if tool['function']['name'] in names]
    result.append({'type':'function','function':{'name':'load_toolkit','description':'Load additional tools only when needed: management for accounts/categories/budgets/goals/recurring changes; corrections for editing a recorded transaction after searching it. Read-only discovery, never changes financial data.','parameters':Toolkit.model_json_schema()}})
    return result


def validate_draft(db,room,name,raw):
    from .chat_dialogue import Suggestion
    from .assistant_management import Plan
    from .assistant_finance import Correct
    model={'prepare_transaction':Suggestion,'prepare_management_plan':Plan,'prepare_correction':Correct}[name]
    try:data=model.model_validate_json(raw)
    except ValidationError as error:
        return dict(error='invalid_arguments',issues=issues(error),message='แก้ช่องที่ระบุตาม schema แล้วส่งร่างใหม่ จำนวนเป็นจำนวนเต็มสตางค์ ไม่ต้องให้ผู้ใช้กรอก JSON')
    values=[]
    if name=='prepare_transaction':
        if data.transactions is not None and (data.intent!='create' or any(getattr(data,k) is not None for k in ('kind','description','amount','account_id','category_id','other_account_id','occurred_on'))):
            return dict(error='invalid_arguments',issues=[dict(field='transactions',code='invalid')],message='ส่งรายการเดี่ยวหรือ transactions ทั้งชุดอย่างใดอย่างหนึ่ง ห้ามผสม')
        values=data.transactions if data.transactions is not None else [data]
    elif name=='prepare_correction':values=[data.changes]
    identifiers={str(getattr(item,key)) for item in values for key in ('account_id','category_id','other_account_id') if getattr(item,key,None) is not None}
    if identifiers:
        owned=set(db.scalars(select(Account.id).where(Account.workspace_id==room.workspace_id,Account.id.in_(identifiers))))
        bad=[dict(field=key,code='unknown_reference') for key in ('account_id','category_id','other_account_id') if any(getattr(item,key,None) is not None and str(getattr(item,key)) not in owned for item in values)]
        if bad:return dict(error='invalid_reference',issues=bad,message='ID บัญชีหรือหมวดไม่อยู่ในพื้นที่นี้ ใช้ lookup_workspace ค้นชื่อจากคำขอเดิม ห้ามเดา ID หรือเปลี่ยนยอด')
    return None


def canonical_read(name,raw):
    from .assistant_lookup import Lookup
    from .assistant_finance import Read
    model=Lookup if name=='lookup_workspace' else Read
    try:value=model.model_validate_json(raw).model_dump(mode='json',exclude_defaults=True)
    except ValidationError:return None
    return name,json.dumps(value,sort_keys=True,ensure_ascii=False)
