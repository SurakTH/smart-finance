"""A model's prose never establishes a review or authorizes a write."""
import re
from sqlalchemy import select
from .models import ChatAction,Job,Message

REPAIR='ข้อความก่อนหน้ายังไม่ได้สร้างร่างจริง ห้ามอ้างว่ามีรายการรอยืนยันหรือบอกให้พิมพ์ยืนยันด้วยข้อความธรรมดา ถ้าคำขอเดิมของผู้ใช้ต้องการบันทึก/แก้ไขจริง ให้ค้นข้อมูลที่ขาดแล้วเรียก prepare_transaction/prepare_correction/prepare_management_plan ระบบจะสร้างข้อความทวนให้เอง ถ้าผู้ใช้เพียงถามรายงานหรือข้อมูลที่บันทึกอยู่แล้ว ให้ตอบข้อมูลเท่านั้น ห้ามสร้างรายการซ้ำ ถ้าข้อมูลไม่ครบให้ถาม ห้ามเดาจากข้อความของตัวเอง การตอบรอบนี้ยังไม่ใช่การอนุมัติให้บันทึก'
UNPREPARED='ฉันยังสร้างร่างรายการไม่สำเร็จค่ะ จึงยังไม่มีรายการให้ยืนยันและยังไม่ได้บันทึกข้อมูล ลองบอกให้ฉันเตรียมรายการอีกครั้งได้เลยค่ะ'

def claims_review(text):
    text=re.sub(r'```.*?```','',text,flags=re.S)
    plain=re.sub(r'[*_`“”"\'‘’]','',text)
    return bool(re.search(r'(?:พิมพ์|ตอบ|ส่ง)\s*(?:คำว่า\s*)?ยืนยัน|(?:รายการ|แผน|ข้อเสนอ)(?:ที่)?\s*รอ(?:การ)?ยืนยัน|(?:รายการ|แผน|ข้อเสนอ)(?:ที่)?\s*รอ(?:การ)?การยืนยัน',plain))

PARTIAL_REPAIR=(
    'คำตอบที่กำลังจะส่งสัญญาว่าจะทำร่าง แต่ยังไม่มีร่างในระบบ '
    'ถ้าคำขอเดิมให้จดรายการ ให้เรียก prepare_transaction ตอนนี้ด้วยเฉพาะข้อมูลที่ผู้ใช้ให้ '
    'เก็บรายละเอียดและหมวดที่ทราบไว้ เว้น amount ถ้าผู้ใช้ยังไม่บอกยอด ระบบจะถามเฉพาะช่องที่ขาด '
    'ไม่ต้องบังคับถามวันที่ถ้าผู้ใช้ไม่ได้ขอวันที่อื่น และห้ามเดายอดหรือบันทึกเอง'
)


def promises_partial_draft(text):
    plain=re.sub(r'[*_`]', '', re.sub(r'```.*?```','',text,flags=re.S))
    promise=re.search(r'(?:จะ|เดี๋ยว(?:ผม|ฉัน)?)\s*(?:(?:สร้าง|เตรียม|ทำ)\s*ร่าง(?:รายการ)?|ร่าง\s*รายการ)'
                      r'|\b(?:I will|I’ll|I\'ll) (?:create|prepare) (?:a |the )?draft\b',plain,re.I)
    capture_question=(re.search(r'(?:จด|บันทึก)(?:รายการ|ค่า)[^\n.!?]{0,60}ให้(?:เลย|ก่อน)',plain)
                      and re.search(r'(?:ยอด|จำนวนเงิน|ราคา|เงิน)(?:[^\n.!?]{0,16})เท่าไหร่|กี่บาท',plain))
    return bool(promise or capture_question)


def recovery_request(db,c,user_id,text):
    """Recover a legacy phantom review by preparing anew, never by posting prose."""
    if text.strip()!='ยืนยัน':return None
    action=db.scalar(select(ChatAction).where(ChatAction.workspace_id==c.workspace_id,ChatAction.conversation_id==c.id,ChatAction.user_id==user_id,ChatAction.id==(c.capture_context or {}).get('review_action_id')))
    if action:return None
    if db.scalar(select(Job.id).where(Job.workspace_id==c.workspace_id,Job.user_id==user_id,Job.task=='chat',Job.status=='pending',Job.payload['conversation_id'].as_string()==c.id).limit(1)):return None
    rows=db.scalars(select(Message).where(Message.workspace_id==c.workspace_id,Message.conversation_id==c.id).order_by(Message.created_at.desc(),Message.id.desc()).limit(20)).all()
    phantom=False
    for row in rows:
        if row.role=='assistant':phantom=phantom or claims_review(row.content)
        elif row.role=='user' and not row.content.strip().startswith('ยืนยัน'):
            return row if phantom else None
    return None
