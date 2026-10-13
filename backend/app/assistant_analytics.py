"""Bounded, read-only analytics. SQL aggregates all matching active journals.

The model selects a typed analysis; every figure and explanatory sentence is
rendered from these aggregates, never accepted from model prose or page samples.
"""
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,func,case
from .models import Entry,Line,Account
from .reporting import transaction_conditions
from .assistant_render import money,clean,totals
from .finance_references import collect

class Analysis(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation:Literal['summary','compare','trend','average','ranking']
    bucket:Literal['day','week','month']|None=None
    group_by:Literal['category','account','description']|None=None
    order:Literal['highest','lowest']='highest'
    limit:int=Field(default=5,ge=1,le=10,strict=True)


def ratio(n,d,scale=1):
    # Rounded only at display boundaries; empty/zero denominators are undefined.
    return None if not d else (Decimal(n)*scale/Decimal(d)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)


def stats(db,wid,task,start,end):
    result=totals(db,wid,task,start,end)
    result.update(days=(end-start).days+1)
    result['daily_average']=ratio(result['amount'],result['days']*100)
    result['transaction_average']=ratio(result['amount'],result['count']*100)
    return result


def buckets(start,end,unit):
    cursor=start;values=[]
    while cursor<=end:
        if unit=='day':last=cursor
        elif unit=='week':last=cursor+timedelta(days=6-cursor.weekday())
        else:
            last=(cursor.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        last=min(last,end)
        values.append((cursor,last))
        if last==end:break
        cursor=last+timedelta(days=1)
    return values


def conditions(db,wid,task):
    return transaction_conditions(db,wid,task.start,task.end,task.transaction_kind,
        task.account.id if task.account else None,task.category.id if task.category else None,task.q)


def trend(db,wid,task,unit):
    windows=buckets(task.start,task.end,unit)
    # Portable SQL CASE groups into calendar-aligned buckets, including clipped
    # first/last weeks/months. No journal rows or daily pages reach the model.
    bucket=case(*[(Entry.occurred_on<=end.isoformat(),start.isoformat()) for start,end in windows])
    rows={key:(int(amount),int(count)) for key,amount,count in db.execute(
        select(bucket,func.sum(Entry.amount),func.count(Entry.id)).where(*conditions(db,wid,task)).group_by(bucket))}
    return [dict(start=s.isoformat(),end=e.isoformat(),days=(e-s).days+1,
        amount=rows.get(s.isoformat(),(0,0))[0],count=rows.get(s.isoformat(),(0,0))[1]) for s,e in windows]


def ranking(db,wid,task,group,order,limit):
    if group=='description':
        ident=Entry.description;name=Entry.description
        query=select(ident.label('id'),name.label('name'),func.sum(Entry.amount).label('amount'),func.count(Entry.id).label('count')).where(*conditions(db,wid,task))
    else:
        ident=Account.id;name=Account.name
        kinds=('asset','liability') if group=='account' else (task.transaction_kind,)
        # Deduplicate journal/account pairs before summing (even malformed or
        # future split journals cannot multiply a journal within one group).
        pairs=select(Line.entry_id,Line.account_id).where(Line.workspace_id==wid).distinct().subquery()
        query=select(ident.label('id'),name.label('name'),func.sum(Entry.amount).label('amount'),func.count(Entry.id).label('count')).select_from(Entry).join(pairs,pairs.c.entry_id==Entry.id).join(Account,(Account.id==pairs.c.account_id)&(Account.workspace_id==Entry.workspace_id)).where(*conditions(db,wid,task),Account.kind.in_(kinds))
    grouped=query.group_by(ident,name).subquery()
    group_count=db.scalar(select(func.count()).select_from(grouped))
    amount_order=grouped.c.amount.desc() if order=='highest' else grouped.c.amount.asc()
    rows=db.execute(select(grouped).order_by(amount_order,grouped.c.name,grouped.c.id).limit(limit)).mappings().all()
    return dict(group_count=group_count,items=[dict(id=r['id'],name=r['name'],amount=int(r['amount']),count=int(r['count'])) for r in rows])


def analyze(db,wid,task):
    options=task.analysis
    current=stats(db,wid,task,task.start,task.end)
    result=dict(operation=options['operation'],current=current)
    if options['operation']=='compare':
        start,end=(date.fromisoformat(options[k]) for k in ('compare_start','compare_end'))
        previous=stats(db,wid,task,start,end)
        delta=current['amount']-previous['amount']
        result.update(previous=previous,delta=delta,percent=ratio(delta,previous['amount'],100),
            daily_delta=ratio(current['amount']*previous['days']-previous['amount']*current['days'],current['days']*previous['days']*100),overlap=task.start<=end and start<=task.end)
    elif options['operation']=='trend':
        result['bucket']=options.get('bucket') or ('day' if current['days']<=31 else 'week' if current['days']<=90 else 'month')
        result['buckets']=trend(db,wid,task,result['bucket'])
    elif options['operation']=='ranking':
        result.update(group_by=options.get('group_by') or 'category',order=options.get('order','highest'))
        result.update(ranking(db,wid,task,result['group_by'],result['order'],options.get('limit',5)))
    return result


def report(db,room,job,task):
    result=analyze(db,room.workspace_id,task);current=result['current'];collect(job,current)
    label=' / '.join(clean(a.name) for a in (task.account,task.category) if a) or 'ทุกบัญชีและทุกหมวด'
    if task.q:label+=' / ค้นคำว่า '+clean(task.q)
    title='รายรับ' if task.transaction_kind=='income' else 'รายจ่าย'
    lines=[f"**วิเคราะห์{title} · {current['start']} ถึง {current['end']}**",label,
        f"- รวม **{money(current['amount'])} บาท** · {current['count']} รายการ · {current['days']} วันปฏิทิน",
        f"- เฉลี่ย **{current['daily_average']:,.2f} บาท/วัน** (รวมวันที่ไม่มีรายการ)"]
    average=current['transaction_average']
    lines.append(f"- เฉลี่ย **{average:,.2f} บาท/รายการ**" if average is not None else '- เฉลี่ยต่อรายการ: ยังไม่มีรายการ จึงคำนวณไม่ได้')
    if not current['count']:lines.append('ไม่พบรายการที่ตรงเงื่อนไขในช่วงนี้ค่ะ ไม่ได้แปลว่าไม่มีการใช้เงินจริงนอกระบบ')
    if result['operation']=='compare':
        previous=result['previous'];collect(job,previous)
        lines.extend([f"\n**เทียบกับ {previous['start']} ถึง {previous['end']}**",
            f"- ช่วงเทียบ: {money(previous['amount'])} บาท · {previous['count']} รายการ · {previous['days']} วัน · เฉลี่ย {previous['daily_average']:,.2f} บาท/วัน"])
        direction='เพิ่มขึ้น' if result['delta']>0 else 'ลดลง' if result['delta']<0 else 'เท่าเดิม'
        lines.append(f"- ยอดรวม{direction} **{money(abs(result['delta']))} บาท**"+(f" ({abs(result['percent']):,.2f}%)" if result['percent'] is not None else ' · คำนวณเปอร์เซ็นต์ไม่ได้ เพราะยอดช่วงเทียบเป็นศูนย์'))
        daily=result['daily_delta'];lines.append(f"- ค่าเฉลี่ยต่อวัน{'เพิ่ม' if daily>0 else 'ลด' if daily<0 else 'เปลี่ยน'} {abs(daily):,.2f} บาท/วัน")
        if current['days']!=previous['days']:lines.append('จำนวนวันไม่เท่ากัน ควรดูค่าเฉลี่ยต่อวันประกอบยอดรวมค่ะ')
        if result['overlap']:lines.append('สองช่วงมีวันที่ซ้อนกัน จึงไม่ใช่ช่วงอิสระจากกันค่ะ')
    elif result['operation']=='trend':
        rows=result['buckets'];unit={'day':'วัน','week':'สัปดาห์ (จันทร์–อาทิตย์)','month':'เดือน'}[result['bucket']]
        lines.append(f"\n**แนวโน้มราย{unit}**")
        for row in rows[-12:]:lines.append(f"- {row['start']} ถึง {row['end']}: {money(row['amount'])} บาท · {row['count']} รายการ · {row['days']} วัน")
        if len(rows)>12:lines.append(f"แสดง 12 ช่วงท้ายจากทั้งหมด {len(rows)} ช่วง ยอดรวมและจุดสูงสุด/ต่ำสุดคำนวณครบทุกช่วง")
        highest=max(rows,key=lambda r:r['amount']);lowest=min(rows,key=lambda r:r['amount'])
        for word,row in [('สูงสุด',highest),('ต่ำสุด',lowest)]:lines.append(f"- ช่วงที่ยอด{word}: {row['start']} ถึง {row['end']} · {money(row['amount'])} บาท (ถ้าเท่ากันแสดงช่วงแรก)")
        lines.append('รวมช่วงที่ไม่มีรายการเป็นศูนย์ ช่วงแรก/ท้ายอาจไม่เต็มสัปดาห์หรือเดือน; ไม่คาดการณ์อนาคตจากข้อมูลนี้ค่ะ')
    elif result['operation']=='ranking':
        group={'category':'หมวด','account':'บัญชี','description':'รายละเอียดตรงกัน'}[result['group_by']]
        lines.append(f"\n**อันดับตาม{group} · {'มากไปน้อย' if result['order']=='highest' else 'น้อยไปมาก'}**")
        for i,row in enumerate(result['items'],1):
            share=ratio(row['amount'],current['amount'],100)
            lines.append(f"{i}. {clean(row['name'])}: **{money(row['amount'])} บาท** · {row['count']} รายการ · {share:,.2f}% ของยอดกรองทั้งหมด")
            filters={k:current[k] for k in ('start','end','kind','account_id','category_id','q') if current.get(k)}
            if result['group_by'] in ('category','account'):
                filters['category_id' if result['group_by']=='category' else 'account_id']=row['id']
                job._finance_refs=[*getattr(job,'_finance_refs',[]),dict(type='category',label=clean(row['name']),amount=row['amount'],filters=filters)][-24:]
        if result['group_count']>len(result['items']):lines.append(f"แสดง {len(result['items'])} จาก {result['group_count']} กลุ่ม สัดส่วนใช้ยอดครบทุกกลุ่ม ไม่ใช่เฉพาะอันดับที่แสดง")
        lines.append('นับเฉพาะกลุ่มที่มีรายการ; ยอดเท่ากันเรียงชื่อแล้วรหัส ไม่เดาสาเหตุจากชื่อกลุ่มค่ะ')
    lines.append('\nจากรายการที่บันทึกแล้ว รวมครบตามตัวกรอง ไม่รวมโอนเงิน/จ่ายบัตรซ้ำ และยังไม่ได้เปลี่ยนข้อมูลค่ะ')
    return '\n'.join(lines)
