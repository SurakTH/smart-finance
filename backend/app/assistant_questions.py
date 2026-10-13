"""Narrow, fully consumed colloquial read questions; never a fuzzy keyword route.

Only complete date + question grammar qualifies. Any subject, account, number,
write verb, analytics or extra content leaves interpretation to the scoped tools.
"""
import re
from dataclasses import dataclass
from datetime import date,timedelta
from .reporting import month_bounds

WEEKDAYS=['จันทร์','อังคาร','พุธ','พฤหัสบดี','ศุกร์','เสาร์','อาทิตย์']
PATTERN=re.compile(r'วัน(?:พฤหัสบดี|อังคาร|อาทิตย์|จันทร์|ศุกร์|เสาร์|พุธ)(?:ที่ผ่านมา|ที่แล้ว|ก่อน|ที่จะถึง|หน้า)?|(?:สัปดาห์|อาทิตย์)(?:ที่แล้ว|ก่อน|นี้)|เดือน(?:ที่แล้ว|ก่อน|นี้)|เมื่อวาน(?:นี้)?|วันนี้')


def relative_period(text):
    """One explicit relative period only. Bare weekdays require clarification."""
    from .reporting import today
    matches=list(PATTERN.finditer(text))
    if len(matches)!=1:return None
    phrase=matches[0][0];current=today();question=None
    if phrase.startswith('วัน') and phrase!='วันนี้':
        day=next((n for n in WEEKDAYS if phrase.startswith('วัน'+n)),None)
        weekday=WEEKDAYS.index(day)
        if re.search(r'ที่จะถึง|หน้า$',phrase):
            offset=(weekday-current.weekday())%7 or 7;start=end=current+timedelta(days=offset)
        elif re.search(r'ที่ผ่านมา|ที่แล้ว|ก่อน$',phrase):
            offset=(current.weekday()-weekday)%7 or 7;start=end=current-timedelta(days=offset)
        else:
            start=end=None;question=f'หมายถึงวัน{day}วันที่เท่าไรคะ? บอกวันที่ หรือบอกว่า “วัน{day}ที่ผ่านมา” ได้เลยค่ะ'
    elif phrase=='วันนี้':start=end=current
    elif phrase.startswith('เมื่อวาน'):start=end=current-timedelta(days=1)
    elif phrase.startswith('เดือน'):
        day=current if phrase=='เดือนนี้' else current.replace(day=1)-timedelta(days=1)
        start,end=month_bounds(day.strftime('%Y-%m'))
    else:
        start=current-timedelta(days=current.weekday()+7*int(not phrase.endswith('นี้')))
        end=start+timedelta(days=6)
    return dict(phrase=phrase,start=start,end=end,question=question)


@dataclass
class Question:
    text:str
    start:date|None
    end:date|None
    include_items:bool
    question:str|None=None

    def scope(self,db=None,room=None):
        from .assistant_scope import Scope
        result=Scope('period',self.text,start=self.start,end=self.end,
            transaction_kind='expense',include_items=self.include_items,error=bool(self.question))
        if self.question or db is None or room is None:return result
        from .models import Account,now
        from sqlalchemy import select
        period=relative_period(self.text)
        residual=self.text.replace(period['phrase'],' ',1) if period else self.text
        previous=(room.capture_context or {}).get('verified_scope',{})
        if re.search(r'ละ|ล่ะ|แล้ว',residual) and previous.get('kind')=='period' and previous.get('expires',0)>now():
            for field,allowed in [('account',('asset','liability')),('category',('expense',))]:
                identifier=previous.get(field+'_id')
                if identifier:
                    row=db.scalar(select(Account).where(Account.workspace_id==room.workspace_id,Account.id==identifier,Account.kind.in_(allowed)))
                    if row is None:result.error=True
                    else:setattr(result,field,row)
            query=previous.get('q','')
            # Repair only the known legacy filler filter, not financial records
            # or arbitrary description text that happens to resemble grammar.
            if re.fullmatch(r'(?:ละ|ล่ะ)?\s*(?:ใช้|เสีย|จ่าย)ตัง(?:ค์)?',query):query=''
            result.q=query
        return result


def parse(text):
    value=relative_period(text)
    if not value:return None
    # This recovery path targets colloquial reads, not all supported model plans.
    if not re.search(r'ตัง(?:ค์)?|เสียเงิน|มีไรบ้าง|วัน(?:จันทร์|อังคาร|พุธ|พฤหัสบดี|ศุกร์|เสาร์|อาทิตย์)',text):return None
    remaining=text.replace(value['phrase'],' ',1)
    grammar=['เสียตังค์','เสียตัง','ใช้ตังค์','ใช้ตัง','จ่ายตังค์','จ่ายตัง','เสียเงิน','ใช้เงิน','รายจ่าย',
        'กับอะไรบ้าง','กับไรบ้าง','อะไรบ้าง','มีไรบ้าง','มีอะไรบ้าง','ไรบ้าง','เท่าไหร่','เท่าไร',
        'ช่วยดู','ขอดู','อยากรู้','ช่วย','ดู','ไป','ไปกับ','บ้าง','มี','ละ','ล่ะ','แล้ว','หน่อย','ค่ะ','ครับ','นะ','อะ']
    pattern=r'(?:\s|[?？,，:：]|'+'|'.join(re.escape(w) for w in sorted(grammar,key=len,reverse=True))+r')*'
    if not re.fullmatch(pattern,remaining) or not remaining.strip(' ?？,，:：'):return None
    items=bool(re.search(r'อะไรบ้าง|ไรบ้าง',remaining))
    return Question(text,value['start'],value['end'],items,value['question'])



def for_turn(db,room,job):
    """Complete an adjacent, expiring weekday clarification in THIS room only."""
    text=job.payload.get('text','');question=parse(text)
    if question:return question
    qualifier=re.sub(r'(?:ค่ะ|ครับ|นะ|[ ?？])+$','',text.strip())
    if qualifier not in ('ที่ผ่านมา','ที่แล้ว','ที่จะถึง'):return None
    from .models import Message,now
    from sqlalchemy import select
    pending=(room.capture_context or {}).get('weekday_question',{})
    if pending.get('expires',0)<=now() or pending.get('day') not in WEEKDAYS:return None
    recent=db.scalars(select(Message.id).where(Message.workspace_id==room.workspace_id,
        Message.conversation_id==room.id,Message.role=='user').order_by(Message.created_at.desc(),Message.id.desc()).limit(2)).all()
    if len(recent)!=2 or recent[0]!=job.payload.get('user_message_id') or recent[1]!=pending.get('source'):return None
    result=parse('วัน'+pending['day']+qualifier+'ใช้ตังกับไรบ้าง')
    if result:result.text=text
    return result


def remember(room,job,question):
    from .models import now
    context={k:v for k,v in (room.capture_context or {}).items() if k!='weekday_question'}
    if question.question:
        phrase=relative_period(question.text)['phrase']
        day=next(n for n in WEEKDAYS if phrase.startswith('วัน'+n))
        context['weekday_question']=dict(day=day,source=job.payload.get('user_message_id'),expires=now()+900)
    room.capture_context=context
