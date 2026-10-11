"""Read and render verified totals without asking a model to calculate money."""
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .reporting import today,month_bounds

class Summary(BaseModel):
    model_config=ConfigDict(extra='forbid')
    report:Literal['balances','monthly']
    month:str|None=Field(default=None,pattern=r'^\d{4}-\d{2}$')

def tool():
    return {'type':'function','function':{'name':'answer_finance_summary','description':'Prefer for current money/balances or monthly income/expenses. Reads complete verified workspace totals and directly answers the user with correct baht amounts. No extra lookup or arithmetic needed. For monthly omit month for current month; use YYYY-MM for a specific month. Read-only, never prepares or confirms a transaction. Do not use for filtered account/category questions or requests to record/edit.','parameters':Summary.model_json_schema()}}

def parse(raw):
    value=Summary.model_validate_json(raw)
    if value.report=='balances' and value.month:raise ValueError('Balances do not accept month')
    if value.month:
        from fastapi import HTTPException
        try:month_bounds(value.month)
        except HTTPException:raise ValueError('Invalid month') from None
    return value

def render(value,result):
    if value.report=='balances':
        from .assistant_balance_reply import fallback
        return fallback({('lookup_workspace',''):result})
    def money(amount):return ('-' if amount<0 else '')+f'{abs(amount)//100:,}.{abs(amount)%100:02d}'
    rows=[f"สรุปเดือน **{result['month']}** จากรายการที่บันทึกไว้ค่ะ",'',f"- รายจ่าย: **{money(result['expense'])} บาท**",f"- รายรับ: **{money(result['income'])} บาท**",f"- รายรับหักรายจ่าย: **{money(result['net'])} บาท**"]
    if result.get('categories'):
        rows.extend(['','รายจ่ายแยกตามหมวด (สูงสุด 5 หมวด):'])
        for item in result['categories'][:5]:
            # Names are untrusted display data; avoid interpreting Markdown/HTML.
            import re
            name=re.sub(r'[\\`*_{}\[\]()<>#!|~]','',item['name']).replace('\n',' ')[:100]
            rows.append(f"- {name}: {money(item['amount'])} บาท")
    rows.extend(['','ยอดนี้เป็นรายการในเดือนที่เลือก ไม่ใช่ยอดเงินคงเหลือทุกบัญชีค่ะ'])
    return '\n'.join(rows)

def answer(db,room,job,raw):
    value=parse(raw)
    if value.report=='balances':
        from .assistant_lookup import read
        result=read(db,room,json.dumps({'queries':[{'resource':'balances'}]}))
    else:
        from .assistant_finance import read
        result=read(db,room,json.dumps({'operation':'monthly_analysis','month':value.month or today().strftime('%Y-%m')}),job.payload.get('user_message_id'))
    if result.get('error'):raise ValueError('Invalid report')
    from .finance_references import collect
    collect(job,result)
    return render(value,result)
