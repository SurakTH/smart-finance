# Smart Finance

**ดูแลเงินของคุณ พร้อมผู้ช่วย AI บนเซิร์ฟเวอร์ของคุณเอง**

[![Smart Finance CI](https://github.com/SurakTH/smart-finance/actions/workflows/pipeline.yml/badge.svg)](https://github.com/SurakTH/smart-finance/actions/workflows/pipeline.yml)

Smart Finance เป็นเว็บจัดการรายรับรายจ่ายแบบ self-hosted ภาษาไทย สำหรับใช้คนเดียวหรือร่วมกันใน workspace มีภาพรวมการเงิน เครื่องมือวิเคราะห์ และผู้ช่วย AI ที่รับข้อความกับรูปสลิปได้ทั้งบนเว็บและ Telegram

หน้าตาโทนสว่างขาวนวล–เขียวอ่อน รองรับคอมพิวเตอร์และมือถือ เริ่มทดลองได้โดยไม่ต้องมี API key แล้วค่อยเชื่อมโมเดลที่ต้องการภายหลัง

[เริ่มใช้งาน](#เริ่มใช้งาน) · [การติดตั้งและอัปเดต](#การติดตั้งและอัปเดต) · [เอกสาร](#เอกสาร) · [สถานะและข้อจำกัด](#สถานะและข้อจำกัด)

## ทำอะไรได้บ้าง

- **บันทึกเงินอย่างเป็นระบบ** — รายรับ รายจ่าย ยอดตั้งต้น โอนระหว่างบัญชี และจ่ายบัตรเครดิต ใช้ double-entry ledger พร้อมการแก้ไข/ยกเลิกแบบเก็บประวัติ
- **ดูภาพรวมได้โดยไม่ต้องไล่รายการ** — Dashboard รายเดือน หน้าวิเคราะห์ช่วงวันที่ เปรียบเทียบช่วง แนวโน้ม อันดับหมวดและบัญชี พร้อมเปิดรายการต้นทางและส่งออก CSV
- **นำเข้า statement / CSV** — จับคู่คอลัมน์ วันที่และหมวด ตรวจรายการอาจซ้ำ แล้วทวนและยืนยันทั้งชุด ไม่ใช้ token AI
- **วางแผนการเงิน** — งบประมาณ เป้าหมายออม และรายการประจำที่สร้างเป็นร่างรอยืนยัน
- **คุยกับผู้ช่วย AI** — ถามข้อมูลการเงิน เตรียมหรือแก้รายการ ส่งรูปพร้อมคำอธิบาย เก็บประวัติ ค้นหาบทสนทนา และเลือกแชทชั่วคราวได้
- **จัดการสลิปใน AI Inbox** — แนบ วาง หรือลากรูปพร้อมข้อความ ตรวจและแก้ร่างก่อนบันทึก มีการตรวจรูปซ้ำ
- **เลือก AI ได้เอง** — Ollama, Gemini, OpenRouter, Groq และ OpenAI-compatible API ตั้งการเชื่อมต่อครั้งเดียวใช้ร่วมหลายโมเดล แยกลำดับตามงาน พร้อม fallback, timeout/retry, Thinking และงบคำตอบตามความสามารถของ provider
- **แยกพื้นที่และผู้ใช้งาน** — workspace ส่วนตัวหรือพื้นที่ร่วม พร้อมสมาชิก คำเชิญ และการตรวจสิทธิ์ฝั่ง backend
- **ใช้ผ่าน Telegram และ PWA** — เชื่อมบอตเพื่อคุย/ส่งสลิป ติดตั้งเว็บเป็นแอป และเลือกเก็บ snapshot กับร่างออฟไลน์แบบเข้ารหัสได้

## AI ทำงานกับข้อมูลอย่างไร

AI เลือกเครื่องมือเพื่ออ่านข้อมูลตามงาน ส่วน backend ตรวจสิทธิ์และคำนวณตัวเลขจากข้อมูลการเงิน การสร้างหรือแก้ข้อมูลต้องมีร่างให้ตรวจและ **ยืนยันก่อนบันทึก** ข้อความจากโมเดลไม่ใช่คำอนุมัติลงบัญชี

API keys เก็บแบบเข้ารหัสฝั่ง backend ตั้งค่าโมเดลผ่านหน้า **ศูนย์ตั้งค่า AI** ได้ รองรับการใช้ Ollama ในเครือข่ายของคุณ และมีสวิตช์อนุญาต Cloud AI ระดับ workspace การส่งผ่าน Telegram จะผ่านบริการ Telegram ด้วย

อ่านรายละเอียดที่ [คู่มือผู้ช่วย AI](docs/AI_ASSISTANT.md), [AI runtime](docs/AI_RUNTIME.md) และ [การตั้งค่าโมเดล](docs/MODEL_SETTINGS.md)

## เริ่มใช้งาน

ขั้นตอนนี้สำหรับ **ติดตั้งใหม่จาก source** ใช้ Docker Engine, Docker Compose v2.24.4 ขึ้นไป, Git และ Python 3 แนะนำเริ่มที่ 2 vCPU / RAM 4 GB / พื้นที่ว่าง 10 GB โดยไม่รวมพื้นที่และทรัพยากรสำหรับโมเดล Ollama

```bash
git clone https://github.com/SurakTH/smart-finance.git
cd smart-finance
python3 scripts/configure.py
docker compose up -d --build
docker compose exec api python -m app.bootstrap
```

Repository แบบ private ต้องมีสิทธิ์เข้าถึงก่อน clone คำสั่ง configure สร้าง `.env` พร้อม secrets สุ่มและไม่เขียนทับไฟล์เดิม ส่วน bootstrap ให้ตั้งอีเมลกับรหัสผ่านของคุณเองและสร้าง workspace ส่วนตัว ไม่มีรหัสผ่านเริ่มต้นตายตัว

เปิด [http://localhost:8080](http://localhost:8080) หากติดตั้งบนเครื่องเดียวกับเบราว์เซอร์ ค่าเริ่มต้นเปิดเฉพาะ loopback ของเซิร์ฟเวอร์ หากอยู่บน Ubuntu VM ให้เปิด tunnel จากเครื่องที่ใช้งาน แล้วเข้า URL เดียวกัน:

```bash
ssh -L 8080:127.0.0.1:8080 USER@SERVER_IP
```

เมื่อเข้าแล้ว เพิ่มบัญชีและยอดตั้งต้น บันทึกรายการแรก แล้วลองดู Dashboard กับหน้าวิเคราะห์ ส่วน AI ตั้งค่าทีหลังได้ที่ **บริการทั้งหมด → ศูนย์ตั้งค่า AI**

## การติดตั้งและอัปเดต

| รูปแบบ | วิธีใช้งาน |
|---|---|
| ติดตั้งใหม่ / พัฒนาในเครื่อง | ใช้ขั้นตอนเริ่มใช้งานด้านบน และไฟล์ [.env.example](.env.example) เป็นรายการค่าที่ตั้งได้ |
| ใช้ Nginx หรือ Nginx Proxy Manager ที่มีอยู่ | ดู [คู่มือ Nginx](docs/NGINX.md) ตั้ง `APP_ORIGIN` ให้ตรงกับ URL จริง และใช้ `COOKIE_SECURE=true` เมื่อให้บริการผ่าน HTTPS |
| ให้ GitHub ทดสอบและ deploy ไป Ubuntu | ดู [คู่มือ CI/CD](docs/CICD.md) รองรับ self-hosted runner, images ตาม commit และสำรองฐานข้อมูลก่อน migrate |

**เครื่องที่ใช้ CI/CD ต้องใช้ release เดียวกับที่ deploy สำเร็จ**: เวอร์ชันอยู่ใน `current-commit` และไฟล์อยู่ใต้ `releases/<commit>/` อย่าสลับไปใช้ `docker compose up -d` หรือ build จาก checkout หลัก เพราะอาจหยิบ image เก่าที่ไม่มี migration ของฐานข้อมูลปัจจุบัน ใช้ไฟล์ Compose overlays และ image tags ของ release นั้นร่วมกันตาม [คู่มือ CI/CD](docs/CICD.md)

สำรองฐานข้อมูลและ `.env` ก่อนอัปเกรด โดยเก็บ `ENCRYPTION_KEY` เดิมไว้สำหรับถอดรหัสข้อมูล อย่าใช้ `docker compose down -v` กับข้อมูลที่ต้องการเก็บ

## เทคโนโลยี

| ส่วน | Stack |
|---|---|
| Web | Next.js, React, TypeScript, Tailwind CSS, Radix UI |
| API | FastAPI, Python, SQLAlchemy, Alembic |
| ข้อมูลและงานเบื้องหลัง | PostgreSQL, Redis, worker |
| Telegram | aiogram |
| Deployment | Docker Compose, Caddy หรือ Nginx, GitHub Actions / GHCR |

โครงสร้างหลัก: `frontend/` สำหรับเว็บ, `backend/` สำหรับ API/worker/bot และ migrations, `scripts/` สำหรับติดตั้ง ทดสอบ สำรองและ deploy, `docs/` สำหรับคู่มือ

## ทดสอบ

รันบนเครื่องพัฒนาหรือสภาพแวดล้อมทดสอบแยกจาก production หลังเปิด stack ตามขั้นตอนติดตั้งใหม่:

```bash
# Backend: ใช้ฐาน PostgreSQL แยกชื่อ finance_test
python3 scripts/test_docker.py

# Frontend: ตรวจ TypeScript และ production build
cd frontend
npm ci
npm run typecheck
npm run build
```

Browser tests ใช้บัญชี demo และข้อมูลสมมติ รันจาก root ของ repository ในสภาพแวดล้อมทดสอบ:

```bash
python3 scripts/seed_demo.py
cd frontend
npm ci
npx playwright install chromium
npx playwright test
```

GitHub Actions ตรวจ backend, migrations, TypeScript, Docker build, browser ทั้งคอม/มือถือ และ backup/restore ก่อน publish images ดูขอบเขตและผลทดสอบที่บันทึกไว้ใน [Verification](docs/VERIFICATION.md)

## เอกสาร

| เรื่อง | คู่มือ |
|---|---|
| โครงสร้างระบบและการแยกข้อมูล | [Architecture](docs/ARCHITECTURE.md) |
| หน้าตาและการใช้งาน | [UI](docs/UI.md) · [วิเคราะห์การเงิน](docs/INSIGHTS.md) |
| ผู้ช่วย AI และบริบทบทสนทนา | [AI Assistant](docs/AI_ASSISTANT.md) · [AI Runtime](docs/AI_RUNTIME.md) |
| ตั้งค่า provider และโมเดล | [AI Settings Hub](docs/AI_SETTINGS_HUB.md) · [Model Settings](docs/MODEL_SETTINGS.md) |
| นำเข้ารายการธนาคาร | [Statement / CSV](docs/STATEMENT_IMPORT.md) |
| สลิปและหน้าแชท | [AI Inbox](docs/AI_INBOX.md) · [Chat UX](docs/CHAT_UX.md) · [โมเดลเล็กและการอ่านสลิป](docs/SMALL_MODELS.md) |
| ติดตั้งผ่าน reverse proxy | [Nginx](docs/NGINX.md) |
| Build, publish และ deploy | [CI/CD](docs/CICD.md) |
| สิ่งที่ทำแล้วและงานถัดไป | [Roadmap](docs/ROADMAP.md) · [Verification](docs/VERIFICATION.md) |
| คู่มือและบันทึกอัปเดตฉบับเดิม | [README เดิม](docs/README_LEGACY.md) — เก็บเป็นข้อมูลอ้างอิงตามช่วงเวลาที่เขียน |

## สถานะและข้อจำกัด

โปรเจกต์กำลังพัฒนา มีแกนการเงินและฟีเจอร์ข้างต้นพร้อมชุดทดสอบ แต่ยังไม่ได้หมายความว่าทุกฟีเจอร์ผ่านการทดสอบกับทุกโมเดลหรือทุกสภาพแวดล้อม

- รองรับ **THB** ในรุ่นนี้ เก็บจำนวนเงินเป็นจำนวนเต็มหน่วยสตางค์
- AI อ่านสลิปและตีความคำสั่งผิดได้ ต้องตรวจยอด วันที่ บัญชี และหมวดก่อนยืนยัน การอ่านรูปไม่ใช่การตรวจว่าสลิปแท้
- คุณภาพคำตอบ ภาพ tools และพารามิเตอร์ขึ้นกับโมเดล/provider การทดสอบอัตโนมัติใช้ข้อมูลสมมติและ mock ในส่วนการเชื่อมต่อ AI
- ออฟไลน์ใช้ snapshot กับร่างที่เลือกเก็บไว้ ไม่รองรับ AI ตอบหรือบันทึก ledger ขณะออฟไลน์
- 2FA และการจัดการอุปกรณ์ยังเป็นงานถัดไป ดูรายละเอียดใน [Roadmap](docs/ROADMAP.md)
