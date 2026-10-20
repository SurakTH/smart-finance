"""Upgrade existing encrypted credentials without decrypting or merging them."""
import uuid
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,text
from app import config
from app.db import engine

@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_existing_keys_migrate_and_restore_without_loss(monkeypatch,tmp_path,dialect):
    name='sf_connections_'+uuid.uuid4().hex+'_test'
    if dialect=='postgresql':
        if engine.dialect.name!='postgresql':pytest.skip('PostgreSQL only')
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:conn.execute(text('CREATE DATABASE '+name))
        url=engine.url.set(database=name).render_as_string(hide_password=False)
    else:url='sqlite:///'+str(tmp_path/'connections_test.db')
    target=None
    try:
        monkeypatch.setattr(config,'DATABASE_URL',url)
        command.upgrade(Config('alembic.ini'),'telegram_all_replies')
        target=create_engine(url)
        with target.begin() as conn:
            conn.execute(text("INSERT INTO workspaces (id,name,ai_epoch,version) VALUES ('w','old',0,1)"))
            for pid,key in [('a','cipher-one'),('b','cipher-two')]:
                conn.execute(text("INSERT INTO providers (id,workspace_id,kind,model,task,priority,encrypted_key,name,endpoint) VALUES (:id,'w','compatible','test','chat',10,:key,'old','https://api.example.com/v1')"),dict(id=pid,key=key))
        command.upgrade(Config('alembic.ini'),'head')
        with target.connect() as conn:
            rows=conn.execute(text('SELECT p.id,p.encrypted_key,c.encrypted_key FROM providers p JOIN ai_connections c ON p.connection_id=c.id ORDER BY p.id')).all()
            assert rows==[('a','','cipher-one'),('b','','cipher-two')]
        command.downgrade(Config('alembic.ini'),'telegram_all_replies')
        with target.connect() as conn:assert conn.execute(text('SELECT id,encrypted_key FROM providers ORDER BY id')).all()==[('a','cipher-one'),('b','cipher-two')]
        command.upgrade(Config('alembic.ini'),'head')
    finally:
        if target:target.dispose()
        if dialect=='postgresql':
            with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:conn.execute(text('DROP DATABASE IF EXISTS '+name+' WITH (FORCE)'))
