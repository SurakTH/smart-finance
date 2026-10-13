"""Calendar transport adapter, not a grammar for user finance commands.

The model can pass date words directly. Calendar math stays on the backend;
unknown/ambiguous expressions never silently turn into the current month.
"""
import re
from datetime import date,timedelta

DIGITS=str.maketrans('๐๑๒๓๔๕๖๗๘๙','0123456789')
MODES=('today','yesterday','month_to_date','current_month','previous_month','current_week','previous_week','last_days','month','range','weekday')
ALIASES={
 'this_month':'current_month','thismonth':'current_month','currentmonth':'current_month','เดือนนี้':'current_month',
 'last_month':'previous_month','lastmonth':'previous_month','previousmonth':'previous_month','เดือนก่อน':'previous_month','เดือนที่แล้ว':'previous_month',
 'this_week':'current_week','thisweek':'current_week','currentweek':'current_week','สัปดาห์นี้':'current_week','อาทิตย์นี้':'current_week',
 'last_week':'previous_week','lastweek':'previous_week','previousweek':'previous_week','สัปดาห์ที่แล้ว':'previous_week','สัปดาห์ก่อน':'previous_week','อาทิตย์ก่อน':'previous_week','อาทิตย์ที่แล้ว':'previous_week',
 'วันนี้':'today','เมื่อวาน':'yesterday','เมื่อวานนี้':'yesterday',
 'mtd':'month_to_date','monthtodate':'month_to_date','this_month_to_date':'month_to_date','current_month_to_date':'month_to_date','this_month_so_far':'month_to_date','since_start_of_month':'month_to_date','since_the_start_of_this_month':'month_to_date','since_month_start':'month_to_date',
 'ตั้งแต่ต้นเดือนถึงวันนี้':'month_to_date','ตั้งแต่ต้นเดือนจนถึงวันนี้':'month_to_date','ตั้งแต่เริ่มเดือนมาจนตอนนี้':'month_to_date','ตั้งแต่เปิดเดือนมาจนตอนนี้':'month_to_date','ตั้งแต่เริ่มเดือนถึงวันนี้':'month_to_date','เดือนนี้ถึงวันนี้':'month_to_date','ต้นเดือนถึงวันนี้':'month_to_date',
 'custom':'range','custom_range':'range','date_range':'range','absolute':'range','between':'range',
}
DATE=r'(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)'


def current():
    from .reporting import today
    return today()


def key(value):return re.sub(r'[\s-]+','_',value.strip().lower().translate(DIGITS))


def day(value):
    if isinstance(value,date):return value.isoformat()
    value=str(value).strip().translate(DIGITS)
    if re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}',value):year,month,number=map(int,value.split('-'))
    elif re.fullmatch(r'\d{1,2}/\d{1,2}(?:/\d{2,4})?',value):
        parts=list(map(int,value.split('/')));number,month=parts[:2];year=parts[2] if len(parts)==3 else current().year
        if year<100:raise ValueError('ambiguous calendar year')
    else:raise ValueError('unknown calendar date')
    if year>=2400:year-=543
    return date(year,month,number).isoformat()


def expression(value):
    if not isinstance(value,str) or not value.strip() or len(value)>120:raise ValueError('unknown calendar expression')
    text=value.strip().translate(DIGITS)
    text=re.sub(r'^(?:วันที่|วัน|date\s+)\s*','',text,flags=re.I) if re.match(r'^(?:วันที่|วัน)\s*\d|^date\s+\d',text,re.I) else text
    normalized=key(text)
    if re.search(r'[ก-๙]',normalized) and normalized.replace('_','') in ALIASES:normalized=normalized.replace('_','')
    mode=ALIASES.get(normalized,normalized)
    if mode in MODES:return {'mode':mode}
    if normalized in ('week_to_date','this_week_so_far','wtd'):
        end=current();return dict(mode='range',start=(end-timedelta(days=end.weekday())).isoformat(),end=end.isoformat())
    if re.fullmatch(DATE,text):return dict(mode='range',start=day(text),end=day(text))
    if re.fullmatch(r'\d{4}-\d{2}',text):
        year,month=map(int,text.split('-'));year=year-543 if year>=2400 else year;date(year,month,1)
        return dict(mode='month',month=f'{year:04}-{month:02}')
    rolling=re.fullmatch(r'(?:last|past|previous)_(\d{1,3})_days?|ย้อนหลัง[_\s]*(\d{1,3})[_\s]*วัน|(\d{1,3})[_\s]*วันที่ผ่านมา',normalized)
    if rolling:return dict(mode='last_days',days=int(next(v for v in rolling.groups() if v is not None)))
    interval=re.fullmatch(r'(?:from\s+|ตั้งแต่\s*)?('+DATE+r')\s*(?:to|through|until|ถึง|จนถึง|\.\.)\s*('+DATE+r')',text,re.I)
    if interval:return dict(mode='range',start=day(interval[1]),end=day(interval[2]))
    raise ValueError('unknown or ambiguous calendar expression')


def normalize(value):
    if value is None:return None
    if isinstance(value,str):return expression(value)
    if not isinstance(value,dict):return value
    data=dict(value)
    # Common model wrappers are accepted only in this exact, date-only shape.
    if set(data)=={'mode','value'} and key(str(data['mode'])) in ('relative','date','period'):
        return expression(data['value'])
    if not set(data)<=set(('mode','days','month','start','end','weekday','relation')):return data
    mode=data.get('mode')
    if mode is None and data.get('start') and data.get('end'):data['mode']='range'
    elif isinstance(mode,str):
        normalized=key(mode)
        if normalized in ('date','single_date') and data.get('start'):
            data.update(mode='range',end=data.get('end') or data['start'])
        elif normalized in MODES:data['mode']=normalized
        else:
            replacement=expression(mode)
            for name,chosen in replacement.items():
                if name!='mode' and data.get(name) is not None and data[name]!=chosen:raise ValueError('conflicting calendar fields')
            data.update(replacement)
    if data.get('mode') in ('date','single_date') and data.get('start') and not data.get('end'):
        data.update(mode='range',end=data['start'])
    for field in ('start','end'):
        if data.get(field) is not None:data[field]=day(data[field])
    if data.get('month') and re.fullmatch(r'\d{4}-\d{2}',str(data['month'])):
        year,month=map(int,str(data['month']).split('-'));year=year-543 if year>=2400 else year
        data['month']=f'{year:04}-{month:02}'
    return data


def schema():
    return dict(description='Calendar date words, not a mode object. Copy the user date phrase directly: สัปดาห์ที่แล้ว, เมื่อวาน, 13/10, last week, month to date. Backend resolves Thai/English relative dates using Bangkok today. For another explicit range send {start:YYYY-MM-DD,end:YYYY-MM-DD}. Unknown phrases: use an explicit range, do not invent mode names. Omit only if no date was requested.',anyOf=[
        dict(type='string',minLength=1,maxLength=120,examples=['สัปดาห์ที่แล้ว','เมื่อวาน','13/10','month to date']),
        dict(type='object',additionalProperties=False,properties=dict(start=dict(type='string',format='date'),end=dict(type='string',format='date')),required=['start','end']),
        dict(type='null')])


def argument_help():
    return dict(calendar=dict(examples=['สัปดาห์ที่แล้ว','เมื่อวาน','13/10','month to date',{'start':current().replace(day=1).isoformat(),'end':current().isoformat()}],
        accepted_modes=list(MODES),message='Prefer period as plain date words copied from the user, or explicit start/end. Do not repeat an invented period.mode. Do not default to this month when the user gave another date.'))


def mention(text):
    """Exactly one calendar mention; conflicting dates never pick the first."""
    if not isinstance(text,str) or len(text)>16000:return None
    words=set(MODES)|set(ALIASES)
    fixed=[]
    for word in sorted(words,key=len,reverse=True):
        token=re.escape(word).replace('_',r'[\s_-]+')
        if re.search(r'[a-z]',word):token=r'(?<![a-z])'+token+r'(?![a-z])'
        fixed.append(token)
    pattern=r'(?<![\d/])'+DATE+r'\s*(?:to|through|until|ถึง|จนถึง|\.\.)\s*'+DATE+r'(?![\d/])|(?<![\d/])'+DATE+r'(?![\d/])|(?:last|past|previous)[\s_-]+\d{1,3}[\s_-]+days?|ย้อนหลัง\s*\d{1,3}\s*วัน|\d{1,3}\s*วันที่ผ่านมา|'+'|'.join(fixed)
    value=text.translate(DIGITS);matches=list(re.finditer(pattern,value,re.I))
    if len(matches)!=1:return None
    match=matches[0]
    try:result=expression(match[0])
    except ValueError:return None
    return dict(value=result,start=match.start(),end=match.end())


def hint(text):
    found=mention(text)
    return found['value'] if found else None


def date_only(text):
    found=mention(text)
    if not found:return False
    rest=text[:found['start']]+text[found['end']:]
    return bool(re.fullmatch(r'(?:\s|[?？,]|วันที่|date|ละ|ล่ะ|แล้ว|ค่ะ|ครับ|นะ|อะ|งั้น|แล้วก็)*',rest,re.I))


def parameters(model):
    result=model.model_json_schema()
    for field in ('period','compare_period'):result['properties'][field]=schema()
    result.get('$defs',{}).pop('Window',None)
    if not result.get('$defs'):result.pop('$defs',None)
    return result
