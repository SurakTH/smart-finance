import os
import tempfile
import uuid
from pathlib import Path
import pytest

# Never test against the production database. Explicit PG databases must end in _test.
url=os.getenv('TEST_DATABASE_URL','sqlite:///'+str(Path(tempfile.mkdtemp())/'finance_test.db'))
if not url.startswith('sqlite:') and not url.rsplit('/',1)[-1].endswith('_test'):
    raise RuntimeError('TEST_DATABASE_URL must end in _test')
os.environ['DATABASE_URL']=url
os.environ['COOKIE_SECURE']='true'

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from app.db import SessionLocal, engine
from app import main
from app.bootstrap import create_user
from app.models import Workspace, Membership
from sqlalchemy import select

@pytest.fixture(scope='session',autouse=True)
def schema():
    command.upgrade(Config('alembic.ini'),'head')

@pytest.fixture
def actor(monkeypatch):
    monkeypatch.setattr(main,'login_limit',lambda _:None)
    # Queue wake-ups are optional; tests drive worker.run_once deterministically.
    monkeypatch.setattr(main.redis,'lpush',lambda *args:1)
    monkeypatch.setattr(main.redis,'ltrim',lambda *args:True)
    with SessionLocal.begin() as db:
        user=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        wid=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
    client=TestClient(main.app,base_url='https://testserver',headers={'X-SF-Request':'1'})
    response=client.post('/auth/login',json={'email':user.email,'password':'secure-test-password'})
    assert response.status_code==200
    yield client,wid,user
    client.close()

@pytest.fixture
def pg_only():
    if engine.dialect.name!='postgresql': pytest.skip('PostgreSQL-only invariant')
