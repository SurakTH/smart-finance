"""Bounded provider-specific reasoning controls; never silently retry without the chosen setting."""
from fastapi import HTTPException
import re

def validate(kind,model,effort):
    if effort=='default':return
    lower=model.lower()
    if kind=='gemini':
        if effort=='xhigh' or (effort=='none' and ('gemini-3' in lower or 'pro' in lower)):
            raise HTTPException(422,'Gemini รุ่นนี้ไม่รองรับระดับ Thinking ที่เลือก ใช้ค่าเริ่มต้นหรือน้อย/ปานกลาง/มาก')
    if kind=='groq' and (effort in ('minimal','xhigh') or (effort=='none' and 'gpt-oss' in lower)):
        raise HTTPException(422,'โมเดล Groq นี้รองรับ Thinking น้อย/ปานกลาง/มาก หรือค่าเริ่มต้น')

def parameters(p):
    effort=getattr(p,'reasoning_effort','default')
    if effort=='default':
        body={('max_completion_tokens' if p.kind in ('openai','groq') else 'max_tokens'):p.max_tokens} if p.max_tokens else {}
        if not (p.kind=='openai' and re.match(r'^(?:o\d|gpt-[56])',p.model)):
            body['temperature']=p.temperature/100
        return body
    validate(p.kind,p.model,effort)
    body={'max_tokens':p.max_tokens} if p.max_tokens else {}
    # Tool continuations can need private reasoning blocks/signatures. They are
    # handled in memory by the backend, never displayed or saved as chat history.
    if p.kind=='openrouter':body['reasoning']={'effort':effort,'exclude':False}
    else:body['reasoning_effort']=effort
    if p.kind in ('openai','groq'):
        body={**({'max_completion_tokens':p.max_tokens} if p.max_tokens else {}),**{k:v for k,v in body.items() if k!='max_tokens'}}
    # Reasoning models may reject temperature; let the model's sampling defaults apply.
    if p.kind=='groq':
        body['include_reasoning']=False if 'gpt-oss' in p.model.lower() else None
        if body['include_reasoning'] is None:
            body.pop('include_reasoning');body['reasoning_format']='hidden'
    return body
