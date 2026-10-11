"""Web Chat uses current workspace routes, not legacy per-room privacy flags."""
import json
import httpx
import pytest
from app import ai
from app.db import SessionLocal
from app.models import Provider
from app.worker import run_once
from test_chat_images import receipt

@pytest.mark.parametrize('legacy',[None,'private','standard'])
def test_all_rooms_use_workspace_priority_fallback_and_cloud_switch(actor,monkeypatch,legacy):
    c,w,u=actor;b=f'/workspaces/{w}'
    with SessionLocal.begin() as db:
        db.add_all([Provider(workspace_id=w,kind='groq',task='chat',model='first-cloud',priority=1,retries=0),Provider(workspace_id=w,kind='ollama',task='chat',model='second-local',priority=2,retries=0)])
    c.put(b+'/ai/settings',json={'cloud_enabled':True})
    body={} if legacy is None else {'privacy':legacy}
    room=c.post(b+'/conversations',json=body).json();assert room['routing']=='workspace'
    calls=[];real=httpx.Client
    def handler(req):
        data=json.loads(req.content);calls.append(data['model'])
        assert w in data['messages'][0]['content'] and 'ไม่ถาม workspace ซ้ำ' in data['messages'][0]['content']
        if data['model']=='first-cloud':return httpx.Response(503)
        return httpx.Response(200,json={'choices':[{'message':{'content':'สวัสดีค่ะ ใช้พื้นที่ที่เลือกอยู่ได้เลย'}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    def send():
        c.post(b+f'/conversations/{room["id"]}/messages',json={'text':'คุยหน่อยค่ะ'})
        while run_once():pass
    send();assert calls==['first-cloud','second-local']
    calls.clear();c.put(b+'/ai/settings',json={'cloud_enabled':False});send()
    assert calls==['second-local']
    assert c.get(b+'/transactions').json()==[]


def test_queued_chat_image_uses_current_workspace_switch_and_vision_route(actor,monkeypatch):
    c,w,u=actor;b=f'/workspaces/{w}'
    with SessionLocal.begin() as db:
        db.add_all([Provider(workspace_id=w,kind='groq',task='chat',model='cloud-text',priority=1,retries=0,supports_images=False),Provider(workspace_id=w,kind='groq',task='chat',model='cloud-vision',priority=2,retries=0,supports_images=True),Provider(workspace_id=w,kind='ollama',task='chat',model='local-vision',priority=3,retries=0,supports_images=True)])
    cid=c.post(b+'/conversations',json={}).json()['id']
    c.put(b+'/ai/settings',json={'cloud_enabled':True})
    calls=[];real=httpx.Client
    def handler(req):
        data=json.loads(req.content);calls.append(data['model'])
        assert any(isinstance(m['content'],list) for m in data['messages'])
        return httpx.Response(200,json={'choices':[{'message':{'content':'เป็นรูปสลิปค่ะ ยังไม่ได้บันทึก'}}]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'รูปนี้คืออะไร'})
    while run_once():pass
    assert calls==['cloud-vision'];calls.clear()
    c.post(b+f'/conversations/{cid}/images',files={'file':receipt()},data={'text':'ช่วยดูภาพอีกครั้ง'})
    c.put(b+'/ai/settings',json={'cloud_enabled':False})
    while run_once():pass
    assert calls==['local-vision']
    assert c.get(b+'/transactions').json()==[]
