# ผลตรวจสอบ Smart Finance

## แก้ browser CI ที่ล้มต่อเนื่อง (12 ตุลาคม 2026)

- ตรวจ log จริงของ GitHub Actions run `38159134253` (commit `078a1b9`): build/backend/types ผ่าน; browser 53 ผ่าน 7 ล้ม ทำให้ publish/deploy ถูกข้าม สาเหตุเริ่มจาก service count เก่า 14 แทน 15 และ test เลือก workspace ใหม่จากข้อก่อนหน้า ซึ่งมีข้อมูลว่างหรือ provider URL จำลอง ก่อนเกิด login failure ต่อเนื่อง
- helper เลือก workspace demo ที่ seed ไว้ชัดเจนก่อนเริ่มแต่ละข้อ; session อยู่ใน memory ตามเดิม ไม่ลด production login throttling; browser timezone Asia/Bangkok และ separate-context tests ใช้ SF_BASE_URL ได้ครบ
- รัน browser suite เต็มบน stack disposable `sf-ci-check` ที่พอร์ต 18080 พร้อม PostgreSQL/Redis/credentials ใหม่ โดยใช้ application images ของ commit เดิม: **60 passed (3.0m)**, desktop 30 และ mobile 30 รวมรายงาน บริการ ยืนยันแชท การตั้งค่า AI สมาชิก และ PWA; TypeScript ผ่านและ deployment helper tests **2 passed**
- ไม่มีการเปลี่ยน application runtime/schema, ไม่เรียกโมเดลจริง, ไม่ deploy Ubuntu; เพิ่มคู่มือ CI อัตโนมัติ + pull บน server ที่ใช้ LAN/Tailscale/Nginx Proxy Manager ใน CICD.md ผลข้างต้นเป็น local replica ส่วนผล run บน GitHub ต้องดูแยกตาม commit


## Ollama หลายเครื่องและ Custom HTTP (11 ตุลาคม 2026)

- Backend PostgreSQL ฐาน disposable ทั้งชุด **364 passed** (Starlette/httpx warningเดิม1รายการ); ชุด AI configuration/secretary/personalizationก่อนรอบรวม **66 passed**
- บันทึก HTTP/HTTPS/LAN/Tailscale/Docker/localhost/IPv6/พอร์ตอื่นผ่านAPIได้ทั้ง Custom API และ Ollama โดยowner; ตรวจ URLและ DNS pin/Host/port/SNI, metadata/link-local/unspecified/multicastยังปิด, named cloud providersยังpublic-only ไม่มีredirect/envproxyและไม่มีkeyในresponse
- จำลอง Ollamaสองเครื่อง: discoveryใช้เครื่องแรก, probeใช้เครื่องสอง, runtimeลองเครื่องสองก่อน503แล้วfallbackเครื่องแรกตามrouteที่ตั้ง แม้ปิดCloud; OllamaURLว่างใช้configเดิม และคีย์ไม่ตามไปเมื่อเปลี่ยนเครื่อง
- TypeScript และ Docker/Next production buildผ่าน (backend `f8e8d95be39f`, web `af5e6b9c0c64`); ไม่ต้องmigration/.envใหม่ หน้าแรกHTTP200หลังเริ่มcontainerครบ
- Chrome **6 passed** desktop3/mobile3: Custom APIแบบHTTPพร้อมพอร์ต, เพิ่ม/แก้/persist OllamaURLในdialog, การจัดลำดับ/คีย์/เปิดปิด, ยืนยันแชทและworkspace default
- รอบรวมแรกหยุดเพราะพื้นที่Dockerเครื่องพัฒนาเต็มระหว่างbuild ไม่ใช่assertionพฤติกรรมฟีเจอร์ คืนพื้นที่เฉพาะcache builderที่ไม่ใช้งาน แล้วรันรวมใหม่ผ่าน ไม่ลบvolume/ข้อมูล สำรองหลังตรวจ `finance-20261011T141507Z.dump` และrestoreลงฐานdisposableผ่าน จำนวนแถว/snapshotsตรงและjournalsสมดุล; archive209ไฟล์ผ่านintegrity/runtime-secret scan
- การเชื่อมต่อใช้ MockTransport ไม่ได้ติดต่อOllamaจริงของผู้ใช้หรือdeploy Ubuntu; ต้องให้URLเข้าถึงจากbackend และใช้ `/v1` ตามAPI OpenAI-compatible รายละเอียดHTTP/เครือข่าย/Cloud switchอยู่ใน AI_ASSISTANT.md


## AI ค้นข้อมูลตามงานและแบ่งหน้า (11 ตุลาคม 2026)

- PostgreSQL disposable database: backend ทั้งชุด **348 passed** (เพิ่ม16เคสจาก332; warning Starlette/httpx เดิม1รายการ) ตรวจ tools→lookup→draft→plainยืนยัน, strict schema, literal wildcard, cursorภายในtenant/filter, ข้อมูลแยกuser/workspace, ยอดbalanceจากledger, เป้า/งบ/รายการประจำ, หน้าถัดไป/หมดอายุ/บริบทที่ไม่เกี่ยวข้อง, cacheและread budget
- เริ่มคุยใน workspace ที่มีบัญชีเพิ่ม120รายการ: system contextไม่รวมชื่อ/ID/ยอดทุกบัญชี และไม่เรียกdashboard/answer_reportล่วงหน้า การแบ่งหน้าบัญชี47รายการและรายการเงิน23รายการได้ครบ ไม่มีซ้ำ รองรับวัน/เวลาซ้ำ
- รายงาน24หมวด/24งบ: ยอดเดือน/เดือนก่อน/งบ/ใช้เกินเท่ารายงานเต็ม รายละเอียดส่งสูงสุด20แถว จำนวนจริง24; แก้งบที่อยู่นอก20แถวทำให้fingerprintเปลี่ยน การทวนแผนอิงการวิเคราะห์ยังปฏิเสธเมื่อledgerเปลี่ยน
- รูปปัจจุบัน/ตอบบัญชีหลังส่งรูปยังเก็บหลักฐานเมื่อทวนและยืนยัน ไม่ส่งรูปย้อนหลังกับคำทักทาย คำถามยอด หรือข้อความสั้นที่ไม่เกี่ยวกับสลิป; รูปfollow-upหมดอายุ15นาที
- Chrome Playwright **16 passed** (desktop8/mobile8): การยืนยัน/แก้รายการ/กันซ้ำ, batch, workspace default, Markdown, streaming, ถามข้อมูลที่ขาด, ประวัติ, personal preferences/evidence/budget และตั้งค่าAI ใช้สาธิต/HTTP mock ตามแต่ละเคส ไม่ใช้API keyจริง
- Docker backend/worker/migrate buildผ่าน (`c3bd7457bb79`), migration `assistant_reads`, webเดิมที่ไม่มีการเปลี่ยน frontendยังใช้งานได้ หน้าแรกHTTP200; ไม่ได้แก้ .env หรือ deploy Ubuntu VM
- สำรองหลังmigration `finance-20261011T140557Z.dump` และกู้คืนลงฐานdisposableผ่าน จำนวนแถว/snapshotsตรงและjournal debit=credit; source archive209ไฟล์ผ่านintegrity/runtime-secret scan
- ขอบเขต: ผลทดสอบนี้ยืนยันความถูกต้อง/ขนาดผลลัพธ์และความปลอดภัย ไม่ใช่benchmarkหลายล้านรายการ ไม่รับรองlatency/token savingsกับproviderจริงหรือคุณภาพการเลือกtools ยังไม่มีprecomputed aggregates, vector search, memory summarization หรือTelegram native tool loopใหม่

## เลขาส่วนตัว: ความจำ ข้อมูลที่ขาด หลักฐานรายงาน และงบ AI (11 ตุลาคม 2026)

- PostgreSQL ฐาน disposable ชุดรวม **332 passed** (เพิ่ม18เคส; 1 Starlette/httpx deprecation warning เดิม) ชุดเฉพาะ personalization/dialogue/natural/configuration **68 passed** ตรวจบัญชีเริ่มต้น/กฎหมวดข้ามห้อง, explicit override, ยอดที่ยังขาด, กฎชนกัน, version conflict, ปิด/ล้าง, ยืนยันความจำไม่ยืนยันเงิน และข้อมูลแยก user+workspace จริง
- ความจำผ่านข้อความ authenticated “จำไว้ว่า…” ทวนและรอ plain ยืนยัน มี expiry/latest review/version checks ไม่รับ memory tool หรือคำสั่งจากรูป ข้อเสนอจำยกเลิกร่างเงินเดิมเพื่อป้องกัน confirmation ข้ามชนิด เพิ่ม membership composite FK + cascade ล้างความชอบเมื่อออกจากพื้นที่
- รายงาน deterministic และ query_finance แนบหลักฐานแบบ structured จาก ledger จริง เก็บพร้อมประวัติและpagination เปิด transaction explorer พร้อมช่วงวัน/บัญชี/หมวด/entry ID โดยไม่รับURLจากโมเดล ปลายทางตรวจ tenant เดิม
- นับทุก POST โมเดลใน engine/probe รวม tool rounds/retry/fallback ใช้ usage JSON/SSE เมื่อมี ไม่มีก็ประมาณการเผื่อ เก็บเฉพาะ metadata/tokens/ราคา snapshot ไม่เก็บprompt/response/key กู้ accounting หลังworker savepoint rollback ตรวจHTTP failure/usage stream/ราคาไม่ทราบ/เติมราคาย้อนหลัง/เปลี่ยนโมเดลล้างราคา
- ทดสอบ PostgreSQL concurrent reserve สองงานภายใต้workspace lock: ใช้วงเงินส่วนเดียวกันได้เพียงงานเดียว Cloud ที่เกินงบ/ไม่มีราคาไม่ส่งnetwork และไปOllamaต่อได้ Owner-only usage policy/report; สมาชิกจริงคนที่สองอ่านusageหรือworkspaceอื่นไม่ได้ ไม่ใช่ hard billing cap ของprovider และprocess crashก่อนcommitยังอาจนับไม่ครบ
- Chrome **16 passed** (desktop8/mobile8): ตั้งความชอบจริง→รีโหลด→ถามยอดที่ขาด→ทวน/ยืนยัน→อ่านรายงาน→เปิดตัวกรองรายการต้นทาง และสั่งจำพร้อมยืนยัน รวม regression settings/Markdown/stream/confirmation/batch/workspace defaults/natural history ไม่พบ horizontal overflow ใช้ UI fixture เฉพาะการแสดงยอดusageที่มีข้อมูลและroleสมาชิก; backendทดสอบusage/สิทธิ์สมาชิกด้วยข้อมูลและคนละผู้ใช้จริง เว็บรอบแรกเริ่มก่อนcontainerพร้อมจึงHTTP failure ตรวจพร้อมแล้วรันใหม่จนผ่านครบ ไม่ถือรอบที่ล้มเป็นผลผ่าน
- สำรองและกู้คืนฐาน disposable ผ่าน ตรวจจำนวนแถวและsnapshotความจำ/policy/usage/หลักฐานแชท รวม ledger balance Source ZIP ตรวจ integrity/runtime-secret scan แล้ว ไม่ได้deploy VM ของผู้ใช้
- TypeScript/Next production build ผ่าน local migration และทุกserviceพร้อม ไม่มีการเรียก provider จริงในการทดสอบ คุณภาพภาษาธรรมชาติ/vision และข้อมูลusageของproviderจริงยังต้องตรวจหลังผู้ใช้ตั้งค่า

## จัดรูปแบบ Web AI Chat ด้วย Markdown (11 ตุลาคม 2026)

- รองรับตัวหนา/เอียง/ขีดฆ่า หัวข้อ รายการ checklist quote ตาราง inline/fenced code พร้อมปุ่มคัดลอก และ ==ไฮไลต์== ทั้งข้อความย้อนหลังและ streaming ใช้ renderer เดียวกัน ตาราง/โค้ดเลื่อนภายใน ไม่ขยายหน้าจอมือถือ
- ไม่ประมวลผล HTML และไม่โหลดรูปภายนอกจาก Markdown; จำกัดลิงก์ http/https/mailto/anchor บล็อก javascript/data/file และ relative API paths ข้อความทวนทางการเงินแสดงชื่อ/รายละเอียดแบบ literal เพื่อไม่ให้เครื่องหมาย Markdown ซ่อนข้อมูลที่จะยืนยัน
- Chrome **12 passed** (desktop6/mobile6) ครอบคลุม Markdown/copy/streaming/XSS/no external image request/no horizontal overflow รวม regression scroll/confirmation/batch/default workspace/natural chat ใช้ mock transport และ fixture สำหรับการจัดรูปแบบ ไม่ใช่การตรวจคุณภาพ provider จริง
- PostgreSQL ชุดเฉพาะ dialogue/secretary/actions/batch/confirmation pending **58 passed**; TypeScript และ Next production build ผ่าน Local Docker ทุก service healthy ไม่มี migration และไม่เพิ่ม model call สำหรับการแสดงผล ไม่ได้รันชุด backend ทั้งหมดใหม่ในรอบนี้
- Source ZIP ตรวจ integrity และ runtime-secret scan แล้ว ไม่ได้อัปเดต server VM ของผู้ใช้

## แก้ scroll ระหว่างคิด/ข้อความซ้อน และยืนยันข้อเสนอเก่า (11 ตุลาคม 2026)

- PostgreSQL ชุดรวม disposable **314 passed**; ชุดเฉพาะ confirmation/actions/dialogue/batch/secretary **58 passed** ตรวจยืนยันขณะคำขอใหม่ยัง pending ไม่โพสต์ข้อเสนอเก่าและไม่อ้างว่าข้อเสนอใหม่บันทึกแล้ว รวม old confirmed/old pending/legacy code/plain confirm/replay และงานในห้องอื่นไม่บล็อก
- ส่งข้อความ/รูปใหม่แล้ว invalidates review-message binding และถอด confirmed action เก่าออกจาก active context งานรอในห้องเดียวกันให้รอทวน ไม่ยืนยันล่วงหน้า Worker ไม่นับข้อความยืนยันก่อนเวลาเป็นคำขอใหม่ที่มา supersede คำขอเดิม โมเดลตอบ prose โดยไม่มี tool ไม่ได้ผูก action เก่ากลับมา
- แก้ auto-follow ให้ใช้ followBottom แทนเงื่อนไขใกล้ท้าย360px หยุดเมื่อเลื่อนขึ้นด้วย wheel/touch/scroll และกลับมาติดตามเมื่อถึงท้าย ไม่บีบความสูง message/thinking และปิด native scroll anchoring ที่ชนกับการเลื่อนของแอป
- Streaming hook ซ่อน draft ทันทีตาม context/baseline เมื่อประวัติจริงมาถึง เก็บงานที่จบแล้วแบบ bounded100 IDs เพื่อไม่ให้ late snapshot/start ชุบข้อความเดิมมาแสดงซ้อน รองรับ polling มาก่อน SSE done
- Chrome scenarios **10 ผ่านรวม** (desktop5/mobile5): confirmation/batch/defaults/natural **8 passed** ในชุดแรก และ streaming **2 passed** หลังแก้ fixture ให้รอ seed history โหลดครบและย้าย screenshot ไปหลังตรวจตำแหน่งเลื่อน เพราะ screenshot ของ Playwright เลื่อน element เข้าจอเอง ไม่แก้ assertion ให้ผ่านอาการ snap ทดสอบคงตำแหน่งอ่านในโซน240px ขณะมี chunks ต่อเนื่อง ความสูง message ไม่ทับกัน และ late snapshot หลัง done/poll ไม่ซ้อน
- Next production build/TypeScript ผ่าน local Docker ทุก service healthy ไม่มี migration ใหม่ สำรอง/restore ผ่าน Source ZIP ตรวจ integrity/runtime-secret scan แล้ว ส่งเฉพาะ source ไม่ได้อัปเดต server VM ของผู้ใช้ Provider/stream ใช้ mock fixtures ในการทดสอบ ไม่ใช่การทดสอบ thinking กับ provider จริง

## ชุดรายการแชทและลดการใช้ AI (11 ตุลาคม 2026)

- PostgreSQL ฐานทดสอบ disposable ชุดรวม **310 passed** (เพิ่ม13เคส; 1 Starlette/httpx deprecation warning เดิม) ชุดเฉพาะ batch/confirmation/dialogue **36 passed** ตรวจหนึ่ง tool call เตรียมหลายรายการ, ทุก item scoped/strict integer, invalid ทั้งชุดไม่สร้าง review, จำกัด10, แก้/นำรายการในร่างออกโดยไม่เรียกโมเดล, plain confirm/replay และ ledger balance
- Fault injection ล้มเหลวที่ post รายการที่2 ผ่าน HTTP จริง: response500, ไม่มี Entry/Line ใหม่และ action ยัง pending; ลองยืนยันใหม่สำเร็จทั้งชุด ตรวจหลักฐานรูปสอง Proposal และบล็อกรูปเดิมเมื่ออัปโหลดห้องอื่น ตรวจ tenant isolation ของคำเตือนซ้ำ และ conflict เมื่อมีรายการซ้ำเพิ่มหลังทวน
- Prompt transport mock ตรวจรูปซ้ำส่งครั้งเดียวและข้อความย้อนหลังรวมไม่เกิน24,000ตัวอักษร สูงสุด20ข้อความ/4,000ต่อข้อความ; ข้อความหลายรายการระบุครบใช้ parser แม้ตั้ง provider โดยไม่มี model call ยืนยัน/ยกเลิก/แก้ยอดตามหมายเลข/ตรวจซ้ำใช้ backend ไม่เสีย model call เพิ่ม ไม่ได้วัดค่าใช้จ่ายเงินจริงหรือ token accounting
- Chrome **16 passed** (desktop8/mobile8) เพิ่ม batch review→แก้รายการ2→ยืนยันครั้งเดียว→replay→เตือนซ้ำ→ยกเลิก ผ่าน API/ledger จริง รวมหน้า AI settings/workspace defaults/management/history/stream/finance/natural chat เดิม ไม่พบ horizontal overflow
- Next.js production build และ TypeScript ผ่าน local Docker ทุก service healthy ไม่มี migration ใหม่ สำรอง/restore ฐาน disposable ตรวจ snapshots และสมดุล ledger ผ่าน
- ชุดรวมรอบแรกสะดุดที่190 passed เพราะ Docker เต็มและ PostgreSQL restart; คืนพื้นที่เฉพาะ image/build cache เก่าที่เลือกจากงานนี้ ไม่ลบ volumes จากนั้นรันชุดรวมใหม่ในฐาน disposable จนครบ310 ไม่ใช้ผลรอบที่ล้มเป็นผลผ่าน
- ภาษาธรรมชาติ/vision ใช้ mock transport ทดสอบ ไม่ได้รับรองคุณภาพ provider จริง การตรวจซ้ำเป็น heuristic วันเดียวกัน/ชนิด/ยอด/บัญชีและคำอธิบายคล้ายกัน ไม่รับประกันพบทุกกรณี ยังไม่มี multi-correction/Telegram native batch/AI cost dashboard/memory summarization; อยู่ขั้น3จาก4 ไม่ได้อัปเดต VM ผู้ใช้ Source ZIP ตรวจ integrity/runtime-secret scan แล้ว

## ใช้ลำดับ AI และ workspace ที่เลือกเป็นค่าเริ่มต้น (11 ตุลาคม 2026)

- PostgreSQL ชุดรวม **297 passed** เพิ่ม Web Chat route tests ทั้งห้องใหม่/legacy private/standard ใช้ Cloud switch + priority/fallback ปัจจุบันของ workspace เหมือนกัน ไม่มี room privacy gate อีกต่อไป ทดสอบ Cloud ล้มแล้วใช้ Ollama, ปิด Cloud แล้วไม่เรียก cloud, รูปข้ามโมเดล text-only และเปลี่ยนสวิตช์ก่อนประมวลผลงานที่รอ
- บริบท native assistant มี ID/ชื่อ workspace ปัจจุบันและคำสั่งให้ใช้พื้นที่นี้โดยไม่ถามซ้ำ ไม่มี tool เปลี่ยนพื้นที่หรืออ่านพื้นที่อื่น ยังคง membership/tenant checks เดิม การรับข้อมูลนอก Web Chat ยังคง explicit privacy เดิม
- Chrome **14 passed** (desktop7/mobile7) รวมเลือกพื้นที่จากหน้าการเงิน → เข้าแชท → สร้างห้อง/เตรียมรายการในพื้นที่นั้น → เปลี่ยนเอง → ยืนยันลงพื้นที่ใหม่เท่านั้น → กลับหน้าการเงิน/รีโหลดจำตัวเลือกเดิม ไม่พบตัวเลือก Private/Standard รายห้อง ชื่อ workspace ยาวบนหัวแชทไม่ทำให้หน้าล้น
- TypeScript/Next production build ผ่าน ไม่มี migration ใหม่ คง privacy metadata เดิมสำหรับ client เก่า เพิ่ม routing=workspace ใน conversation response และงาน chat; สวิตช์ Cloud ไม่ถูกเปิดเอง ค่าปัจจุบันใช้กับห้องเดิมด้วย
- รอบแรกพื้นที่ Docker เต็มจน PostgreSQL/ชุดทดสอบขัดข้อง ลบเฉพาะ image เก่าจากงานนี้ที่ไม่ใช้งาน ไม่แตะ volumes จากนั้นทุก service healthy ชุดรวมและ browser ผ่าน พร้อมสำรอง/restore ในฐาน disposable ตรวจ row counts/snapshots/ledger balance ผ่าน
- Model transport ยังเป็น mock ไม่ได้ยืนยันคุณภาพกับ provider จริง ไม่มีการอัปเดต VM ผู้ใช้ Source ZIP ตรวจ integrity/runtime-secret scan แล้ว ยังอยู่ขั้น3จาก4


## แก้การส่ง ยืนยัน แบบไม่มีเครื่องหมายคำพูด (11 ตุลาคม 2026)

- พบ composer ล็อกปุ่มส่งเมื่อมี pending job ใด ๆ ใน workspace จึงส่ง ยืนยัน ไม่ได้แม้งานนั้นเป็นรูปหรือข้อความอื่น แก้ให้ปุ่มส่งใช้ได้เมื่อพิมพ์คำสั่งยืนยัน/ทวน และคำสั่ง ยืนยัน/ยกเลิก/ทวนอีกที ส่งตรงไปยัง backend ได้ ข้อความคุยใหม่หรือรูปยังรอคำตอบก่อน และไม่ล้างร่างที่พิมพ์ไว้
- API รับข้อความ ยืนยัน โดยไม่บังคับ hidden review_message_id ตรวจ action และข้อความทวนล่าสุดที่สร้างโดยระบบในห้องเจ้าของ หาก client ส่ง ID มาก็ยังตรวจ stale ID เว็บใช้ ID assistant ล่าสุดแทนข้อความ user ที่อาจอยู่ท้ายประวัติ
- เอาเครื่องหมายคำพูดออกจากคำแนะนำบนหน้าแชทและข้อความทวน พร้อมระบุว่าไม่ต้องพิมพ์รหัส ตรวจ server-side confirmations สำหรับ create/correction/management แบบ text-only, replay/หมดอายุ/ข้อความเลียนแบบ/ต่างห้อง/ข้อมูลเปลี่ยนยังคงถูกป้องกัน
- PostgreSQL ชุดรวม **293 passed**; TypeScript/Next production build ผ่าน ไม่มี migration ใหม่
- Chrome รอบสุดท้าย **12 passed** (desktop6/mobile6) รวม fixture pending workspace job แล้วพิมพ์ ยืนยัน ผ่าน API/ledger จริง ตรวจ replay/แก้รายการและส่งรูปต่อด้วย รอบก่อนพบ ordinary send เปิดก่อนงานเสร็จจึงแก้ให้เปิดระหว่างรอเฉพาะคำสั่งที่ backend จัดการตรง อีกครั้งติด login throttle จากการรันทดสอบซ้ำ ล้างเฉพาะ local test email/proxy counters แล้วตรวจครบใหม่ ไม่ลด threshold
- Source ZIP ตรวจ integrity และ runtime-secret scan ผ่าน อัปเดต local Docker แล้วทุก service healthy ไม่ได้อัปเดต VM ของผู้ใช้


## AI ค้นหา/แก้รายการและวิเคราะห์เพื่อปรับงบ (11 ตุลาคม 2026)

- PostgreSQL ชุดรวมล่าสุด **292 passed**; เพิ่ม 26 เคสจากรอบก่อน รวม native read→tool result→correction/plan, streamed tool ID fragments ไม่เผย arguments/reasoning, ยืนยันซ้ำ และไม่เขียน ledger ก่อนยืนยัน
- ทดสอบขอบเขต workspace/account จริง, คำค้น wildcard แบบ literal, ช่วงวันที่/ชนิด/ยอด strict, active entries หลัง correction, ผลสูงสุด10พร้อม has_more, หมดอายุ/ไม่มีผลค้นหา, หลายรายการ/ป้องกันโมเดลค้นแคบเองเพื่อข้ามการเลือกใน turn เดียว และป้องกันสลับรายการที่ผู้ใช้เลือก
- ทดสอบ monthly actual/previous/budget amounts จาก backend, วิเคราะห์อย่างเดียวไม่สร้าง action, คำขอ “สรุป...แล้วปรับงบ...ได้ไหม” สร้างแผนรอยืนยัน และบล็อกทั้งแผนเมื่อ ledger เปลี่ยนจากข้อมูลที่ใช้วิเคราะห์
- จำกัด reads3 ต่อข้อความรวม retry/fallback, รอบโมเดล4 ต่อ attempt และ deadline เดิม ส่ง tool result ด้วย call_id เดิม ตรวจ validation ไม่ส่งรายละเอียด SQL/provider errors ให้โมเดล
- TypeScript/Next production build ผ่าน อัปเดต Docker local แล้วทุก service healthy ไม่มี schema migration ใหม่ ใช้ JSON context/payload เดิม
- Chrome regression **12 passed** (desktop6/mobile6): settings, helper history, typed confirmation/correction/replay, streaming, natural capture/older history และ finance isolation/layout; native model tool behavior ตรวจด้วย HTTP/PostgreSQL ด้านบน ไม่ได้เรียก LLM จริงผ่าน browser
- สำรองและ restore ในฐาน disposable ผ่าน จำนวนแถว snapshots รวม capture_context/ChatAction และ ledger balance ตรงกัน Source ZIP ตรวจ integrity/ไม่รวม runtime secrets แล้ว
- Model transport เป็น HTTP MockTransport ทั้งหมด ยังไม่ได้ทดสอบคุณภาพภาษา/vision/tools ของ provider จริง Telegram ไม่ใช้ tools ใหม่นี้ ไม่มี deployment ไป VM ผู้ใช้ ยังอยู่ขั้น3จาก4


## แผน AI จัดการหลายงานพร้อมยืนยัน (11 ตุลาคม 2026)

- PostgreSQL ชุดรวมล่าสุด **266 passed** รวมเคส stream ของ management tool และแก้บางส่วนของแผนรอยืนยันพร้อมส่ง operations เดิมเป็นบริบทให้โมเดล
- Chrome **12 passed** ในรอบเดียว: desktop6/mobile6 ครอบคลุมแชทเดิม/ยืนยัน/แก้รายการ/รายงาน/รูป demo/streaming/ตั้งค่า AI และประวัติงานใหม่ หน้าประวัติใช้ response fixture เพื่อตรวจ presentation/แบ่งหน้า/escape HTML ส่วน prepare/confirm และผลข้อมูลจริงทดสอบผ่าน HTTP กับ PostgreSQL
- Native tool `prepare_management_plan` รับ schema แบบ allowlist 1–10 operations สร้าง/เปลี่ยนชื่อบัญชีหรือหมวด ตั้ง/นำงบออก/คัดลอกเดือนก่อน สร้าง/แก้/เก็บเป้าออม สร้าง/พัก/เปิดรายการประจำ รวมสร้างหมวดแล้วอ้างในงบ/รายการประจำในชุดเดียว ไม่มีการเพิ่มเงินจากแผนจัดการ
- ทดสอบก่อนยืนยันไม่เปลี่ยนข้อมูล ยืนยันครั้งเดียวทำทั้งชุด replay/พร้อมกัน4คำขอลงเพียงครั้งเดียว rollback เมื่อขั้นตอนถัดไปล้มเหลว ไม่เหลือบัญชี/ประวัติครึ่งชุด หมดอายุ/ข้อความทวนผิด/เพิกถอนสมาชิก/ข้าม workspace และชื่อซ้ำ/คำสั่งซ้ำ/เกิน10/ยอด bool หรือ float ถูกปฏิเสธ
- Snapshot ตรวจบัญชีทั้งพื้นที่ งบเดือนต้นทาง/ปลายทาง และเวอร์ชันเป้า/รายการประจำ หากเปลี่ยนขณะรอจะไม่เขียนส่วนใดและให้เตรียมใหม่ ใช้ workspace lock เดียวกับหน้าจัดการและ worker
- Migration additive `assistant_management` เพิ่ม audit append-only PostgreSQL; ทดสอบ SQL update/delete ถูกปฏิเสธ ประวัติยังอยู่หลังลบแชท สมาชิกอ่านร่วมกันแต่ยืนยันห้องผู้อื่นไม่ได้ API ไม่คืน payload/snapshots ทั้งหมด แบ่งหน้า10/1ผ่าน
- TypeScript/Next production build ผ่าน local Docker healthy และตรวจภาพ dialog ประวัติมือถือแล้วเวลาไทยถูกต้อง ไม่ล้นแนวนอน สำรองหลัง migration/restore ในฐาน disposable ผ่าน รวมจำนวนแถวและ snapshot ของ assistant_changes
- โมเดลทดสอบด้วย HTTP MockTransport ยังไม่ได้ยืนยันคุณภาพกับบริการ AI จริง คำสั่งแก้รายละเอียด recurring ที่มีอยู่/จัดสรรเงินเข้าเป้า/ลบ ledger หรือบัญชี/เปลี่ยน kind/สมาชิก/รหัส/API keys ยังไม่รองรับ Telegram ยังใช้ระบบเดิม ไม่มี deployment ไปเครื่องผู้ใช้ อยู่ในขั้น3จาก4


## สนทนาปกติ รูปในแชท และ Thinking ต่อโมเดล (11 ตุลาคม 2026)

- PostgreSQL ชุดรวมล่าสุด **242 passed** ใน Docker รวม native function tool, สนทนาทั่วไป/JSON ตัวอย่างไม่สร้างรายการ, ถามรายละเอียดต่อจากประวัติรูป, validation satang/บัญชี/tenant และคุ้มครองคำถามที่โมเดลพยายามสร้างร่าง
- Chrome **10 passed ในรอบเดียว**: desktop 5 + Pixel 7 emulation 5 ครอบคลุมบันทึกค่า Thinking/รับรูป/ลำดับ/คีย์ไม่ส่งกลับ/สลับพื้นที่, แชทยืนยันคำเดียวและแก้พร้อมประวัติ, streaming/reconnect, แนบรูป/demo ไม่แต่งยอด, รายงานและเลื่อนประวัติ ตรวจภาพตั้งค่า AI ทั้งสองขนาดแล้ว ไม่มี horizontal overflow
- TypeScript และ Next production build ผ่าน; local Docker อัปเดตและ healthy โดย migration additive `assistant_models` เพิ่ม reasoning_effort/default และ supports_images/false ให้ Provider เดิม
- โมเดลงาน Chat ที่มีสิทธิ์ใช้รับข้อความทั่วไปทั้งหมดพร้อม function `prepare_transaction`; tool arguments/reasoning fields ไม่ทยอยแสดง ไม่ตีความ JSON ที่ตอบเป็น prose ให้เป็นคำสั่ง ทดสอบ tool fragments/interrupted/unknown/multiple tools และข้อความโมเดลปลอม review
- รูป Web Chat ใช้ Chat vision และประวัติ 20 ข้อความ/3 รูป; กรองโมเดลรับรูปก่อนจำกัดจำนวน fallback ทดสอบรูปพร้อม caption → ถามบัญชี → ส่งรูปใน follow-up → ทวนพร้อม thumbnail → พิมพ์ยืนยัน → ledger + confirmed evidence ใน transaction เดียว
- ทดสอบรูปจากห้องอื่นถูกปฏิเสธ/สมาชิกยังไม่เห็นรูปส่วนตัว, รูปยืนยันแล้วคงอยู่หลังลบห้อง, บันทึกล้มเหลว rollback ทั้ง ledger/evidence, replay ไม่เพิ่มเงิน และ Inbox ไม่ยืนยันรูปที่ Chat ลงบัญชีแล้ว
- Thinking mappings ทดสอบ OpenAI/Gemini/OpenRouter/Groq/Compatible/Ollama, default/temperature/output token compatibility, settings persist และปฏิเสธค่าที่รู้ว่าไม่รองรับ ไม่มีการ retry โดยแอบลบ effort; upstream อาจมีข้อจำกัดต่างกันตามรุ่น
- รอบ browser แรกตัวทดสอบหา Thinking ด้วย label แบบ exact ไม่พบ และมี race ของรายการ workspace หลัง API create; แก้ให้หา combobox ตามชื่อที่เข้าถึงได้และ reload หลังสร้าง workspace แล้วรอบสุดท้ายทั้ง 10 ผ่าน ไม่ลด throttle ของระบบ
- สำรองหลัง migration และตรวจ restore ในฐาน disposable ผ่าน เทียบจำนวนแถวและ snapshots รวม Thinking/รับรูปตรงกับต้นฉบับ ledger สมดุล
- ใช้ HTTP MockTransport ไม่มี API key/บริการโมเดลจริง จึงยังไม่รับรองความแม่นยำ OCR/ภาษา/ทุกโมเดลหรือทุกระดับ thinking บนอุปกรณ์จริง Telegram ยังใช้ deterministic capture/Inbox ตามเดิม ไม่ได้เปิด native conversation แบบเว็บในรอบนี้ อยู่ระหว่างขั้น 3 จาก 4; ไม่มีการ deploy เครื่อง Ubuntu ของผู้ใช้


## แชทแบบเลขาและยืนยันคำเดียว (11 ตุลาคม 2026)

- PostgreSQL ชุดรวม **224 passed**; หลังแยกการเรียกโมเดลของเว็บกับ Telegram ทดสอบแชทล่าสุด **44 passed** รวมเพิ่มกรณี Telegram ถามบัญชีต่อได้แม้ตั้ง Chat provider ไว้
- Chrome **6 passed**: คอม/มือถือครอบคลุมคำยืนยันสั้น, replay ไม่บันทึกซ้ำ, แก้รายการพร้อมประวัติ, คำตอบ “เงินสดจ้า”, โหลดประวัติต่อเนื่อง, รายงานจากข้อมูลจริง และไม่ล้นแนวนอน ตรวจภาพข้อความทวนบนมือถือแล้ว
- TypeScript และ Next production build ผ่าน ไม่มี migration ใหม่ ใช้ capture_context JSON เดิม; เว็บส่ง ID ข้อความที่กำลังยืนยัน และ backend ตรวจว่าตรงกับข้อความทวนล่าสุดที่สร้างจาก draft จริง
- ทดสอบ missing/stale review ID, re-review, expiry, cancelled/superseded draft, ข้ามห้อง/ผู้ใช้/workspace, ยืนยันพร้อมกัน 4 คำขอลง ledger ครั้งเดียว, rollback และโมเดลเลียนแบบข้อความทวนเดิมแล้วยืนยันสั้นไม่ได้
- บทสนทนากฎภาษาไทยถามยอด/บัญชี/หมวดต่อ รองรับคำลงท้ายสุภาพ เปลี่ยนยอด pending แล้วทวนใหม่; คำถาม/สมมติ/ตัวอย่างไม่สร้างร่าง รายงานสั้นก่อน และแสดงรายการเมื่อขอ
- โมเดลที่ตั้งงาน Chat แปลคำขอสร้างรายการเป็น JSON; ทดสอบ transport ด้วย MockTransport ว่า JSON ไม่ stream เข้า UI, สะกดจำนวนเงินเป็นคำและตอบต่อจาก history ได้, Private ไม่เรียก Cloud, งานเก่าไม่แทน draft ใหม่, จำนวน strict/ID ข้ามพื้นที่/ชนิด opening/confirmed field ถูกปฏิเสธ และยังไม่ลง ledger จนผู้ใช้ยืนยัน
- ไม่มี API key จริงในการทดสอบ ไม่อ้างว่าคุณภาพทุกโมเดล/ทุกสำนวนผ่านการใช้งานจริง Private ต้องใช้ Ollama; Cloud ต้องเปิดระดับ workspace และห้อง Standard หากใช้ mock ยังเป็นตัวแปลแบบกฎ แชทแก้ข้อมูลทุกประเภทแบบอิสระยังไม่รองรับ และรูปยังยืนยันที่ Inbox
- Telegram ใช้คำยืนยันสั้น/กฎภาษาไทย; JSON interpreter ในรอบนี้ใช้เฉพาะ Web Chat ยังไม่ได้ทดสอบส่งกับ Telegram จริง หน้า offline drafts เดิมยังใช้รหัสยืนยัน
- ไม่ได้ deploy ไป Ubuntu ของผู้ใช้ และไม่ได้ตรวจผล GitHub CI ในรอบนี้


## ศูนย์ตั้งค่า AI บนเว็บ (11 ตุลาคม 2026)

- PostgreSQL ชุดรวม **203 passed**; หลังเพิ่มการล้างคีย์เมื่อเปลี่ยน URL และตรวจจำนวนโมเดลสูงสุด ทดสอบกลุ่ม AI/security/images/stream ซ้ำ **32 passed**
- กลุ่ม AI configuration ล่าสุดทดสอบซ้ำ **16 passed** รวม migration จาก compatible URL เดิมที่ไม่ให้คีย์ตามไป URL ใหม่
- สำรอง/restore ลงฐานชั่วคราวผ่าน รวม row counts และ snapshots ของ `ai_settings`/providers/คีย์เข้ารหัส โดยไม่แสดงค่าคีย์; journals สมดุล
- TypeScript และ Docker/Next production build ผ่าน; migration `ai_configuration` อัปเกรดฐานเดิมโดยคง providers และ encrypted keys เดิม
- Chrome เฉพาะฟีเจอร์ใหม่ **2 passed** (คอม/มือถือ): เปิด Cloud AI, เพิ่ม Custom API, ไม่อ่านคีย์กลับ, แก้ไขโดยใช้คีย์เดิม, เลื่อนลำดับ, เปิด–ปิด, persist หลัง reload, ลบแบบยืนยัน และสลับ workspace ที่ไม่มีโมเดล/ปิด Cloud โดยไม่มีค่าพื้นที่เก่าติดไป
- Tests ของ backend ตรวจ owner-only/สมาชิกถูกปฏิเสธ/tenant ID ข้ามพื้นที่ 404, encryption/retain/rotate/clear key, ปิด cloud แม้ legacy env เปิด, validate URL ไม่สะท้อน key, DNS private ถูกปฏิเสธและ pin public IP พร้อม SNI, probe ส่ง synthetic prompt เท่านั้น/ไม่คืน model response, ลำดับ/retry/disabled/max attempts/privacy/demo fallback และไม่มีการลง ledger
- Custom API รองรับ HTTPS public พอร์ต 443 เท่านั้น ไม่ redirect/ไม่เชื่อ environment proxy; Local Ollama ยังคงใช้บริการที่ผู้ดูแลกำหนด ไม่ให้ tenant ระบุ URL ภายในตามใจ และหน้านี้ไม่ติดตั้งโมเดล
- ไม่ได้เรียก provider ภายนอกด้วย API key จริง การทดสอบ transport ใช้ MockTransport; ความพร้อม/สิทธิ์โมเดล/ค่าใช้จ่ายจริงต้องตรวจด้วยปุ่มทดสอบหลังผู้ใช้ตั้งค่า
- Chrome ชุดเดิม 44 ข้อไม่ได้รันซ้ำในเครื่องรอบนี้ GitHub CI จะรันชุดรวมเมื่อ push; ไม่ได้ deploy ไป Ubuntu ของผู้ใช้


## ตัวเลือก Nginx (11 ตุลาคม 2026)

Compose overlay ตรวจผ่าน; Nginx stable-alpine ตรวจ syntax ของ internal gateway และ snippet สำหรับ Nginx เดิมผ่าน ทดสอบ gateway ชั่วคราวกับแอปจริงผ่าน: หน้าเว็บ, API พร้อม query string, login/session cookie, workspace ที่ต้อง login, SSE ส่ง ready ทันที, ลบห้องทดสอบและ logout แอปที่พอร์ต 8080 ยังใช้ gateway เดิม ไม่แก้ Nginx ภายนอกของผู้ใช้ โดเมน/ใบรับรอง/HTTPS ของเครื่องปลายทางยังไม่ได้ตรวจ

## ยืนยันอีเมลและกู้รหัสผ่าน — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL **187 passed** รวมทดสอบระบบเดิมและกรณีใหม่ 13 กรณี: คำตอบขอกู้บัญชีไม่แยกอีเมลที่มี/ไม่มี, ปิด SMTP, เข้ารหัส outbox/hash token, ตั้งรหัสผ่านและเพิกถอนทุก session, ใช้ซ้ำ/หมดอายุ/ขอใหม่/ผิดประเภท, เปลี่ยนรหัสผ่านยกเลิกลิงก์เดิม, validation ไม่สะท้อน token/password, rate limit, retry 3 ครั้งและล้าง payload, สมัครแล้วเข้าคิว verification, STARTTLS transport ที่จำลอง, รหัสยืนยันไม่ตรงไม่ใช้ token, สอง transaction ใช้ token พร้อมกันสำเร็จครั้งเดียว และล้าง outbox หมดอายุแม้ SMTP ปิด
- SQLite ชุดรวมก่อนเพิ่ม cleanup **166 passed, 19 skipped**; หลังเพิ่ม concurrency/cleanup ทดสอบเฉพาะ email recovery **12 passed, 1 PostgreSQL-only skipped**. TypeScript และ Next.js production build ผ่าน
- Chrome ชุดรวม **44 passed** (คอม 22/มือถือ 22) รวมหน้าลืมรหัสผ่าน/SMTP ปิด, ยืนยันอีเมลแบบกดเอง, รหัสผ่านไม่ตรง/ตรง และ fragment ไม่ค้างในแถบที่อยู่ ตรวจภาพมือถือ `artifacts/email-recovery-mobile.png` แล้ว ไม่มีการล้นแนวนอน
- หน้าจอลืมรหัสผ่านและแจ้งสถานะ SMTP; ลิงก์ fragment ถูกนำออกหลังอ่าน; เปิดลิงก์อย่างเดียวยังไม่ทำงาน ต้องกด/กรอกรหัสผ่านยืนยันเอง; หน้า reset สำเร็จล้าง vault ของเครื่องนี้และไม่ auto-login
- คิวอีเมลอยู่ใน transaction เดียวกับการออก token; worker ใช้ User → EmailToken locks เหมือน request/consume/password change. SMTP timeout 10 วินาที, TLS certificate validation, retry ไม่เกิน 3 ครั้ง, ไม่บันทึก exception/recipient/body/password ลง log
- สำรองและ restore ลงฐานชั่วคราวผ่านหลังทดสอบ UI จบ รวม schema/จำนวนแถว email_tokens และ snapshot email_verified_at ใน users; จำนวนแถวและ snapshots ตรงกัน journal สมดุล
- SMTP ปิดเป็นค่าเริ่มต้น ไม่มีอีเมลจริงถูกส่งในการทดสอบ การยืนยันอีเมลยังเป็นทางเลือก ไม่บังคับ login. 2FA/รายการอุปกรณ์/เปลี่ยนอีเมล และการส่ง–รับ SMTP จริงยังไม่ผ่านการตรวจ

## แชทธรรมชาติ / Telegram และ PWA — ผลก่อนเพิ่มบัญชีกู้คืน (11 ตุลาคม 2026)

- PostgreSQL **174 passed**; SQLite **155 passed, 19 PostgreSQL-only skipped**. TypeScript และ Next.js production build ผ่าน
- Chrome ชุดรวม **38 passed** (คอม 19/มือถือ 19) รวมแชทที่ถามข้อมูลขาด/แก้รายการ/โหลดข้อความเก่าต่อเนื่องโดย polling ไม่ทิ้งประวัติ และตัดอินเทอร์เน็ตจริง เปิดแอปจาก navigation fallback ปลดล็อกผิด/ถูก เก็บร่าง เข้ารหัสไม่เห็น plaintext ตรวจเจ้าของบัญชี ส่งทวนแต่ยอดไม่เปลี่ยนจนพิมพ์ยืนยัน logout ล้าง vault และ pending encryption เขียนกลับไม่ได้
- หลังเพิ่ม guard การล็อกระหว่าง async decryption ตรวจ PWA ซ้ำ **2 passed** ทั้งคอม/มือถือ การล็อกระหว่างปลดล็อกไม่ทำให้ข้อมูลเปิดกลับมาเอง
- สำรองและ restore ลงฐานชั่วคราวผ่าน รวม capture_context ของแชท จำนวนแถวและ snapshots ตรงกัน journal สมดุล
- 15 tests ใหม่: รายจ่าย/รายรับ/เมื่อวาน/ยอดทศนิยม, ถามบัญชีและหมวดต่อ, หมดอายุข้อมูลที่ขาด, โอน/จ่ายบัตร/แก้รายการล่าสุดเฉพาะห้อง, จำนวนหลายยอด/ติดลบ/ทศนิยมเกิน/วันที่ผิด, ยกเลิกข้อมูลที่กรอก, คำถามรายงานไม่สร้าง draft, Telegram message ID dedup และห้อง/ผู้ใช้แยกกัน รวม history cursor ที่มี timestamp ซ้ำ/ก่อน–หลัง/ห้องอื่น
- Telegram text ใช้ trusted handler โดยตรงและ transaction หลัก ไม่ผ่าน worker/savepoint เมื่อยืนยัน ledger ยอดสมดุล ยืนยันข้อความเดิมซ้ำไม่บันทึกเพิ่ม ทดสอบ handler ภายใน ยังไม่ได้เรียก Telegram จริงหรือทดสอบ delivery ของ aiogram กับ token จริง
- PWA มี manifest id/scope และ PNG icons 192/512, service worker cache เฉพาะไฟล์ public/static, offline navigation fallback, install prompt/fallback guidance และปุ่มอัปเดตรุ่นใหม่ หน้า offline จำกัด CSP เฉพาะไฟล์/การเชื่อมต่อ same-origin
- Vault ปิดเป็นค่าเริ่มต้น เก็บ snapshot 100 รายการล่าสุดหนึ่ง workspace และ 20 ร่างข้อความโดยเลือกเก็บ เข้ารหัส AES-256-GCM/PBKDF2-SHA256 210,000 รอบ salt/IV ใหม่ ไม่เก็บรหัสปลดล็อก ข้อมูล API/ภาพ/แชท/credentials ไม่อยู่ใน service worker cache ล็อกเมื่อไปเบื้องหลัง ล้างเมื่อ logout ป้องกัน pending encryption เขียนกลับหลัง clear
- ข้อจำกัด: natural language ใช้กฎภาษาไทยที่รองรับและยังไม่ครอบคลุมทุกสำนวน รูปยังต้องยืนยันใน Inbox บนเว็บ ออฟไลน์ไม่เรียก AI/ไม่ลง ledger/ไม่ส่งร่างอัตโนมัติ ต้องใช้ HTTPS หรือ localhost และยังไม่ได้ติดตั้งตรวจบนมือถือจริง Snapshot บนเครื่องออฟไลน์ไม่หายทันทีเมื่อ server revoke สิทธิ์ แต่ส่ง/ยืนยันต้องตรวจบัญชีและสมาชิกใหม่ ภาพรวมยังอยู่ขั้น 3 จาก 4


## สมัครบัญชีผ่านเว็บ — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL **159 passed**; SQLite **140 passed, 19 PostgreSQL-only skipped**; TypeScript และ Docker/Next.js production build ผ่าน
- เพิ่ม `/auth/options`, `/auth/register`, `/register` และปุ่มสมัครในหน้าเข้าสู่ระบบตามค่า runtime `ALLOW_REGISTRATION` ค่าเริ่มต้น false และบล็อก API โดยตรงเมื่อปิด ไม่ต้อง build frontend ใหม่เมื่อเปลี่ยนค่า
- 10 tests ใหม่ตรวจเปิด–ปิด, สมัคร/ชื่อ/ปรับอีเมลเป็นตัวเล็ก/Argon2/session/logout/login, พื้นที่ส่วนตัวใหม่กับ 6 บัญชีเริ่มต้นและไม่มีรายการ, การอ่านข้าม tenant, อีเมลซ้ำไม่สร้างพื้นที่เพิ่ม, validation ที่ไม่สะท้อนรหัสผ่าน, password confirmation, throttle และ request origin รวมการจำลองสร้าง session ล้มเหลวแล้ว rollback บัญชี/พื้นที่ทั้งหมด
- Chrome โหมดเปิดสมัคร **2 passed** (คอม/มือถือ): สมัครจากหน้าเข้าสู่ระบบ ยืนยันรหัสไม่ตรงแล้วแก้ไข สมัครเพื่อนใน session แยก ตรวจข้ามพื้นที่ 404 แล้ว logout/login ด้วยบัญชีที่สมัครใหม่ ภาพหน้าสมัคร 1440/393/360px ไม่มีส่วนล้นแนวนอนและตรวจภาพมือถือแล้ว
- Chrome ชุดรวมเมื่อปิดสมัคร **34 passed** (คอม 17/มือถือ 17) รวมบัญชีเดิม คำเชิญ และระบบการเงิน
- หลังแก้ transaction ตรวจหน้าเว็บสมัครซ้ำ **2 passed** เมื่อเปิด และ **2 passed** เมื่อปิด; สำรอง/restore ลงฐาน disposable ผ่าน row counts/snapshots ตรงกันและ ledger สมดุล
- คืนค่าเว็บในเครื่องเป็นปิดสมัครหลังทดสอบ บัญชีเดิมและคำเชิญยังใช้ได้ ยังไม่มีอีเมลยืนยัน กู้รหัสผ่าน หรือ 2FA ภาพรวมยังอยู่ขั้น 3 จาก 4


## รุ่นก่อนหน้า — พื้นที่ทำงานและบัญชีแยกคน (11 ตุลาคม 2026)

- PostgreSQL **149 passed**; SQLite **130 passed, 19 PostgreSQL-only skipped**; TypeScript และ Next.js production build ผ่าน
- เปลี่ยนชื่อพร้อม trim/ป้องกันชื่อว่าง, version เก่าได้ 409, owner เท่านั้น, member ไม่มีสิทธิ์, พื้นที่คนอื่นไม่แสดงใน management list และแก้ไขไม่ได้
- เก็บ/กู้คืนต้องพิมพ์ชื่อให้ตรง พื้นที่ที่เก็บไม่อยู่ในรายการ active และข้อมูล/API/ledger post/SSE/Telegram linking หรือ capture ผ่าน linked helper/งานคิว/การสร้างข้อเสนอ recurring ถูกพัก ทดสอบ restore แล้ว job ที่ยังใช้ได้ทำต่อ และ recurring สร้างข้อเสนอ pending ได้อีกครั้ง
- ลบถาวรได้เฉพาะ default workspace ที่ยังว่าง มี owner คนเดียว ไม่มีข้อมูลอื่น ตรวจสดใต้ lock; พื้นที่ที่มีรายการหรือคำเชิญ/ประวัติลบไม่ได้ PostgreSQL ตรวจลบพื้นที่สุดท้าย commit ผ่านโดยยังเก็บ user/session และสร้างพื้นที่ใหม่ได้
- PostgreSQL archive 2 threads ใช้ version เดียวกัน ได้หนึ่งสำเร็จ/หนึ่ง 409 พร้อมรักษา owner guard และ immutable ledger เดิม
- รหัสบัญชีส่วนตัวเก็บ hash เท่านั้น แสดง preview ประเภท personal, ผูกอีเมล/วันหมดอายุ/ยกเลิก/ใช้ครั้งเดียว; validation ไม่สะท้อน password/token การสมัครได้ personal workspace เพียงหนึ่งพื้นที่ ผู้เชิญไม่เป็นสมาชิกในพื้นที่นั้นและผู้รับไม่เป็นสมาชิกพื้นที่ผู้เชิญ ทดสอบ cross-tenant read ถูกปฏิเสธทั้งสองฝั่ง และแชร์ได้หลังรับ shared invite แยกต่างหากเท่านั้น
- Chrome **32 passed ในรอบเดียว** (desktop 16 + mobile emulation 16) รวมตรวจสร้าง/ค้นหา/เปลี่ยนชื่อ/พิมพ์ชื่อผิดแล้วปุ่ม disabled/เก็บ/กู้คืนและรายการเดิมยังอยู่/ลบพื้นที่ว่าง/รหัสบัญชีส่วนตัว/สมัครผ่าน browser context แยก/เข้าข้อมูลของกันและกันไม่ได้/เก็บพื้นที่สุดท้ายแล้วกู้คืน ทั้งคอมและมือถือจำลอง

- หลังแบ่งหน้าครั้งละ 6 พื้นที่ ตรวจ workspace scenario อีก **2 passed** ทั้ง desktop/mobile รวมหน้าถัดไปและค้นหาแล้วกลับหน้าแรก ตรวจ 14 หน้าที่ 1440/393/360px รวม **42 จุด** หลังการ์ดพื้นที่โหลดแล้ว ไม่มี horizontal overflow
- สำรองและ restore ลงฐาน disposable ผ่าน ตรวจสถานะ/ชื่อ/version workspace และชนิด/สถานะ/token hash คำเชิญตรงกัน ledger สมดุล API/worker/web พร้อมใช้งาน

ข้อจำกัด: ไม่มีการล้างประวัติการเงินถาวร ณ รุ่นนี้ signup ยังเป็น invitation-only โดยเจ้าของพื้นที่ที่ใช้งานอยู่ (รุ่นล่าสุดด้านบนเพิ่มสมัครผ่านเว็บที่เปิด–ปิดได้แล้ว) โค้ดผูกพื้นที่ที่ออกและพักระหว่าง archive ไม่มีอีเมลส่งอัตโนมัติหรือ public registration ไม่มีการลบบัญชีผู้ใช้หรือกู้รหัสผ่าน มี version guard แต่ไม่มีประวัติชื่อ/สถานะ workspace แบบ audit log อายุคำเชิญและนโยบายล้างแชทไม่หยุดระหว่าง archive; recurring อาจสร้างข้อเสนอ backlog เมื่อกู้คืน ยังไม่ได้ทดสอบ Telegram/provider จริง มือถือจริง หรือ Ubuntu/Hyper-V ภาพรวมขั้น 3 จาก 4

## แชททวนและพิมพ์ยืนยันรายการ — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL **142 passed**; SQLite **124 passed, 18 PostgreSQL-only skipped**. TypeScript และ Next.js production build ผ่าน
- ทดสอบทวนรายละเอียด/ยอด/วันที่/บัญชี/หมวดก่อนบันทึก, บาททศนิยม 2 ตำแหน่ง, รายรับ/รายจ่าย/โอน/จ่ายบัตร, ข้อมูลไม่ครบ/ผิด/ชื่อซ้ำไม่สร้างข้อเสนอ
- `ยืนยัน CODE` ต้องเป็นข้อความผู้ใช้ที่ส่งผ่าน authenticated text endpoint ทั้งข้อความ: ยืนยันเปล่า/รหัสผิด/ต่อท้ายข้อความไม่ลง ledger รหัสจากห้องอื่นหรือ workspace อื่นใช้ไม่ได้ สมาชิก workspace เดียวกันเข้าห้องของคนอื่นไม่ได้
- รหัสอายุ 15 นาที; ยกเลิก/หมดอายุ/ข้อเสนอใหม่แทนทำให้รหัสเดิมใช้ไม่ได้ ยืนยันซ้ำไม่บันทึกซ้ำ PostgreSQL 4 threads ยืนยันพร้อมกันได้เพียงรายการเดียว ทุก journal สมดุล
- การแก้แสดงก่อน/หลัง/เหตุผลและใช้ original + inverse + replacement พร้อมประวัติ รายการที่ถูกแก้ไปแล้วหรือชื่อบัญชีเปลี่ยนหลังทวนถูกปฏิเสธ การจำลองล้มเหลวหลังสร้าง journal rollback ทั้งคำขอ รวม lines/messages/status (pending ยังอยู่เพื่อให้ลองใหม่)
- ใช้ top-level transaction สำหรับ posting เพื่อคง PostgreSQL xmin guard ของ immutable ledger ไม่ลดข้อจำกัดฐานข้อมูล; ผู้ใช้/ข้อความ/สถานะ/ledger commit พร้อมกันก่อน HTTP success ข้อเสนอและการยืนยันไม่ผ่าน worker/model/OCR; จำลองโมเดลตอบ `ยืนยัน CODE` แล้ว ledger ยังว่าง
- ลบห้องแล้วข้อเสนอหาย แต่รายการเงินและประวัติที่ยืนยันไว้ยังอยู่ โมเดลยังไม่มีเครื่องมือเขียน ledger และไม่ได้อ่านรหัสยืนยันกลับมาเป็นสิทธิ์ดำเนินการ
- Chrome **30 passed ในรอบเดียว** (desktop 15 + mobile emulation 15) รวมตรวจคำแนะนำ/ใส่ตัวอย่าง/ทวน/ยืนยันเปล่า/ยืนยันจริง/ส่งซ้ำ/คัดลอกคำขอแก้จากรายละเอียดผ่าน clipboard จริง/ก่อน-หลัง/ยอดใหม่/ประวัติ ทั้ง desktop และ mobile emulation

- ตรวจ 13 หน้าที่ 1440/393/360px รวม **39 จุด** ไม่มี horizontal overflow และช่องแชทอยู่ใน viewport
- สำรองและ restore ลงฐาน disposable ผ่าน ตรวจจำนวนแถวรวม chat_actions และ snapshot payload/status/code/entry_id ตรงกัน ledger สมดุล API/worker/web รุ่นล่าสุดพร้อมใช้งาน Source archive ไม่รวม .env, credentials, รูป/ฐานข้อมูล runtime หรือไฟล์สำรอง

ข้อจำกัด: ใช้คำขอระบุช่อง/ชื่อที่ตรงแน่นอนบน backend และคำขอสั้นบางแบบ ไม่ได้ตีความภาษาธรรมชาติอิสระทุกสำนวน ไม่แก้ยอดตั้งต้นหรือข้อมูลบัญชี/หมวด/งบ/สมาชิก/รหัสผ่านผ่านแชท ไม่ลบหรือย้อนยกเลิกรายการผ่านแชท รูปยังยืนยันใน Inbox ไม่มีโอนเงินจริง ยังไม่ได้ทดสอบ provider ภายนอก โทรศัพท์จริง หรือ Ubuntu/Hyper-V อยู่ขั้น 3 จาก 4

## แชททยอยตอบ — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL **135 passed**; SQLite **118 passed, 17 PostgreSQL-only skipped**. TypeScript และ Next.js production build ผ่าน ไม่มี migration ใหม่ API/worker/web อัปเดตแล้ว
- ทดสอบ OpenAI-compatible SSE ด้วย HTTP MockTransport: ข้อความไทย/HTML untrusted, ข้อความเกิน 16,000 ตัวอักษร, JSON ผิดรูปแบบ/ชนิดผิด/provider error/จบกลางทางถูกปฏิเสธ และ retry ล้าง preview ก่อนตอบใหม่
- PostgreSQL + Redis Pub/Sub จริง: preview มาถึงระหว่าง worker ยังไม่ commit และยังไม่มี assistant Message; หลังปล่อย HTTP stream ให้จบจึงมีข้อความเต็มหนึ่งรายการและได้ done หลัง job เป็น done แล้ว ไม่มีการโพสต์ ledger
- ตรวจ auth/foreign workspace/สมาชิกอื่นในพื้นที่เดียวกัน/เซสชันที่ถูกเพิกถอน; generator ตรวจสิทธิ์ซ้ำและปิด Redis resources; การตรวจสิทธิ์ stream ไม่รอ workspace lock ของ worker
- ตรวจ HTTP SSE ผ่าน Caddy และ Redis จริงบน localhost: รับ ready แล้วส่ง preview ได้ทันที ไม่รอ response จบ และ preview ไม่สร้าง Message หรือรายการเงิน ทดสอบนี้เป็นข้อความ fixture ไม่ได้เรียก provider จริง
- Chrome **28/28 passed ในรอบเดียว** (desktop 14 + mobile 14) รวม live preview แบบข้อความธรรมดา/ไม่รัน HTML, snapshot หลังพลาด start, provider retry ล้างคำตอบเดิม, done ล้าง preview แม้ history ID เดิม, reconnect และเปลี่ยนห้องปิด stream เดิม เคส UI streaming ใช้ EventSource fixture; backend/HTTP wire/Redis ตรวจแยกตามด้านบน
- รอบแรกชุดทดสอบใช้ชื่อปุ่มเก่าจึงหมดเวลา แก้ selector ให้ตรง UI แล้วตรวจใหม่ครบ 28 เคส ไม่เพิ่ม retry หรือลดการป้องกัน login เตรียมเฉพาะตัวนับของบัญชีสมมติและ proxy ภายในก่อนรันทดสอบ


- ตรวจ 13 หน้า × 1440/393/360px = **39 จุดไม่พบ horizontal overflow** ช่องพิมพ์แชทยังอยู่ใน viewport ตรวจภาพ preview ทั้งคอมและมือถือแล้ว
- สำรอง/กู้คืนฐาน disposable หลัง browser tests และตรวจ HTTP SSE รุ่นสุดท้ายผ่าน จำนวนแถวและ snapshot ชื่อบัญชี/แชท/นโยบายอายุ/สมาชิก/คำเชิญ/ตารางประจำ/แผนออมตรงกัน ledger สมดุล Source ZIP ไม่รวม credentials/.env/DB dumps/runtime screenshots

ข้อจำกัด: โหมดสาธิต/รายงานตรง/compatible server ที่ไม่ส่ง SSE ยังแสดงคำตอบเต็มทันที ไม่มีปุ่มยกเลิกงานโมเดล ปิดหน้าแค่หยุดรับ stream; ไม่มี replay ทุก event และ load test ของ connection จำนวนมาก External provider/Ollama vision จริงและ Ubuntu/Hyper-V ยังไม่ได้ตรวจ อยู่ขั้น 3/4


## ตั้งค่าบัญชีผู้ใช้ — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL **129 passed**; SQLite **114 passed, 15 PostgreSQL-only skipped**. TypeScript และ Next.js production build ผ่าน เพิ่ม migration `user_profile` โดยคงอีเมลและ hash รหัสผ่านเดิม แล้วเปิด API/worker/web รุ่นล่าสุด
- ชื่อที่แสดงตัดช่องว่างหัวท้าย จำกัด 1–100 ตัวอักษร ห้ามอักขระควบคุม บันทึกเฉพาะผู้ใช้ที่เข้าสู่ระบบ แม้ส่ง ID ของคนอื่นมา ชื่อไม่เปลี่ยน memberships หรือบัญชีเงิน
- เปลี่ยนรหัสตรวจรหัสปัจจุบัน ความยาว 12–200 การยืนยันและต้องต่างจากเดิม ก่อนเขียน Argon2 hash เพิกถอนทุกเซสชันเก่าและสร้าง opaque session ใหม่ให้เครื่องที่เปลี่ยน ตรวจ HttpOnly/SameSite และรหัสเก่าเข้าไม่ได้
- ทดสอบรหัสผิด/ยืนยันไม่ตรง/รหัสสั้น/ช่องว่างทั้งหมด แล้วเซสชันอื่นยังใช้ได้ ไม่มี password hash ในข้อมูลโปรไฟล์ ผล validation ของ `/auth/password` ไม่สะท้อนค่ารหัสกลับ ตรวจ CSRF และ identity ของ rate limiter
- PostgreSQL ทดสอบเปลี่ยนรหัสพร้อมกันด้วยเซสชันเดียว ได้ผลสำเร็จหนึ่งคำขอ อีกคำขอ 401 หลังตรวจเซสชันซ้ำภายใต้ user lock เหลือเซสชันใหม่หนึ่งรายการ Login ใช้ user lock เดียวกัน
- Chrome **26/26 passed** ในรอบเดียว ทั้ง desktop/mobile รวมตั้งชื่อ reload ตรวจรหัสไม่ตรง/รหัสเดิมผิด แล้วเปลี่ยนสำเร็จ เครื่องอื่นได้ 401 รหัสเก่าเข้าไม่ได้ รหัสใหม่เข้าได้ และชื่อยังอยู่ ตรวจภาพการ์ดจริงทั้งสองขนาดแล้ว
- ตรวจซ้ำเฉพาะตั้งค่าบัญชี **2/2 passed** หลังปรับชุดทดสอบให้สร้าง workspace แยก สมาชิกสมมติจากรอบแรกที่เข้าไปในพื้นที่ของบัญชีทดสอบถูกนำออกผ่าน service เดิมพร้อม audit ไม่ลบบัญชีหรือประวัติ
- รอบแรกติด login throttle จากการทดสอบก่อนหน้า เตรียมเฉพาะ counters ของบัญชีสมมติ/proxy ภายในก่อนรันใหม่ ไม่เปลี่ยน threshold หรือปิด rate limiter
- ตรวจ 13 หน้า × 1440/393/360px = **39 จุดไม่พบ horizontal overflow** ช่องพิมพ์แชทอยู่ใน viewport
- สำรองและกู้คืนฐาน disposable หลัง browser tests ผ่าน จำนวนแถว/ledger และ snapshot บัญชีผู้ใช้ (email/name/password hash) ตรงกัน ไม่แสดง hash ในผลตรวจหรือรวม backup/credentials ใน source ZIP

ข้อจำกัด: อีเมลอ่านอย่างเดียว ไม่มี email verification/reset password/2FA/device list/account deletion การเพิกถอนเซสชันไม่ยกเลิก Telegram link หรือย้อนธุรกรรมที่เริ่มทำงานแล้ว ชื่อที่แสดงยังไม่มีประวัติแก้ไข อยู่ขั้น 3/4 และยังไม่ได้ยืนยัน Ubuntu/Hyper-V หรือ provider/Telegram จริง


## ค้นหาและเปลี่ยนชื่อแชท — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL **124 passed**; SQLite **110 passed, 14 PostgreSQL-only skipped**. TypeScript และ Next.js production build ผ่าน อัปเดต API/worker/web แล้ว ไม่มี migration ใหม่
- Chrome **24/24 passed** ทั้ง desktop/mobile รวมค้นหาจากชื่อและข้อความ แบ่งหน้า 20 ห้อง เปิดข้อความที่พบ กลับข้อความล่าสุด เปลี่ยนชื่อ ค้นหาชื่อใหม่ และคุยต่อ ตรวจภาพค้นหาจริงทั้งสองขนาดแล้ว
- ตรวจ 13 หน้า × 1440/393/360px = **39 จุดไม่พบ horizontal overflow** ช่องพิมพ์แชทอยู่ใน viewport
- ทดสอบคำค้นภาษาไทย/อังกฤษ ตัวพิมพ์เล็กใหญ่ และ literal `%`, `_`, backslash; snippets จำกัดความยาว; ห้องชั่วคราว/หมดอายุไม่อยู่ในผลค้นหา แยกผู้ใช้แม้เป็นสมาชิก workspace เดียวกัน ตรวจ foreign room/message และชื่อว่าง
- สร้าง 650 ข้อความเพื่อยืนยันหน้าปกติเปิด 500 ข้อความล่าสุด ค้นหาข้อความเก่ากว่านั้นและเปิดบริบทก่อน/หลังอย่างละไม่เกิน 50 ได้ เปลี่ยนชื่อไม่ต่ออายุประวัติ ไม่เรียกโมเดลหรือแก้ ledger จากการค้นหา
- สำรองและกู้คืนฐาน disposable ผ่าน จำนวนแถวและ snapshot ชื่อห้อง/privacy/temporary/created_at/updated_at ตรงกัน พร้อมนโยบายอายุ สมาชิก คำเชิญ ตารางประจำและแผนออม ledger สมดุล

ข้อจำกัด: ค้นหาข้อความแบบ substring ไม่ใช่ semantic search/OCR ไม่มี full-text index หรือผลทดสอบประวัติปริมาณมาก หน้าปกติยังไม่เลื่อนโหลดประวัติเก่าแบบต่อเนื่อง อยู่ขั้น 3/4 ยังเหลือคำตอบแบบทยอยและ PWA offline; ยังไม่ได้ทดสอบ Ubuntu/Hyper-V, provider หรือ Telegram จริง


## แชทชั่วคราวและอายุประวัติ — รุ่นก่อนหน้า (11 ตุลาคม 2026)

PostgreSQL จริงผ่าน **121 เคส** SQLite ชั่วคราวผ่าน **107 เคส/ข้าม PostgreSQL-only 14 เคส** TypeScript และ Next.js production build ผ่าน อัปเกรด migration `chat_retention` และเปิด API/worker/web รุ่นล่าสุดแล้ว

Chrome desktop/mobile ผ่าน **22/22** พร้อมตรวจขั้นตอนแชทชั่วคราว/ตั้งอายุซ้ำ 2/2 หลังปรับระยะเมนู ตรวจ 13 หน้า × 3 ความกว้าง (1440/393/360) = **39 จุดไม่พบ horizontal overflow** ตรวจภาพแชทชั่วคราว desktop/mobile จริงแล้ว

เคสใหม่ตรวจแชทชั่วคราวไม่อยู่ในประวัติ หมดอายุแล้วส่ง/อ่าน/ดูรูปไม่ได้ งานหมดอายุไม่เรียกโมเดล ล้างข้อความ/งาน/รูปที่ไม่เหลือการอ้างอิง เก็บรูป Inbox และรูปที่ห้องอื่นอ้างอิง อายุประวัติแยกผู้ใช้/พื้นที่ ต่ออายุจากข้อความผู้ใช้ PostgreSQL ล้างพร้อมกันไม่ซ้ำ และข้อจำกัด privacy/temporary บนฐานข้อมูลยังอยู่ครบ

สำรองก่อนอัปเกรดและกู้คืนหลังอัปเกรดในฐาน disposable ผ่าน ตรวจจำนวนแถวแชท/ข้อความ/งาน/นโยบายอายุ และ snapshot นโยบายร่วมกับสมาชิก/คำเชิญ/ตารางประจำ/แผนออม ledger ยังสมดุล ห้องเก่าเริ่มนับอายุใหม่ตอน migration และไม่ถูกล้างเองโดยค่าเริ่มต้น

ข้อจำกัด: เก็บชั่วคราวใน PostgreSQL ไม่ใช่ Incognito แบบไม่เขียนดิสก์ Worker อาจทยอยล้างหลังหมดอายุ API ปิดการเข้าถึงแล้วแต่ backup/Cloud ไม่ถูกลบด้วย อายุไม่ครอบคลุม Inbox/หลักฐานการเงิน ยังอยู่ขั้น 3/4 ไม่มีผลยืนยันบริการจริงหรือ Ubuntu/Hyper-V


## สมาชิกและคำเชิญ — รุ่นก่อนหน้า (11 ตุลาคม 2026)

- PostgreSQL จริงในฐาน `finance_test`: **114 passed**; SQLite ชั่วคราว: **101 passed, 13 PostgreSQL-only skipped**
- TypeScript และ Next.js production build ผ่าน Docker Compose อัปเกรดถึง migration `workspace_members` แล้ว API/ฐานข้อมูล/Redis ทำงานปกติ
- Chrome desktop และ Pixel 7 emulation: **20/20 ผ่าน** รวมบริการเดิมและการรับคำเชิญสร้างบัญชี เปลี่ยนสิทธิ์ และตัดสิทธิ์หลังนำออก
- ตรวจ 13 หน้า × 1440/393/360px = **39 จุด ไม่พบ horizontal overflow** ตรวจภาพสมาชิก desktop/mobile และหน้ารับคำเชิญจริงแล้ว
- สำรองก่อนอัปเกรดและกู้คืน backup หลังอัปเกรดในฐาน disposable ผ่าน จำนวนแถวและ snapshot สมาชิก/คำเชิญ/ตารางประจำ/การจัดสรรตรงกัน และ ledger สมดุล

เคสใหม่ตรวจรหัสเก็บเฉพาะ hash/ไม่คืนรหัสเดิม, หมดอายุ/ยกเลิก/อีเมลไม่ตรง, สมาชิกเชิญ/จัดการเจ้าของไม่ได้, register-invite rollback ทั้งชุดเมื่อเต็มพื้นที่, cookie ใช้งานได้หลังตอบสำเร็จ, ไม่เพิ่มสมาชิกซ้ำเมื่อรับรหัสพร้อมกัน, อีเมลเดียวสร้างบัญชีพร้อมกันจากสองพื้นที่ได้ครั้งเดียว และประวัติแบ่งหน้า/ห้ามแก้ย้อนหลัง

ตรวจ PostgreSQL concurrency เมื่อเจ้าของสองคนออกพร้อมกันต้องเหลือหนึ่งคน และ worker ถือ workspace authorization lock แล้วการนำออกต้องรอให้ธุรกรรมเดิมจบก่อน ไม่กลับสิทธิ์จากรหัสเชิญเก่าหลังนำออก Telegram link/code ถูกลบ งานค้างของสมาชิกที่ถูกนำออกไม่เรียกโมเดล แชทส่วนตัวไม่เปิดให้เจ้าของคนอื่นอ่านทั้งก่อนและหลังจัดการสมาชิก

ผลนี้เป็น Docker/Colima บนเครื่องพัฒนา ยังไม่ใช่การยืนยัน Ubuntu/Hyper-V, email delivery, provider/Telegram จริง หรือ load/security audit แผนรวมยังอยู่ขั้น 3/4 รายละเอียดงานที่เหลืออยู่ใน ROADMAP.md

## บันทึกการตรวจรุ่นก่อนหน้า

ตรวจวันที่ 10 ตุลาคม 2026 (Asia/Bangkok) บน macOS host และ Docker/Colima Linux ARM64 ไม่ได้เข้าถึง Ubuntu/Hyper-V ของผู้ใช้

| การตรวจ | ผล |
|---|---|
| Docker Compose build ของ Next.js standalone และ Python backend | ผ่าน |
| Alembic migrations บน PostgreSQL 17 | ผ่าน |
| API / PostgreSQL / Redis health checks | ผ่าน |
| Backend tests บน PostgreSQL จริงใน finance_test | **47 passed** |
| Backend tests บน SQLite แยกชั่วคราว | **44 passed, 3 PostgreSQL-only cases skipped** |
| TypeScript typecheck | ผ่าน |
| Next.js production build | ผ่าน |
| Chrome desktop 1440×1000 / Pixel 7 emulation | **10 passed** (รวมงบประมาณ แชท รายงาน และเมนู) |
| ตรวจ layout จาก screenshot desktop/mobile | ผ่าน; ไม่พบ horizontal page overflow |
| npm audit ของ production dependencies | ไม่พบช่องโหว่ที่รายงาน ณ เวลาตรวจ |
| pip-audit หลังอัปเดตชุด dependencies | ไม่พบช่องโหว่ที่รายงาน ณ เวลาตรวจ |
| pip check | ไม่พบ dependency conflict |
| HTTPS Compose override syntax พร้อม placeholder domain | ผ่าน; ไม่ได้ขอ certificate จริง |
| pg_dump backup + pg_restore ในฐานข้อมูล disposable | ผ่าน; จำนวนแถวตรงและ ledger สมดุล |

Backend tests ครอบคลุม:

- รายรับ/รายจ่าย/โอน/จ่ายบัตร ยอดตั้งต้นสินทรัพย์และหนี้สิน รายงานไม่รวมโอน/จ่ายบัตรซ้ำ
- จำนวนเงินผิดรูปแบบ ศูนย์ ติดลบ ทศนิยมสตางค์ผิด type และเกินขอบเขต
- Workspace membership, cross-workspace account rejection และ composite FK ระดับฐานข้อมูล
- Deferred balance check, journal immutability และป้องกันเติม line ภายหลัง
- Concurrent idempotent posting 4 threads และ request replay/conflict
- Proposal ต้องยืนยัน ยืนยันซ้ำไม่ลงบัญชีซ้ำ และรายการปฏิเสธยืนยันไม่ได้
- รูปผิดชนิด รูปซ้ำ และข้าม workspace ดูรูปไม่ได้
- Worker demo extraction, model output ผิด schema, retry/fallback, model ไม่ได้สิทธิ์บันทึก ledger
- Private chat ไม่เรียก Cloud แม้มี Cloud provider, history/delete, history privacy ระหว่างสมาชิก
- API key encryption, ไม่คืน key ผ่าน API และ owner-only provider configuration
- CSRF origin/header, session cookie flags, logout/revocation, invalid password, throttle/fail-closed
- Telegram linking ใช้รหัสได้ครั้งเดียว และยกเลิก link

Browser tests ครอบคลุมล็อกอิน → dashboard → ส่งข้อความเข้า Inbox → worker → เลือกบัญชี/หมวดหมู่ → manual confirm → เห็นรายการจริง → private chat/mock reply → logout ทั้ง desktop และ mobile

ตัวเลขและภาพหน้าจอทั้งหมดเป็น workspace สาธิต ไม่ใช่ข้อมูลการเงินจริง Tests เพิ่มรายการสมมติในบัญชี demo; source archive ไม่รวม credentials, screenshots, database dumps หรือ .env

Warnings ที่เหลือ: Starlette เตือนว่า TestClient ที่ใช้ httpx จะเลิกใช้ในอนาคต ไม่มี test failure รุ่นนี้ยังใช้ httpx สำหรับ provider adapter และทดสอบผ่านครบ

ยังไม่ได้ยืนยัน: Cloud API/ภาพจริงผ่าน provider, Ollama model จริง, Telegram long polling จริง, domain/TLS จริง, Hyper-V VM เป้าหมาย, load test, formal penetration test, container OS vulnerability scan และ browser PWA installation/offline audit ข้อจำกัดฟีเจอร์ทั้งหมดอยู่ใน README หัวข้อขอบเขตรุ่นนี้

การตรวจ package vulnerabilities เป็นผลตามฐานข้อมูลที่เครื่องมือเข้าถึง ณ เวลาตรวจ ไม่ได้แทนการตรวจความปลอดภัยทั้งระบบ ควรตรวจซ้ำก่อนอัปเดตหรือเปิดบริการให้ผู้อื่น

## UI refresh — โทนสว่างและตัวอักษรใหญ่ขึ้น

ปรับพื้นหลังเป็นขาวนวล/ลาเวนเดอร์ การ์ดสีขาว ตัวอักษรหลัก 17px หัวข้อหลัก 36px และยอดเงิน 36px; ปุ่มหลักสูง 48px บนมือถือแสดงเมนูครบ 6 รายการและการ์ดยอดเงินเต็มแถว

Production build และ TypeScript ผ่าน Browser flow เดิมผ่าน 2/2 บน desktop/mobile อีกครั้ง ตรวจทุกหน้า (Dashboard, Transactions, Accounts, Inbox, Assistant, Settings) ที่ความกว้าง 1440, 393, 360px รวม 18 จุด ไม่พบ horizontal overflow และยืนยัน computed body font 17px/palette light ภาพผลอยู่ใน artifacts/light-*.png ไม่รวมใน source ZIP การแก้ครั้งนี้เป็น UI เท่านั้น

## Web Chat Images

เพิ่ม migration `chat_images` และทดสอบ PostgreSQL 31/31, SQLite 29 ผ่าน (ข้าม 2 PostgreSQL-only): ส่งรูปพร้อมข้อความ/รูปอย่างเดียว, ประวัติและการดูภาพ, ownership ก่อนเผยแพร่เป็น Inbox, ข้าม workspace ไม่ได้, ลบห้องยกเลิกงาน, รูปไม่ถูกต้องไม่สร้างข้อความ/งานค้าง, Private ไม่เรียก Cloud, caption ไม่ถูก mock แปลเป็นยอดสลิป, model vision request ส่ง JPEG และ caption, ผลโมเดลไม่ลงบัญชีเอง และรูปซ้ำไม่สร้างข้อเสนอเพิ่ม

การอ่านภาพด้วย provider ใช้ mock HTTP ตรวจรูปแบบ request/response ยังไม่ได้ใช้ API key หรือ Ollama vision model จริง

Chrome desktop/mobile ผ่าน 2/2: เลือกรูป → แสดง preview → นำออก → ส่งรูปอย่างเดียว → แสดงคำตอบและรูป → reload และเปิดห้องเดิม → รูปยังเปิดได้ → จำนวนรายการเงินไม่เปลี่ยน พร้อมตรวจ horizontal overflow แก้ race ที่งาน AI เสร็จก่อนหน้าเว็บเห็นสถานะ pending แล้วทำให้คำตอบไม่อัปเดต

ทดสอบ browser รอบนี้ใช้บัญชีสมมติแยกใน artifacts/e2e-access.json เพราะ credentials ของ demo เดิมไม่ตรง ไม่แก้รหัสหรือข้อมูลของบัญชีเดิม รันซ้ำได้ด้วย SF_DEMO_CREDENTIALS='../artifacts/e2e-access.json' ใน frontend หรือสร้าง demo ใหม่ตาม README บนเครื่องติดตั้งใหม่ ไฟล์ credentials ไม่รวมใน source archive

## UX/UI rebuild — โครงหน้าการเงินและแอป AI Chat แยกกัน

เปลี่ยน stylesheet เดิมที่ซ้อนหลายรุ่นเป็นชุดเดียว โทนขาวนวล/เขียวอ่อน desktop sidebar 216px, mobile bottom navigation 5 รายการและ header สั้น แชทเต็ม viewport มี history drawer, focus trap/Escape บนมือถือ, แยกส่วนข้อความเลื่อนจากช่องพิมพ์, auto-scroll คำตอบล่าสุด, textarea ยืดตามเนื้อหา, Enter/Shift+Enter บน desktop และ VisualViewport resize เพื่อปรับพื้นที่ compose ดูข้อกำหนดใน UI.md

TypeScript และ Next production build ผ่าน; Chrome 4/4 ครอบคลุม flow การเงิน/แชทรูปเดิมทั้ง desktop/mobile และเพิ่มตรวจเมนู/หน้าต้อนรับ/ข้อความแนะนำ/ซ่อนและเปิด history/ปิด drawer ด้วย Escape พร้อมคืน focus/ย่อ viewport ให้ composer ยังอยู่ในจอ

ตรวจทุกหน้า (overview, transactions, accounts, inbox, assistant, settings) ที่ 1440, 393, 360px รวม 18 จุดหลังโหลดข้อมูลครบ ไม่พบ horizontal overflow แชทสูงเท่า viewport และ composer อยู่ในจอ ภาพผลอยู่ใน artifacts/redesign-*.png, assistant-new-*.png และ chat-*.png เป็นข้อมูลบัญชีทดสอบ ไม่รวมใน source ZIP

ยังไม่ได้ตรวจแป้นพิมพ์บน iOS/Android เครื่องจริงหรือ accessibility audit เต็มรูปแบบ Browser mobile เป็น Chrome emulation การเปลี่ยนนี้ไม่เพิ่มฟีเจอร์การเงินที่ยัง pending ใน ROADMAP.md และไม่ได้แก้ backend/ledger

## Monthly reports / transaction explorer / chat reports

- Backend: PostgreSQL **36 passed**; SQLite **34 passed, 2 skipped**. เพิ่ม tests ช่วงวันแบบ inclusive, page totals จากข้อมูลเต็ม, wildcard search literal, กรองบัญชี/หมวดร่วมกัน, transfer ไม่ซ้ำ, foreign workspace filter rejection, dashboard recent เฉพาะเดือน, ย้อนเดือนข้ามปี, เดือนผิดรูปแบบ และ report chat ไม่เรียก provider/ไม่ลงบัญชี
- AI report: ทดสอบเดือนที่แล้ว → คำถามต่อเนื่องบัญชีไหน → เดือนที่ระบุ → วันไม่ถูกต้อง → บัญชีไม่รู้จัก → บัญชีที่มีจริง มีการระบุช่วงวัน/ขอบเขตชัดเจน และตอบจากข้อมูลจริง ตัวกรองบัญชีใน query ใช้ correlated EXISTS ที่ผูกกับ Entry โดยตรง
- Chrome desktop/mobile **6 passed**: flow เดิมครบและเพิ่มเลือกเดือนก่อน/เปิด dialog/กลับเดือนปัจจุบัน, category drilldown, เลือกช่วงวัน, ค้นหาและล้างค้นหา, กรองหมวด และไม่ล้นจอ
- ตรวจ screenshot ทั้ง 6 หน้าที่ 1440/393/360px รวม 18 จุด ไม่พบ horizontal page overflow; chat composer ยังอยู่ใน viewport
- TypeScript/Next production build ผ่าน ไม่มี migration ใหม่ แกน ledger เดิมและการยืนยัน manual ไม่เปลี่ยน ยอดบัญชีแสดง latest ชัดเจน ไม่อ้างเป็นยอดสิ้นเดือน
- ข้อจำกัด: เทียบเต็มเดือนกับเต็มเดือนก่อน ไม่ใช่ MTD เท่ากัน; report chat รองรับรูปแบบที่กำหนด ไม่ใช่ SQL/tool-calling อิสระ; แสดง 20 รายการต่อคำตอบ (รวมยอดเต็ม) และย้อนหลังไม่เกิน 366 วันต่อคำถาม บริการ AI จริงและเครื่อง Ubuntu/Hyper-V ยังไม่ได้ทดสอบ

## Services hub / accounts and categories

เพิ่ม `/services` และ `/categories` แยกบัญชีเงิน/หนี้จากหมวดรายรับ/รายจ่าย; Mobile 5 tab ใช้ “ทั้งหมด” เข้าบริการรอง Desktop มีเมนูบริการทั้งหมดและส่วนจัดการ เมนูเลื่อนได้เมื่อจอเตี้ย จัดการ loading ให้ไม่แสดงจำนวนศูนย์/หมวดว่างก่อนข้อมูลพร้อม

Browser เพิ่มทดสอบค้นหาบริการ/empty/reset, เลือกบัญชีจาก hub, focus form ที่ปุ่มหัวหน้า, เพิ่มบัญชีเงินจริงผ่าน API, หมวดไม่แสดงบัญชีเงิน, สลับหมวดรายรับแล้ว form ตรงประเภท, สร้างหมวดและกดไป filtered transactions, ลิงก์ Telegram ไปส่วน settings และ mobile navigation ครบ 5 tab

ตรวจ screenshot ทั้ง 8 หน้าที่ 1440/393/360px รวม 24 จุด ไม่พบ horizontal overflow TypeScript/Next production build ผ่าน Ledger, backend API และสิทธิ์ workspace ใช้ชุดเดิม ผล backend รอบล่าสุดยังเป็น PostgreSQL 36 ผ่าน (ไม่มีการแก้ backend ในรอบนี้)

รอบ browser แรกชน login rate limit จากการทดสอบหลายรอบติดกัน จัดการเฉพาะ counters ของบัญชีทดสอบและ development proxy แล้วรันทดสอบใหม่ ไม่เปลี่ยนหรือลดการป้องกัน login ของระบบ

รันทดสอบ browser รอบสุดท้ายครบ **8 passed** ทั้ง desktop/mobile หลังปรับ loading และเมนูใหม่

## Monthly budgets

- PostgreSQL **47 passed** รวม concurrent budget upsert 4 threads ได้เพียงหนึ่งวงเงินต่อหมวด/เดือน; SQLite **44 passed, 3 PostgreSQL-only cases skipped** (หลังแก้ copy count ตรวจ budget tests เพิ่ม 10 passed, 1 skipped)
- Migration `monthly_budgets` เพิ่มตารางโดยไม่แก้ ledger พร้อม composite FK category/workspace, unique workspace/month/category และ amount check สำรองข้อมูลก่อนอัปเดต local DB แล้ว migration/health checks ผ่าน
- รวมยอดใช้จริงตามวันที่เกิด expense ในเดือน ไม่รวม pending Inbox/โอน/จ่ายบัตรซ้ำ ทดสอบยอดขอบเดือน, หมวดไม่มีงบ, status ใกล้เต็ม/ครบ/เกิน, แก้ไข/ลบไม่เปลี่ยนยอดบัญชี, validation จำนวนเงินและประเภทบัญชี, ข้าม workspace ทั้ง API และ DB FK
- คัดลอกเดือนก่อนข้ามปี เติมเฉพาะหมวดที่ขาด เรียกซ้ำไม่เพิ่มซ้ำ PostgreSQL driver รายงาน rowcount ไม่แน่นอน จึงนับจาก `RETURNING` ของแถวที่เพิ่มจริง
- AI budget reports คำนวณบน backend ไม่เรียก model/ไม่สร้างหรือแก้งบและไม่ลง ledger
- Chrome **10 passed**: รวมสร้าง disposable workspace/รายการรายจ่าย, ตั้งงบและเงินเหลือจริง, แก้เป็นเกินงบ, reload แล้วข้อมูลอยู่, เลือก workspace อยู่ต่อข้ามหน้า/reload, คัดลอกเดือนถัดไปแบบไม่ทับของเดิม, นำวงเงินออกแล้ว ledger ยังอยู่ครบ ทั้ง desktop/mobile
- ตรวจทั้ง 9 หน้าที่ 1440/393/360px รวม 27 จุด ไม่พบ page overflow ตรวจภาพงบที่มีข้อมูล/เกินงบทั้ง desktop/mobile ด้วย
- Next production build/TypeScript ผ่าน Source archive ไม่รวม DB backup, credentials หรือ .env
- ข้อจำกัด: ไม่มี rollover เงินเหลือ/งบรายสัปดาห์/แจ้งเตือน push/ประวัติแก้งบ (shared plan แก้ล่าสุดมีผล) เป้าหมายออม รายการประจำ และ correction/reversal ยัง pending

ตรวจ backup/restore หลัง migration ด้วยฐานข้อมูล disposable แล้ว จำนวนแถวรวม budgets ตรงกันและ ledger สมดุล


## Transaction correction / reversal — 11 ตุลาคม 2026

- PostgreSQL **61 passed**; SQLite **55 passed, 6 PostgreSQL-only cases skipped**. รองรับแก้ไขและกลับรายการครบ opening/income/expense/transfer/card payment โดยไม่แก้ ledger เดิม
- ทดสอบแก้ยอดแล้ว balances/report totals/dashboard/budget/AI direct report ตรงกัน ย้ายวันที่ไปเดือนก่อนและเปลี่ยนบัญชี/หมวดแล้วเดือนเดิมเป็นศูนย์ เดือนใหม่ใช้ยอดทดแทน กลับรายการล่าสุดแล้ว balances และรายงานเป็นศูนย์
- ตรวจเดบิต=เครดิตทุก journal; idempotency replay คืนผลเดิมและ key reuse กับข้อมูลอื่น 409; กดแก้/ยกเลิกรายการเก่าหรือ journal ภายในไม่ได้; foreign account/workspace/member isolation; invalid replacement rollback ทั้งชุด; PostgreSQL correction พร้อมกัน 4 threads ได้ audit เดียวและ ledger 3 journals
- Migration `entry_revisions` เป็น additive มี composite tenant FKs, unique original/reversal/replacement/action key, audit immutability trigger, inverse journal ตรวจ account sums ต้องตรงข้ามต้นฉบับและสร้างใน transaction เดียวกัน ทดสอบ DB ปฏิเสธปลอม inverse/foreign audit/update/delete audit
- พบ race หลัง HTTP login response ก่อน session commit ใน Chrome จึงเปลี่ยน DB dependency ทั้ง API/security เป็น `scope='function'` เพื่อ commit ก่อนส่ง response ไม่เพิ่ม retry กลบปัญหา เพิ่ม ASGI regression ตรวจจาก connection แยกตอน `http.response.start` ว่า session/workspace commit แล้ว และ commit failure ต้องตอบ 500 พร้อม rollback
- Browser setup ของ test ใหม่ต้อง reload membership ก่อนเลือก workspace ที่เพิ่งสร้าง แก้ test ให้รอข้อมูลจริง ไม่เปลี่ยนข้อมูลบัญชีเดิม ใช้เฉพาะ workspace สาธิตแยกกัน
- Chrome รอบสุดท้าย **12 passed** ทั้ง desktop/mobile รวมแก้ยอด 75 → 125.50 บาท ตรวจ dashboard/budget/balance ก่อนและหลังยกเลิก ยอดกลับเป็นศูนย์ เปิดต้นฉบับที่ยกเลิกเป็น read-only และรีโหลดแล้วประวัติ 2 เหตุการณ์ยังครบ
- TypeScript และ Next production build ผ่าน ตรวจ 9 หน้าที่ 1440/393/360px รวม 27 จุดไม่พบ page overflow แชท composer ยังอยู่ใน viewport ตรวจภาพรายละเอียด/ประวัติทั้ง desktop/mobile แล้ว
- สำรองก่อน migration และทดสอบ restore หลังทดสอบ browser ในฐาน disposable แล้ว จำนวนแถวรวม entry_revisions ตรงกันและ ledger สมดุล
- การรันทดสอบซ้ำล้างเฉพาะ login counters ของบัญชีสมมติและ proxy local ไม่เปลี่ยน threshold หรือปิด throttle ของระบบ

ข้อจำกัด: การแก้ใช้ประเภทรายการเดิม ยอดตั้งต้นคงบัญชีเดิม แต่แก้จำนวนเงิน/วันที่ได้; ไม่มี restore ปุ่มเดียวสำหรับรายการที่ยกเลิก; ประวัติแชร์ตามสิทธิ์ workspace ไม่ใช่ chat ส่วนตัว; การแก้วงเงินงบยังไม่มี audit trail; ไม่ได้ทดสอบมือถือเครื่องจริง Ubuntu/Hyper-V หรือ provider/Telegram จริง


## CSV exports — 11 ตุลาคม 2026

- PostgreSQL **77 passed**, SQLite **71 passed, 6 PostgreSQL-only cases skipped**. เพิ่ม export transactions/history, ใช้ filter conditions ชุดเดียวกับรายงาน และไม่แบ่งตามหน้าจอ 30 แถว
- ทดสอบ UTF-8 BOM/Thai/CSV quoting ของ comma/quotes/newline, จำนวนเงิน 0.01 และ 1,000,000,000.00 บาทแบบไม่มี float, inclusive dates, literal wildcard search, account/category/type filters, ทิศ transfer/card payment และไม่รวม pending
- แก้ยอด/ย้ายเดือนแล้วไฟล์ปัจจุบันมีเฉพาะรายการทดแทน ยกเลิกแล้วหายจาก export ปัจจุบัน ประวัติยังมีข้อมูลเดิม/ใหม่ เหตุผลและผู้แก้ ทดสอบ 31 เหตุการณ์เพื่อยืนยันว่าไม่ตัดตาม pagination
- History filter ใช้ created_at ของการแก้ไขตาม Asia/Bangkok ตรวจขอบ 00:00:00.000 และ 23:59:59.999 รวมทั้งก่อน/หลัง 1 ms เทียบรายการบนหน้าและ CSV ให้ตรงกัน โดยวันที่เกิดรายการต้นฉบับเป็นคนละเดือน
- Guard จำกัด 10,000 แถว ตรวจด้วยการลด threshold เฉพาะ test: เกินขีดจำกัดได้ JSON 413 ไม่มี attachment หรือไฟล์บางส่วน Empty export มี header, invalid filters 422, unauthenticated 401, foreign member/workspace/account/category 404 สมาชิก workspace ดาวน์โหลดได้ตามสิทธิ์รายงาน
- ข้อความที่เสี่ยง spreadsheet formula (`=`, `+`, `-`, `@`, leading whitespace/control/BOM) เติม apostrophe โดยไม่แก้ต้นทาง ทดสอบทั้ง description/account/category/reason; ไม่มี chat/รูป/provider secrets ใน schema ไฟล์
- Chrome **14 passed** ทั้ง desktop/mobile รวมดาวน์โหลดจริง 32 รายการข้ามหน้า, กรองเหลือ 1, แก้ 1.31 → 76.54, export history ก่อน/หลัง, empty header-only, error message และ balances ไม่เปลี่ยนจาก export ค้นหา CSV ใน service hub แล้วเข้าหน้าส่งออกได้
- TypeScript/Next production build ผ่าน ตรวจ 9 หน้าที่ 1440/393/360px รวม 27 จุด ไม่พบ page overflow ตรวจภาพ history export ทั้ง desktop/mobile แล้ว สำรองและ restore ฐาน disposable หลัง browser tests ผ่าน จำนวนแถวและ ledger balance ตรงกัน
- ไม่มี migration ใหม่ ไม่มีไฟล์ export เก็บบนเซิร์ฟเวอร์ Runtime credentials/downloads/screenshots/backups ไม่รวมใน source ZIP ล้างเฉพาะ counters ของบัญชีทดสอบ/proxy local เพื่อรันทดสอบซ้ำ ไม่เปลี่ยน login throttle

ข้อจำกัด: CSV เท่านั้น ไม่มี XLSX/PDF/import หรือ export background job; ไม่เกิน 10,000 แถวต่อไฟล์; ไม่มี export แชท/รูปแบบ bundle; CSV export ไม่ใช่ DB backup เปิดไฟล์ด้วย Excel/Numbers และทดสอบมือถือเครื่องจริงยังไม่ได้ทำ เครื่อง Ubuntu/Hyper-V และ provider/Telegram จริงยัง pending เช่นเดิม

## Savings goals — 11 ตุลาคม 2026

- PostgreSQL **87 passed**; SQLite **80 passed, 7 PostgreSQL-only cases skipped**. TypeScript และ Next production build ผ่าน
- Migration `savings_goals` เพิ่ม goals/goal_movements พร้อม composite workspace FK, idempotency uniqueness, amount checks และ PostgreSQL immutable allocation trigger/deferred aggregate guard สำรองก่อน migration แล้วอัปเดต local Docker สำเร็จ ไม่แก้ ledger เดิม
- ทดสอบ create/replay/conflict, validation จำนวนเงินแบบ strict/ชื่อว่าง/วันที่ผิด/วันที่อนาคต, เพิ่ม/นำออกเกินยอด, edit stale version, ถึงเป้า/เลยกำหนด, archive/reopen และ safe replay หลัง archive, scope/API/DB FK/สิทธิ์ member, ประวัติ 31 เหตุการณ์แบ่ง 30/1, limit 500 เป้าหมายและยอดจัดสรรสูงสุด
- PostgreSQL ทดสอบ 4 threads สร้างรหัสเดิมได้หนึ่งเป้าหมาย จัดสรรรหัสเดิมได้หนึ่งเหตุการณ์ นำออกพร้อมกันไม่ติดลบ ทดสอบ SQL update/delete ประวัติถูกปฏิเสธ และ direct insert ที่ทำให้ยอดติดลบ commit ไม่ผ่าน ยอดบัญชีและ ledger ไม่เปลี่ยนจากแผนออม
- Chrome **16 passed** รวม desktop 8 + Pixel 7 emulation 8 (รันแยก project และล้างเฉพาะ local test login counters ระหว่างรอบ ไม่เปลี่ยน throttle) ครอบคลุมสร้างแผนออม/จัดสรร 250/นำออก 50/แก้เป้าเป็น 200/ถึงเป้า/reload/ประวัติสองเหตุการณ์/archive/reopen/workspace isolation และฟีเจอร์เดิม
- ตรวจ 10 หน้าที่ 1440/393/360px รวม **30 จุด** ไม่พบ horizontal page overflow แชท composer อยู่ใน viewport ตรวจภาพหน้าเป้าหมายที่มีข้อมูลทั้ง desktop/mobile แล้ว (ภาพใช้ข้อมูลสมมติและไม่รวม source ZIP)
- สำรองและ restore ฐาน disposable หลัง browser tests จำนวนแถวรวม goals/goal_movements และยอดจัดสรรรายเป้าหมายตรงกัน ledger สมดุล Runtime credentials/.env/DB dump ไม่รวม source archive

ข้อจำกัด: เป็นแผนจัดสรรที่ผู้ใช้บันทึกเอง ไม่ผูกบัญชี ไม่ตรวจว่ามีเงินจริง และไม่โอน/กันเงินอัตโนมัติ ไม่มี recurrence/แจ้งเตือน/AI goal reports/goal export หรือประวัติแก้ชื่อ/ยอดเป้า ยังไม่ได้ตรวจมือถือเครื่องจริง Ubuntu/Hyper-V หรือ provider/Telegram จริง อยู่ในขั้น 3 จาก 4 ตาม ROADMAP.md

## Recurring schedules — 11 ตุลาคม 2026

- PostgreSQL **104 passed**; SQLite **96 passed, 8 PostgreSQL-only cases skipped**. TypeScript และ Next production build ผ่าน
- Migration `recurring_rules` ต่อจาก `savings_goals` เพิ่มตารางกำหนดรอบ/ประวัติ และ unique proposal/workspace เพื่อทำ composite tenant FK มี PostgreSQL trigger ป้องกัน update/delete ประวัติรอบ สำรองก่อน migration และอัปเดต Docker local ผ่าน ไม่เปลี่ยน ledger เดิม
- ทดสอบ daily/weekly/monthly, มกราคมวันที่ 30/31 → กุมภาพันธ์ 28/29 → มีนาคมวันที่เดิม, inclusive end, create/replay/conflict, strict amounts/blank descriptions/past start/end/invalid frequency/year, account/category kinds, tenant/API/DB isolation และ member access
- ตรวจ pause/resume พร้อม backlog, ครั้งละไม่เกิน 10 รอบต่อตาราง, pending cap และไม่เลื่อนวันข้ามรอบเมื่อเต็ม, ประวัติ 32 รอบแบ่ง 30/2, worker scheduling และ pending-first Inbox แม้มี rejected ใหม่กว่า 101 รายการ
- PostgreSQL 4 threads สร้างตารางรหัสเดิมได้หนึ่งตาราง และสร้างข้อเสนอของรอบเดียวกันได้หนึ่งรายการ ทดสอบ crash ก่อน commit แล้วข้อเสนอ/ประวัติ/วันถัดไป rollback พร้อมกัน สั่ง SQL แก้/ลบประวัติรอบถูกปฏิเสธ
- ข้อเสนอเก็บวันที่ บัญชี หมวด และยอดตามแผนตอนสร้าง แก้ตารางแล้วข้อเสนอเก่าไม่เปลี่ยน ยืนยันซ้ำไม่สร้าง ledger ซ้ำ ยกเลิกรอบหนึ่งแล้วไม่สร้างรอบนั้นซ้ำและไม่หยุดรอบถัดไป การสร้างข้อเสนอไม่เปลี่ยน balances/ledger
- Chrome **18 passed ในรอบเดียว**: desktop 9 + Pixel 7 emulation 9 รวมตั้งรายการ 600 บาท/ตรวจถึงกำหนด/แก้ตารางเป็น 650/พัก-เปิดใหม่/reload/ตรวจ snapshot 600 ใน Inbox/เปลี่ยนยอดจริงเป็น 555 ก่อนยืนยัน/ประวัติยังแสดงยอดตามแผน 600/เปิดรายละเอียดตรง ID เห็นยอดจริง 555 และ workspace isolation
- ทดสอบ worker ที่รันจริงใน Docker เพิ่มอีกรายการผ่าน API โดยไม่กดตรวจถึงกำหนด รอจนมีข้อเสนอ pending อัตโนมัติทั้ง desktop/mobile และตรวจว่า ledger ยังมีเฉพาะรายการที่ผู้ใช้ยืนยันไว้
- ปรับ browser auth helper ให้ reuse session ที่ยังใช้ได้ใน memory ภายใน Playwright worker ตรวจ `/auth/me` ก่อนใช้และยังทดสอบ UI login/logout จริง ไม่เก็บ cookies ลงไฟล์ ไม่ลด throttle รอบสุดท้ายทั้ง 18 tests ผ่านโดยไม่ต้องล้าง counters ระหว่าง desktop/mobile (เตรียมเฉพาะบัญชีทดสอบก่อนเริ่มรอบ)
- ตรวจ 11 หน้าที่ 1440/393/360px รวม **33 จุด** ไม่มี horizontal overflow แชท composer อยู่ใน viewport ตรวจภาพการ์ดรายการประจำและประวัติบน desktop/mobile แล้ว ช่อง select มีชื่อ aria-label ชัดเจน และทดสอบ dialog ไม่ล้นความกว้าง
- สำรองและ restore ฐาน disposable หลัง browser tests ผ่าน จำนวนแถวรวม recurring_rules/recurring_occurrences ตรงกัน รวมวันถัดไป/สถานะพัก/ข้อมูลรอบ และยอดจัดสรรเป้าหมายออมตรงกัน ledger สมดุล Source archive ไม่รวม credentials/.env/session states/DB dumps/runtime screenshots

ข้อจำกัด: รองรับรายรับ/รายจ่ายรายวัน สัปดาห์ เดือนเท่านั้น ไม่มี transfer/card payment ประจำ รอบรายปี กำหนดหลายวัน ปุ่มข้าม backlog รวม หรือแจ้งเตือน push/Telegram ไม่มี auto-post/auto-pay ตารางเดิมเปลี่ยนรายละเอียดได้แต่เปลี่ยนความถี่/วันเริ่ม-สิ้นสุดต้องพักแล้วสร้างใหม่ ไม่มี audit trail การแก้รายละเอียดตาราง และยังไม่มี AI อ่าน/สร้างรายการประจำ การตรวจอัตโนมัติต้องเปิด worker และอาจช้าลงตามงานในคิว ยังไม่ได้ตรวจมือถือเครื่องจริง Ubuntu/Hyper-V หรือ provider/Telegram จริง อยู่ระหว่างขั้น 3 จาก 4

## 2026-10-11 — AI diagnostics และปุ่มหยุด Web Chat

- PostgreSQL disposable DB: **384 tests passed** ทั้ง backend หลัง migration `chat_generation_stop` ครอบคลุม queued stop, stop ระหว่าง worker ถือ workspace/job lock, silent-thinking stream close, late draft/text rejection, queued stop ในอีกห้องระหว่าง workspace ถูกล็อก, room/user scope, idempotency, งานที่ commit แล้วไม่เปลี่ยน และ usage accounting หลัง rollback
- Provider diagnostics: ทดสอบ HTTP 400/401/404/429/500/redirect, missing model, tools/images/Thinking ไม่รองรับ, connect/read timeout, configured probe timeout, ไม่สะท้อน upstream secrets, fallback ไปโมเดลสำรอง และ all-provider failure ไม่ post ข้อมูล Tests ใช้ MockTransport ไม่ได้เรียก Ollama/Cloud จริง
- Browser: **10 scenarios ผ่านในการรันทดสอบสุดท้ายของแต่ละไฟล์** (desktop/mobile: chat-stop, chat-stream, ai-settings, chat-actions, chat-defaults) ปุ่มหยุดแสดงก่อน token แรก, disabled ขณะ stopping, ละทิ้ง late chunks, โหลดประวัติหยุด, พิมพ์ต่อได้ และไม่ล้นจอ ภาพ `artifacts/chat-stop-desktop.png` / `chat-stop-mobile.png` ตรวจแล้ว งาน Inbox ที่ไม่เกี่ยวข้องไม่ทำให้ห้องนี้แสดงกำลังคิด จึงแก้ assertion เก่าและรัน chat-actions ซ้ำจนผ่านทั้งสองขนาด
- TypeScript typecheck, production Docker build และ HTTP root 200 ผ่าน Docker services ในเครื่อง healthy; migration head `chat_generation_stop` ไม่มีการ deploy เครื่อง Ubuntu ของผู้ใช้
- ข้อจำกัด: upstream close เป็น best effort หลัง headers อาจรอ timeout ก่อนจบ และไม่รับประกันยกเลิกการประมวลผลหรือค่าบริการฝั่ง provider; ปุ่มหยุดครอบคลุม Web Chat เท่านั้น ยังต้องทดสอบกับ Ollama/provider จริงบนเครื่องผู้ใช้

- Backup/restore หลัง migration ผ่านใน disposable DB รวมจำนวนแถวและ snapshot `chat_generations.stop_requested` และ ledger สมดุล (backup `finance-20261011T144653Z.dump`)

## 2026-10-11 — อ่านหน้าเว็บระหว่าง AI ตอบช้า

- Backend PostgreSQL disposable DB: **387 tests passed** รวมทดสอบคำขอ GET dashboard/accounts/transactions/proposals/conversations/jobs/message history/AI settings/providers/preferences/usage ระหว่าง worker ถือ workspace lock และ mock upstream ยังไม่ส่ง response headers ทุก endpoint ตอบ 200 ภายใน 2 วินาทีและเห็นเฉพาะ committed state งานใน jobs ยัง pending ตามจริง
- ตรวจ workspace ที่ archive และสมาชิกที่ถูกนำออกแล้วได้ 404 ตามเดิม ตรวจ mutation dependency ถือ Workspace FOR UPDATE จริงจาก connection อิสระด้วย NOWAIT รวม regression ledger, isolation, membership และปุ่มหยุดทั้งชุด
- เปลี่ยนเฉพาะ read authorization ไม่เพิ่ม schema migration และไม่ลด write guards การเขียนใน workspace เดียวกันยังอาจรอ inference ไม่ได้ตรวจสาเหตุ RAM/OOM/502/restart บน Ubuntu ของผู้ใช้
- Backend Docker build และ Compose health ผ่าน; HTTP root 200; browser chat-defaults และ chat-stop ผ่านทั้ง desktop/mobile **4 tests** หลังอัปเดต backend ในเครื่อง ไม่มีการ deploy Ubuntu server

## 2026-10-11 — ยอดเงินรวมและ AI ค้นวน

- PostgreSQL disposable DB: **393 tests passed** ครอบคลุมยอดรวมทุกบัญชีขณะที่แสดงเพียง1แถว, cursor/query scope, บัญชียอด0, opening/expense/income/transfer/card payment/credit expense, หนี้แยกจากเงินและสุทธิ, ไม่ปนยอดอีก workspace และถาม “ต่อ” แล้วอ่านยอดปัจจุบันใหม่
- ทดสอบคำถาม “ตอนนี้ฉันมีเงินเท่าไร?” ผ่าน MockTransport: lookup balances หนึ่งครั้งแล้วตอบธรรมชาติ, โมเดลขอ balances เดิมซ้ำแล้วตอบด้วยยอดจาก backend ใน2คำขอ, การอ่านชนิดอื่นซ้ำแล้วสรุปด้วย final request ที่ไม่มี tools และกรณีอ่าน3ชุดต่างกันยังมีขอบเขต5คำขอ
- Final synthesis ไม่ดำเนินการ tools แม้โมเดลส่ง prepare_transaction ที่มีข้อมูลครบกลับมา ไม่มี ChatAction หรือ ledger entry ใหม่ Regression confirmation/tenant isolation/stop/read responsiveness ผ่านทั้งชุด ไม่เพิ่ม migration
- Tests ไม่ได้เรียก Gemma/Ollama บนเครื่องผู้ใช้ จึงยังต้องลองคุณภาพการเลือก tools ของโมเดลจริง ไม่รับประกันความถูกต้องของข้อความธรรมชาติที่โมเดลสร้างทุกประโยค
- Backend Docker build/Compose health ผ่าน, root HTTP 200; browser chat-stream/chat-stop **4 tests passed** ทั้ง desktop/mobile ไม่มีการ deploy เครื่องผู้ใช้ Source archive รวมไฟล์ใหม่และตรวจ integrity/runtime secrets

## AI lab และ metadata diagnostics (11 ตุลาคม 2026)

- PostgreSQL disposable database: **409 passed** ทั้ง backend (เพิ่ม 16 เคสจาก 393; Starlette/httpx deprecation warning เดิมหนึ่งรายการ) ตรวจ 5 โจทย์สังเคราะห์ผ่าน HTTP MockTransport, tool arguments/ยอดผิด/บัญชีอื่น/management tool ถูกปฏิเสธโดยไม่สร้าง Entry, ChatAction, Proposal, Conversation หรือ Message จริง; selected/fallback provider, Cloud-off, owner/tenant isolation, pending guard, budget ก่อน network, token accounting, metadata redaction, retention และ clear ผ่าน
- Chrome Playwright **8 passed** (desktop 4/mobile 4): AI lab, AI settings, Stop และ streaming; lab เรียกเริ่มเฉพาะกดปุ่ม มีโจทย์ 5 แบบ สถานะรอ/ผ่าน ขั้นตอน/tokens และล้างประวัติ ไม่มี horizontal overflow หน้า lab ใช้ API response mock เพื่อไม่เรียก provider จริง ชุด backend ตรวจ network pipeline ผ่าน MockTransport แยกต่างหาก
- TypeScript typecheck และ Docker build backend/worker/migrate/web ผ่าน backend `e5571883a6fb`, web `e0e65ea5e10b`; local Compose healthy, migration `ai_diagnostics`, หน้าแรก HTTP 200
- สำรอง `finance-20261011T153150Z.dump` และกู้คืนใน disposable database ผ่าน ตรวจจำนวนแถว snapshots รวม `jobs.diagnostics`/expiry และ journals สมดุล
- ไม่ได้ทดสอบ Ollama/Gemma หรือ Cloud provider ของผู้ใช้จริง ไม่ deploy Ubuntu server ผล lab เป็นการตรวจโจทย์ตัวอย่าง ไม่ใช่การรับรองคุณภาพทั่วไป งาน AI ยังใช้ workspace write lock เดิม และผล diagnostics ปรากฏหลัง job commit

## แก้ข้อความยืนยันที่ไม่มีร่าง และ lab lookup (11 ตุลาคม 2026)

- Backend PostgreSQL disposable database: **421 passed** (เพิ่ม 12 เคส; warning Starlette/httpx เดิม 1 รายการ) ครอบคลุมโมเดลทวนเป็น prose → ขอแก้ → draft จริง → plain ยืนยันครั้งเดียว, ปฏิเสธ prose ซ้ำ, ถามรายงานไม่กลายเป็น draft, กู้ห้อง legacy ที่ยืนยันแล้วไม่มี action, schema lookup แบบ inline, q/null/empty optional fields, error field metadata ไม่รั่ว input, lab อ่าน preferences/ยอดและโอกาสแก้คำสั่งหนึ่งรอบภายในเพดานเดิม
- Browser Chrome Playwright **8 passed** (คอม 4/มือถือ 4): diagnostics แสดงชื่อช่องผิด, ยืนยัน/แก้รายการเดี่ยว, batch/กันซ้ำ และหยุด AI; ตรวจภาพเฉพาะ AI lab บนมือถือ ไม่มี horizontal overflow
- TypeScript และ Docker build ผ่าน backend `90246f993da2`, web `4553313b9e3d`; local Compose healthy หน้าแรก HTTP 200 ไม่มี migration ใหม่
- สำรอง `finance-20261011T160644Z.dump` และตรวจ restore ใน disposable database ผ่าน: จำนวนแถวและ snapshots รวม diagnostics ตรงกัน ledger สมดุล
- การเรียกโมเดลใน regression ใช้ HTTP mock ยังไม่ได้ติดต่อ Gemma จริงของผู้ใช้ รายงานเก่าที่ไม่มี arguments ไม่พอระบุว่าช่องใดทำให้ invalid_arguments จึงไม่อ้างว่าพิสูจน์สาเหตุของทั้ง 4 โจทย์บนเครื่องผู้ใช้แล้ว ต้องอัปเดตและรันทดสอบใหม่ ข้อความทวนที่ผู้ใช้ส่งยืนยันว่ามีกรณีโมเดลอ้างว่าร่างพร้อมทั้งที่ backend ไม่มี action; การแก้ไม่อนุญาตให้บันทึกจาก prose

## ปรับโครงสร้าง AI Chat runtime (11 ตุลาคม 2026)

- Backend PostgreSQL disposable database: **431 passed** (warning Starlette/httpx เดิม 1 รายการ) เพิ่ม 10 tests สำหรับ lazy toolkit → review → ยืนยัน, repair ชนิดข้อมูล/ID, invalid reads ไม่กิน successful-read budget, canonical cache, cached evidence หลัง retry, partial draft ที่พ้นหน้าต่างประวัติ/หมดอายุ, batch clarification คงรายการทั้งหมด, bounded account choices และเพดาน 8 คำขอร่วมกับ retries/fallback
- Browser Chrome Playwright **10 passed** (desktop 5/mobile 5): diagnostics, typed confirmation/correction, batch/duplicate protection, stop/late output และ streaming/progress/reconnect/room switching ตรวจภาพ live answer มือถือและข้อความสถานะด้วย assertions; ไม่ได้ตรวจทุกหน้าของแอปใหม่
- TypeScript และ production Docker build ผ่าน backend `1431bde29eff`, web `e0768ea8da2d`; local Compose healthy หน้าแรก HTTP 200 ไม่มี migration ใหม่ ไม่ deploy Ubuntu server
- สำรอง `finance-20261011T162801Z.dump` และตรวจ restore ใน disposable database ผ่าน จำนวนแถว/configuration snapshots ตรงกันและ journals สมดุล
- วัด system instruction + initial tool schemas ด้วย workspace ตัวอย่างเดียวกัน: 26,405 → 12,814 UTF-8 bytes ลด 51.5% ไม่ใช่ token/cost/latency benchmark และไม่รวมประวัติ รูป ผลอ่าน หรือชุดเครื่องมือเพิ่มเติม
- Model regression ใช้ HTTP mocks ยังไม่ได้เรียก Gemma/Ollama ของผู้ใช้จริง Worker ยังถือ workspace write lock ระหว่าง inference; request cap เป็นต่อ processing attempt ไม่ใช่ durable cap หลัง crash ดูข้อจำกัดและแผนต่อที่ AI_RUNTIME.md

## Gemma batch intent และการแยก output limit (11 ตุลาคม 2026)

- Backend **435 passed**, warning Starlette/httpx เดิม 1 รายการ เพิ่ม tests: child intent default โดย root intent ยังคงจำเป็นและ amount strict, lab prose repair ผ่านเมื่อได้ร่างจริงเท่านั้น/ปฏิเสธ prose ซ้ำโดยไม่มีการเขียนข้อมูล, SSE/JSON finish_reason length แยก output_limit
- Browser **4 passed** desktop/mobile สำหรับ diagnostics และ batch review/แก้/ยืนยัน/กันซ้ำ; TypeScript และ production build ผ่าน backend `9726be4cd910`, web `3411dab6f0e0`; local Compose healthy ไม่มี migration และไม่ได้ deploy Ubuntu
- ไม่ได้เรียก Gemma จริง ผลทดสอบโมเดลใช้ HTTP mocks ไม่สรุปสาเหตุรายเดือน answer_mismatch หรือสลิป invalid จาก metadata เก่าเพียงอย่างเดียว ไม่เปลี่ยนจำนวนเงินที่คาดหวังเพื่อทำให้ผลผ่าน

## Verified summary tool สำหรับงานเลขา (11 ตุลาคม 2026)

- Backend **444 passed** (warning Starlette/httpx เดิม 1 รายการ) เพิ่ม 9 เคส: ยอดเงินและรายเดือนผ่าน model request เดียวแล้ว render จาก backend, ไม่เพิ่ม ledger, invalid month/filter/report ถูกปฏิเสธ, cents exact และชื่อหมวดไม่สร้าง Markdown link/HTML, lab ทั้ง balance/monthly ผ่าน tool ใหม่ด้วย fixture เท่านั้น
- Production backend build `6edf2e54321a`, local Compose healthy, HTTP root 200; ไม่มี frontend changes หรือ migration ใหม่ในรอบนี้ จึงไม่ได้รัน browser suite ซ้ำ
- Backup `finance-20261011T164740Z.dump` และ disposable restore ผ่าน snapshots/row counts/ledger balance ไม่ deploy Ubuntu และไม่ได้เรียก Gemma จริง การคุมตัวเลขโดย renderer ครอบคลุม tool ใหม่เท่านั้น ไม่รับรองคำตอบอิสระทุกชนิดของโมเดล

## ปิด AI Chat audit ทั้ง 6 ข้อ — 12 ตุลาคม 2026

- Final PostgreSQL disposable suite: **457 passed** (Starlette/httpx deprecation warning เดิม 1 รายการ) เพิ่ม 13 adversarial/concurrency cases: fabricated balance, false saved claim, wrong category scope, wrong fallback report, writes during inference, membership revocation, room deletion, crash/claim recovery with persisted usage, suppressed raw stream, lab numeric false positive corrected by renderer, independent workspace jobs, prose embedded in tool, unsupported comparison fails closed
- AI Lab ใช้ production converse loop ผ่าน synthetic adapter; ไม่อ่านบัญชีจริงและไม่ resolve drafts ในห้องทดสอบ Expected-output checks ของตัวเลขดิบถูกแทนด้วยผลที่ backend render จาก fixture ที่ตรวจแล้ว ผลผ่านไม่ใช่คะแนนความถูกต้องของ raw model prose
- Browser Chrome Playwright **10 passed** (desktop/mobile อย่างละ 5): diagnostics label, confirmation/correction/replay, batch, stop/late output และ UI stream/reconnect/room change; raw production preview suppression ตรวจใน backend integration ด้วย ตรวจ screenshot AI lab มือถือและไม่มี horizontal overflow
- TypeScript และ production build ผ่าน backend `aee3ea5ea32e`, web `63d78e0ab2d8`; local Compose healthy HTTP root 200; migration head `ai_evidence_epoch` สำเร็จ ไม่มีการ deploy Ubuntu ของผู้ใช้
- Backup ก่อน migration `finance-20261011T171000Z.dump`; หลัง migration `finance-20261011T171657Z.dump` และ disposable restore ผ่าน row counts/configuration snapshots รวม `workspaces.ai_epoch` และ journals สมดุล
- Network model tests ใช้ HTTP mocks ไม่ได้เรียก Gemma/Ollama ของผู้ใช้จริง ขอบเขตภาษา/รายงานที่ยังตีความไม่ได้ต้องถามเพิ่ม ไม่รับรองความแม่นยำของโมเดลทุกคำถาม Tests count เป็น regression evidence ไม่ใช่ model-quality score
