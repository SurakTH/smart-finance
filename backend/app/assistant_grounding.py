"""Bind financial figures to their meaning; render canonical labels from facts.

Free prose checks are a compatibility boundary, not a general language parser.
The primary renderer lets the model select evidence, never author its amounts,
account labels, dates or increase/decrease signs.
"""
import re
from decimal import Decimal
from pydantic import BaseModel,ConfigDict,Field

NUMBER=re.compile(r'[-+]?\d[\d,]*(?:\.\d+)?')
ALIASES={
    'income':r'รายรับ|รายได้|รับมา|เงินเข้า|income',
    'expense':r'รายจ่าย|ใช้ไป|จ่ายไป|ใช้จ่าย|หมดไป|expense|spent',
    'net':r'ยอดสุทธิ|สุทธิ|net',
    'amount':r'ยอดรวม|total',
    'assets':r'สินทรัพย์|assets',
    'liabilities':r'หนี้สิน|หนี้|debt|liabilities',
    'planned':r'งบที่ตั้ง|งบที่วาง|งบประมาณ|planned',
    'remaining':r'ยังเหลือ|เหลืองบ|คงเหลือ|remaining',
    'previous_amount':r'ก่อนหน้า|ช่วงก่อน|previous',
    'delta':r'ลดลง|เพิ่มขึ้น|ส่วนต่าง|decreased?|increased?|delta',
    'daily_average':r'เฉลี่ยต่อวัน|เฉลี่ยวันละ|daily.average',
    'transaction_average':r'เฉลี่ยต่อรายการ|transaction.average',
    'highest_amount':r'สูงสุด|มากสุด|highest',
    'lowest_amount':r'ต่ำสุด|น้อยสุด|lowest',
}


def numeric(value):
    match=NUMBER.search(str(value))
    return Decimal(match[0].replace(',','')) if match else None


def local_context(text,match):
    start=text.rfind('\n',0,match.start())+1
    end=text.find('\n',match.end());end=len(text) if end<0 else end
    line=text[start:end]
    if '|' in line:
        column=text[start:match.start()].count('|')
        previous=text[:start].splitlines()
        headers=next((s for s in reversed(previous) if '|' in s and re.search(r'[ก-๙a-zA-Z]',s)),None)
        cells=line.split('|')
        heading=headers.split('|')[column] if headers and len(headers.split('|'))>column else ''
        return ' '.join(cells[:column])+ ' '+heading+' '+text[max(start,match.start()-60):match.start()]
    # Do not associate an amount with a label from the next sentence/row.
    prefix=text[max(start,match.start()-100):match.start()]
    boundaries=list(re.finditer(r'ค่ะ|ครับ|[;!?]|แต่|ส่วน|ขณะที่|ตอนนี้|ปัจจุบัน|ช่วงนี้',prefix))
    return prefix[boundaries[-1].end():] if boundaries else prefix


def check_relationships(datasets,text):
    """Reject recognized label/value swaps and allow signed decrease magnitudes."""
    variants=set();facts=[d['facts'] for d in datasets]
    for match in NUMBER.finditer(text):
        value=Decimal(match[0].replace(',',''));context=local_context(text,match)
        suffix=text[match.end():match.end()+20]
        if re.match(r'\s*รายการ',suffix):continue
        percent=bool(re.match(r'\s*%',suffix))
        anchors=[]
        for metric,pattern in ALIASES.items():
            values={numeric(f[metric]) for f in facts if metric in f}
            if metric=='expense':values|={numeric(f['spent']) for f in facts if 'spent' in f}
            if not values:continue
            for cue in re.finditer(pattern,context,re.I):anchors.append((cue.end(),metric,values))
        # Entity labels bind their associated values, never another account's.
        for f in facts:
            for key,label in f.items():
                if not key.endswith(('_name','_description')) or not str(label).strip():continue
                prefix=key.rsplit('_',1)[0]+'_'
                values={numeric(v) for k,v in f.items() if k.startswith(prefix) and k.endswith(('_balance','_balance_satang','_amount','_target','_saved','_remaining'))}
                if not values:continue
                for cue in re.finditer(re.escape(str(label)),context,re.I):anchors.append((cue.end(),'entity',values))
        if percent:
            allowed={numeric(f['change_percent']) for f in facts if 'change_percent' in f}
            anchors=[(len(context),'change_percent',allowed)] if allowed else []
        if not anchors:continue
        _,metric,allowed=max(anchors,key=lambda a:(a[0],a[1]=='entity'))
        if metric in ('delta','change_percent'):
            decreasing=bool(re.search(r'ลดลง|decreased?',context,re.I))
            increasing=bool(re.search(r'เพิ่มขึ้น|increased?',context,re.I))
            if decreasing or increasing:
                signed=-abs(value) if decreasing else abs(value)
                if signed not in allowed:raise ValueError('financial direction mismatch')
                if value not in allowed:variants.add((match.start(),value))
                continue
        if value not in allowed:raise ValueError('financial label mismatch')
    return variants


class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id:int=Field(ge=1,le=6,strict=True)
    facts:list[str]=Field(min_length=1,max_length=20)


class Answer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    intro:str=Field(default='',max_length=500)
    reports:list[Selection]|None=Field(default=None,min_length=1,max_length=6)
    advice:str=Field(default='',max_length=1000)


def tool():
    return dict(type='function',function=dict(name='render_finance',description='Call with {} to show the verified answer, including totals and any requested breakdown. Optional reports selects exact dataset_id and quantity keys for a custom layout. intro/advice are optional and contain no numbers, URLs or claims of writes.',parameters=Answer.model_json_schema()))


LABELS={'income':'รายรับ','expense':'รายจ่าย','assets':'สินทรัพย์','liabilities':'หนี้สิน','net':'ยอดสุทธิ',
    'amount':'ยอดรวม','count':'จำนวนรายการ','planned':'งบที่ตั้ง','spent':'ใช้ไปจากงบ','remaining':'งบคงเหลือ',
    'daily_average':'เฉลี่ยต่อวัน','transaction_average':'เฉลี่ยต่อรายการ','previous_amount':'ยอดช่วงก่อนหน้า',
    'highest_amount':'ยอดสูงสุด','lowest_amount':'ยอดต่ำสุด'}


def render(job,raw):
    from .assistant_data import identity,quantity
    from .ai_fence import Invalidated
    from .semantic_assistant import general_reply
    from .assistant_evidence import UNVERIFIED,NO_WRITE,clean
    from .assistant_contract import claims_review
    data=getattr(job,'_direct_evidence',None)
    if not data or data['actor']!=identity(job):raise Invalidated('membership_revoked')
    answer=Answer.model_validate_json(raw);lines=[]
    for prose in (answer.intro,answer.advice):
        if claims_review(prose) or re.search(r'\d|[๐-๙]|https?://',prose) or general_reply(prose) in (UNVERIFIED,NO_WRITE):raise ValueError('unverified commentary')
    if answer.reports is None:
        from .assistant_data import fallback
        if not any(d.get('purpose','answer')=='answer' for d in data['datasets']):raise ValueError('missing answering scope')
        return '\n\n'.join(part for part in (answer.intro,fallback(job),answer.advice) if part)[:16000]
    selected=[data['datasets'][r.dataset_id-1] for r in answer.reports if r.dataset_id<=len(data['datasets'])]
    if not any(d.get('purpose','answer')=='answer' for d in selected):raise ValueError('missing answering scope')
    if answer.intro:lines.append(answer.intro)
    for selection in answer.reports:
        if selection.dataset_id>len(data['datasets']):raise ValueError('unknown dataset')
        dataset=data['datasets'][selection.dataset_id-1];facts=dataset['facts']
        primary={'net'} if 'net' in facts else {'amount'} if 'amount' in facts else {'income','expense','planned','spent','remaining'}
        if primary.intersection(facts) and not primary.intersection(selection.facts):raise ValueError('missing requested total')
        lines.append(dataset['scope'])
        for key in dict.fromkeys(selection.facts):
            if key not in facts or not quantity(key):raise ValueError('unknown quantity')
            label=LABELS.get(key)
            if key in ('delta','change_percent'):
                n=numeric(facts[key]);label=('ลดลง' if n<0 else 'เพิ่มขึ้น' if n>0 else 'เปลี่ยนแปลง')+(' (%)' if key=='change_percent' else '')
                value=str(facts[key]).lstrip('-+')
            else:
                value=str(facts[key])
                if label is None:
                    prefix=key.rsplit('_',1)[0]
                    # balance_satang has a two-part suffix.
                    if key.endswith('_balance_satang'):prefix=key.removesuffix('_balance_satang')
                    label=str(facts.get(prefix+'_name') or facts.get(prefix+'_description') or facts.get(prefix+'_period') or key)
                    for suffix,title in (('_assets_satang','สินทรัพย์'),('_liabilities_satang','หนี้สิน'),('_net_satang','ยอดสุทธิ')):
                        if key.endswith(suffix):label=title
                    for suffix,title in (('_target','เป้าหมาย'),('_saved','ออมแล้ว'),('_remaining','คงเหลือ')):
                        if key.endswith(suffix):label+=' · '+title
                    if facts.get(prefix+'_date'):label+=' · '+str(facts[prefix+'_date'])
            lines.append('- '+clean(label)+': **'+clean(value)+'**')
    if answer.advice:lines.append(answer.advice)
    result='\n\n'.join(lines)
    if len(result)>16000:raise ValueError('answer too large')
    return result
