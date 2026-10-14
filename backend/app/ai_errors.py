"""Static, actionable diagnostics. Never return raw URLs, keys or upstream text."""
import json
import httpx

MESSAGES={
 'context_changed':'ข้อมูลในพื้นที่นี้เปลี่ยนระหว่างรอ AI จึงไม่ใช้คำตอบหรือร่างเก่า กรุณาส่งคำขออีกครั้ง',
 'membership_revoked':'สิทธิ์หรือสถานะพื้นที่เปลี่ยนแล้ว จึงยกเลิกคำตอบนี้',
 'output_limit':'คำตอบถูกตัดเพราะถึงเพดาน output tokens เพิ่มเพดานในการตั้งค่าโมเดล หรือลด Thinking แล้วลองใหม่ ยังไม่ได้บันทึกข้อมูล',
 'turn_limit':'คำขอนี้ใช้จำนวนรอบ AI ถึงขอบเขตแล้ว กรุณาแบ่งงานเป็นคำขอเล็กลง ยังไม่ได้บันทึกข้อมูล',
 'connection':'เชื่อมต่อเครื่อง AI ไม่ได้ ตรวจ IP พอร์ต firewall และให้ Ollama รับการเชื่อมต่อจากเครือข่าย; localhost ใน URL หมายถึง container Smart Finance',
 'dns':'แปลงชื่อหรือใช้ปลายทางไม่ได้ ตรวจ URL/DNS จากเครื่อง Smart Finance และใช้ปลายทางที่อนุญาต',
 'timeout':'รอคำตอบนานเกิน Timeout ที่ตั้งไว้ Ollama อาจกำลังโหลดโมเดล ลองเพิ่ม Timeout หรืออุ่นโมเดลก่อนทดสอบใหม่',
 'model_missing':'เชื่อมต่อ API ได้ แต่ไม่พบโมเดลนี้บนเครื่องปลายทาง กดโหลดโมเดลแล้วเลือกชื่อพร้อม tag ให้ตรง หรือดาวน์โหลดโมเดลบนเครื่อง Ollama ก่อน',
 'tools_unsupported':'โมเดลนี้ไม่รองรับ tools ที่ผู้ช่วยต้องใช้ กรุณาเลือกโมเดลที่รองรับ tools',
 'images_unsupported':'โมเดลนี้ไม่รองรับรูป ปิดรับรูปภาพหรือเลือกโมเดล vision',
 'thinking_unsupported':'โมเดลไม่รองรับระดับ Thinking นี้ ลองเลือกค่าเริ่มต้นของโมเดลใน Settings',
 'thinking_history':'แอปส่งบริบท Thinking สำหรับการใช้เครื่องมือไม่ครบ จึงคุยต่อกับโมเดลไม่สำเร็จ',
 'tool_history':'รูปแบบบทสนทนาเครื่องมือที่แอปส่งไปไม่ถูกต้อง จึงคุยต่อกับโมเดลไม่สำเร็จ',
 'message_order':'แอปส่งลำดับข้อความระบบที่ปลายทางไม่รองรับ จึงคุยต่อกับโมเดลไม่สำเร็จ',
 'authentication':'API ปฏิเสธสิทธิ์ ตรวจ API key หรือสิทธิ์ที่ proxy หน้า Ollama',
 'api_path':'ไม่พบเส้นทาง API ตรวจ Base URL ให้เป็น OpenAI-compatible เช่น http://IP:11434/v1 ไม่ใช่ /api หรือ /chat/completions',
 'rate_limited':'API จำกัดจำนวนคำขอหรือทรัพยากรชั่วคราว กรุณารอสักครู่แล้วลองใหม่',
 'upstream':'เซิร์ฟเวอร์ AI ตอบผิดพลาด ตรวจว่าโมเดลโหลดได้และ RAM/VRAM พอบนเครื่อง Ollama',
 'redirect':'URL ตอบกลับเป็นการเปลี่ยนเส้นทาง กรุณาใส่ Base URL ปลายทางโดยตรง',
 'invalid_request':'API ปฏิเสธรูปแบบคำขอ ตรวจชื่อโมเดล Thinking และความสามารถรับ tools/รูปภาพ',
 'invalid_response':'API ส่งคำตอบที่อ่านไม่ได้หรือว่าง หากเปิด Thinking ลองเพิ่มเพดาน tokens และตรวจว่า URL เป็น OpenAI-compatible',
 'key_invalid':'อ่าน API key ที่เก็บไว้ไม่ได้ กรุณากรอกคีย์ใหม่ หรือล้างคีย์หาก Ollama ไม่ต้องใช้',
 'budget':'วงเงิน AI ไม่พอหรือยังไม่ได้ตั้งราคาครบ ตรวจตั้งค่า AI → การใช้งานและงบ',
 'processing_failed':'เตรียมคำตอบไม่สำเร็จ กรุณาลองส่งข้อความอีกครั้ง',
}
class AIRequestError(ValueError):
    def __init__(self,code,http_status=None,field=None):
        self.code=code;self.http_status=http_status;self.field=field;super().__init__(code)

FIELDS=('reasoning_content','reasoning_details','reasoning_effort','tool_call_id','tool_calls','max_completion_tokens','max_tokens','tool_choice','tools','messages','model','stream')

def metadata(error):
    return {**({'http_status':error.http_status} if isinstance(error,AIRequestError) and type(error.http_status) is int else {}),
            **({'field':error.field} if isinstance(error,AIRequestError) and error.field in FIELDS else {})}

def message(code):return MESSAGES.get(code,MESSAGES['processing_failed'])

def http_code(status,raw):
    text=''
    try:
        data=json.loads(raw);error=data.get('error','')
        if isinstance(error,dict):error=error.get('message','')
        if isinstance(error,str):text=error[:2048].casefold()
    except (ValueError,TypeError,AttributeError):pass
    if status in (401,403):return 'authentication'
    if status in (400,422) and 'system' in text and any(w in text for w in ('beginning','first message','start of','position')):return 'message_order'
    if 'model' in text and any(w in text for w in ('not found','does not exist','not exist')):return 'model_missing'
    unsupported=any(w in text for w in ('not support','unsupported','does not support'))
    if 'tool' in text and unsupported:return 'tools_unsupported'
    if status in (400,422) and any(w in text for w in ('missing','required','must include','must contain','cannot be empty')):
        if any(w in text for w in ('reasoning_content','reasoning_details')):return 'thinking_history'
        if any(w in text for w in ('tool_call','tool message','tool role')):return 'tool_history'
    if any(w in text for w in ('image','vision')) and unsupported:return 'images_unsupported'
    if any(w in text for w in ('reasoning','thinking','think')) and (unsupported or 'invalid' in text):return 'thinking_unsupported'
    if status==404:return 'api_path'
    if status==429:return 'rate_limited'
    if status>=500:return 'upstream'
    if 300<=status<400:return 'redirect'
    return 'invalid_request'

def ensure_response(response):
    if 200<=response.status_code<300:return
    raw=b''
    for chunk in response.iter_bytes():
        raw+=chunk[:max(0,8192-len(raw))]
        if len(raw)>=8192:break
    field=None
    try:
        error=json.loads(raw).get('error',{})
        param=error.get('param','') if isinstance(error,dict) else ''
        if isinstance(param,str):field=next((f for f in FIELDS if f in param),None)
    except (ValueError,TypeError,AttributeError):pass
    raise AIRequestError(http_code(response.status_code,raw),response.status_code,field)

def diagnose(error):
    if isinstance(error,AIRequestError):return error.code
    if isinstance(error,httpx.ConnectError):return 'connection'
    if isinstance(error,httpx.TimeoutException):return 'timeout'
    from .ai_usage import BudgetExceeded
    if isinstance(error,BudgetExceeded):return 'budget'
    return 'invalid_response'
