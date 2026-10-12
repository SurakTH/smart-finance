import asyncio
import uuid
import pytest
from sqlalchemy import select, delete
from app.db import SessionLocal
from app.models import TelegramLink, TelegramDelivery, Job, Message, Provider, Membership, Conversation, now
from app.telegram_chat import submit, ACK, claim, completed, deliver_once
from app.ai import process_job
from test_assistant_finance import assistant, tool
from test_chat_images import receipt


@pytest.fixture
def channel(assistant):
    c,w,u,b,cid,wallet,cat,state,post,send=assistant
    tid=int(uuid.uuid4().hex[:12],16)
    with SessionLocal.begin() as db:
        db.add(TelegramLink(telegram_id=str(tid),workspace_id=w,user_id=u.id))
    def capture(mid,text,data=None):
        with SessionLocal.begin() as db:
            return submit(db,tid,mid,text,data)
    def process():
        with SessionLocal.begin() as db:
            job=db.scalar(select(Job).where(Job.workspace_id==w,Job.status=='pending'))
            assert job
            jid=job.id
            process_job(db,job)
        return jid
    yield c,w,u,b,wallet,cat,state,tid,capture,process
    with SessionLocal.begin() as db:
        db.execute(delete(Job).where(Job.workspace_id==w))


class Sender:
    def __init__(self,fail=False):self.sent=[];self.fail=fail
    async def send_message(self,tid,text,**kwargs):
        assert kwargs['parse_mode'] is None
        if self.fail:raise RuntimeError('synthetic failure')
        self.sent.append((tid,text))


def test_picture_caption_model_review_and_plain_confirm(channel):
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    with SessionLocal.begin() as db:
        db.scalar(select(Provider).where(Provider.workspace_id==w)).supports_images=True
    state['responses']=[tool('prepare_transaction',dict(intent='create',kind='expense',amount=21200,
        description='ค่าหนังสือ',account_id=wallet,category_id=cat,occurred_on='2026-09-30'))]
    assert capture(1,'ค่าหนังสือ',receipt()[1])==ACK
    assert capture(1,'ค่าหนังสือ',receipt()[1])==ACK
    with SessionLocal() as db:
        jobs=db.scalars(select(Job).where(Job.workspace_id==w)).all()
        assert len(jobs)==1 and jobs[0].task=='chat' and jobs[0].payload['routing']=='workspace'
        assert jobs[0].payload['text']=='ค่าหนังสือ' and jobs[0].payload['attachment_id']
    jid=process()
    assert 'ยังส่งข้อความทวนล่าสุดให้ไม่ครบ' in capture(99,'ยืนยัน')
    assert c.get(b+'/transactions').json()==[]
    # Same runtime/tool schema as web; image and user caption both reach the model.
    body=state['calls'][0]
    assert any(isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content']) for m in body['messages'])
    assert 'ค่าหนังสือ' in str(body['messages'])
    bot=Sender()
    assert asyncio.run(deliver_once(bot))
    assert bot.sent[0][0]==tid and '212.00' in bot.sent[0][1] and 'ยืนยัน' in bot.sent[0][1]
    assert not asyncio.run(deliver_once(bot))
    assert 'บันทึกรายการเรียบร้อย' in capture(2,'ยืนยัน')
    assert len(c.get(b+'/transactions').json())==1
    capture(2,'ยืนยัน')
    assert len(c.get(b+'/transactions').json())==1
    with SessionLocal() as db:assert db.get(TelegramDelivery,jid).status=='sent'


def test_natural_conversation_and_history_use_chat_model(channel):
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[{'content':'คุยได้เลยค่ะ วันนี้เป็นยังไงบ้าง?'}]
    assert capture(1,'วันนี้เหนื่อยจัง')==ACK
    process()
    bot=Sender();asyncio.run(deliver_once(bot))
    assert 'วันนี้เป็นยังไง' in bot.sent[-1][1]
    state['responses']=[{'content':'พักสักนิดได้นะคะ'}]
    capture(2,'ขอพักแป๊บนึง');process();asyncio.run(deliver_once(bot))
    assert 'วันนี้เป็นยังไง' in str(state['calls'][-1]['messages'])
    assert c.get(b+'/transactions').json()==[]


@pytest.mark.parametrize('change',['unlink','relink','revoke','erase'])
def test_no_delivery_after_access_or_recipient_changes(channel,change):
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[{'content':'คุยได้เลยค่ะ'}]
    capture(1,'สวัสดี');jid=process()
    alternate=c.post('/workspaces',json={'name':'อื่น'}).json()['id'] if change=='relink' else None
    with SessionLocal.begin() as db:
        row=db.get(TelegramDelivery,jid)
        if change=='unlink':db.delete(db.get(TelegramLink,str(tid)))
        elif change=='relink':db.get(TelegramLink,str(tid)).workspace_id=alternate
        elif change=='revoke':
            from app.bootstrap import create_user
            successor=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
            db.add(Membership(user_id=successor.id,workspace_id=w,role='owner'));db.flush()
            db.delete(db.get(Membership,(u.id,w)))
        else:
            from app.chat_privacy import erase
            erase(db,db.get(Conversation,row.conversation_id))
    bot=Sender();assert not asyncio.run(deliver_once(bot));assert bot.sent==[]


def test_retry_recovers_after_restart_and_keeps_full_review(channel):
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    state['responses']=[{'content':'คุยได้เลยค่ะ'}]
    capture(1,'สวัสดี');jid=process()
    long='รายละเอียด'*500+'\nพิมพ์ ยืนยัน เมื่อถูกต้อง'
    with SessionLocal.begin() as db:
        row=db.get(TelegramDelivery,jid)
        db.get(Message,row.reply_message_id).content=long
    assert asyncio.run(deliver_once(Sender(fail=True)))
    with SessionLocal.begin() as db:db.get(TelegramDelivery,jid).next_attempt=now()-1
    bot=Sender()
    while asyncio.run(deliver_once(bot)):pass
    assert ''.join(text for _,text in bot.sent)==long
    assert all(len(text)<=3500 for _,text in bot.sent)
    assert all(who==tid for who,_ in bot.sent)


def test_provider_error_returns_safe_diagnostic(channel):
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    capture(1,'สวัสดี')
    with SessionLocal.begin() as db:
        job=db.scalar(select(Job).where(Job.workspace_id==w))
        job.status='failed';job.error='timeout';job.payload={}
    bot=Sender();assert asyncio.run(deliver_once(bot))
    assert 'Timeout' in bot.sent[0][1] and 'http' not in bot.sent[0][1]


def test_photo_handler_passes_caption_and_starts_delivery_background(channel):
    from types import SimpleNamespace
    from app.bot import capture as receive, start_delivery, stop_delivery
    c,w,u,b,wallet,cat,state,tid,capture,process=channel
    replies=[]
    async def answer(text,**kwargs):replies.append(text)
    class Bot(Sender):
        async def download(self,photo,destination):destination.write(receipt()[1])
    message=SimpleNamespace(chat=SimpleNamespace(type='private'),from_user=SimpleNamespace(id=tid),
        photo=[SimpleNamespace(file_size=100)],caption='ค่าหนังสือ',text=None,message_id=77,answer=answer)
    asyncio.run(receive(message,Bot()))
    assert replies==[ACK]
    with SessionLocal() as db:
        job=db.scalar(select(Job).where(Job.workspace_id==w))
        assert job.payload['text']=='ค่าหนังสือ' and job.payload['attachment_id']
    async def lifecycle():
        await start_delivery(Bot())
        await asyncio.sleep(0)
        await stop_delivery()
    asyncio.run(lifecycle())
