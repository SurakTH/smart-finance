# ใช้ Nginx เดิมกับ Smart Finance

แนะนำใช้ subdomain แยก เช่น `finance.example.com` โดย Nginx เดิมจัดการ HTTPS/certificate และส่งทุก path มาที่ gateway ของแอป `127.0.0.1:8080` บนเครื่องเดียวกัน ไม่ต้องแย่งพอร์ต 80/443 และไม่ต้องเปิด PostgreSQL/Redis/API ออกอินเทอร์เน็ต รุ่นนี้ยังไม่รองรับติดตั้งใต้ path อย่าง `/finance/`

## 1. ตั้งค่าแอป

แก้ `.env` ของ Smart Finance (แทนโดเมนด้วยของจริง):

```dotenv
APP_ORIGIN=https://finance.example.com
COOKIE_SECURE=true
BIND_ADDRESS=127.0.0.1
APP_PORT=8080
```

`APP_ORIGIN` ต้องตรงกับโดเมนที่เปิดจริง รวม scheme/port ถ้ามี เพื่อให้ login, CSRF และลิงก์อีเมลทำงาน หากเปลี่ยนพอร์ต 8080 ให้แก้ proxy_pass ในไฟล์ host-location ให้ตรงด้วย

ใช้ Nginx แทน gateway Caddy ที่แถมมาได้ด้วยไฟล์ Compose เพิ่มเติม:

```sh
docker compose -f compose.yaml -f compose.nginx.yaml up -d --build
```

คำสั่งนี้เปลี่ยนเฉพาะ gateway เป็น Nginx และคง volumes/ข้อมูลเดิม สำหรับคำสั่ง Compose ถัดไปที่ปรับ service ให้ใช้ `-f` ทั้งสองไฟล์เหมือนเดิม เพื่อไม่ย้อน gateway กลับไปเป็น Caddy; หรือใส่ `COMPOSE_FILE=compose.yaml:compose.nginx.yaml` ใน `.env` บน Ubuntu แล้วใช้ `docker compose ...` ตามปกติ

ไฟล์ Caddyfile ที่ merge มาจาก Compose หลักอาจยังถูก mount แบบอ่านอย่างเดียว แต่ Nginx ไม่อ่านไฟล์นั้น ไม่ต้องแก้ Compose หลัก หากต้องการคง gateway Caddy ไว้ก็ใช้คำสั่งเดิมได้ Nginx ภายนอกยังส่งมาที่ 8080 เหมือนกัน

## 2. เพิ่มในเว็บไซต์ HTTPS ของ Nginx เดิม

ใน `server { ... }` ของ `finance.example.com` ที่มี certificate อยู่แล้ว ใส่เนื้อหาจาก `deploy/nginx/host-location.conf` หรือ include ด้วย absolute path หลีกเลี่ยงการมี `location /` ซ้ำใน server เดียวกัน รักษา TLS/certificate/HTTP redirect ของ Nginx เดิมไว้ตามที่ตั้งแล้ว

```nginx
# ภายใน server ที่ listen 443 ssl ของ finance.example.com
include /opt/smart-finance/deploy/nginx/host-location.conf;
```

แทน `/opt/smart-finance` ด้วยตำแหน่งติดตั้งจริง แล้วตรวจและ reload:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

ปิด response buffering/cache เพื่อให้ SSE แชททยอยตอบได้และไม่เก็บข้อมูลการเงินที่ proxy; ปิด request buffering เพื่อไม่เขียนรูปสลิป/ข้อความลง temp file; upload limit 10 MiB และ read timeout 1 ชั่วโมงตั้งไว้ในไฟล์แล้ว หลักการ proxy ดู [เอกสาร Nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering)

ไฟล์ตัวอย่างปิด access log และเก็บ error เฉพาะระดับ crit เพื่อหลีกเลี่ยง URL/ข้อมูลส่วนตัวใน log ไม่ส่งรหัสผ่าน/token ผ่าน query string แอปยังไม่เชื่อ X-Forwarded-For สำหรับ authentication/rate limit โดยนับ IP ของ gateway ร่วมกันพร้อมตัวนับรายอีเมล ไม่ควรเปิด trust proxy ทั้งหมดโดยไม่กำหนดขอบเขต

## Nginx อยู่ใน Docker หรือเครื่องอื่น

`127.0.0.1` หมายถึงเครื่อง/คอนเทนเนอร์ที่ Nginx ทำงานอยู่ ถ้า Nginx เป็นคอนเทนเนอร์ แนะนำเชื่อมกับ Docker network ของ Smart Finance แล้ว proxy ไป `http://proxy:80` (หรือกำหนด network alias ที่ไม่ซ้ำเมื่อมีหลายแอป) แทน loopback ตรวจ DNS/reconnect หลังสร้าง gateway ใหม่ใน config ของ Nginx ภายนอกด้วย

ถ้า Nginx อยู่คนละเครื่อง ให้ bind gateway ที่ private IP ของเซิร์ฟเวอร์แอปแทน `127.0.0.1`, เปลี่ยน proxy_pass เป็น private IP:8080 และจำกัด firewall ให้รับเฉพาะเครื่อง Nginx เส้นทางระหว่างเครื่องต้องเป็นเครือข่ายที่ไว้ใจได้หรือเข้ารหัสผ่าน tunnel/VPN; ตัวอย่าง loopback ในชุดนี้สำหรับ Nginx บน Docker host เดียวกัน

## ตรวจหลังติดตั้ง

เปิด HTTPS → login → รายการ/รายงาน → แชทเห็นคำตอบทยอยมา → แนบรูป → ทดลอง PWA จากมือถือจริง หาก login ติด 403 ตรวจ APP_ORIGIN และ Origin ของเบราว์เซอร์ ถ้า 502 ตรวจ gateway/web/api และ DNS ถ้า 413 ตรวจ client_max_body_size ทั้ง Nginx ภายนอกและ gateway

การตรวจบนเครื่องพัฒนาตรวจ syntax/HTTP routing ได้ ส่วน certificate, โดเมนจริง และ Nginx เดิมของผู้ใช้ยังต้องตรวจที่เครื่องปลายทาง
