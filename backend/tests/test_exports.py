import csv
import io
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import exports, main
from app.db import SessionLocal
from app.models import Membership
from app.bootstrap import create_user
from test_finance import ids, payload
from test_reporting import record
from test_corrections import correction


def rows(response):
    assert response.status_code==200,response.text
    assert response.content.startswith(b'\xef\xbb\xbf')
    assert response.headers['content-type'].startswith('text/csv')
    assert response.headers['cache-control']=='no-store'
    assert 'attachment;' in response.headers['content-disposition']
    return list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))


def test_csv_all_pages_inclusive_filters_totals_exact_money_and_special_text(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}';url=b+'/exports/transactions.csv'
    for i in range(32):record(c,w,a,amount=101+i,day='2026-10-01' if i<16 else '2026-10-31',description='กาแฟ, "ร้านเดิม"\n100%_แท้' if i==0 else 'กาแฟ')
    record(c,w,a,kind='income',amount=100_000_000_000)
    record(c,w,a,amount=999999,day='2026-09-30')
    c.post(b+'/proposals',json={'description':'pending','amount':7777,'kind':'expense'})
    data=rows(c.get(url,params={'start':'2026-10-01','end':'2026-10-31'}))
    assert len(data)==33
    assert sum(int(r['จำนวนเงิน (บาท)'].replace('.','')) for r in data if r['ประเภท']=='รายจ่าย')==sum(range(101,133))
    assert next(r['จำนวนเงิน (บาท)'] for r in data if r['ประเภท']=='รายรับ')=='1000000000.00'
    exact=rows(c.get(url,params={'q':'%_','kind':'expense','account_id':a['asset'],'category_id':a['expense']}))
    assert len(exact)==1 and exact[0]['รายละเอียด']=='กาแฟ, "ร้านเดิม"\n100%_แท้'
    assert exact[0]['จำนวนเงิน (บาท)']=='1.01' and exact[0]['หมวดหมู่']
    assert exact[0]['บัญชีขาออก'] and not exact[0]['บัญชีขาเข้า']
    assert rows(c.get(url,params={'start':'2026-09-30','end':'2026-09-30'}))[0]['จำนวนเงิน (บาท)']=='9999.99'


def test_corrections_and_reversals_export_active_truth_and_separate_history(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    old=record(c,w,a,amount=10000)
    data=correction(a,amount=12550,day='2026-09-30');data['reason']='=HYPERLINK("https://invalid.example")'
    revised=c.post(b+f'/transactions/{old["id"]}/correct',json=data).json()
    new=revised['replacement'];exported=rows(c.get(b+'/exports/transactions.csv'))
    assert len(exported)==1 and exported[0]['รหัสรายการ']==new['id'] and exported[0]['จำนวนเงิน (บาท)']=='125.50'
    assert rows(c.get(b+'/exports/transactions.csv?start=2026-10-01'))==[]
    audit=rows(c.get(b+'/exports/history.csv'))
    assert len(audit)==1 and audit[0]['เหตุผล'].startswith("'=HYPERLINK")
    assert audit[0]['เดิม: จำนวนเงิน (บาท)']=='100.00' and audit[0]['ใหม่: จำนวนเงิน (บาท)']=='125.50'
    assert audit[0]['รหัสผู้แก้ไข'] and '+07:00' in audit[0]['เวลาแก้ไข (Asia/Bangkok)']
    response=c.post(b+f'/transactions/{new["id"]}/reverse',json={'reason':'ซ้ำ','idempotency_key':str(uuid.uuid4())});assert response.status_code==200
    assert rows(c.get(b+'/exports/transactions.csv'))==[]
    audit=rows(c.get(b+'/exports/history.csv'));assert len(audit)==2
    reversed_row=next(r for r in audit if r['การเปลี่ยนแปลง']=='ยกเลิก')
    assert reversed_row['เดิม: รหัสรายการ']==new['id'] and reversed_row['ใหม่: รหัสรายการ']==''
    assert len(c.get(b+'/transaction-report').json()['items'])==0


def test_csv_wallet_directions_transfer_and_card_payment(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    bank=c.post(b+'/accounts',json={'name':'ธนาคาร','kind':'asset'}).json()['id']
    card=c.post(b+'/accounts',json={'name':'บัตรเครดิต','kind':'liability'}).json()['id']
    record(c,w,a,kind='transfer',amount=10001,other_account_id=bank)
    record(c,w,a,kind='card_payment',amount=5550,other_account_id=card)
    result=rows(c.get(b+'/exports/transactions.csv'))
    transfer=next(r for r in result if r['ประเภท']=='โอนเงิน');assert transfer['บัญชีขาเข้า']=='ธนาคาร' and transfer['บัญชีขาออก']=='เงินสด'
    payment=next(r for r in result if r['ประเภท']=='จ่ายบัตร');assert payment['บัญชีขาเข้า']=='บัตรเครดิต' and payment['หมวดหมู่']==''


@pytest.mark.parametrize('value',['=1+1',' +cmd','-cmd','@SUM(1)','\ttext','\rtext','\ntext','\ufeff =1+1'])
def test_untrusted_spreadsheet_formula_text_is_neutralized(value):
    assert exports.text_cell(value)=="'"+value
    assert exports.text_cell('กาแฟ = อร่อย')=='กาแฟ = อร่อย'


def test_csv_formula_account_category_description_and_integer_precision(actor):
    c,w,_=actor;b=f'/workspaces/{w}'
    wallet=c.post(b+'/accounts',json={'name':' =1+1','kind':'asset'}).json()['id']
    category=c.post(b+'/accounts',json={'name':'@SUM(1)','kind':'expense'}).json()['id']
    record(c,w,{'asset':wallet,'expense':category},amount=1,description='\t=2+2')
    row=rows(c.get(b+'/exports/transactions.csv'))[0]
    assert row['บัญชีขาออก']=="' =1+1" and row['หมวดหมู่']=="'@SUM(1)" and row['รายละเอียด']=="'\t=2+2"
    assert row['จำนวนเงิน (บาท)']=='0.01'


def test_exports_require_membership_and_scope_filters(actor):
    c,w,user=actor;a=ids(c,w);b=f'/workspaces/{w}'
    record(c,w,a)
    other=c.post('/workspaces',json={'name':'other export workspace'}).json()['id'];foreign=ids(c,other)
    assert rows(c.get(f'/workspaces/{other}/exports/transactions.csv'))==[]
    assert c.get(b+'/exports/transactions.csv',params={'account_id':foreign['asset']}).status_code==404
    assert c.get(b+'/exports/transactions.csv',params={'category_id':foreign['expense']}).status_code==404
    with SessionLocal.begin() as db:
        unrelated=create_user(db,uuid.uuid4().hex+'@test.local','secure-export-password')
        unauthorized=db.scalar(select(Membership.workspace_id).where(Membership.user_id==unrelated.id))
    with TestClient(main.app,base_url='https://testserver') as anon:
        for filename in ('transactions','history'):
            assert anon.get(b+f'/exports/{filename}.csv').status_code==401
    for filename in ('transactions','history'):
        assert c.get(f'/workspaces/{unauthorized}/exports/{filename}.csv').status_code==404
    with SessionLocal.begin() as db:
        db.add(Membership(user_id=user.id,workspace_id=unauthorized,role='member'))
    assert rows(c.get(f'/workspaces/{unauthorized}/exports/transactions.csv'))==[]
    assert rows(c.get(f'/workspaces/{unauthorized}/exports/history.csv'))==[]


def test_invalid_filters_empty_exports_and_bounded_no_partial_output(actor,monkeypatch):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    for filename in ('transactions','history'):assert rows(c.get(b+f'/exports/{filename}.csv'))==[]
    for query in ({'start':'2026-13-01'},{'start':'2026-10-31','end':'2026-10-01'},{'kind':'bad'},{'account_id':a['expense']},{'q':'x'*101}):
        assert c.get(b+'/exports/transactions.csv',params=query).status_code==422
    for _ in range(3):
        old=record(c,w,a)
        assert c.post(b+f'/transactions/{old["id"]}/correct',json=correction(a)).status_code==200
    monkeypatch.setattr(exports,'MAX_EXPORT_ROWS',2)
    for filename in ('transactions','history'):
        response=c.get(b+f'/exports/{filename}.csv');assert response.status_code==413
        assert response.headers['content-type'].startswith('application/json') and 'Content-Disposition' not in response.headers
    assert len(rows(c.get(b+'/exports/transactions.csv',params={'q':'ไม่พบ'})))==0


def test_history_export_all_pages_without_changing_ledger(actor):
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    for i in range(31):
        old=record(c,w,a,amount=100+i)
        response=c.post(b+f'/transactions/{old["id"]}/reverse',json={'reason':f'เหตุผล {i}','idempotency_key':str(uuid.uuid4())});assert response.status_code==200
    assert len(c.get(b+'/transaction-history').json()['items'])==30
    assert len(rows(c.get(b+'/exports/history.csv')))==31
    assert rows(c.get(b+'/exports/transactions.csv'))==[]
    assert all(a['balance']==0 for a in c.get(b+'/accounts').json())


def test_history_date_filters_use_bangkok_event_day_inclusively(actor):
    from sqlalchemy import event
    from datetime import datetime
    from app.models import EntryRevision
    c,w,_=actor;a=ids(c,w);b=f'/workspaces/{w}'
    start=int(datetime.fromisoformat('2026-10-11T00:00:00+07:00').timestamp())*1000
    stamps=iter([start-1,start,start+86400000-1,start+86400000])
    def set_time(mapper,connection,target):target.created_at=next(stamps)
    event.listen(EntryRevision,'before_insert',set_time)
    try:
        for i in range(4):
            old=record(c,w,a,day='2026-09-01')
            assert c.post(b+f'/transactions/{old["id"]}/reverse',json={'reason':f'event-{i}','idempotency_key':str(uuid.uuid4())}).status_code==200
    finally:event.remove(EntryRevision,'before_insert',set_time)
    params={'start':'2026-10-11','end':'2026-10-11'}
    result=rows(c.get(b+'/exports/history.csv',params=params));assert len(result)==2
    assert {r['เหตุผล'] for r in result}=={'event-1','event-2'}
    assert all(r['เดิม: วันที่']=='2026-09-01' for r in result)
    assert {r['id'] for r in c.get(b+'/transaction-history',params=params).json()['items']}=={r['รหัสประวัติ'] for r in result}
    assert len(rows(c.get(b+'/exports/history.csv',params={'start':'2026-10-12'})))==1
    for route in ('exports/history.csv','transaction-history'):
        assert c.get(b+'/'+route,params={'start':'2026-10-12','end':'2026-10-10'}).status_code==422
        assert c.get(b+'/'+route,params={'end':'2026-13-01'}).status_code==422
