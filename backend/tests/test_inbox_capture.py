"""Receipt captions, deduplication and bounded extraction; no ledger writes."""
import io
import json
from PIL import Image
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import Job,Provider,Proposal,Entry
from app import ai
from app.worker import run_once

def image():
    buf=io.BytesIO();Image.new('RGB',(24,24),'green').save(buf,'PNG')
    return {'file':('receipt.png',buf.getvalue(),'image/png')}

def test_caption_validation_retry_and_duplicate_queue(actor):
    c,w,u=actor;base=f'/workspaces/{w}'
    assert c.post(base+'/attachments',files=image(),data={'text':'x'*4001}).status_code==422
    response=c.post(base+'/attachments',files=image(),data={'text':'  ค่าหนังสือ  ','privacy':'standard'})
    assert response.status_code==200
    first=response.json();assert first['queued'] and not first['reused']
    again=c.post(base+'/attachments',files=image(),data={'text':'different'}).json()
    assert again['reused'] and again['job_id']==first['job_id']
    with SessionLocal.begin() as db:
        job=db.get(Job,first['job_id'])
        assert job.payload['text']=='ค่าหนังสือ' and job.payload['privacy']=='standard'
        assert db.scalar(select(func.count()).select_from(Job).where(Job.workspace_id==w))==1
        job.status='failed';job.payload={};job.error='processing_failed'
    retry=c.post(base+'/attachments',files=image(),data={'text':'ลองใหม่'}).json()
    assert retry['duplicate'] and retry['queued'] and not retry['reused']
    assert retry['job_id']!=first['job_id']
    while run_once():pass
    assert c.get(base+'/transactions').json()==[]
    done=c.post(base+'/attachments',files=image()).json()
    assert done['reused'] and not done['queued'] and done['job_id'] is None
    other=c.post('/workspaces',json={'name':'Separate receipts'}).json()['id']
    isolated=c.post(f'/workspaces/{other}/attachments',files=image()).json()
    assert not isolated['duplicate'] and isolated['id']!=first['id']

def test_receipt_request_uses_caption_vision_provider_and_small_output_budget(actor,monkeypatch):
    c,w,u=actor;base=f'/workspaces/{w}';requests=[]
    with SessionLocal.begin() as db:
        db.add_all([Provider(workspace_id=w,kind='ollama',task='extract',model='text-only',priority=0,supports_images=False,max_tokens=0),Provider(workspace_id=w,kind='ollama',task='extract',model='vision',priority=1,supports_images=True,max_tokens=100000)])
    monkeypatch.setattr(ai,'target',lambda p:('http://unused/v1',{},{}))
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_bytes(self):
            yield json.dumps({'choices':[{'message':{'content':'  ```json\n{"proposals":[{"description":"ค่าหนังสือ","amount":12550,"kind":"expense"}]}\n```  '}}]}).encode()
    def stream(db,job,provider,client,method,url,**kwargs):
        requests.append(kwargs['json']);return Reply()
    monkeypatch.setattr(ai,'tracked_stream',stream)
    monkeypatch.setattr(ai,'ensure_response',lambda r:None)
    result=c.post(base+'/attachments',files=image(),data={'text':'ค่าหนังสือ'}).json()
    while run_once():pass
    assert len(requests)==1
    body=requests[0];assert body['model']=='vision' and body['max_tokens']==4096
    assert 'tools' not in body and len(body['messages'])==2
    assert 'ค่าหนังสือ' in body['messages'][1]['content'][0]['text']
    assert body['messages'][1]['content'][1]['type']=='image_url'
    drafts=c.get(base+'/proposals').json()
    assert len(drafts)==1 and drafts[0]['amount']==12550 and drafts[0]['attachment_id']==result['id']
    assert drafts[0]['source']=='ai' and drafts[0]['status']=='pending'
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Entry).where(Entry.workspace_id==w))==0
    c.post(base+'/attachments',files=image())
    while run_once():pass
    assert len(requests)==1

import pytest

@pytest.mark.parametrize('cloud_enabled',[False,True])
@pytest.mark.parametrize('with_image',[False,True])
def test_inbox_without_mode_follows_workspace_routes(actor,monkeypatch,cloud_enabled,with_image):
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    assert c.put(base+'/ai/settings',json={'cloud_enabled':cloud_enabled}).status_code==200
    with SessionLocal.begin() as db:
        db.add_all([Provider(workspace_id=w,kind='compatible',task='extract',model='cloud-first',priority=0,supports_images=True),Provider(workspace_id=w,kind='ollama',task='extract',model='local-second',priority=1,supports_images=True)])
    monkeypatch.setattr(ai,'target',lambda p:('http://unused/v1',{},{}))
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_bytes(self):yield json.dumps({'choices':[{'message':{'content':json.dumps({'proposals':[{'description':'ค่าหนังสือ','amount':6000,'kind':'expense'}]})}}]}).encode()
    def stream(db,job,provider,client,*args,**kwargs):
        calls.append(provider.model);return Reply()
    monkeypatch.setattr(ai,'tracked_stream',stream)
    monkeypatch.setattr(ai,'ensure_response',lambda r:None)
    response=c.post(base+'/attachments',files=image(),data={'text':'ค่าหนังสือ'}) if with_image else c.post(base+'/capture',json={'text':'ค่าหนังสือ 60'})
    assert response.status_code==200
    with SessionLocal() as db:assert db.get(Job,response.json()['job_id']).payload['privacy'] is None
    while run_once():pass
    assert calls==['cloud-first' if cloud_enabled else 'local-second']
    assert c.get(base+'/proposals').json()[0]['status']=='pending'
    assert c.get(base+'/transactions').json()==[]
