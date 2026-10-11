"""Bounded, read-only CSV exports. UTF-8 BOM for Thai text in Excel."""
import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException, Response
from sqlalchemy import select
from .models import Entry, EntryRevision
from .corrections import revision_conditions
from .reporting import entry_details, transaction_conditions

MAX_EXPORT_ROWS=10_000
LABELS={'expense':'รายจ่าย','income':'รายรับ','transfer':'โอนเงิน','card_payment':'จ่ายบัตร','opening':'ยอดตั้งต้น'}


def text_cell(value):
    value=str(value or '')
    # CSV quoting alone cannot stop a spreadsheet treating user text as a formula.
    significant=value.lstrip('\ufeff \t\r\n\v\f')
    if significant.startswith(('=','+','-','@')) or (value and ord(value[0])<32):
        return "'"+value
    return value


def baht(amount):
    return f'{amount//100}.{amount%100:02d}'


def response(headers,rows,filename):
    output=io.StringIO(newline='')
    writer=csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(content=output.getvalue().encode('utf-8-sig'),media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})


def bounded(rows):
    if len(rows)>MAX_EXPORT_ROWS:
        raise HTTPException(413,'ส่งออกได้ไม่เกิน 10,000 รายการต่อไฟล์ กรุณาลดช่วงวันหรือตัวกรอง โดยระบบยังไม่ส่งออกไฟล์บางส่วน')
    return rows


def transactions_csv(db,wid,start=None,end=None,kind=None,account_id=None,category_id=None,q=''):
    conditions=transaction_conditions(db,wid,start,end,kind,account_id,category_id,q)
    entries=bounded(db.scalars(select(Entry).where(*conditions).order_by(Entry.occurred_on.desc(),Entry.created_at.desc(),Entry.id).limit(MAX_EXPORT_ROWS+1)).all())
    items=entry_details(db,wid,entries)
    rows=([item['id'],item['occurred_on'],LABELS[item['kind']],text_cell(item['description']),baht(item['amount']),
           text_cell(' | '.join(a['name'] for a in item['accounts'] if a['direction']=='out')),
           text_cell(' | '.join(a['name'] for a in item['accounts'] if a['direction']=='in')),
           text_cell(item['category']['name'] if item['category'] else '')] for item in items)
    return response(['รหัสรายการ','วันที่','ประเภท','รายละเอียด','จำนวนเงิน (บาท)','บัญชีขาออก','บัญชีขาเข้า','หมวดหมู่'],rows,'smart-finance-transactions.csv')


def history_csv(db,wid,start=None,end=None):
    revisions=bounded(db.scalars(select(EntryRevision).where(*revision_conditions(wid,start,end)).order_by(EntryRevision.created_at.desc(),EntryRevision.id).limit(MAX_EXPORT_ROWS+1)).all())
    ids={eid for r in revisions for eid in (r.original_id,r.replacement_id) if eid}
    entries=db.scalars(select(Entry).where(Entry.workspace_id==wid,Entry.id.in_(ids))).all() if ids else []
    details={item['id']:item for item in entry_details(db,wid,entries)}
    def snapshot(eid):
        item=details.get(eid)
        if not item:return ['']*7
        return [item['id'],item['occurred_on'],LABELS[item['kind']],text_cell(item['description']),baht(item['amount']),
                text_cell(' → '.join(a['name'] for a in item['accounts'])),text_cell(item['category']['name'] if item['category'] else '')]
    rows=([r.id,datetime.fromtimestamp(r.created_at/1000,ZoneInfo('Asia/Bangkok')).isoformat(timespec='milliseconds'),
           'แก้ไข' if r.replacement_id else 'ยกเลิก',text_cell(r.reason),r.created_by,r.reversal_id,
           *snapshot(r.original_id),*snapshot(r.replacement_id)] for r in revisions)
    base=['รหัสรายการ','วันที่','ประเภท','รายละเอียด','จำนวนเงิน (บาท)','บัญชี','หมวดหมู่']
    return response(['รหัสประวัติ','เวลาแก้ไข (Asia/Bangkok)','การเปลี่ยนแปลง','เหตุผล','รหัสผู้แก้ไข','รหัสกลับรายการ',
                     *['เดิม: '+name for name in base],*['ใหม่: '+name for name in base]],rows,'smart-finance-history.csv')
