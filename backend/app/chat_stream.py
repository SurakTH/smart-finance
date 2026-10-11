"""Ephemeral Pub/Sub previews. Only committed Message rows are chat history."""
import asyncio
import anyio
import json
import time
from fastapi import HTTPException
from redis.asyncio import Redis as AsyncRedis
from starlette.concurrency import run_in_threadpool
from .config import REDIS_URL
from .db import SessionLocal
from .models import Session,Membership,Conversation,Workspace,now
from .security import digest,redis

MAX_TEXT=16000

def channel(wid,cid):return 'sf:chat-live:'+wid+':'+cid

def publish(job,kind,**data):
    cid=job.payload.get('conversation_id')
    if not cid or getattr(job,'_stream_disabled',False):return
    try:
        redis.publish(channel(job.workspace_id,cid),json.dumps(dict(kind=kind,job_id=job.id,**data),ensure_ascii=False))
    except Exception:
        # No stored Redis keys, replay cache or logs containing chat content.
        job._stream_disabled=True

def authorized(token,wid,cid):
    with SessionLocal() as db:
        session=db.get(Session,digest(token))
        if not session or session.expires<=now():raise HTTPException(401,'กรุณาเข้าสู่ระบบ')
        ws=db.get(Workspace,wid)
        if not ws or ws.archived_at is not None:raise HTTPException(404,'ไม่พบห้องสนทนา')
        if not db.get(Membership,(session.user_id,wid)):raise HTTPException(404,'ไม่พบห้องสนทนา')
        c=db.get(Conversation,cid)
        from .chat_privacy import expired
        if not c or c.workspace_id!=wid or c.user_id!=session.user_id or expired(db,c):
            raise HTTPException(404,'ไม่พบห้องสนทนา หรือหมดอายุแล้ว')

def frame(data):return 'data: '+json.dumps(data,ensure_ascii=False)+'\n\n'

async def events(request,token,wid,cid):
    client=AsyncRedis.from_url(REDIS_URL,socket_connect_timeout=2,socket_timeout=2)
    sub=client.pubsub()
    try:
        await sub.subscribe(channel(wid,cid))
        yield frame({'kind':'ready'})
        deadline=time.monotonic()+120
        while time.monotonic()<deadline and not await request.is_disconnected():
            # Short read-only transactions never wait on the worker's workspace lock.
            try:await run_in_threadpool(authorized,token,wid,cid)
            except HTTPException:
                yield frame({'kind':'closed'});return
            item=await sub.get_message(ignore_subscribe_messages=True,timeout=1)
            if item and item['type']=='message':
                try:await run_in_threadpool(authorized,token,wid,cid)
                except HTTPException:
                    yield frame({'kind':'closed'});return
                raw=item['data']
                if len(raw)>100000:continue
                data=json.loads(raw)
                if data.get('kind') in ('start','delta','done','failed','stopping','cancelled'):
                    yield frame(data)
            else:
                yield ': heartbeat\n\n'
            await asyncio.sleep(.02)
    except Exception:
        yield frame({'kind':'unavailable'})
    finally:
        # ASGI cancels the producer on disconnect; still close its Redis sockets.
        with anyio.move_on_after(3,shield=True):
            try:await sub.aclose()
            finally:await client.aclose()

def read_completion(response,job):
    """Bounded OpenAI-compatible SSE reader; interrupted output is never committed."""
    text='';size=0;finished=False;fields=[];deadline=time.monotonic()+45
    for line in response.iter_lines():
        from .chat_stop import check
        check(job)
        if time.monotonic()>deadline:raise ValueError('Stream timeout')
        size+=len(line.encode('utf-8'))+1
        if size>256000:raise ValueError('Response too large')
        if line.startswith('data:'):fields.append(line[5:].lstrip(' '))
        elif line=='':
            if not fields:continue
            raw='\n'.join(fields);fields=[]
            if raw=='[DONE]':finished=True;break
            data=json.loads(raw)
            if not isinstance(data,dict) or 'error' in data:raise ValueError('Provider stream failed')
            choices=data.get('choices',[])
            if not isinstance(choices,list):raise ValueError('Invalid choices')
            if not choices:continue
            first=choices[0]
            if not isinstance(first,dict) or not isinstance(first.get('delta',{}),dict):raise ValueError('Invalid delta')
            if first.get('finish_reason') is not None:finished=True
            delta=first.get('delta',{}).get('content')
            if delta is None:continue
            if not isinstance(delta,str) or len(text)+len(delta)>MAX_TEXT:raise ValueError('Invalid response')
            text+=delta
            if delta:publish(job,'delta',text=text,snapshot=True)
    if not finished or not text:raise ValueError('Interrupted or empty stream')
    return text
