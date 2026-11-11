"""Reject text-only draft amounts when the model has no possible user source.

This is a negative evidence check, not a money parser. Finding a number does not
authorize, extract, or prove any amount. Receipt and ledger tools retain their
own evidence and scoping rules.
"""
import re

from sqlalchemy import select

from .models import Message

_POSSIBLE_NUMBER = re.compile(
    r'\d|หนึ่ง|นึง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ร้อย|พัน|หมื่น|แสน|ล้าน|ครึ่ง'
    r'|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen'
    r'|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy'
    r'|eighty|ninety|hundred|thousand|million|half|dozen)\b', re.I
)


def has_read_amount(job):
    from .assistant_data import quantity
    evidence = getattr(job, '_direct_evidence', None) or {}
    for dataset in evidence.get('datasets', []):
        if any(quantity(key) and str(value).endswith(' บาท')
               for key,value in dataset.get('facts', {}).items()):
            return True
    for (tool,_), result in (getattr(job, '_read_cache', None) or {}).items():
        if tool != 'query_finance' or result.get('source') != 'ledger_backend':
            continue
        if any(type(result.get(key)) is int for key in ('income','expense')):
            return True
        if any(type(item.get('amount')) is int for item in result.get('items', [])):
            return True
    return False


def without_unsourced_amounts(db, room, job, draft):
    items = draft.transactions if draft.transactions is not None else [draft]
    if (draft.intent == 'chat' or not any(item.amount is not None for item in items)
        or job.payload.get('attachment_id') or draft.attachment_id
        or any(item.attachment_id for item in items)
        or has_read_amount(job)):
        return draft
    if draft.continue_draft:
        from .chat_dialogue import continuing
        try:
            merged = continuing(db, room, job.user_id, draft)
        except ValueError:
            return draft
        if merged.attachment_id:
            return draft
    # Only authenticated user messages in the current room, not system examples,
    # model replies, account names or prompt-injected tool payloads.
    texts = db.scalars(select(Message.content).where(
        Message.workspace_id == room.workspace_id, Message.conversation_id == room.id,
        Message.role == 'user',
    ).order_by(Message.created_at.desc(), Message.id.desc()).limit(12))
    if any(_POSSIBLE_NUMBER.search(text) for text in texts):
        return draft
    if draft.transactions is not None:
        return draft.model_copy(update={'transactions':[
            item.model_copy(update={'amount':None}) for item in items
        ]})
    return draft.model_copy(update={'amount':None})
