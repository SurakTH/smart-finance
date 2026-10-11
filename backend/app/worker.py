import logging
import time
from sqlalchemy import select
from .db import SessionLocal
from .models import Job,Workspace
from .security import redis
from .ai import process_job

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

def run_once():
    live=None
    try:
        with SessionLocal.begin() as db:
            candidate=db.execute(select(Job.id,Job.workspace_id).join(Workspace,Workspace.id==Job.workspace_id).where(Job.status=='pending',Workspace.archived_at.is_(None)).order_by(Job.created_at,Job.id).with_for_update(of=Workspace,skip_locked=True).limit(1)).first()
            if not candidate:return False
            job=db.scalar(select(Job).where(Job.id==candidate.id,Job.status=='pending').with_for_update(skip_locked=True))
            if not job:return False
            cid=job.payload.get('conversation_id')
            if cid:live=(job.workspace_id,cid,job.id)
            try:
                with db.begin_nested(): process_job(db,job)
            except Exception:
                job.status='failed';job.error='processing_failed';job.payload={}
            from .ai_usage import recover
            recover(db,job)
            status=job.status
        # Never announce completion before the transaction has actually committed.
        if live:notify(live,'done' if status=='done' else 'failed')
        return True
    except Exception:
        if live:notify(live,'failed')
        raise

def notify(live,kind):
    import json
    from .chat_stream import channel
    wid,cid,jid=live
    try:redis.publish(channel(wid,cid),json.dumps({'kind':kind,'job_id':jid}))
    except Exception:pass

def schedule_once(wid=None):
    from .recurring import generate_due
    with SessionLocal.begin() as db:return generate_due(db,wid=wid)

def cleanup_once():
    from .chat_privacy import cleanup
    from .email_recovery import cleanup as cleanup_mail
    with SessionLocal.begin() as db:
        cleanup_mail(db)
        return cleanup(db)

if __name__=='__main__':
    next_schedule=0.0
    while True:
        try:
            if time.monotonic()>=next_schedule:
                next_schedule=time.monotonic()+30;cleanup_once();schedule_once()
            from .email_recovery import deliver_once
            mailed=deliver_once()
            if not run_once() and not mailed:
                try: redis.blpop('sf:wakeup',timeout=2)
                except Exception: time.sleep(2)
        except Exception:
            # No exception bodies: they may include user input or provider data.
            time.sleep(2)
