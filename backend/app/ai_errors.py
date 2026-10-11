"""Static, actionable diagnostics. Never return raw URLs, keys or upstream text."""
import json
import httpx

MESSAGES={
 'connection':'เชื่อมต่อเครื่อง AI ไม่ได้ ตรวจ IP พอร์ต firewall และให้ Ollama รับการเชื่อมต่อจากเครือข่าย; localhost ใน URL หมายถึง container Smart Finance',
 'dns':'แปลงชื่อหรือใช้ปลายทางไม่ได้ ตรวจ URL/DNS จากเครื่อง Smart Finance และใช้ปลายทางที่อนุญาต',
 'timeout':'รอคำตอบนานเกิน Timeout ที่ตั้งไว้ Ollama อาจกำลังโหลดโมเดล ลองเพิ่ม Timeout หรืออุ่นโมเดลก่อนทดสอบใหม่',
 'model_missing':'เชื่อมต่อ API ได้ แต่ไม่พบโมเดลนี้บนเครื่องปลายทาง กดโหลดโมเดลแล้วเลือกชื่อพร้อม tag ให้ตรง หรือดาวน์โหลดโมเดลบนเครื่อง Ollama ก่อน',
 'tools_unsupported':'โมเดลนี้ไม่รองรับ tools ที่ผู้ช่วยต้องใช้ กรุณาเลือกโมเดลที่รองรับ tools',
 'images_unsupported':'โมเดลนี้ไม่รองรับรูป ปิดรับรูปภาพหรือเลือกโมเดล vision',
 'thinking_unsupported':'โมเดลไม่รองรับระดับ Thinking นี้ ลองเลือกค่าเริ่มต้นของโมเดลใน Settings',
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
    def __init__(self,code):self.code=code;super().__init__(code)

def message(code):return MESSAGES.get(code,MESSAGES['processing_failed'])

def http_code(status,raw):
    text=''
    try:
        data=json.loads(raw);error=data.get('error','')
        if isinstance(error,dict):error=error.get('message','')
        if isinstance(error,str):text=error[:2048].casefold()
    except (ValueError,TypeError,AttributeError):pass
    if status in (401,403):return 'authentication'
    if 'model' in text and any(w in text for w in ('not found','does not exist','not exist')):return 'model_missing'
    unsupported=any(w in text for w in ('not support','unsupported','does not support'))
    if 'tool' in text and unsupported:return 'tools_unsupported'
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
    raise AIRequestError(http_code(response.status_code,raw))

def diagnose(error):
    if isinstance(error,AIRequestError):return error.code
    if isinstance(error,httpx.ConnectError):return 'connection'
    if isinstance(error,httpx.TimeoutException):return 'timeout'
    from .ai_usage import BudgetExceeded
    if isinstance(error,BudgetExceeded):return 'budget'
    return 'invalid_response'
