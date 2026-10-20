"""Bounded CSV ingestion. Preview never posts; explicit confirmation is atomic."""
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select,delete
from sqlalchemy.orm import Session
from .db import get_db
from .ledger import get_scoped, post
from .models import Account, Entry, Line, Membership, StatementImport, StatementRow, Workspace, now
from .schemas import TransactionInput
from .security import workspace_member
from .reporting import active_entry

router=APIRouter(prefix='/workspaces/{wid}/imports')
MAX_BYTES=2*1024*1024
MAX_ROWS=500
ALIASES={
    'date':['date','transaction date','วันที่','วันที่ทำรายการ','วันที่รายการ'],
    'description':['description','details','รายละเอียด','รายการ','รายละเอียดรายการ'],
    'amount':['amount','จำนวนเงิน','จำนวนเงิน (บาท)','ยอดเงิน'],
    'debit':['debit','withdrawal','withdrawals','ถอน','เงินออก','รายจ่าย','ถอนเงิน'],
    'credit':['credit','deposit','deposits','ฝาก','เงินเข้า','รายรับ','ฝากเงิน'],
    'kind':['type','kind','ประเภท'],
    'category':['category','หมวดหมู่','หมวด'],
    'reference':['reference','transaction id','reference no','เลขที่รายการ','รหัสรายการ'],
}
KINDS={'expense':'expense','รายจ่าย':'expense','debit':'expense','withdrawal':'expense','income':'income','รายรับ':'income','credit':'income','deposit':'income'}


def fail(detail):raise HTTPException(422,detail)


async def read(file,encoding):
    raw=await file.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise HTTPException(413,'ไฟล์ต้องไม่เกิน 2 MB')
    if encoding not in ('utf-8-sig','cp874'):fail('เลือก UTF-8 หรือ Thai Windows-874')
    try:text=raw.decode(encoding)
    except UnicodeError:fail('อ่านภาษาในไฟล์ไม่ได้ ลองเปลี่ยนการเข้ารหัสไฟล์')
    if '\x00' in text:fail('รองรับไฟล์ CSV เท่านั้น ไม่รองรับ PDF หรือ Excel โดยตรง')
    try:
        dialect=csv.Sniffer().sniff(text[:8192],delimiters=',;\t')
    except csv.Error:dialect=csv.excel
    try:
        rows=list(csv.reader(io.StringIO(text,newline=''),dialect))
    except csv.Error:fail('โครงสร้าง CSV ไม่ถูกต้อง')
    rows=[r for r in rows if any(c.strip() for c in r)]
    if len(rows)<2:fail('ต้องมีหัวคอลัมน์และอย่างน้อยหนึ่งรายการ')
    headers=[h.strip() for h in rows[0]]
    if not all(headers) or len(set(headers))!=len(headers) or len(headers)>50:fail('ชื่อคอลัมน์ต้องไม่ว่าง ไม่ซ้ำ และไม่เกิน 50 คอลัมน์')
    if len(rows)-1>MAX_ROWS:raise HTTPException(413,'นำเข้าได้ไม่เกิน 500 รายการต่อไฟล์')
    if any(len(r)!=len(headers) for r in rows[1:]):fail('จำนวนคอลัมน์บางแถวไม่ตรงกับหัวตาราง')
    return headers,[dict(zip(headers,r)) for r in rows[1:]]


def suggested(headers):
    normalized={h.casefold():h for h in headers}
    return {key:next((normalized[a] for a in aliases if a in normalized),'') for key,aliases in ALIASES.items()}


def amount(value):
    value=value.strip().replace(',','').replace('฿','').strip()
    if not value or value=='-':return None
    if not re.fullmatch(r'[+-]?\d+(?:\.\d{1,2})?',value):raise ValueError('จำนวนเงินต้องเป็นบาทและมีทศนิยมไม่เกิน 2 ตำแหน่ง')
    try:result=Decimal(value)*100
    except InvalidOperation:raise ValueError('จำนวนเงินไม่ถูกต้อง') from None
    n=int(result)
    if abs(n)>100_000_000_000:raise ValueError('จำนวนเงินเกินขอบเขต')
    return n


def day(value,mode):
    value=value.strip()
    if mode=='iso':parts=value.split('-');y,m,d=map(int,parts)
    else:d,m,y=map(int,re.split(r'[/\-.]',value))
    if y>=2400:y-=543
    if not 1900<=y<=2200:raise ValueError('ปีต้องเป็น 4 หลัก (ค.ศ. หรือ พ.ศ.)')
    return date(y,m,d).isoformat()


def normalized(rows,mapping,date_format,categories):
    out=[];occurrences=Counter()
    for index,row in enumerate(rows):
        item={'index':index,'line':index+2,'description':'','error':None,'category_id':None}
        try:
            get=lambda key:row.get(mapping.get(key,''),'').strip()
            item['description']=get('description')
            if not item['description'] or len(item['description'])>300:raise ValueError('รายละเอียดต้องมี 1–300 ตัวอักษร')
            occurred=day(get('date'),date_format)
            if mapping.get('debit') or mapping.get('credit'):
                debit=amount(get('debit')) or 0;credit=amount(get('credit')) or 0
                if debit<0 or credit<0 or bool(debit)==bool(credit):raise ValueError('ต้องมีเงินเข้าหรือเงินออกเพียงด้านเดียวและมากกว่า 0')
                kind='expense' if debit else 'income';value=debit or credit
            else:
                value=amount(get('amount'))
                if not value:raise ValueError('จำนวนเงินต้องไม่เป็นศูนย์หรือว่าง')
                supplied=get('kind').casefold()
                if supplied and supplied not in KINDS:raise ValueError('รองรับเฉพาะรายรับ/รายจ่าย โอนเงินและจ่ายบัตรให้ตรวจแยก')
                kind=KINDS.get(supplied,'expense' if value<0 else 'income')
                value=abs(value)
            signature=json.dumps([occurred,kind,value,item['description']],ensure_ascii=False)
            occurrences[signature]+=1
            reference=get('reference')
            if len(reference)>200:raise ValueError('รหัสอ้างอิงยาวเกินไป')
            fingerprint=hashlib.sha256(('reference:'+reference if reference else f'{signature}:{occurrences[signature]}').encode()).hexdigest()
            matches=[c for c in categories if c.name==get('category') and c.kind==kind]
            item.update(occurred_on=occurred,kind=kind,amount=value,digest=fingerprint,category_id=matches[0].id if len(matches)==1 else None)
        except (ValueError,TypeError):
            item['error']='ตรวจวันที่ จำนวนเงิน รายละเอียด และประเภทของแถวนี้ (รองรับรายรับ/รายจ่ายเท่านั้น)'
        out.append(item)
    return out


def duplicate(db,wid,account_id,item):
    if item.get('error'):return 'invalid'
    if db.scalar(select(StatementRow.id).where(StatementRow.workspace_id==wid,StatementRow.account_id==account_id,StatementRow.digest==item['digest']).limit(1)):return 'imported'
    match=db.scalar(select(Entry.id).join(Line,(Line.entry_id==Entry.id)&(Line.workspace_id==Entry.workspace_id)).where(Entry.workspace_id==wid,active_entry(wid),Line.account_id==account_id,Entry.occurred_on==item['occurred_on'],Entry.amount==item['amount'],Entry.kind==item['kind'],Entry.description==item['description']).limit(1))
    return 'possible' if match else 'new'


@router.post('/columns')
async def columns(wid:str,file:UploadFile=File(...),encoding:str=Form('utf-8-sig'),member:Membership=Depends(workspace_member)):
    headers,rows=await read(file,encoding)
    fields=suggested(headers)
    first=rows[0].get(fields.get('date',''),'').strip()
    return {'columns':headers,'suggested':fields,'count':len(rows),'date_format':'iso' if re.match(r'^\d{4}-',first) else 'dmy'}


@router.post('/preview')
async def preview(wid:str,file:UploadFile=File(...),account_id:str=Form(...),mapping:str=Form('{}'),date_format:str=Form('iso'),encoding:str=Form('utf-8-sig'),member:Membership=Depends(workspace_member),db:Session=Depends(get_db,scope='function')):
    account=get_scoped(db,Account,wid,account_id)
    if account.kind!='asset':fail('เลือกรายการบัญชีเงินสำหรับ statement นี้')
    headers,raw=await read(file,encoding)
    try:fields=json.loads(mapping)
    except ValueError:fail('การเลือกคอลัมน์ไม่ถูกต้อง')
    if not isinstance(fields,dict) or any(k not in ALIASES or not isinstance(v,str) or (v and v not in headers) for k,v in fields.items()):fail('เลือกคอลัมน์จากไฟล์นี้เท่านั้น')
    fields={**suggested(headers),**fields}
    if not fields.get('date') or not fields.get('description') or not (fields.get('amount') or fields.get('debit') or fields.get('credit')):fail('เลือกคอลัมน์วันที่ รายละเอียด และจำนวนเงิน หรือเงินเข้า/เงินออก')
    if date_format not in ('iso','dmy'):fail('รูปแบบวันที่ไม่ถูกต้อง')
    categories=db.scalars(select(Account).where(Account.workspace_id==wid,Account.kind.in_(['income','expense']))).all()
    rows=normalized(raw,fields,date_format,categories)
    fingerprints=Counter(r['digest'] for r in rows if not r.get('error'))
    for r in rows:
        if not r.get('error') and fingerprints[r['digest']]>1:r['error']='รหัสอ้างอิงซ้ำในไฟล์ กรุณาตรวจแถวนี้'
    for item in rows:item['duplicate']=duplicate(db,wid,account.id,item)
    batch=StatementImport(workspace_id=wid,user_id=member.user_id,account_id=account.id,rows=rows)
    db.add(batch);db.flush()
    return {'id':batch.id,'rows':rows,'account_id':account.id,'expires_at':batch.created_at+86400}


class Selection(BaseModel):
    index: int=Field(ge=0,le=MAX_ROWS-1)
    category_id: str=Field(min_length=1,max_length=36)
    allow_duplicate: bool=Field(default=False,strict=True)

class Confirmation(BaseModel):
    rows: list[Selection]=Field(min_length=1,max_length=MAX_ROWS)


@router.post('/{iid}/confirm')
def confirm(wid:str,iid:str,data:Confirmation,member:Membership=Depends(workspace_member),db:Session=Depends(get_db,scope='function')):
    ws=db.scalar(select(Workspace).where(Workspace.id==wid).with_for_update())
    if not ws or ws.archived_at is not None:raise HTTPException(409,'พื้นที่ถูกเก็บเข้าคลัง')
    batch=db.scalar(select(StatementImport).where(StatementImport.id==iid,StatementImport.workspace_id==wid,StatementImport.user_id==member.user_id))
    if not batch:raise HTTPException(404,'ไม่พบชุดนำเข้า')
    items=sorted(data.rows,key=lambda r:r.index)
    if len({r.index for r in items})!=len(items):fail('เลือกแถวซ้ำ')
    payload=hashlib.sha256(json.dumps([r.model_dump() for r in items],sort_keys=True).encode()).hexdigest()
    if batch.confirmed_digest:
        if payload!=batch.confirmed_digest:raise HTTPException(409,'ชุดนี้บันทึกไปแล้วด้วยรายการที่ต่างกัน')
        return batch.result
    if batch.created_at+86400<now():raise HTTPException(409,'ตัวอย่างหมดอายุ กรุณาอัปโหลดเพื่อตรวจใหม่')
    statuses={r.index:duplicate(db,wid,batch.account_id,batch.rows[r.index]) for r in items if r.index<len(batch.rows)}
    entries=[];skipped=0
    for selected in items:
        if selected.index>=len(batch.rows):fail('ไม่พบแถวที่เลือก')
        row=batch.rows[selected.index]
        if row.get('error'):fail('มีแถวที่ข้อมูลไม่ถูกต้อง กรุณานำออกจากชุด')
        status=statuses[selected.index]
        if status=='imported':skipped+=1;continue
        if status=='possible' and not selected.allow_duplicate:raise HTTPException(409,'พบรายการอาจซ้ำเพิ่มหลังเปิดตัวอย่าง กรุณากลับไปตรวจรายการใหม่และอนุญาตแถวนั้นอย่างชัดเจน')
        entry=post(db,wid,member.user_id,TransactionInput(kind=row['kind'],amount=row['amount'],occurred_on=row['occurred_on'],description=row['description'],account_id=batch.account_id,category_id=selected.category_id,idempotency_key=uuid4()))
        db.add(StatementRow(workspace_id=wid,account_id=batch.account_id,digest=row['digest'],entry_id=entry.id));db.flush()
        entries.append(entry.id)
    result={'imported':len(entries),'skipped':skipped,'entry_ids':entries}
    batch.confirmed_digest=payload;batch.result=result
    return result


def cleanup(db):
    # Expired unconfirmed previews contain private transaction descriptions.
    # Confirmed import receipts remain available for replay and audit.
    db.execute(delete(StatementImport).where(StatementImport.created_at < now()-86400,StatementImport.confirmed_digest.is_(None)))
