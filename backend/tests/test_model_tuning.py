"""Settings must survive editing and reach the real request adapter unchanged."""
import json
from types import SimpleNamespace
import httpx
import pytest
from app import ai
from app.ai_parameters import parameters
from app.worker import run_once

@pytest.mark.parametrize('kind',['compatible','ollama','openrouter','gemini'])
@pytest.mark.parametrize('effort',['default','none','high'])
def test_temperature_and_thinking_are_independent_for_compatible_providers(kind,effort):
    body=parameters(SimpleNamespace(kind=kind,model='test-model',reasoning_effort=effort,max_tokens=32000,temperature=70))
    assert body['temperature']==.7 and body['max_tokens']==32000
    if effort!='default':
        assert (body['reasoning']['effort'] if kind=='openrouter' else body['reasoning_effort'])==effort

@pytest.mark.parametrize('budget',[32000,0])
def test_saved_custom_thinking_temperature_and_budget_reach_request(actor,monkeypatch,budget):
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    assert c.put(base+'/ai/settings',json={'cloud_enabled':True}).status_code==200
    result=c.post(base+'/providers',json={'kind':'compatible','endpoint':'http://192.168.1.30:8081/v1','model':'qwen-test','task':'extract','reasoning_effort':'high','temperature':70,'max_tokens':budget})
    assert result.status_code==200
    saved=c.get(base+'/providers').json()[0]
    assert saved['max_tokens']==budget and saved['temperature']==70 and saved['reasoning_effort']=='high'
    real=httpx.Client
    def handler(req):
        body=json.loads(req.content);calls.append(body)
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'proposals':[{'description':'ค่าหนังสือ','amount':6000,'kind':'expense'}]})}}]})
    monkeypatch.setattr(ai,'target',lambda p:('http://unused/v1',{},{}))
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    assert c.post(base+'/capture',json={'text':'ค่าหนังสือ 60'}).status_code==200
    while run_once():pass
    assert len(calls)==1
    assert calls[0]['temperature']==.7 and calls[0]['reasoning_effort']=='high'
    if budget:assert calls[0]['max_tokens']==budget
    else:assert 'max_tokens' not in calls[0] and 'max_completion_tokens' not in calls[0]
    assert c.get(base+'/proposals').json()[0]['amount']==6000
    assert c.get(base+'/transactions').json()==[]
