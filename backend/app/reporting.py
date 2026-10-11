"""Read-only, workspace-scoped finance reports. All amounts are integer satang."""
import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, case
from fastapi import HTTPException
from .models import Entry, Account, Line, EntryRevision
from .ledger import account_balances, get_scoped

def active_entry(wid):
    # Reversal journals retain the original kind; their audit role excludes them
    # and superseded originals from business reports, never from account balances.
    return ~select(EntryRevision.id).where(EntryRevision.workspace_id==wid,
        (EntryRevision.original_id==Entry.id)|(EntryRevision.reversal_id==Entry.id)).correlate(Entry).exists()

KINDS = {'opening','income','expense','transfer','card_payment'}

def today():
    return datetime.now(ZoneInfo('Asia/Bangkok')).date()

def month_bounds(month):
    try:
        if len(month)!=7: raise ValueError()
        start=date.fromisoformat(month+'-01')
        if not 2<=start.year<=9998: raise ValueError()
        end=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1])
        return start,end
    except (ValueError,TypeError): raise HTTPException(422,'เดือนต้องอยู่ในรูป YYYY-MM และเป็นเดือนที่ถูกต้อง')

def entry_details(db,wid,entries):
    values={e.id:{k:getattr(e,k) for k in ('id','kind','description','amount','occurred_on')}|{'accounts':[],'category':None} for e in entries}
    if values:
        rows=db.execute(select(Line,Account).join(Account,(Line.account_id==Account.id)&(Line.workspace_id==Account.workspace_id)).where(Line.workspace_id==wid,Line.entry_id.in_(values)))
        for line,account in rows:
            if account.kind in ('asset','liability'):
                values[line.entry_id]['accounts'].append({'id':account.id,'name':account.name,'direction':'in' if line.signed_amount>0 else 'out'})
            elif account.kind in ('income','expense'):
                values[line.entry_id]['category']={'id':account.id,'name':account.name}
    for row in values.values(): row['accounts'].sort(key=lambda a:(a['direction']!='out',a['name'],a['id']))
    return list(values.values())

def transaction_conditions(db,wid,start=None,end=None,kind=None,account_id=None,category_id=None,q=''):
    if start and end and start>end: raise HTTPException(422,'วันเริ่มต้นต้องไม่เกินวันสิ้นสุด')
    if kind and kind not in KINDS: raise HTTPException(422,'ประเภทรายการไม่ถูกต้อง')
    conditions=[active_entry(wid),Entry.workspace_id==wid]
    if start: conditions.append(Entry.occurred_on>=start.isoformat())
    if end: conditions.append(Entry.occurred_on<=end.isoformat())
    if kind: conditions.append(Entry.kind==kind)
    if q.strip(): conditions.append(func.lower(Entry.description).contains(q.strip().lower(),autoescape=True))
    for aid,allowed in [(account_id,('asset','liability')),(category_id,('income','expense'))]:
        if aid:
            account=get_scoped(db,Account,wid,aid)
            if account.kind not in allowed: raise HTTPException(422,'ชนิดตัวกรองบัญชีไม่ถูกต้อง')
            conditions.append(select(Line.id).where(Line.workspace_id==wid,Line.entry_id==Entry.id,Line.account_id==aid).correlate(Entry).exists())
    return conditions


def transaction_report(db,wid,start=None,end=None,kind=None,account_id=None,category_id=None,q='',page=1,page_size=30):
    conditions=transaction_conditions(db,wid,start,end,kind,account_id,category_id,q)
    count,income,expense=db.execute(select(func.count(Entry.id),func.coalesce(func.sum(case((Entry.kind=='income',Entry.amount),else_=0)),0),func.coalesce(func.sum(case((Entry.kind=='expense',Entry.amount),else_=0)),0)).where(*conditions)).one()
    rows=db.scalars(select(Entry).where(*conditions).order_by(Entry.occurred_on.desc(),Entry.created_at.desc(),Entry.id).offset((page-1)*page_size).limit(page_size)).all()
    return {'items':entry_details(db,wid,rows),'total':count,'income':int(income),'expense':int(expense),'page':page,'page_size':page_size,'start':start.isoformat() if start else None,'end':end.isoformat() if end else None}

def period_summary(db,wid,start,end,account_id=None,category_id=None):
    conditions=[active_entry(wid),Entry.workspace_id==wid,Entry.occurred_on>=start.isoformat(),Entry.occurred_on<=end.isoformat()]
    for aid in (account_id,category_id):
        if aid: conditions.append(select(Line.id).where(Line.workspace_id==wid,Line.entry_id==Entry.id,Line.account_id==aid).correlate(Entry).exists())
    total,income,expense=db.execute(select(func.count(Entry.id),func.coalesce(func.sum(case((Entry.kind=='income',Entry.amount),else_=0)),0),func.coalesce(func.sum(case((Entry.kind=='expense',Entry.amount),else_=0)),0)).where(*conditions)).one()
    daily=[{'day':d,'income':int(i or 0),'expense':int(e or 0)} for d,i,e in db.execute(select(Entry.occurred_on,func.sum(case((Entry.kind=='income',Entry.amount),else_=0)),func.sum(case((Entry.kind=='expense',Entry.amount),else_=0))).where(*conditions).group_by(Entry.occurred_on).order_by(Entry.occurred_on))]
    grouped=db.execute(select(Account.id,Account.name,func.sum(Entry.amount),func.count(Entry.id)).join(Line,(Line.account_id==Account.id)&(Line.workspace_id==Account.workspace_id)).join(Entry,(Entry.id==Line.entry_id)&(Entry.workspace_id==Line.workspace_id)).where(*conditions,Entry.kind=='expense',Account.kind=='expense').group_by(Account.id,Account.name).order_by(func.sum(Entry.amount).desc(),Account.name)).all()
    categories=[{'id':aid,'name':n,'amount':int(amount),'count':count} for aid,n,amount,count in grouped]
    wallet_rows=db.execute(select(Account.id,Account.name,func.sum(Entry.amount),func.count(Entry.id)).join(Line,(Line.account_id==Account.id)&(Line.workspace_id==Account.workspace_id)).join(Entry,(Entry.id==Line.entry_id)&(Entry.workspace_id==Line.workspace_id)).where(*conditions,Entry.kind=='expense',Account.kind.in_(('asset','liability'))).group_by(Account.id,Account.name).order_by(func.sum(Entry.amount).desc(),Account.name)).all()
    wallets=[{'id':aid,'name':n,'expense':int(amount),'count':count} for aid,n,amount,count in wallet_rows]
    return {'start':start.isoformat(),'end':end.isoformat(),'income':int(income),'expense':int(expense),'net':int(income-expense),'count':total,'daily':daily,'categories':categories,'spending_accounts':wallets}

def monthly_report(db,wid,month):
    start,end=month_bounds(month)
    current=period_summary(db,wid,start,end)
    previous_end=start-timedelta(days=1)
    previous=period_summary(db,wid,previous_end.replace(day=1),previous_end)
    balances=account_balances(db,wid)
    return dict(current,month=month,previous=previous,balances=balances,net_worth=sum(a['balance'] for a in balances if a['kind']=='asset')-sum(a['balance'] for a in balances if a['kind']=='liability'),recent=transaction_report(db,wid,start,end,page_size=5)['items'])
