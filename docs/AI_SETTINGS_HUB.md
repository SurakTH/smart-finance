# AI settings hub

The owner settings page now has five panels, with Models selected by default:
Models/routes, Connections, Usage/budget, My memory and AI Lab. Models has a
separate Chat/text-receipt task selector. The active panel is encoded as the
`section` query parameter, supports browser back/forward and keyboard arrows,
and resets in the usual workspace-keyed component lifecycle. On mobile the five
panel tabs scroll horizontally without widening the document.

Panels load their data on first visit. Previously visited forms stay mounted and
hidden, so switching panels does not discard unsaved memory or budget edits.
Personal memory reads only preferences/accounts, while the usage panel reads
workspace usage/providers. Members retain access to their own memory and never
receive owner configuration, usage or lab controls through this page.

Model cards display the current routing role (primary/backup, disabled or blocked
by workspace Cloud policy), selected output/Thinking/Temperature and image ability.
Timeout/retry details are collapsed; secondary discovery, duplicate and delete
operations live in the more menu. Duplicating copies settings, never an API key.
The separate Connections view exposes configured destinations and whether an
encrypted key exists, never the key itself.

Tests are explicit user actions: Test or Save and test. Saving does not otherwise
invoke a provider. Save and test persists the settings first; a failed probe does
not roll back or hide a successful settings save. Probe results carry the time in
Asia/Bangkok and are labelled as results for the current page session. Reloading
starts with no in-session probe result; no persisted health claim is fabricated.
Visiting models, memory, usage or lab never automatically starts an AI generation.

## Shared connections and model profiles

Connections now own workspace-scoped destinations and encrypted credentials.
Multiple Provider profiles can reference one connection across Chat and Extract,
while retaining their existing IDs, routing order, parameters and usage history.
Legacy per-model connection settings remain compatible. The migration preserves
old connections separately rather than merging secrets based on a matching URL.

Probe history remains session-only; persistent health history tied to configuration
versions is still pending. A connection edit must not be interpreted as a fresh
successful probe of every linked model.

Validation includes the existing settings/model tuning, owner/member personalization
and lab regressions, plus panel boundaries, retained drafts, reload navigation,
current routing status, no implicit AI calls and save-and-test success/failure.

## การเชื่อมต่อร่วมหลายโมเดล (20 ตุลาคม 2026)

แท็บ **การเชื่อมต่อ → เพิ่มการเชื่อมต่อ** เก็บชื่อ บริการ Base URL และคีย์ครั้งเดียว จากนั้นกด **เพิ่มโมเดลจากการเชื่อมต่อนี้** เพื่อกำหนดโมเดล งานแชท/อ่านสลิป และพารามิเตอร์แต่ละตัวได้ โมเดลใช้ connection เดียวกันได้ทั้งสองงาน ยังแยกลำดับ fallback และค่า Thinking/Temperature/จำนวน token/timeout/retry ตาม profile เดิม

แก้คีย์หรือปลายทางครั้งเดียวมีผลกับทุกโมเดลที่ผูกอยู่ หากเปลี่ยนบริการ/URL โดยไม่ส่งคีย์ใหม่ ระบบล้างคีย์เดิมเพื่อไม่ให้ตามไปปลายทางใหม่ และล้างราคาที่ตั้งไว้สำหรับโมเดลที่ได้รับผลกระทบ ต้องตั้งราคาใหม่หากต้องการใช้วงเงิน Cloud ส่วนการหมุนคีย์ในปลายทางเดิมเก็บราคาเดิมได้ คีย์เป็น ciphertext ฝั่ง backend และไม่คืนใน API

โมเดลเลือก connection ด้วย ID ที่ตรวจ workspace ใน backend และมี composite foreign key กันการผูกข้ามพื้นที่ เฉพาะเจ้าของพื้นที่สร้าง/แก้/ลบ connection ได้ ลบ connection ที่ยังมีโมเดลใช้อยู่ไม่ได้ แต่ลบโมเดลไม่ลบ connection ที่แชร์อยู่

Migration `connections_and_imports` ย้าย endpoint/key ของแต่ละโมเดลเดิมเป็น connection แยกโดยคง ciphertext เดิม ไม่รวมคีย์ตาม URL โดยพลการและไม่ต้องกรอกคีย์ใหม่ หลังอัปเกรดเลือกให้โมเดลต่าง ๆ ใช้ connection เดียว แล้วลบ connection ที่ไม่ใช้ได้ การตั้งค่าเฉพาะโมเดลแบบเก่ายังรองรับเพื่อความเข้ากันได้

ผลทดสอบ connection ยังเป็นผลเฉพาะรอบเปิดหน้านี้ ไม่ใช่ประวัติ health ถาวร และไม่มี API call อัตโนมัติเมื่อเปิดหน้า

การเปลี่ยนคีย์ร่วมอย่างเดียวเพิ่ม workspace AI epoch ด้วย เพื่อให้งาน AI ที่ยังรอคำตอบตรวจพบว่าการตั้งค่าเปลี่ยนและไม่ใช้บริบทเก่าต่อเหมือนไม่มีการเปลี่ยนแปลง
