"""Static validation metadata only; never include model input or unknown keys."""
FIELDS={'category_choice','continue_draft','resource','account_id','category_id','clear_filters','text','metric','reuse_previous_scope','compare_period','weekday','relation','bucket','group_by','order','question','period','mode','phrase','days','account','category','source_message_id','action','missing','queries','resource','q','kind','month','cursor','limit','operation','start','end','account_id','category_id','other_account_id','amount','intent','description','occurred_on','transactions','attachment_id','reply','toolkit','operations','changes','entry_id','reason','name','target','due_on','rationale'}
CODES={'missing','extra_forbidden','string_type','string_too_long','literal_error','uuid_parsing','int_type','greater_than','less_than_equal','greater_than_equal','string_pattern_mismatch','date_from_datetime_parsing','json_invalid','model_type'}

def issues(error):
    result=[]
    for issue in error.errors(include_input=False,include_url=False)[:5]:
        path=[p for p in issue['loc'] if isinstance(p,str) and p in FIELDS]
        result.append({'field':'.'.join(path) or 'arguments','code':issue['type'] if issue['type'] in CODES else 'invalid'})
    return result

def valid_issues(values):
    if not isinstance(values,list):return []
    return [dict(field=v['field'],code=v['code']) for v in values[:5] if isinstance(v,dict) and isinstance(v.get('field'),str) and all(p in FIELDS|{'arguments'} for p in v['field'].split('.')) and isinstance(v.get('code'),str) and v.get('code') in CODES|{'invalid','unsupported_filter','unknown_reference'}]

HELP={
 'period':'ช่วงวันที่ไม่ตรงหรือไม่ครบ ตรวจคำวันที่ในข้อความผู้ใช้และวันนี้จากระบบ ส่งคำวันที่ของผู้ใช้ตรง ๆ ได้ ถ้าถามจนถึงตอนนี้อย่าใช้วันสิ้นเดือนในอนาคต ไม่ต้องให้ผู้ใช้กรอก format',
 'q':'q เป็นการค้นข้อความย่อยตามตัวอักษร ใช้เฉพาะหัวเรื่องที่ผู้ใช้ขอ ไม่ใส่คำพูดทั่วไปหรือรวมหลายคำด้วย OR หากต้องค้นหลายหัวเรื่องให้แยกอ่าน ไม่ต้องให้ผู้ใช้กรอก format',
 'metric':'เลือกประเภทรายการที่ผู้ใช้ต้องการ ไม่ปนยอดบัญชี รายรับ และรายจ่าย',
 'resource':'เลือกชนิดข้อมูลให้ตรงคำถาม ใช้ summary หรือ transactions สำหรับรายจ่ายตามช่วงวัน',
 'reuse_previous_scope':'ใช้ scope ก่อนหน้าเฉพาะเมื่อมีบริบทที่ตรวจแล้วจริง หากไม่มีให้กำหนดช่วงและตัวกรองจากคำขอปัจจุบัน',
}

def feedback(error):
    from pydantic import ValidationError
    found=issues(error) if isinstance(error,ValidationError) else valid_issues(getattr(error,'issues',[]))
    field=getattr(error,'field',None)
    if not found and isinstance(field,str) and field in FIELDS:found=[dict(field=field,code='unknown_reference')]
    hints=list(dict.fromkeys(HELP[v['field'].split('.')[0]] for v in found if v['field'].split('.')[0] in HELP))
    from .assistant_data import BalanceFilterConflict
    if isinstance(error,BalanceFilterConflict):
        return dict(issues=found,message='balances is the current accumulated wallet balance, not transactions in a period. Remove the listed transaction-only filters (including period/metric/category). Keep the requested wallet if any. For period spending use summary instead. Do not ask the user to rephrase.')
    return dict(issues=found,message=' '.join(hints[:3]) or 'แก้ argument ของเครื่องมือเองจากบริบทหรือค้นชื่อจริงก่อน ไม่ต้องให้ผู้ใช้กรอก format ห้ามเลือกผู้ใช้หรือ workspace อื่น')
