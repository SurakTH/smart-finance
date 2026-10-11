"""Durable, owner-scoped cancellation independent of the worker's workspace lock."""
import time
from sqlalchemy import select
from .db import SessionLocal
from .models import ChatGeneration,Message,message_time

class Stopped(Exception):pass

def check(job,force=False):
    if getattr(job,'task',None)!='chat' or not job.payload.get('conversation_id'):return
    if not force and time.monotonic()<getattr(job,'_stop_checked_until',0):return
    with SessionLocal() as db:
        requested=db.scalar(select(ChatGeneration.stop_requested).where(ChatGeneration.job_id==job.id))
    job._stop_checked_until=time.monotonic()+.2
    if requested:raise Stopped()

def fence(db,job):
    if getattr(job,'task',None)!='chat' or not job.payload.get('conversation_id'):return
    # Held until commit: Stop either wins before any draft is resolved, or sees
    # the already committed outcome. No window for a late draft after stop ACK.
    control=db.scalar(select(ChatGeneration).where(ChatGeneration.job_id==job.id).with_for_update().execution_options(populate_existing=True))
    if control and control.stop_requested:raise Stopped()

def stopped_message(db,wid,cid):
    db.add(Message(workspace_id=wid,conversation_id=cid,role='assistant',content='หยุดคำตอบแล้วค่ะ ยังไม่ได้บันทึกหรือแก้ข้อมูลจากคำขอนี้',created_at=message_time(db,wid,cid)))


def watch(job,response):
    """Best-effort socket close during a silent thinking/cold-start period."""
    import threading
    event=threading.Event()
    if getattr(job,'task',None)!='chat' or not job.payload.get('conversation_id'):return event
    # Never share ORM state/session access with the socket watcher thread.
    from types import SimpleNamespace
    control=SimpleNamespace(task='chat',id=job.id,payload={'conversation_id':job.payload['conversation_id']})
    def monitor():
        while not event.wait(.25):
            try:check(control,True)
            except Stopped:
                try:response.close()
                except Exception:pass
                return
            except Exception:pass
    threading.Thread(target=monitor,daemon=True,name='chat-stop-watch').start()
    return event
