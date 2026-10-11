"""Budgets are plans, never ledger postings. All amounts use integer satang."""
from datetime import timedelta
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from fastapi import HTTPException
from .models import Budget, Account, uid
from .ledger import get_scoped
from .reporting import month_bounds, period_summary


def budget_report(db,wid,month):
    start,end=month_bounds(month)
    spending=period_summary(db,wid,start,end)
    actual={c['id']:c['amount'] for c in spending['categories']}
    rows=db.execute(select(Budget,Account.name).join(Account,(Account.id==Budget.category_id)&(Account.workspace_id==Budget.workspace_id)).where(Budget.workspace_id==wid,Budget.month==month).order_by(Account.name,Budget.category_id)).all()
    items=[]
    for budget,name in rows:
        spent=actual.get(budget.category_id,0)
        status='over' if spent>budget.amount else 'reached' if spent==budget.amount else 'near' if spent*100>=budget.amount*80 else 'healthy'
        items.append(dict(category_id=budget.category_id,name=name,amount=budget.amount,spent=spent,remaining=budget.amount-spent,percent=spent*100//budget.amount,status=status))
    planned=sum(r['amount'] for r in items)
    used=sum(r['spent'] for r in items)
    budgeted={r['category_id'] for r in items}
    return dict(month=month,start=start.isoformat(),end=end.isoformat(),items=items,planned=planned,spent=used,remaining=planned-used,total_expense=spending['expense'],unbudgeted_expense=spending['expense']-used,unbudgeted_categories=[c for c in spending['categories'] if c['id'] not in budgeted],over_count=sum(r['status']=='over' for r in items))


def insertion(db):
    return pg_insert(Budget) if db.bind.dialect.name=='postgresql' else sqlite_insert(Budget)


def set_budget(db,wid,month,category_id,amount):
    month_bounds(month)
    category=get_scoped(db,Account,wid,category_id)
    if category.kind!='expense': raise HTTPException(422,'ตั้งงบได้เฉพาะหมวดรายจ่าย')
    stmt=insertion(db).values(id=uid(),workspace_id=wid,month=month,category_id=category_id,amount=amount)
    db.execute(stmt.on_conflict_do_update(index_elements=['workspace_id','month','category_id'],set_={'amount':amount}))


def remove_budget(db,wid,month,category_id):
    month_bounds(month)
    result=db.execute(delete(Budget).where(Budget.workspace_id==wid,Budget.month==month,Budget.category_id==category_id))
    if not result.rowcount: raise HTTPException(404,'ไม่พบงบประมาณ')


def copy_previous(db,wid,month):
    start,_=month_bounds(month)
    previous=(start-timedelta(days=1)).strftime('%Y-%m')
    rows=db.scalars(select(Budget).where(Budget.workspace_id==wid,Budget.month==previous)).all()
    copied=0
    for row in rows:
        stmt=insertion(db).values(id=uid(),workspace_id=wid,month=month,category_id=row.category_id,amount=row.amount)
        inserted=db.execute(stmt.on_conflict_do_nothing(index_elements=['workspace_id','month','category_id']).returning(Budget.id)).scalar_one_or_none()
        copied+=int(inserted is not None)
    return copied
