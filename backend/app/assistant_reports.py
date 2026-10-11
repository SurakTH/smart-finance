"""AI reports omit dashboard balances, daily series and recent journals.

SQL computes complete totals. Group rows stream in bounded batches for a full
freshness digest; only the top20 groups/plans are retained for the model.
"""
import hashlib
import json
from datetime import timedelta
from sqlalchemy import select,func,case
from .models import Entry,Account,Line,Budget
from .reporting import active_entry,month_bounds

def feed(digest,value):
    digest.update(json.dumps(value,sort_keys=True,ensure_ascii=False).encode());digest.update(b'\n')

def period(db,wid,start,end,digest):
    conditions=[Entry.workspace_id==wid,active_entry(wid),Entry.occurred_on>=start.isoformat(),Entry.occurred_on<=end.isoformat()]
    count,income,expense=db.execute(select(func.count(Entry.id),func.coalesce(func.sum(case((Entry.kind=='income',Entry.amount),else_=0)),0),func.coalesce(func.sum(case((Entry.kind=='expense',Entry.amount),else_=0)),0)).where(*conditions)).one()
    result=dict(start=start.isoformat(),end=end.isoformat(),income=int(income),expense=int(expense),net=int(income-expense),count=count)
    feed(digest,result)
    for key,kinds,amount_key,count_key in [('categories',('expense',),'amount','category_count'),('spending_accounts',('asset','liability'),'expense','account_count')]:
        stmt=select(Account.id,Account.name,func.sum(Entry.amount),func.count(Entry.id)).join(Line,(Line.account_id==Account.id)&(Line.workspace_id==Account.workspace_id)).join(Entry,(Entry.id==Line.entry_id)&(Entry.workspace_id==Line.workspace_id)).where(*conditions,Entry.kind=='expense',Account.kind.in_(kinds)).group_by(Account.id,Account.name).order_by(func.sum(Entry.amount).desc(),Account.name,Account.id)
        rows=db.execute(stmt.execution_options(yield_per=100));items=[];total=0
        for aid,name,amount,n in rows:
            item=dict(id=aid,name=name,**{amount_key:int(amount)},count=n);feed(digest,[key,item]);total+=1
            if len(items)<20:items.append(item)
        result[key]=items;result[count_key]=total
    return result

def monthly(db,wid,month):
    start,end=month_bounds(month);digest=hashlib.sha256()
    current=period(db,wid,start,end,digest)
    previous_end=start-timedelta(days=1)
    previous=period(db,wid,previous_end.replace(day=1),previous_end,digest)
    # Aggregate category spend in SQL and join just this month's plans, not all
    # categories/entries in Python. Superseded/reversal entries are excluded.
    spend=select(Line.account_id.label('category_id'),func.sum(Entry.amount).label('spent')).join(Entry,(Entry.id==Line.entry_id)&(Entry.workspace_id==Line.workspace_id)).where(Line.workspace_id==wid,Entry.workspace_id==wid,active_entry(wid),Entry.kind=='expense',Entry.occurred_on>=start.isoformat(),Entry.occurred_on<=end.isoformat()).group_by(Line.account_id).subquery()
    stmt=select(Budget.category_id,Account.name,Budget.amount,func.coalesce(spend.c.spent,0)).join(Account,(Account.id==Budget.category_id)&(Account.workspace_id==Budget.workspace_id)).outerjoin(spend,spend.c.category_id==Budget.category_id).where(Budget.workspace_id==wid,Budget.month==month).order_by(Account.name,Budget.category_id)
    items=[];planned=used=over=total=0
    for aid,name,amount,spent in db.execute(stmt.execution_options(yield_per=100)):
        spent=int(spent);status='over' if spent>amount else 'reached' if spent==amount else 'near' if spent*100>=amount*80 else 'healthy'
        item=dict(category_id=aid,name=name,amount=amount,spent=spent,remaining=amount-spent,percent=spent*100//amount,status=status)
        feed(digest,['budget',item]);planned+=amount;used+=spent;over+=int(status=='over');total+=1
        if len(items)<20:items.append(item)
    budgets=dict(items=items,item_count=total,planned=planned,spent=used,remaining=planned-used,total_expense=current['expense'],unbudgeted_expense=current['expense']-used,over_count=over)
    report=dict(current,month=month,previous=previous,budgets=budgets)
    snapshot=dict(month=month,fingerprint=digest.hexdigest(),income=current['income'],expense=current['expense'],previous_expense=previous['expense'],planned=planned,spent=used)
    return report,snapshot
