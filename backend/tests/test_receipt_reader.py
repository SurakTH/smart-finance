"""Document extraction is separate from tools, bank layouts and permission."""
import io,json
import httpx
import pytest
from PIL import Image
from app import ai
from app.receipt_reader import Reading,normalize,satang,printed_date,text_messages
from app.db import SessionLocal
from app.models import Provider
from app.worker import run_once


def document(**patch):
    data=dict(is_receipt=True,currency='THB',paid_amount='100.00',paid_label='Amount paid',gross_amount='120.00',subsidy_or_discount='-20.00',fee=None,date_text='20 ต.ค. 2569 12:10',merchant='Synthetic merchant',kind='expense')
    return {**data,**patch}


def extracted(**patch):
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(document(**patch),ensure_ascii=False)}}],'usage':{'prompt_tokens':500,'completion_tokens':100}})


def image():
    raw=io.BytesIO();Image.new('RGB',(300,500),'white').save(raw,'JPEG')
    return ('synthetic.jpg',raw.getvalue(),'image/jpeg')


@pytest.mark.parametrize('gross,discount,paid',[('120.00','-20.00','100.00'),('45','27','18'),('987.65','12.34','975.31')])
def test_paid_not_gross_or_subsidy(gross,discount,paid):
    value=normalize(Reading(**document(gross_amount=gross,subsidy_or_discount=discount,paid_amount=paid)))
    assert value['paid_satang']==satang(paid) and 'conflicting_amounts' not in value['warnings']
    assert value['occurred_on']=='2026-10-20'


@pytest.mark.parametrize('patch,warning',[
    ({'paid_amount':'120.00'},'conflicting_amounts'),({'paid_amount':None},'paid_unreadable'),
    ({'paid_label':None},'paid_unreadable'),({'currency':'other'},'not_thb_receipt'),
    ({'paid_amount':'18,50'},'invalid_amount'),({'paid_amount':'1e6'},'invalid_amount'),
])
def test_no_guess_for_conflicting_or_unclear_amount(patch,warning):
    value=normalize(Reading(**document(**patch)))
    assert value['paid_satang'] is None and warning in value['warnings']


@pytest.mark.parametrize('raw,expected',[
    ('20 ต.ค. 2569 12:10','2026-10-20'),('๒๐ ตุลาคม ๒๕๖๙','2026-10-20'),
    ('2026-10-20T12:10:00','2026-10-20'),('20/10/2569','2026-10-20'),
    ('20 Oct 2026','2026-10-20'),('29/02/2025',None),('20/10/69',None),('not readable',None),
])
def test_calendar_is_independent_of_bank_layout(raw,expected):assert printed_date(raw)==expected


def test_chat_uses_facts_without_repeating_pixels():
    doc=normalize(Reading(**document()))
    messages=[{'role':'user','content':[{'type':'text','text':'ค่าอาหาร'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,PRIVATE-PIXELS'}}]}]
    result=text_messages(messages,doc,'image-id')
    assert 'PRIVATE-PIXELS' not in json.dumps(result) and 'ค่าอาหาร' in result[0]['content']
    assert '10000' in result[0]['content'] and 'untrusted' in result[0]['content']
    assert messages[0]['content'][1]['type']=='image_url'


def transport(monkeypatch,answers,calls):
    real=httpx.Client
    def handler(request):
        body=json.loads(request.content);calls.append(body);answer=answers.pop(0)
        return answer(body) if callable(answer) else answer
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))


def test_inbox_preserves_date_and_components_without_posting(actor,monkeypatch):
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='extract',supports_images=True,retries=0))
    transport(monkeypatch,[extracted()],calls)
    response=c.post(base+'/attachments',files={'file':image()},data={'text':'ค่าอาหาร'}).json()
    while run_once():pass
    proposals=c.get(base+'/proposals').json();assert len(proposals)==1;p=proposals[0]
    assert p['amount']==10000 and p['description']=='ค่าอาหาร' and p['occurred_on']=='2026-10-20'
    assert p['receipt']['gross_satang']==12000 and p['receipt']['subsidy_satang']==2000
    assert p['attachment_id']==response['id'] and p['status']=='pending'
    assert c.get(base+'/transaction-report').json()['total']==0
    assert len(calls)==1 and 'tools' not in calls[0] and len(calls[0]['messages'])==2
    assert calls[0]['response_format']['type']=='json_schema'
    c.post(base+'/attachments',files={'file':image()})
    while run_once():pass
    assert len(calls)==1


def test_chat_pixel_stage_then_text_draft_then_confirmation(actor,monkeypatch):
    from test_assistant_finance import tool
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    accounts=c.get(base+'/accounts').json();wallet=next(a['id'] for a in accounts if a['kind']=='asset');category=next(a['id'] for a in accounts if a['kind']=='expense')
    draft=dict(intent='create',kind='expense',description='ค่าอาหาร',amount=100000,occurred_on='2026-10-21',account_id=wallet,category_id=category)
    def text_only(body):
        assert 'data:image' not in json.dumps(body) and 'paid_satang' in json.dumps(body)
        return httpx.Response(200,json={'choices':[{'message':tool('prepare_transaction',draft)}]})
    transport(monkeypatch,[extracted(),text_only],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    upload=c.post(path+'/images',files={'file':image()},data={'text':'ค่าอาหาร เงินสด จดให้หน่อย'}).json()
    while run_once():pass
    reply=c.get(path+'/messages').json()[-1]
    assert '฿100.00' in reply['content'] and '2026-10-20' in reply['content']
    assert '120.00 บาท' in reply['content'] and '20.00 บาท' in reply['content']
    assert reply['attachment_id']==upload['attachment_id']
    assert c.get(base+'/transaction-report').json()['total']==0 and len(calls)==2
    for _ in range(2):c.post(path+'/messages',json={'text':'ยืนยัน'})
    report=c.get(base+'/transaction-report').json()
    assert report['total']==1 and report['expense']==10000
    assert c.get(base+'/proposals').json()[0]['receipt']['paid_satang']==10000


def test_followup_does_not_resend_pixels(actor,monkeypatch):
    from test_assistant_finance import tool
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    accounts=c.get(base+'/accounts').json();wallet=next(a['id'] for a in accounts if a['kind']=='asset');category=next(a['id'] for a in accounts if a['kind']=='expense')
    first=tool('prepare_transaction',dict(intent='create',kind='expense',description='ค่าอาหาร',amount=10000))
    followup=tool('prepare_transaction',dict(intent='create',continue_draft=True,account_id=wallet,category_id=category))
    def continue_text(body):
        assert 'data:image' not in json.dumps(body) and 'paid_satang' in json.dumps(body)
        return httpx.Response(200,json={'choices':[{'message':followup}]})
    transport(monkeypatch,[extracted(),httpx.Response(200,json={'choices':[{'message':first}]}),continue_text],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    c.post(path+'/images',files={'file':image()},data={'text':'ค่าอาหาร จดให้หน่อย'})
    while run_once():pass
    c.post(path+'/messages',json={'text':'เงินสด หมวดอาหาร'})
    while run_once():pass
    assert 'กรุณาตรวจสอบ' in c.get(path+'/messages').json()[-1]['content']
    assert sum('data:image' in json.dumps(b) for b in calls)==1
    assert c.get(base+'/transaction-report').json()['total']==0


def test_unreadable_paid_cannot_be_replaced_by_guessed_gross(actor,monkeypatch):
    from test_assistant_finance import tool
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    output=tool('prepare_transaction',dict(intent='create',kind='expense',description='ค่าอาหาร',amount=12000))
    transport(monkeypatch,[extracted(paid_amount=None),extracted(paid_amount=None),httpx.Response(200,json={'choices':[{'message':output}]})],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    c.post(path+'/images',files={'file':image()},data={'text':'จดให้หน่อย'})
    while run_once():pass
    assert 'ยอดเท่าไหร่' in c.get(path+'/messages').json()[-1]['content']
    c.post(path+'/messages',json={'text':'ยืนยัน'})
    assert c.get(base+'/transaction-report').json()['total']==0


def test_one_retry_for_unclear_financial_document_then_preserve_paid_amount(actor,monkeypatch):
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='extract',supports_images=True,retries=0))
    transport(monkeypatch,[extracted(paid_amount=None),extracted()],calls)
    c.post(base+'/attachments',files={'file':image()})
    while run_once():pass
    assert len(calls)==2 and c.get(base+'/proposals').json()[0]['amount']==10000
    assert c.get(base+'/transaction-report').json()['total']==0


def test_unrelated_image_does_not_force_receipt_or_retry(actor,monkeypatch):
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='extract',supports_images=True,retries=0))
    transport(monkeypatch,[extracted(is_receipt=False,currency='unknown',paid_amount=None,paid_label=None,gross_amount=None,subsidy_or_discount=None,date_text=None,merchant=None,kind='unknown')],calls)
    c.post(base+'/attachments',files={'file':image()})
    while run_once():pass
    assert len(calls)==1 and c.get(base+'/proposals').json()==[]
    assert c.get(base+'/transaction-report').json()['total']==0


@pytest.mark.parametrize('amounts,valid',[( (6000,4000),True),((10000,10000),False)])
def test_image_batch_preserves_item_amounts_and_checks_sum(actor,monkeypatch,amounts,valid):
    from test_assistant_finance import tool
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    accounts=c.get(base+'/accounts').json();wallet=next(a['id'] for a in accounts if a['kind']=='asset');category=next(a['id'] for a in accounts if a['kind']=='expense')
    items=[dict(kind='expense',description='item '+str(i),amount=n,account_id=wallet,category_id=category) for i,n in enumerate(amounts)]
    output=tool('prepare_transaction',dict(intent='create',transactions=items))
    transport(monkeypatch,[extracted(),httpx.Response(200,json={'choices':[{'message':output}]})],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    c.post(path+'/images',files={'file':image()},data={'text':'จดแยกรายการให้หน่อย'})
    while run_once():pass
    reply=c.get(path+'/messages').json()[-1]['content']
    assert ('กรุณาตรวจสอบ' in reply) is valid
    assert c.get(base+'/transaction-report').json()['total']==0
    c.post(path+'/messages',json={'text':'ยืนยัน'})
    report=c.get(base+'/transaction-report').json()
    assert report['total']==(2 if valid else 0)
    if valid:assert report['expense']==10000


def test_phone_exif_orientation_is_applied_before_model_input(actor):
    c,w,u=actor;base=f'/workspaces/{w}'
    im=Image.new('RGB',(200,100),'red');exif=Image.Exif();exif[274]=6
    raw=io.BytesIO();im.save(raw,'JPEG',exif=exif)
    result=c.post(base+'/attachments',files={'file':('rotated.jpg',raw.getvalue(),'image/jpeg')}).json()
    stored=c.get(base+'/attachments/'+result['id']).content
    with Image.open(io.BytesIO(stored)) as decoded:
        assert decoded.size==(100,200) and not decoded.getexif()


def test_receipt_from_another_room_is_rejected_before_network(actor,monkeypatch):
    from app.models import Job
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    rooms=[c.post(base+'/conversations',json={}).json()['id'] for _ in range(2)]
    foreign=c.post(base+f'/conversations/{rooms[0]}/images',files={'file':image()}).json()
    # Keep the foreign room's queued job from running; only probe the tampered
    # current-room job, whose attachment must match a user message in that room.
    with SessionLocal.begin() as db:db.get(Job,foreign['job_id']).status='cancelled'
    other=io.BytesIO();Image.new('RGB',(320,500),'blue').save(other,'JPEG')
    current=c.post(base+f'/conversations/{rooms[1]}/images',files={'file':('own.jpg',other.getvalue(),'image/jpeg')}).json()
    with SessionLocal.begin() as db:
        job=db.get(Job,current['job_id']);job.payload={**job.payload,'attachment_id':foreign['attachment_id']}
    transport(monkeypatch,[],calls)
    while run_once():pass
    assert calls==[] and c.get(base+'/transaction-report').json()['total']==0


def test_receipt_question_renders_document_not_ledger_numbers(actor,monkeypatch):
    from test_assistant_finance import tool
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    output=tool('render_receipt',{})
    transport(monkeypatch,[extracted(),httpx.Response(200,json={'choices':[{'message':output}]})],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    c.post(path+'/images',files={'file':image()},data={'text':'รูปนี้จ่ายจริงเท่าไหร่ ทำไมมีส่วนลด'})
    while run_once():pass
    reply=c.get(path+'/messages').json()[-1]
    assert '100.00 บาท' in reply['content'] and '120.00 บาท' in reply['content']
    assert 'ข้อมูลจากภาพ ไม่ใช่ยอดในบัญชี' in reply['content']
    assert not reply.get('references') and c.get(base+'/transaction-report').json()['total']==0
    assert len(calls)==2


@pytest.mark.parametrize('prose',['จ่ายจริง 100 บาทค่ะ','รบกวนส่งรูปสลิปมาด้วยนะครับ','อยากใช้บัญชีไหนและหมวดอะไรคะ?'])
def test_small_model_prose_recovers_to_real_draft_with_structured_decision(actor,monkeypatch,prose):
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    decision=dict(action='prepare',kind='expense',description='ค่าอาหาร',account='เงินสด',category='อาหารและเครื่องดื่ม',other_account=None)
    def decide(body):
        assert body['response_format']['json_schema']['name']=='receipt_action'
        assert 'data:image' not in json.dumps(body) and 'tools' not in body
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(decision,ensure_ascii=False)}}]})
    transport(monkeypatch,[extracted(),httpx.Response(200,json={'choices':[{'message':{'content':prose}}]}),decide],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    c.post(path+'/images',files={'file':image()},data={'text':'ช่วยจดค่าอาหารจากรูป เงินสด'})
    while run_once():pass
    assert 'กรุณาตรวจสอบ' in c.get(path+'/messages').json()[-1]['content']
    assert c.get(base+'/transaction-report').json()['total']==0 and len(calls)==3
    c.post(path+'/messages',json={'text':'ยืนยัน'})
    assert c.get(base+'/transaction-report').json()['expense']==10000


def test_valid_reading_cache_matches_source_and_does_not_freeze_unclear_results():
    from app.receipt_reader import cached,signature
    from types import SimpleNamespace
    p=SimpleNamespace(id='p',kind='ollama',model='vision',temperature=10,reasoning_effort='none',max_tokens=4096,connection_id=None,endpoint='http://local/v1')
    value=dict(attachment_id='a',signature=signature(p,'caption'),document=normalize(Reading(**document())))
    room=SimpleNamespace(capture_context={'receipt_reading':value})
    assert cached(room,'a',p,'caption') is value
    assert cached(room,'other-image',p,'caption') is None and cached(room,'a',p,'different-caption') is None
    p.endpoint='http://other/v1'
    assert cached(room,'a',p,'caption') is None
    p.endpoint='http://local/v1';value['document']['paid_satang']=None
    assert cached(room,'a',p,'caption') is None


def test_nonreceipt_photo_does_not_override_amount_explicitly_supplied_by_user(actor,monkeypatch):
    from test_assistant_finance import tool
    c,w,u=actor;base=f'/workspaces/{w}';calls=[]
    with SessionLocal.begin() as db:db.add(Provider(workspace_id=w,kind='ollama',model='vision',task='chat',supports_images=True,retries=0))
    accounts=c.get(base+'/accounts').json();wallet=next(a['id'] for a in accounts if a['kind']=='asset');category=next(a['id'] for a in accounts if a['kind']=='expense')
    output=tool('prepare_transaction',dict(intent='create',kind='expense',description='กาแฟ',amount=7500,account_id=wallet,category_id=category))
    unrelated=extracted(is_receipt=False,currency='unknown',paid_amount=None,paid_label=None,gross_amount=None,subsidy_or_discount=None,date_text=None,merchant=None,kind='unknown')
    transport(monkeypatch,[unrelated,httpx.Response(200,json={'choices':[{'message':output}]})],calls)
    cid=c.post(base+'/conversations',json={}).json()['id'];path=base+f'/conversations/{cid}'
    c.post(path+'/images',files={'file':image()},data={'text':'นี่รูปกาแฟ ซื้อ75บาทเงินสด ช่วยจดหน่อย'})
    while run_once():pass
    reply=c.get(path+'/messages').json()[-1]['content']
    assert 'กรุณาตรวจสอบ' in reply and '฿75.00' in reply
    assert c.get(base+'/transaction-report').json()['total']==0
