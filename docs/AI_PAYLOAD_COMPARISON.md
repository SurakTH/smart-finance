# ผลวัด AI payload หลัง audit

Baseline: commit `0feca1b` · branch ทดลอง: `fix/ai-grounding-and-context`

วัดคำสั่งและ schema จาก source ทั้งสองเวอร์ชันด้วย workspace สมมติเดียวกัน ใช้ UTF-8 bytes ไม่ใช่ tokenizer ของ Qwen และไม่ใช่ยอดเรียกเก็บ ไม่มีการเรียก API จริงเพื่อวัดรอบนี้

| องค์ประกอบ | ก่อน | หลัง |
|---|---:|---:|
| System instruction | 7,009 bytes | 4,763 bytes |
| Tools ชุดแรก 4 ตัว | 11,041 bytes | 8,601 bytes |
| รวมสองส่วนคงที่ข้างต้น | 18,050 bytes | 13,364 bytes |
| Tools หลังอ่านยอด (เพิ่ม renderer) | 11,041 bytes | 9,553 bytes |
| งบข้อความประวัติ main agent | 24,000 ตัวอักษร | 12,000 ตัวอักษร |
| ข้อความล่าสุดสูงสุด | 20 | 12 |

ส่วนคงที่เริ่มต้นลด **ประมาณ 26%** หลังเปิด renderer ส่วนคงที่รวม instruction+tools ยังลดประมาณ 21% ไม่ใช่เปอร์เซ็นต์ลด token/ค่าบิลทั้งงาน เพราะยังขึ้นกับ history, ภาพ, ผล tools, reasoning, retries และการ tokenize/caching ของ provider

การเปรียบเทียบเชิงพฤติกรรมใน tests:

- คำถามยอดช่วงหนึ่ง: fetch → render จบใน 2 model calls ยอดจาก SQL และไม่มี financial writes
- เรียก fetch ชุดเดิม 3 ครั้ง: backend aggregate เพียง 1 ครั้ง มี feedback อ้างผลเดิมและหยุด loop โดยไม่มี call สุดท้ายเพิ่มเพื่อแต่งคำตอบ
- หลังอ่านภาพเป็นร่างแล้ว ถามรายจ่ายเมื่อวาน: model calls ของคำถามใหม่ส่งภาพ **0 ครั้ง** และร่างยังมี attachment ID/ยอดเดิม
- ถ้ารายละเอียดภาพยังไม่อยู่ในร่าง: AI โหลดภาพต้นฉบับในห้องเดิมผ่าน toolkit ได้ การอ่านข้ามห้องถูกปฏิเสธ
- หลักฐาน 6 ชุดยังอยู่ครบ การอ่านซ้ำรักษา dataset ID เดิม
- เคสสลับยอดรายรับ/รายจ่ายและยอดระหว่างบัญชีถูกปฏิเสธ; “ลดลง 50 บาท” จาก delta −50 ใช้ได้ แต่ “เพิ่มขึ้น 50” ใช้ไม่ได้

รูปที่ส่งใหม่หรือถูกขออ่านใน turn ยังอาจส่งซ้ำภายใน tool rounds ของ turn นั้น ไม่ได้อ้างว่าค่า image token เป็นศูนย์ทุกกรณี และไม่ได้ลดเพดาน output ที่ผู้ใช้ตั้งเป็น provider default

ก่อน merge ควรทดลองบน preview ด้วยโมเดล/Thinking เดียวกับ production โดยใช้บทสนทนาและข้อมูลสมมติชุดเดียวกัน เก็บจำนวน calls, input/output **ที่ provider รายงาน**, latency, correctness และจำนวน repair แยกจากค่าประมาณ ระบบ production และ main ไม่เปลี่ยนจากการสร้าง PR นี้
