import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select,func
from app.db import SessionLocal
from app.models import Entry,Line,StatementImport,StatementRow,Membership,Account,Workspace
from app.bootstrap import create_user
from test_finance import ids

CSV='วันที่,รายละเอียด,เงินออก,เงินเข้า,หมวดหมู่\n20/10/2569,กาแฟ,80,,อาหารและเครื่องดื่ม\n20/10/2569,เงินเดือน,,11000,เงินเดือน\n'


def upload(c,w,account,text=CSV,**data):
    return c.post(f'/workspaces/{w}/imports/preview',files={'file':('statement.csv',text.encode('utf-8-sig'),'text/csv')},data={'account_id':account,'date_format':'dmy',**data})


def selection(batch,a):
    return {'rows':[dict(index=r['index'],category_id=a[r['kind']]) for r in batch['rows'] if not r['error']]}


def test_preview_confirm_balanced_and_replay(actor):
    c,w,u=actor;a=ids(c,w);base=f'/workspaces/{w}/imports'
    headers=c.post(base+'/columns',files={'file':('x.csv',CSV.encode('utf-8-sig'))}).json()
    assert headers['count']==2 and headers['suggested']['date']=='วันที่'
    preview=upload(c,w,a['asset']);assert preview.status_code==200,preview.text
    p=preview.json();assert p['rows'][0]['amount']==8000 and p['rows'][0]['occurred_on']=='2026-10-20'
    with SessionLocal() as db:assert not db.scalar(select(Entry.id).where(Entry.workspace_id==w))
    payload=selection(p,a)
    result=c.post(base+'/'+p['id']+'/confirm',json=payload)
    assert result.status_code==200,result.text
    assert result.json()['imported']==2
    assert c.post(base+'/'+p['id']+'/confirm',json=payload).json()==result.json()
    assert c.post(base+'/'+p['id']+'/confirm',json={'rows':payload['rows'][:1]}).status_code==409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Entry).where(Entry.workspace_id==w))==2
        assert all(n==0 for n in db.scalars(select(func.sum(Line.signed_amount)).where(Line.workspace_id==w).group_by(Line.entry_id)))
    again=upload(c,w,a['asset']).json();assert {r['duplicate'] for r in again['rows']}=={'imported'}
    assert c.post(base+'/'+again['id']+'/confirm',json=selection(again,a)).json()['skipped']==2


def test_atomic_rollback_scope_invalid_and_expiry(actor):
    c,w,u=actor;a=ids(c,w);base=f'/workspaces/{w}/imports'
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        foreign=db.scalar(select(Membership.workspace_id).where(Membership.user_id==other.id))
        other_category=db.scalar(select(Account.id).where(Account.workspace_id==foreign,Account.kind=='expense'))
    assert upload(c,w,other_category).status_code==404
    p=upload(c,w,a['asset']).json();payload=selection(p,a);payload['rows'][-1]['category_id']=other_category
    assert c.post(base+'/'+p['id']+'/confirm',json=payload).status_code==404
    with SessionLocal() as db:assert not db.scalar(select(Entry.id).where(Entry.workspace_id==w))
    assert c.post(f'/workspaces/{foreign}/imports/{p["id"]}/confirm',json=selection(p,a)).status_code==404
    assert c.post(base+'/'+p['id']+'/confirm',json={'rows':[{'index':499,'category_id':a['expense']}]}).status_code==422
    with SessionLocal.begin() as db:db.get(StatementImport,p['id']).created_at=0
    assert c.post(base+'/'+p['id']+'/confirm',json=selection(p,a)).status_code==409


def test_possible_duplicates_require_explicit_override_and_same_file_repetitions(actor):
    c,w,u=actor;a=ids(c,w);base=f'/workspaces/{w}/imports'
    csv='date,description,debit,credit\n2026-10-20,coffee,80,\n2026-10-20,coffee,80,\n'
    p=upload(c,w,a['asset'],csv,date_format='iso').json()
    assert c.post(base+'/'+p['id']+'/confirm',json=selection(p,a)).json()['imported']==2
    # A previously entered manual transaction is only a possible duplicate.
    from test_finance import payload
    c.post(f'/workspaces/{w}/transactions',json={**payload('expense',a['asset'],12500,category_id=a['expense']),'description':'book','occurred_on':'2026-10-20'})
    p=upload(c,w,a['asset'],'date,description,amount\n2026-10-20,book,-125\n',date_format='iso').json()
    assert p['rows'][0]['duplicate']=='possible'
    data=selection(p,a)
    assert c.post(base+'/'+p['id']+'/confirm',json=data).status_code==409
    data['rows'][0]['allow_duplicate']=True
    assert c.post(base+'/'+p['id']+'/confirm',json=data).json()['imported']==1


def test_csv_bounds_decimals_mapping_invalid_rows_and_windows874(actor):
    c,w,u=actor;a=ids(c,w)
    p=upload(c,w,a['asset'],'date,description,amount\n2026-10-20,"quoted, coffee",-12.35\n2026-02-30,bad,3\n2026-10-20,precision,3.001\n',date_format='iso').json()
    assert p['rows'][0]['amount']==1235 and p['rows'][0]['description']=='quoted, coffee'
    assert p['rows'][1]['error'] and p['rows'][2]['error']
    invalid=upload(c,w,a['asset'],mapping='{"date":"does not exist"}')
    assert invalid.status_code==422
    assert upload(c,w,a['asset'],'date,description,amount\n'+('2026-10-20,x,-1\n'*501),date_format='iso').status_code==413
    assert upload(c,w,a['asset'],'x'* (2*1024*1024+1)).status_code==413
    response=c.post(f'/workspaces/{w}/imports/columns',files={'file':('s.csv',CSV.encode('cp874'))},data={'encoding':'cp874'})
    assert response.status_code==200 and response.json()['count']==2


def test_other_member_cannot_confirm_someone_elses_preview(actor):
    from fastapi.testclient import TestClient
    from app.main import app
    c,w,u=actor;a=ids(c,w);p=upload(c,w,a['asset']).json()
    with SessionLocal.begin() as db:
        other=create_user(db,uuid.uuid4().hex+'@test.local','secure-test-password')
        db.add(Membership(user_id=other.id,workspace_id=w,role='member'))
    with TestClient(app,base_url='https://testserver',headers={'X-SF-Request':'1'}) as client:
        assert client.post('/auth/login',json={'email':other.email,'password':'secure-test-password'}).status_code==200
        assert client.post(f'/workspaces/{w}/imports/{p["id"]}/confirm',json=selection(p,a)).status_code==404


def test_parallel_confirm_two_previews_posts_each_bank_row_once(actor,pg_only):
    c,w,u=actor;a=ids(c,w);base=f'/workspaces/{w}/imports'
    batches=[upload(c,w,a['asset']).json() for _ in range(2)]
    def confirm_batch(p):
        r=c.post(base+'/'+p['id']+'/confirm',json=selection(p,a))
        assert r.status_code==200,r.text
        return r.json()
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(confirm_batch,batches))
    assert sum(r['imported'] for r in results)==2
    assert sum(r['skipped'] for r in results)==2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(StatementRow).where(StatementRow.workspace_id==w))==2


def test_bank_reference_handles_reexported_descriptions_and_does_not_cross_accounts(actor):
    c,w,u=actor;a=ids(c,w);base=f'/workspaces/{w}/imports'
    csv='date,description,amount,reference\n2026-10-20,coffee,-80,bank-id-1\n'
    p=upload(c,w,a['asset'],csv,date_format='iso').json()
    assert c.post(base+'/'+p['id']+'/confirm',json=selection(p,a)).json()['imported']==1
    changed=upload(c,w,a['asset'],csv.replace('coffee','updated merchant'),date_format='iso').json()
    assert changed['rows'][0]['duplicate']=='imported'
    other=c.post(f'/workspaces/{w}/accounts',json={'name':'other bank','kind':'asset'}).json()['id']
    assert upload(c,w,other,csv,date_format='iso').json()['rows'][0]['duplicate']=='new'
    same_ref=upload(c,w,a['asset'],csv+'2026-10-20,other,-90,bank-id-1\n',date_format='iso').json()
    assert all(row['error'] for row in same_ref['rows'])


def test_expired_preview_cleanup_keeps_confirmed_import_audit(actor):
    from app.statement_imports import cleanup
    c,w,u=actor;a=ids(c,w);base=f'/workspaces/{w}/imports'
    old=upload(c,w,a['asset']).json();kept=upload(c,w,a['asset']).json()
    assert c.post(base+'/'+kept['id']+'/confirm',json=selection(kept,a)).status_code==200
    with SessionLocal.begin() as db:
        for p in (old,kept):db.get(StatementImport,p['id']).created_at=0
        db.flush();cleanup(db)
    with SessionLocal() as db:
        assert db.get(StatementImport,old['id']) is None
        assert db.get(StatementImport,kept['id']).result['imported']==2
