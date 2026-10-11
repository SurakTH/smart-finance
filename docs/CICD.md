# GitHub CI/CD

วางเนื้อหาโฟลเดอร์ `smart-finance` ที่ root ของ repo (`backend/`, `frontend/`, `.github/` อยู่ที่ root) ไม่อัปโหลด `.env`, artifacts, backups, ฐานข้อมูล, node_modules หรือ .venv

## CI และ images

`.github/workflows/pipeline.yml` ทำงานเมื่อ PR, push main และกด Run workflow:

1. สร้าง secrets ชั่วคราวบน GitHub-hosted Ubuntu runner แล้วเปิด PostgreSQL/Redis/API/worker/web/Nginx ด้วย Docker
2. ทดสอบ deploy helper, PostgreSQL invariants/tenant isolation/migrations, TypeScript และ Next production build
3. สร้างบัญชี demo เฉพาะ runner รัน Playwright desktop/mobile แล้วตรวจ backup/restore ลงฐานชั่วคราว
4. ลบคอนเทนเนอร์/volumes/config/credentials ของ runner ไม่ upload artifacts ที่มีข้อมูลทดสอบ
5. main ที่ผ่านเท่านั้น build และ push `ghcr.io/<owner>/<repo>/backend:<commit-sha>` กับ `.../web:<commit-sha>` โดยใช้ GITHUB_TOKEN ที่มี packages:write เฉพาะ publish job ไม่ใช้ latest ใน production และไม่ส่ง secrets ให้ PR jobs

Private repo ต้องมี GitHub Actions quota และอนุญาต package publishing ในบัญชี/องค์กร อาจมีค่าใช้จ่ายตามแพ็กเกจ ตรวจสิทธิ์ Actions/Packages ก่อนใช้งานจริง CI สร้าง images ใหม่หลังผ่านด้วย source SHA เดียวกัน แต่ base image tags ยังไม่ pin digest จึงยังไม่ใช่ reproducible build แบบ bit-for-bit

## เตรียม Ubuntu ครั้งแรก

CD นี้ใช้สำหรับ **อัปเกรดเซิร์ฟเวอร์ที่ติดตั้งและเปิดใช้งานแล้ว** ไม่ติดตั้ง Docker/Nginx/HTTPS/ฐานข้อมูลให้ครั้งแรก:

- ติดตั้ง Docker + Compose และให้ SSH deploy user เรียก Docker ได้ (สิทธิ์ Docker เทียบเท่า root จึงใช้บัญชีที่ควบคุมไว้)
- สร้าง `/opt/smart-finance/releases` และ `/opt/smart-finance/backups` ให้ deploy user เขียนได้
- เก็บ `.env` จริงไว้ `/opt/smart-finance/.env` permission 0600 พร้อม APP_ORIGIN=https://โดเมนจริง, COOKIE_SECURE=true, BIND_ADDRESS=127.0.0.1 และ secrets เดิม **ห้ามสร้าง ENCRYPTION_KEY/POSTGRES_PASSWORD ใหม่เวลา deploy**
- เปิด stack ชื่อ Compose `smart-finance` ตามคู่มือเดิม ให้ postgres/api/web ทำงานและมีฐานข้อมูลที่ migrate แล้ว ใช้ volumes เดิมได้
- Nginx เดิมรับ HTTPS และ proxy ไป localhost:8080 ตาม NGINX.md
- SSH user ต้องเข้าถึง GHCR private images ได้ โดย docker login ghcr.io ด้วย credential ที่มี read:packages บนเซิร์ฟเวอร์ ผ่าน --password-stdin ด้วยตัวเอง ไม่ส่ง credential นี้เข้า workflow
- Runner ต้องเข้าถึง SSH host ได้ หากเซิร์ฟเวอร์เป็น private LAN/Hyper-V ที่ไม่มีเส้นทางจาก GitHub-hosted runner ต้องเตรียม tunnel/VPN หรือ deployment runner ที่ไว้ใจได้ก่อน ไม่ควรรัน PR ที่ไม่ไว้ใจบน production runner

## ตั้ง GitHub Environment และ Secrets

สร้าง environment ชื่อ `production` และจำกัด deployment branches ให้เฉพาะ main ตั้ง required reviewers ถ้าแพ็กเกจรองรับ แล้วใส่ environment secrets:

| Secret | ค่า |
|---|---|
| DEPLOY_HOST | DNS หรือ IPv4 ของ SSH server ไม่มี URL scheme |
| DEPLOY_USER | SSH deploy user |
| DEPLOY_PORT | พอร์ต SSH (เว้นว่างใช้ 22) |
| DEPLOY_SSH_KEY | private SSH key ของ deploy user |
| DEPLOY_KNOWN_HOSTS | known_hosts ที่ตรวจ fingerprint กับเซิร์ฟเวอร์แล้ว รวม [host]:port ถ้าใช้พอร์ตพิเศษ |

ไม่ใช้ StrictHostKeyChecking=no และไม่ใช้ ssh-keyscan จาก runner แล้วเชื่อผลทันที ไม่มี secrets ฐานข้อมูล, SMTP หรือ AI keys ใน GitHub ต้องเก็บอยู่ใน .env เซิร์ฟเวอร์เท่านั้น [วิธีตั้ง Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets), [ตั้ง Environment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## Deploy

Actions → Smart Finance → Run workflow → เลือก main → เปิด deploy → Run ระบบทดสอบ/publish commit ที่เลือกอีกครั้ง แล้วจึงรอ production protection และ SSH deploy:

- ส่งเฉพาะ source จาก git archive ของ commit ที่ทดสอบไป `/opt/smart-finance/releases/<sha>` ไม่มี working files/.env/ข้อมูลทดสอบติดไป
- เชื่อม .env และ backups จาก root, ล็อกไม่ให้ deploy พร้อมกัน, pull images ของ SHA เดียวกัน
- สำรองฐานข้อมูลก่อน migration, หยุด worker เก่า, migrate และเปิด stack จาก images โดยไม่ build บนเซิร์ฟเวอร์
- ตรวจ health ของ API และเว็บ แล้วบันทึก SHA ลง current-commit

GitHub-hosted runner เผยแพร่ images สำหรับ linux/amd64 ตาม Ubuntu Server/Hyper-V ในแผนนี้ ยังไม่มี multi-architecture ARM publish

ไม่มีการ deploy อัตโนมัติทุก push; ไม่มี SSH action จาก third party และไม่แก้ Nginx/ใบรับรองของ host การจัดการ Secrets/Environment และการเชื่อมเซิร์ฟเวอร์จริงต้องตั้งเองก่อน CD ทำงานได้

## ถ้า deploy ล้มเหลว

ระบบไม่ลบ volumes/ฐานข้อมูล/backup ไม่ auto-downgrade schema และไม่ auto-restore เพราะอาจทำให้ข้อมูลที่เพิ่งบันทึกหาย `current-commit` เปลี่ยนเมื่อ health ผ่านเท่านั้น แต่ไม่ใช่ตัวจัดการ traffic หรือ atomic rollout หาก migrate/health ล้มเหลวให้ตรวจ stack และเลือกกลับ images เดิมเฉพาะเมื่อ schema compatible หรือ restore backup ตามแผน downtime ที่ตรวจแล้ว อาจมี downtime ระหว่างอัปเกรด ยังไม่ใช่ blue/green deployment

แนะนำ branch protection ให้ main ต้องผ่าน verify ก่อน merge และใช้ Dependabot ที่แนบมาเพื่อติดตาม Actions updates
