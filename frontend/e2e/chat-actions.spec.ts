import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('chat reviews before typed confirmation, prevents replay and preserves correction history',async({page},info)=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'ยืนยันผ่านแชท '+Date.now()}})).json();const base=`/api/workspaces/${ws.id}`;
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'ทวนก่อนบันทึก'}})).json();
 await page.goto('/assistant');const mobile=(page.viewportSize()?.width||1440)<=900;
 async function history(){if(mobile&&await page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true}).getAttribute('aria-expanded')!=='true')await page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true}).click();}
 await history();await page.getByLabel('เลือก workspace ในแชท',{exact:true}).selectOption(ws.id);await history();await page.locator('.rooms button').filter({hasText:'ทวนก่อนบันทึก'}).click();
 async function send(text:string){const input=page.getByLabel('ข้อความถึง AI',{exact:true});await input.fill(text);await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();await expect(input).toHaveValue('');}
 const report=async()=>await(await page.request.get(base+'/transaction-report')).json();
 await page.locator('.chat-action-help summary').click();await page.getByRole('button',{name:'ใส่ตัวอย่างคำขอบันทึก',exact:true}).click();
 await expect(page.getByLabel('ข้อความถึง AI',{exact:true})).toHaveValue(/กาแฟ 75 จากเงินสด/);
 await page.locator('.chat-action-help summary').click();await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();
 const reviews=page.locator('.message.assistant').filter({hasText:'กรุณาตรวจสอบ — ยังไม่บันทึก'});await expect(reviews).toHaveCount(1);expect((await report()).total).toBe(0);
 await send('ยืนยัน');await expect(page.locator('.message.assistant').last()).toContainText('บันทึกรายการเรียบร้อยแล้ว');expect((await report()).expense).toBe(7500);
 await send('ยืนยัน');await expect(page.locator('.message.assistant').last()).toContainText('ไม่มีการบันทึกซ้ำ');expect((await report()).total).toBe(1);
 const id=(await report()).items[0].id;
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);await page.goto('/transactions');await page.getByLabel(mobile?'เลือก workspace บนมือถือ':'เลือก workspace',{exact:true}).selectOption(ws.id);await page.getByRole('button',{name:'รายละเอียด กาแฟ',exact:true}).click();await page.getByRole('button',{name:'คัดลอกคำขอแก้ผ่านแชท',exact:true}).click();await expect(page.locator('dialog[open]')).toHaveCount(0);await expect(page.getByRole('status').filter({hasText:'คัดลอกแล้ว'})).toBeVisible();const copied=await page.evaluate(()=>navigator.clipboard.readText());expect(copied).toContain('แก้รายการ '+id);
 await page.goto('/assistant');await history();await page.getByLabel('เลือก workspace ในแชท',{exact:true}).selectOption(ws.id);await history();await page.locator('.rooms button').filter({hasText:'ทวนก่อนบันทึก'}).click();await send(copied.replace('จำนวน: 75.00','จำนวน: 95.00'));await expect(reviews).toHaveCount(2);await expect(reviews.last()).toContainText('ก่อนแก้ไข:');await expect(reviews.last()).toContainText('฿95.00');expect((await report()).expense).toBe(7500);
 await reviews.last().screenshot({path:`../artifacts/chat-action-review-${info.project.name}.png`});
 await send('ยืนยัน');await expect(page.locator('.message.assistant').last()).toContainText('เก็บประวัติเดิม');expect((await report()).expense).toBe(9500);expect((await(await page.request.get(base+'/transaction-history')).json()).total).toBe(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
