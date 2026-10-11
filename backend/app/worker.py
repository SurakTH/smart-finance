import logging
import time
from sqlalchemy import select,text
from .db import SessionLocal,engine
from .models import Job,Workspace
from .security import redis
from .ai import process_job
from .chat_stop import Stopped,check,stopped_message
from .ai_fence import Gone,Invalidated

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


from contextlib import contextmanager
@contextmanager
def owned_connection():
    with engine.connect() as connection:
        try:yield connection
        finally:
            if connection.in_transaction():connection.rollback()
            if connection.dialect.name=='postgresql':
                connection.execute(text('SELECT pg_advisory_unlock_all()'));connection.commit()

def run_once():
    live=None
    try:
        with owned_connection() as connection, SessionLocal(bind=connection,autoflush=False) as db, db.begin():
            # Connection-scoped ownership survives transaction work, releases on crash.
            candidates=db.scalars(select(Job).join(Workspace,Workspace.id==Job.workspace_id).where(Job.status=='pending',Workspace.archived_at.is_(None)).order_by(Job.created_at,Job.id).limit(50)).all()
            job=None
            for candidate in candidates:
                postgres=connection.dialect.name=='postgresql'
                if postgres and not db.scalar(text('SELECT pg_try_advisory_lock(hashtextextended(:id, 0))'),{'id':candidate.id}):continue
                if postgres and not db.scalar(text('SELECT pg_try_advisory_lock(hashtextextended(:id, 0))'),{'id':'workspace:'+candidate.workspace_id}):
                    db.execute(text('SELECT pg_advisory_unlock(hashtextextended(:id, 0))'),{'id':candidate.id});continue
                db.refresh(candidate)
                if candidate.status!='pending':
                    if postgres:db.execute(text('SELECT pg_advisory_unlock_all()'))
                    continue
                job=candidate;break
            if not job:return False
            job._diagnostic_started=time.monotonic()
            cid=job.payload.get('conversation_id')
            if cid:live=(job.workspace_id,cid,job.id)
            job._diagnostic_started=time.monotonic()
            try:
                with db.begin_nested():
                    if job.task=='ai_test':
                        from .ai_sandbox import run
                        run(db,job)
                    else:process_job(db,job)
            except Gone:
                db.expunge(job)
                return True
            except Invalidated as invalid:
                job.status='failed';job.error=invalid.code;job.payload={}
            except Stopped:
                if cid:stopped_message(db,job.workspace_id,cid)
                job.status='cancelled';job.error=None;job.payload={}
            except Exception:
                try:check(job,True)
                except Stopped:
                    if cid:stopped_message(db,job.workspace_id,cid)
                    job.status='cancelled';job.error=None;job.payload={}
                else:job.status='failed';job.error=getattr(job,'_last_ai_error','processing_failed');job.payload={}
            from .ai_usage import recover
            recover(db,job)
            from .ai_diagnostics import finish
            finish(db,job)
            status=job.status
            db.flush()
        # Never announce completion before the transaction has actually committed.
        if live:notify(live,'done' if status=='done' else 'cancelled' if status=='cancelled' else 'failed',job.error)
        return True
    except Exception:
        if live:notify(live,'failed')
        raise

def notify(live,kind,error=None):
    import json
    from .chat_stream import channel
    wid,cid,jid=live
    from .ai_errors import message
    try:redis.publish(channel(wid,cid),json.dumps({'kind':kind,'job_id':jid,**({'message':message(error)} if kind=='failed' else {})},ensure_ascii=False))
    except Exception:pass

def schedule_once(wid=None):
    from .recurring import generate_due
    with SessionLocal.begin() as db:return generate_due(db,wid=wid)

def cleanup_once():
    from .chat_privacy import cleanup
    from .email_recovery import cleanup as cleanup_mail
    with SessionLocal.begin() as db:
        cleanup_mail(db)
        from .ai_diagnostics import cleanup as cleanup_diagnostics
        cleanup_diagnostics(db)
        return cleanup(db)

if __name__=='__main__':
    # Separate workspace jobs may infer concurrently. Each owns its DB session;
    # session advisory locks serialize jobs within one workspace, not HTTP writes.
    import os
    from concurrent.futures import ThreadPoolExecutor
    workers=max(1,min(4,int(os.getenv('AI_WORKERS','2'))))
    next_schedule=0.0;pending=set()
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='ai-job') as pool:
        while True:
            try:
                if time.monotonic()>=next_schedule:
                    next_schedule=time.monotonic()+30;cleanup_once();schedule_once()
                from .email_recovery import deliver_once
                deliver_once()
                for future in list(pending):
                    if future.done():
                        pending.remove(future)
                        try:future.result()
                        except Exception:pass  # Never log provider data or secrets.
                while len(pending)<workers:pending.add(pool.submit(run_once))
                time.sleep(.5)
            except Exception:time.sleep(2)
