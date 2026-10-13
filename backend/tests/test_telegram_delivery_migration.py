"""Legacy queued replies survive the primary-key transition, on SQLite and PG."""
import uuid
import pytest
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.orm import Session
from alembic import command
from alembic.config import Config
from app import config
from app.db import engine
from app.models import User,Workspace,Conversation,Job

@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_legacy_delivery_upgrade_roundtrip(monkeypatch,tmp_path,dialect):
    database='sf_delivery_'+uuid.uuid4().hex+'_test'
    if dialect=='postgresql':
        if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL only')
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as admin:
            admin.execute(text('CREATE DATABASE '+database))
        url=engine.url.set(database=database).render_as_string(hide_password=False)
    else:url='sqlite:///'+str(tmp_path/'migration_test.db')
    target=None
    try:
        monkeypatch.setattr(config,'DATABASE_URL',url)
        command.upgrade(Config('alembic.ini'),'telegram_rooms')
        target=create_engine(url)
        with Session(target) as db,db.begin():
            user=User(email=uuid.uuid4().hex+'@test.local',password='synthetic')
            workspace=Workspace(name='migration fixture');db.add_all([user,workspace]);db.flush()
            room=Conversation(workspace_id=workspace.id,user_id=user.id);db.add(room);db.flush()
            job=Job(workspace_id=workspace.id,user_id=user.id,task='chat',payload={},status='done');db.add(job);db.flush()
            jid=job.id
            params=dict(jid=jid,w=workspace.id,c=room.id,u=user.id)
            db.execute(text("INSERT INTO telegram_deliveries (job_id,workspace_id,conversation_id,user_id,telegram_id,status,attempts,part,next_attempt) VALUES (:jid,:w,:c,:u,'123','pending',2,1,10)"),params)
        command.upgrade(Config('alembic.ini'),'head')
        assert any('status' in c['sqltext'] for c in inspect(target).get_check_constraints('telegram_deliveries'))
        with target.begin() as db:
            row=db.execute(text('SELECT id,job_id,status,attempts,part FROM telegram_deliveries')).one()
            assert tuple(row)==(jid,jid,'pending',2,1)
            db.execute(text("INSERT INTO telegram_deliveries (id,job_id,body,created_at,workspace_id,conversation_id,user_id,telegram_id,status,attempts,part,next_attempt) VALUES ('sync',NULL,'synthetic reply',20,:w,:c,:u,'123','pending',0,0,0)"),params)
        command.downgrade(Config('alembic.ini'),'telegram_rooms')
        command.upgrade(Config('alembic.ini'),'head')
        with target.connect() as db:
            assert db.execute(text('SELECT id,job_id,attempts,part FROM telegram_deliveries')).one()==(jid,jid,2,1)
    finally:
        if target:target.dispose()
        if dialect=='postgresql':
            with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as admin:
                admin.execute(text('DROP DATABASE '+database+' WITH (FORCE)'))
