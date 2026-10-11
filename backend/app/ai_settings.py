"""Owner-only AI configuration. Keys never leave the backend; custom HTTP(S) endpoints are owner-managed."""
import ipaddress
import socket
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import config
from .db import get_db
from .models import AISettings, Provider, Workspace
from .schemas import AISettingsInput, AIRoutesInput, ProviderInput
from .security import owner, login_limit
from .ledger import get_scoped

router=APIRouter(prefix='/workspaces/{wid}',dependencies=[Depends(owner)])
ENDPOINTS={
    'gemini':'https://generativelanguage.googleapis.com/v1beta/openai',
    'openrouter':'https://openrouter.ai/api/v1',
    'groq':'https://api.groq.com/openai/v1',
    'openai':'https://api.openai.com/v1',
}

def settings(db,wid):
    row=db.get(AISettings,wid)
    # Legacy .env is an initial default only; a saved workspace choice takes precedence.
    return dict(cloud_enabled=row.cloud_enabled if row else config.EXTERNAL_AI_ENABLED,
        demo_fallback=row.demo_fallback if row else True,
        max_attempted_providers=row.max_attempted_providers if row else 3)

def allowed_ip(value):
    ip=ipaddress.ip_address(value)
    if isinstance(ip,ipaddress.IPv6Address) and ip.ipv4_mapped:ip=ip.ipv4_mapped
    if str(ip) in ('100.100.100.200','fd00:ec2::254'):return False
    if ip.is_loopback:return True
    # Local AI may use LAN, loopback, Docker and Tailscale. Never metadata,
    # link-local, unspecified or multicast destinations, even through DNS.
    return not (ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved) and (ip.is_global or ip.is_private or ip.is_loopback or ip in ipaddress.ip_network('100.64.0.0/10'))

def custom_endpoint(value):
    """Validate an owner-supplied custom HTTP(S) base URL without echoing it."""
    try:
        u=urlsplit(value)
        if u.scheme not in ('http','https') or not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment or (u.port is not None and not 1<=u.port<=65535):raise ValueError()
        if any(c.isspace() or ord(c)<32 for c in value) or '\\' in value:raise ValueError()
        host=u.hostname.encode('idna').decode()
        try:ip=ipaddress.ip_address(host)
        except ValueError:ip=None
        if ip is not None and not allowed_ip(str(ip)):raise ValueError()
        return value.rstrip('/')
    except (ValueError,UnicodeError):
        raise HTTPException(422,'URL ต้องเป็น HTTP หรือ HTTPS พร้อมพอร์ตที่ถูกต้อง ไม่มีรหัสผ่าน query หรือ fragment และไม่ใช่ metadata/link-local')

def target(p):
    """Resolve and pin custom destinations; keep Host/port and TLS SNI.

    Owner-selected local endpoints may reach the server's LAN/Tailscale/Docker
    network. Named cloud providers remain restricted to public destinations.
    """
    if p.kind=='ollama' and not p.endpoint:
        return config.OLLAMA_URL.rstrip('/'),{},{}
    custom=p.kind in ('compatible','ollama')
    base=p.endpoint if custom else ENDPOINTS[p.kind]
    base=custom_endpoint(base or config.COMPATIBLE_URL)
    url=httpx.URL(base);port=url.port or (443 if url.scheme=='https' else 80)
    try:
        addresses=socket.getaddrinfo(url.host,port,type=socket.SOCK_STREAM)
        ips=list(dict.fromkeys(item[4][0] for item in addresses))
        if not ips or any(not (allowed_ip(ip) if custom else ipaddress.ip_address(ip).is_global) for ip in ips):raise ValueError()
    except (OSError,ValueError):
        raise ValueError('Endpoint unavailable') from None
    return str(url.copy_with(host=ips[0])),{'Host':url.netloc.decode()},{'sni_hostname':url.host} if url.scheme=='https' else {}

def serialize(p):
    return {**{k:getattr(p,k) for k in ('id','kind','model','task','priority','name','endpoint','enabled','timeout_seconds','retries','max_tokens','temperature','reasoning_effort','supports_images')},'has_key':bool(p.encrypted_key)}

def lock(db,wid):
    db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())

@router.get('/ai/settings')
def read_settings(wid:str,db:Session=Depends(get_db,scope='function')):
    return settings(db,wid)

@router.put('/ai/settings')
def save_settings(wid:str,data:AISettingsInput,db:Session=Depends(get_db,scope='function')):
    lock(db,wid)
    row=db.get(AISettings,wid)
    if not row:
        row=AISettings(workspace_id=wid);db.add(row)
    for key,value in data.model_dump().items():setattr(row,key,value)
    return data.model_dump()

@router.get('/providers')
def providers(wid:str,db:Session=Depends(get_db,scope='function')):
    return [serialize(p) for p in db.scalars(select(Provider).where(Provider.workspace_id==wid).order_by(Provider.task,Provider.priority,Provider.id))]

def apply(p,data,creating=False):
    from .ai_parameters import validate
    validate(data.kind,data.model,data.reasoning_effort)
    values=data.model_dump(exclude={'api_key','clear_key'})
    if data.kind=='compatible':values['endpoint']=custom_endpoint(data.endpoint or config.COMPATIBLE_URL)
    elif data.kind=='ollama':values['endpoint']=custom_endpoint(data.endpoint) if data.endpoint else ''
    elif data.endpoint:raise HTTPException(422,'ตั้ง URL ได้เฉพาะ Ollama และ Custom API')
    if data.api_key and any(ord(c)<32 or ord(c)>126 for c in data.api_key):raise HTTPException(422,'รูปแบบ API key ไม่ถูกต้อง')
    if data.clear_key and data.api_key:raise HTTPException(422,'เลือกล้างคีย์หรือใส่คีย์ใหม่อย่างใดอย่างหนึ่ง')
    if not creating and (p.kind!=data.kind or (data.kind in ('compatible','ollama') and (p.endpoint or (config.OLLAMA_URL if p.kind=='ollama' else config.COMPATIBLE_URL)).rstrip('/')!=(values['endpoint'] or config.OLLAMA_URL))) and not data.api_key:p.encrypted_key=''
    if data.clear_key:p.encrypted_key=''
    if data.api_key:p.encrypted_key=config.cipher().encrypt(data.api_key.encode()).decode()
    if data.kind in ENDPOINTS and not p.encrypted_key:raise HTTPException(422,'ต้องระบุ API key')
    for key,value in values.items():setattr(p,key,value)

@router.post('/providers')
def create_provider(wid:str,data:ProviderInput,db:Session=Depends(get_db,scope='function')):
    lock(db,wid)
    count=len(db.scalars(select(Provider.id).where(Provider.workspace_id==wid)).all())
    if count>=30:raise HTTPException(422,'เพิ่มได้สูงสุด 30 โมเดลต่อพื้นที่')
    p=Provider(workspace_id=wid,encrypted_key='');apply(p,data,True);db.add(p);db.flush()
    return serialize(p)

@router.put('/providers/{pid}')
def edit_provider(wid:str,pid:str,data:ProviderInput,db:Session=Depends(get_db,scope='function')):
    lock(db,wid);p=get_scoped(db,Provider,wid,pid)
    changed=p.kind!=data.kind or p.model!=data.model or (p.endpoint or '')!=(data.endpoint or '')
    apply(p,data)
    if changed:
        from .models import AIUsagePolicy
        policy=db.get(AIUsagePolicy,wid)
        if policy:policy.prices={k:v for k,v in policy.prices.items() if k!=pid}
    db.flush();return serialize(p)

@router.delete('/providers/{pid}')
def delete_provider(wid:str,pid:str,db:Session=Depends(get_db,scope='function')):
    lock(db,wid);db.delete(get_scoped(db,Provider,wid,pid));return {'ok':True}

@router.put('/ai/routes')
def reorder(wid:str,data:AIRoutesInput,db:Session=Depends(get_db,scope='function')):
    lock(db,wid)
    rows=db.scalars(select(Provider).where(Provider.workspace_id==wid,Provider.task==data.task)).all()
    if len(data.provider_ids)!=len(set(data.provider_ids)) or set(data.provider_ids)!={p.id for p in rows}:
        raise HTTPException(409,'รายการโมเดลเปลี่ยนแล้ว กรุณาโหลดใหม่')
    positions={pid:i for i,pid in enumerate(data.provider_ids)}
    for p in rows:p.priority=positions[p.id]
    return {'ok':True}

def probe(db,wid,pid,models=False):
    # User-triggered, bounded requests; no financial information or provider errors returned.
    login_limit('ai-probe:'+wid)
    p=get_scoped(db,Provider,wid,pid)
    if p.kind!='ollama' and not settings(db,wid)['cloud_enabled']:
        raise HTTPException(403,'เปิดการใช้ Cloud AI ของพื้นที่ก่อนทดสอบ')
    try:
        url,headers,extensions=target(p)
        key=config.cipher().decrypt(p.encrypted_key.encode()).decode() if p.encrypted_key else ''
        if key:headers['Authorization']='Bearer '+key
        with httpx.Client(timeout=httpx.Timeout(10,connect=5),trust_env=False,follow_redirects=False) as client:
            # Models discovery never sends a prompt. Connection test uses a small synthetic prompt.
            method='GET' if models else 'POST'
            path='/models' if models else '/chat/completions'
            from .ai_parameters import parameters
            kwargs={} if models else {'json':{'model':p.model,'messages':[{'role':'user','content':'Reply OK.'}],**parameters(p),'stream':False}}
            if not models and p.task=='chat':
                from .chat_dialogue import tool
                from .ai import assistant_tools
                kwargs['json'].update(tools=assistant_tools(),tool_choice='auto')
                if p.supports_images:
                    import base64,io
                    from PIL import Image
                    buffer=io.BytesIO();Image.new('RGB',(16,16),'white').save(buffer,format='JPEG')
                    kwargs['json']['messages'][0]['content']=[{'type':'text','text':'Reply OK. This is a synthetic test image.'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()}}]
            from .ai_usage import tracked_stream
            from types import SimpleNamespace
            meter_job=SimpleNamespace(workspace_id=wid,task='probe')
            stream=client.stream(method,url+path,headers=headers,extensions=extensions,**kwargs) if models else tracked_stream(db,meter_job,p,client,method,url+path,headers=headers,extensions=extensions,**kwargs)
            with stream as response:
                response.raise_for_status();raw=b''
                for chunk in response.iter_bytes():
                    raw+=chunk
                    if len(raw)>256000:raise ValueError()
                import json
                data=json.loads(raw)
        if models:
            import re
            items=data.get('data',[])
            if not isinstance(items,list):raise ValueError()
            names=sorted({item['id'] for item in items if isinstance(item,dict) and isinstance(item.get('id'),str) and re.fullmatch(r'[a-zA-Z0-9_./:@-]{1,100}',item['id'])})[:300]
            return {'models':names}
        if not isinstance(data['choices'][0]['message']['content'],str):raise ValueError()
        return {'ok':True,'message':'เชื่อมต่อและเรียกโมเดลได้แล้ว'}
    except Exception:
        db.commit()
        # Never expose URL, key, headers, response body, or traceback.
        raise HTTPException(422,'เชื่อมต่อไม่สำเร็จ ตรวจ URL คีย์ ชื่อโมเดล และสิทธิ์ของผู้ให้บริการ') from None

@router.post('/providers/{pid}/test')
def test_provider(wid:str,pid:str,db:Session=Depends(get_db,scope='function')):
    return probe(db,wid,pid)

@router.post('/providers/{pid}/models')
def list_models(wid:str,pid:str,db:Session=Depends(get_db,scope='function')):
    return probe(db,wid,pid,True)
