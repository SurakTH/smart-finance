# AI Chat audit — 14 ตุลาคม 2026

ฐานโค้ด: `e528643` (`main`) ตรวจทั้งเว็บและ Telegram, runtime/tools, evidence renderer, context, confirmation, privacy, worker และ delivery ข้อมูลทดสอบทั้งหมดสังเคราะห์ ไม่ใช้สลิป/ประวัติเงินจริงหรือเรียก provider/Telegram จริง ไม่ตรวจ deployment หรือโมเดลบน Ubuntu ของผู้ใช้

> สถานะหลัง audit: F1–F5 ได้รับการแก้ในรอบถัดมา ดู regression tests `test_ai_scope_regressions.py`, migration tests `test_telegram_delivery_migration.py` และผลล่าสุดใน VERIFICATION.md รายงานด้านล่างบันทึกอาการของฐานโค้ด e528643 ก่อนแก้

## คำตัดสิน

ระบบดีขึ้นชัดเจนด้านขอบเขตการเขียนข้อมูล การแยกผู้ใช้/พื้นที่ การยืนยัน และ Telegram ที่ใช้ runtime ร่วมกับเว็บ แต่ยังไม่ควรเรียกว่าเลขาที่เชื่อถือคำตอบการเงินได้ทุกสำนวน พบ **5 ประเด็นจาก 6 กรณีที่ทำซ้ำได้: P1 สองประเด็น, P2 สามประเด็น** ทั้งหมดพิสูจน์ด้วย mock model ที่เลือกเครื่องมือหรือข้อมูลถูกได้ จึงไม่สามารถแก้ด้วยเปลี่ยนโมเดลอย่างเดียว

จุดสำคัญ: ยอดที่มาจาก SQL อาจถูกต้องสำหรับข้อมูลที่ query แต่ผิดคำถามของผู้ใช้ได้ ชั้น evidence ปัจจุบันใช้ regex ตีขอบเขตใหม่แล้วคำนวณรายงานแทนผล tools ทำให้คำตอบที่ดูตรวจสอบแล้วกลับรายงานคนละเดือน/คนละกลุ่มรายการ

## Findings ตามความสำคัญ

### F1 — P1: ขอบเขต “ค่ากาแฟ” หาย กลายเป็นยอดรายจ่ายทั้งหมด

**ตัวอย่าง:** มีรายการกาแฟ 80 บาท และอาหาร 920 บาทในตุลาคม ถาม `กาแฟเดือนนี้ใช้ไปเท่าไหร่` โมเดลเรียก search_transactions ด้วย q=กาแฟ และได้กาแฟเพียงรายการเดียว 8,000 สตางค์ คำตอบสุดท้ายกลับเป็นรายจ่าย **1,000 บาท ทุกบัญชีและทุกหมวด**

**สาเหตุ:** `assistant_evidence.scope()` (บรรทัด 32–64) จับคำว่าเดือนเป็น period แต่ scope รองรับแค่ชื่อบัญชี/หมวดที่ตรงในฐาน ไม่เก็บ description/merchant/q จากคำถาม `grounded()` (85–91) ไม่ใช้ผล search ที่กรองถูกแล้ว แต่เรียก period_summary ใหม่โดยไม่มี q

**ผล:** ตัวเลขถูกสำหรับยอดทั้งพื้นที่ แต่ไม่ตรงสิ่งที่ผู้ใช้ถาม อาจใช้ตัดสินใจทางการเงินผิด การใส่ label ว่าทุกหมวดไม่ได้ทำให้ตอบโจทย์กาแฟถูก

**แนวแก้:** สร้าง structured scope เดียวตั้งแต่การตีความถึงการอ่านและ render มี operation, dates, account/category IDs, q, transaction kind และความมั่นใจ หากกรองครบไม่ได้ให้ถามก่อน ห้าม broaden เป็นรายจ่ายทั้งหมดเงียบ ๆ และห้ามใช้ผล search หน้าเดียวเป็นยอดรวม ต้องเพิ่ม aggregate ที่กรองครบใน SQL

### F2 — P1: เดือนแบบย่อถูกเปลี่ยนเป็นเดือนปัจจุบัน แม้โมเดลเลือกถูก

**ตัวอย่าง:** กันยายน 80 บาท ตุลาคม 900 บาท วันที่อ้างอิง 2026-10-14 ถาม `รายจ่าย ก.ย. 2569 เท่าไหร่` โมเดลเรียก answer_finance_summary โดย month=2026-09 แต่ระบบตอบ **2026-10-01 ถึง 2026-10-31, 900 บาท**

**สาเหตุ:** `finance_chat.resolve_period()` (13–42) ไม่รู้จัก ก.ย. แล้ว fallback เป็นเดือนปัจจุบัน ฝั่ง `assistant_runtime.converse()` (78–90) parse arguments ของ summary แต่ไม่ใช้ report/month ใน production เลือก evidence.grounded จาก regex scope แทน ต่างจาก sandbox.summary ที่ใช้ arguments นั้นจริง

**ผล:** โมเดล/tool call ถูกต้องก็ยังตอบเดือนผิด และผลผ่านใน AI Lab ไม่ครอบคลุมการ resolve scope จริงของ production

**แนวแก้:** ไม่ fallback เป็นเดือนนี้หากข้อความระบุช่วงที่ยังตีความไม่ได้ รองรับชื่อเดือนเต็ม/ย่อและ พ.ศ.; ตรวจ structured model scope กับข้อความผู้ใช้และใช้ report/month ที่ตรวจแล้วใน renderer เดียวกันกับ production/evaluation

### F3 — P2: เปรียบเทียบเดือนและถามงบถูกปิดกั้น หลังอ่าน tools สำเร็จ

**ตัวอย่าง A:** `เปรียบเทียบรายจ่ายเดือนนี้กับเดือนก่อนให้หน่อย` monthly_analysis ส่งตุลาคม 900 บาทและกันยายน 80 บาทครบแล้ว แต่คำตอบเป็น “ยังไม่มีข้อมูลที่ตรวจสอบได้พอ”

**ตัวอย่าง B:** `งบเดือนนี้เหลือเท่าไหร่` ตั้งงบไว้ 500 บาทและใช้จริง 80 บาท monthly_analysis ส่งงบคงเหลือ 420 บาทครบแล้ว แต่ตอบข้อความปฏิเสธเดียวกัน

**สาเหตุ:** `assistant_evidence.scope()` (36–37) ตั้ง error=True เมื่อพบเปรียบเทียบ/งบเดือน และ `grounded()` (74) คืน UNVERIFIED ทันที ไม่ประเมินข้อมูล tools ที่มีจริง นอกจากนี้สำนวน `เทียบ...กับ...` ซึ่งไม่ตรง regex กลับตกเป็นรายงานเดือนเดียวได้

**ผล:** ฟีเจอร์วิเคราะห์และงบมี tools/backend อยู่ แต่ถูก evidence layer ทำให้ใช้งานไม่ครบ เสียรอบโมเดล/เวลาโดยไม่ได้ใช้ข้อมูลที่อ่านมา

**แนวแก้:** renderer แยกชนิด balances, period total, filtered total, budgets, comparison และ transaction list; คืนตัวเลขจริงพร้อมขอบเขต/หลักฐาน และให้โมเดลช่วยเฉพาะคำอธิบายที่ไม่แต่งตัวเลข การอ่านงบคงเหลือต้องใช้ spend/remaining จาก backend ไม่ใช้แค่ยอดวงเงินของ lookup

### F4 — P2: รายการค้นพบแยกไม่ออก เพราะ renderer ทิ้งวัน บัญชี และหมายเลขเลือก

**ตัวอย่าง:** กาแฟ 80 บาทวันที่ 10 และ 11 ตุลาคม ถาม `ค้นรายการกาแฟ` เครื่องมือคืนสองรายการพร้อมวันที่/บัญชี/number แต่คำตอบคือ `กาแฟ: จำนวนเงิน 80.00 บาท` สองบรรทัดเหมือนกัน ไม่มีวันที่หรือหมายเลข

**สาเหตุ:** `assistant_evidence.grounded()` (98–103) ใช้ generic formatter ที่เก็บเพียง label กับค่าตัวเลข ไม่แสดง occurred_on, accounts, number

**ผล:** ผู้ใช้เลือก “รายการที่ 2” เพื่อแก้ข้อมูลได้ไม่มั่นใจ ต้องเปิดเว็บหรือถามเพิ่ม ทั้งที่ tools มีรายละเอียดครบแล้ว

**แนวแก้:** transaction renderer เฉพาะ แสดงหมายเลขที่ผูกกับผลค้นจริง วันที่ รายละเอียด ยอด และบัญชี พร้อม pagination/selected scope ไม่สร้างหมายเลขใหม่ที่ต่างจาก context

### F5 — P2: ผลยืนยัน Telegram ไม่มี durable delivery

**ตัวอย่าง:** รับร่างกาแฟ 80 บาทสำเร็จ พิมพ์ยืนยัน แล้วจำลอง Telegram ส่งข้อความตอบกลับล้ม ผลคือ ledger บันทึกแล้ว 1 รายการ แต่ไม่มี pending delivery สำหรับข้อความสำเร็จ และ delivery worker ไม่มีอะไรให้ retry

**สาเหตุ:** `telegram_chat.submit()` (64–71) เก็บ synchronous replies แล้วคืน string; `bot.capture()` (72–76) commit transaction ก่อนเรียก message.answer โดยไม่ได้ผ่าน durable outbox ต่างจากคำตอบ AI ที่เป็น job

**ผล:** ผู้ใช้ไม่เห็นใบตอบรับการบันทึก/ทวนแบบ synchronous เมื่อเครือข่ายสะดุด แม้ ledger ถูกต้องและยังกันบันทึกซ้ำได้ ไม่ได้แปลว่าทุกกรณีจะเงียบ แต่ระบบไม่มีคิวรับประกัน retry สำหรับผลนี้

**แนวแก้:** outbox รองรับ synchronous replies โดยอ้าง message ID และแยก delivery ID จาก job ID การสร้างข้อความ/ผลบันทึก/คิวส่งต้องอยู่ transaction เดียวกัน และ confirmation gate ต้องใช้ delivery state เดียวกันทุกเส้นทาง

## สิ่งที่ดีขึ้นและควรรักษา

- Tool ไม่มีสิทธิ์โพสต์ ledger เอง; backend สร้าง ChatAction จริงและให้เจ้าของห้องยืนยัน ตรวจ stale review/duplicate และทำ ledger ใน transaction หลัก
- Tool arguments ไม่เลือก tenant/user; room/worker/outbox ตรวจ workspace และ membership มี final epoch/context/stop fence ก่อนรับคำตอบหรือร่าง
- API key เข้ารหัส backend-only, provider serialization ไม่ส่งคีย์กลับ, HTTP client ไม่ตาม redirect/ไม่ใช้ environment proxy, custom endpoints มี DNS/IP checks ตามนโยบาย local AI
- คำตอบการเงินไม่ปล่อย raw streaming text ที่โมเดลยังไม่ตรวจ; false success/phantom review มี guard และ repair
- จำกัด request/reads/repair, จัดลำดับ provider/fallback, มี accounting/metadata diagnostics ไม่เก็บ prompt/คีย์ใน diagnostic events
- Recent context จำกัด 20 ข้อความ/24,000 ตัวอักษร มี bounded older excerpts และเลือกภาพจำเป็น; ไม่ส่งแชททั้งห้องทุกครั้ง
- Telegram ใช้ runtime/vision/caption/history เดียวกับเว็บ มี /new /reset, cancel old jobs/drafts และ durable delivery สำหรับ AI job results

สิ่งเหล่านี้เป็นข้อสรุปจากโค้ดและชุดทดสอบที่ระบุ ไม่ใช่การรับรองว่าไม่มีช่องโหว่ทั้งหมด

## Context และความเป็นธรรมชาติ

ระบบมี bounded recent history + 8 short user excerpts ไม่ใช่ semantic summary ของประวัติทั้งห้อง รายละเอียดเก่าหรือข้อมูลเกิน 4,000 ตัวอักษรต่อข้อความอาจหาย ไม่ควรโฆษณาว่าจำทุกเรื่องได้ และ text budget ไม่ใช่ tokenizer/context-window cap ทั้ง request เพราะยังมี system/tool schema/tool results/images

ความทื่อส่วนหนึ่งมาจากการตั้งใจไม่ให้โมเดลแต่งตัวเลข แต่ generic renderer/regex scope ปัจจุบันเข้มเกินและเสียรายละเอียด ทางที่เหมาะคือให้ backend รับผิดชอบตัวเลขและขอบเขตอย่างมีชนิด ส่วนโมเดลรับผิดชอบการสนทนา การถามเพิ่ม และคำอธิบาย ไม่จำเป็นต้องคืนอิสระให้โมเดลเขียนยอดจากความจำ

## หลักฐานและการทดสอบ

- Reproductions: `artifacts/ai-audit-2026-10-14/reproduce.py` และ `reproductions.log` จำลอง 6 กรณีครบ **6 observed / 6** คำว่า passed ใน log นี้หมายถึงตรวจพบอาการตาม assertion ไม่ใช่ฟีเจอร์ทำงานถูกต้อง
- วันที่จำลองตรึงที่ 2026-10-14 เพื่อไม่ให้ข้อผิดพลาดเดือนขึ้นกับวันที่รัน
- PostgreSQL disposable แยกจากฐานผู้ใช้; model และ Telegram เป็น mock ไม่ใช้คีย์จริง
- Regression ชุดเดิม **472 passed / 1 deprecation warning**, 74.82 วินาที; `artifacts/ai-audit-2026-10-14/baseline.log` การผ่านทั้งหมดไม่ครอบคลุมอาการที่ repro เพิ่มเติมพบ
- ไม่แก้ application runtime, ไม่ push/deploy ในรอบ audit นี้

รัน reproduction โดยคัดลอกไฟล์ไป `backend/tests/_audit_20261014.py` ชั่วคราว แล้วรัน pytest ใน backend container ที่ mount source พร้อม TEST_DATABASE_URL ชื่อฐานลงท้าย `_test` ตาม test guard ห้ามใช้ฐาน production; ลบไฟล์ชั่วคราวเมื่อจบ

## ลำดับแก้ที่แนะนำ

1. F1/F2 ก่อน: สร้าง typed request scope และบังคับไม่ broaden/date fallback เงียบ ๆ เพิ่ม golden tests ภาษาไทยหลายสำนวน ทั้ง full/abbreviated months, description filters, follow-ups และ model-selected arguments
2. F3/F4: typed evidence renderers ให้ข้อมูลครบและตอบคำถามจริง โดยยังไม่ปล่อยให้โมเดลคำนวณยอดจาก partial lists
3. F5: outbox ร่วมทุกชนิดคำตอบ รวมผลยืนยัน/ทวน/ข้อผิดพลาดที่เกิด synchronous
4. ขยาย AI Lab ให้ทดสอบ scope/render/confirmation เหมือน production มี seeded ledger scenario, หลาย turn และ network-failure cases ไม่วัดแค่เลือก tool/ยอดตัวอย่างถูก
5. หลังแก้ regression แล้วจึงตรวจโมเดลจริงที่ผู้ใช้เลือก ด้วยชุดข้อมูลสังเคราะห์และสลิปที่ผู้ใช้อนุญาต วัดความสำเร็จ/ความถูกต้องของ scope/latency/request count/tokens แยกจากคะแนน safety ไม่ใช้จำนวน tests เป็นคะแนนคุณภาพเลขา

## ผลหลังแก้

F1–F5 แก้แล้วและ regression ทั้งชุดผ่าน 495 ข้อ (เพิ่ม23ข้อ); Docker backend/worker/migrate ผ่าน ดู VERIFICATION.md โค้ดยังไม่ได้รับรองทุกสำนวนหรือโมเดลจริง ชุดนี้ไม่ได้เปิดใช้ auto-post และยังต้องยืนยันทุกการเปลี่ยนข้อมูล
