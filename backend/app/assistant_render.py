"""Typed SQL-backed answers: amounts and filters stay together through rendering."""
from datetime import timedelta
from sqlalchemy import select,func,case
from .models import Entry
from .reporting import transaction_conditions,transaction_report
from .finance_references import collect


def money(value):return ('-' if value<0 else '')+f'{abs(value)//100:,}.{abs(value)%100:02d}'
def clean(value):
    from .assistant_evidence import clean
    return clean(value)


def transaction_line(item,number):
    names=' → '.join(clean(a['name']) for a in item.get('accounts',[]))
    return f"{number}. {clean(item['occurred_on'])} · {clean(item['description'])} · {money(item['amount'])} บาท"+(' · '+names if names else '')


def totals(db,wid,task,start,end):
    filters=dict(start=start.isoformat(),end=end.isoformat(),q=task.q,
        account_id=task.account.id if task.account else None,category_id=task.category.id if task.category else None,kind=task.transaction_kind)
    conditions=transaction_conditions(db,wid,start,end,task.transaction_kind,filters['account_id'],filters['category_id'],task.q)
    n,i,e,total=db.execute(select(func.count(Entry.id),func.coalesce(func.sum(case((Entry.kind=='income',Entry.amount),else_=0)),0),func.coalesce(func.sum(case((Entry.kind=='expense',Entry.amount),else_=0)),0),func.coalesce(func.sum(Entry.amount),0)).where(*conditions)).one()
    return dict(source='ledger_backend',**filters,count=n,income=int(i),expense=int(e),amount=int(total))


def financial_report(db,room,job,task):
    label=' / '.join(clean(a.name) for a in (task.account,task.category) if a)
    if task.q:label+=' / ค้นคำว่า '+clean(task.q)
    label=label.strip(' /') or 'ทุกบัญชีและทุกหมวดในพื้นที่นี้'
    if task.kind=='budget':
        from .budgets import budget_report
        result=budget_report(db,room.workspace_id,task.start.strftime('%Y-%m'))
        items=[r for r in result['items'] if not task.category or r['category_id']==task.category.id]
        if not items:return f"เดือน **{result['month']}** · {label} ยังไม่ได้ตั้งงบประมาณค่ะ"
        planned=sum(r['amount'] for r in items);spent=sum(r['spent'] for r in items)
        lines=[f"งบเดือน **{result['month']}** · {label}",f"- วงเงิน: **{money(planned)} บาท**",f"- ใช้จริงในหมวดที่ตั้งงบ: **{money(spent)} บาท**",f"- คงเหลือ: **{money(planned-spent)} บาท**"]
        for r in items[:20]:lines.append(f"- {clean(r['name'])}: ใช้ {money(r['spent'])} / {money(r['amount'])} บาท · เหลือ {money(r['remaining'])} บาท")
        if len(items)>20:lines.append('แสดงรายละเอียด 20 หมวดแรก ยอดรวมรวมครบทุกหมวดที่ตั้งงบแล้วค่ะ')
        if not task.category:lines.append(f"รายจ่ายหมวดที่ไม่ได้ตั้งงบ: {money(result['unbudgeted_expense'])} บาท (ไม่รวมในยอดใช้งบด้านบน)")
        collect(job,dict(source='ledger_backend',month=result['month'],start=result['start'],end=result['end'],category_id=task.category.id if task.category else None,income=0,expense=spent))
        return '\n'.join(lines)+'\n\nอ่านจากระบบ ยังไม่ได้เปลี่ยนงบค่ะ'
    result=totals(db,room.workspace_id,task,task.start,task.end);collect(job,result)
    if task.kind=='comparison':
        previous_end=task.start-timedelta(days=1);previous_start=previous_end.replace(day=1)
        previous=totals(db,room.workspace_id,task,previous_start,previous_end);collect(job,previous)
        lines=[f"เปรียบเทียบ **{task.start.strftime('%Y-%m')}** กับ **{previous_start.strftime('%Y-%m')}** · {label}"]
        for key,title in [('expense','รายจ่าย'),('income','รายรับ')]:
            delta=result[key]-previous[key]
            lines.append(f"- {title}: เดือนนี้ **{money(result[key])} บาท** · เดือนก่อน **{money(previous[key])} บาท** · {'เพิ่ม' if delta>=0 else 'ลด'} **{money(abs(delta))} บาท**")
        return '\n'.join(lines)+'\n\nจากรายการที่บันทึกแล้ว ไม่ใช่ยอดคงเหลือสะสมค่ะ'
    lines=[f"ช่วง **{task.start.isoformat()} ถึง {task.end.isoformat()}** · {label}"]
    if task.transaction_kind in ('transfer','card_payment'):
        title={'transfer':'โอนเงิน','card_payment':'จ่ายบัตรเครดิต'}[task.transaction_kind]
        lines.append(f"- {title}: **{money(result['amount'])} บาท** ({result['count']} รายการ) ไม่คิดเป็นรายจ่ายซ้ำ")
    else:lines.extend([f"- รายจ่าย: **{money(result['expense'])} บาท**",f"- รายรับ: **{money(result['income'])} บาท**",f"- รายรับหักรายจ่าย: **{money(result['income']-result['expense'])} บาท**"])
    if task.include_items or __import__('re').search(r'มีอะไร|รายการ|รายละเอียด|บัญชีไหน',task.text):
        report=transaction_report(db,room.workspace_id,task.start,task.end,task.transaction_kind,
            result['account_id'],result['category_id'],task.q,page_size=10)
        lines.append(f"\nรายการที่ตรงเงื่อนไข {report['total']} รายการ:")
        lines.extend(transaction_line(item,i) for i,item in enumerate(report['items'],1))
        if report['total']>10:lines.append('แสดง 10 รายการแรก ยอดรวมด้านบนรวมรายการที่ตรงเงื่อนไขทั้งหมดแล้วค่ะ')
        from .models import now
        turn=job.payload.get('user_message_id')
        room.capture_context={**(room.capture_context or {}),'finance_search':dict(items=report['items'],total=report['total'],has_more=report['total']>10,next_cursor=report['items'][-1]['id'] if report['total']>10 else None,filters=dict(operation='search_transactions',start=result['start'],end=result['end'],q=task.q,kind=task.transaction_kind,account_id=result['account_id'],category_id=result['category_id']),expires=now()+900,turn=turn,ambiguous_turn=turn if report['total']>1 else None)}
        collect(job,{**result,'items':report['items']})
    return '\n'.join(lines)+'\n\nจากรายการที่บันทึกแล้ว ไม่ใช่ยอดคงเหลือสะสมค่ะ'
