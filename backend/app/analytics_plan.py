"""Validate model analytics choices against the user's quoted request."""
import re

def validate(value,result,text,current):
    from .request_interpreter import NeedInfo,date_range
    if not value.analysis:raise NeedInfo('intent')
    a=value.analysis
    if value.transaction_kind not in (None,'income','expense'):raise NeedInfo('intent')
    result.transaction_kind=value.transaction_kind or 'expense'
    if result.category and result.category.kind!=result.transaction_kind:raise NeedInfo('category')
    if re.search(r'รายรับ|income',current,re.I) and not re.search(r'รายจ่าย|expense',current,re.I) and result.transaction_kind!='income':raise NeedInfo('intent')
    if re.search(r'รายจ่าย|expense',current,re.I) and result.transaction_kind!='expense':raise NeedInfo('intent')
    # Mixed income/expense comparisons require separate analyses, never silently
    # answer one metric while implying both. All dates and filters stay explicit.
    if re.search(r'รายรับ|income',current,re.I) and re.search(r'รายจ่าย|expense',current,re.I):raise NeedInfo('intent')
    requested=[(r'เปรียบเทียบ|เทียบ.*กับ|compare',{'compare'}),
        (r'แนวโน้ม|trend',{'trend'}),(r'อันดับ|ranking',{'ranking'}),
        (r'มากที่สุด|น้อยที่สุด|สูงสุด|ต่ำสุด',{'ranking','trend'}),
        (r'เฉลี่ย|average',{'average','summary','compare','trend','ranking'})]
    for pattern,allowed in requested:
        if re.search(pattern,current,re.I) and a.operation not in allowed:raise NeedInfo('intent')
    if a.bucket and a.operation!='trend':raise NeedInfo('intent')
    if a.group_by and a.operation!='ranking':raise NeedInfo('intent')
    if a.operation!='ranking' and (a.order!='highest' or a.limit!=5):raise NeedInfo('intent')
    if a.operation=='ranking':
        if re.search(r'น้อยที่สุด|ต่ำสุด|น้อยไปมาก',current) and a.order!='lowest':raise NeedInfo('intent')
        group='account' if re.search(r'บัญชีไหน|ตามบัญชี|อันดับบัญชี',current) else 'description' if re.search(r'ตามรายละเอียด',current) else None
        if group and a.group_by!=group:raise NeedInfo('intent')
    if a.operation=='trend' and a.bucket:
        for pattern,unit in [(r'รายวัน','day'),(r'รายสัปดาห์','week'),(r'รายเดือน','month')]:
            if re.search(pattern,current) and a.bucket!=unit:raise NeedInfo('intent')
    options=a.model_dump(exclude_none=True)
    if a.operation=='compare':
        if not value.compare_period or value.compare_period.phrase not in text:raise NeedInfo('period')
        try:start,end=date_range(value.compare_period)
        except (ValueError,OverflowError):raise NeedInfo('period') from None
        options.update(compare_start=start.isoformat(),compare_end=end.isoformat())
    elif value.compare_period:raise NeedInfo('period')
    # Preserve recognized description words when stripping only analysis grammar.
    # Ambiguous residual language is clarified rather than broadening the query.
    remaining=current
    for period in (value.period,value.compare_period):
        if period:remaining=remaining.replace(period.phrase,' ')
    # Protect literal descriptions before removing analysis grammar. A name
    # such as กับข้าว must not lose its inner กับ or other request-like words.
    if value.q:remaining=remaining.replace(value.q,' LITERAL_QUERY ')
    for reference in (value.account,value.category):
        if reference:remaining=remaining.replace(reference.phrase,' ')
    for account in (result.account,result.category):
        if account:remaining=remaining.replace(account.name,' ')
    remaining=re.sub(r'(?<!\d)\d+\s*(?:อันดับ|กลุ่ม)(?!\w)',' ',remaining)
    for word in sorted(['วิเคราะห์','แนวโน้ม','ค่าเฉลี่ย','เฉลี่ย','ต่อวันปฏิทิน','ต่อวัน','ต่อรายการ',
        'จัดอันดับ','อันดับ','มากที่สุด','น้อยที่สุด','สูงสุด','ต่ำสุด','มากไปน้อย','น้อยไปมาก',
        'รายวัน','รายสัปดาห์','รายเดือน','ตามหมวด','ตามบัญชี','ตามรายละเอียด','บัญชีไหน',
        'เป็นอย่างไร','เป็นไงบ้าง','ยังไงบ้าง','เป็นไง','ให้ที','ให้ดู','เปรียบเทียบ','เทียบกับ','เทียบ'],key=len,reverse=True):
        remaining=remaining.replace(word,' ')
    remaining=re.sub(r'(?<!\S)กับ(?!\S)',' ',remaining)
    from .assistant_scope import subject
    try:description=subject(remaining,[]).replace('LITERAL_QUERY',value.q).strip()
    except ValueError:raise NeedInfo('description') from None
    if description and re.search(r'[ก-๙]',description) and description!=value.q:raise NeedInfo('description')
    result.analysis=options
