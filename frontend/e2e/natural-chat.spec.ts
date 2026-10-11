import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('natural capture asks missing details, confirms corrections and scrolls through older messages',async({page})=>{
 await signIn(page);const headers={'X-SF-Request':'1'},ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'แชทภาษาธรรมชาติ '+crypto.randomUUID()}})).json(),base='/api/workspaces/'+ws.id;
 await page.request.post(base+'/accounts',{headers,data:{name:'ธนาคาร',kind:'asset'}});
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'ห้องทดสอบภาษาธรรมชาติ'}})).json();
 await page.evaluate(wid=>sessionStorage.setItem('sf-workspace',wid),ws.id);await page.goto('/assistant?conversation='+room.id);await expect(page.locator('.rooms .selected')).toContainText('ห้องทดสอบภาษาธรรมชาติ');
 async function send(text:string){const input=page.getByLabel('ข้อความถึง AI',{exact:true});await input.fill(text);await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();await expect(input).toHaveValue('');}
 const last=()=>page.locator('.message.assistant').last();await send('เมื่อกี้จ่ายค่ากาแฟ 75 บาท');await expect(last()).toContainText('ใช้บัญชีไหน');await send('เงินสดจ้า');await expect(last()).toContainText('กรุณาตรวจสอบ — ยังไม่บันทึก');
 const total=async()=>(await(await page.request.get(base+'/transaction-report')).json()).total;expect(await total()).toBe(0);await send('ยืนยัน');await expect(last()).toContainText('บันทึกรายการเรียบร้อย');
 await send('แก้รายการล่าสุดเป็น 90 บาท');await expect(last()).toContainText('ก่อนแก้ไข');await expect(last()).toContainText('฿90.00');await send('ยืนยัน');await expect(last()).toContainText('เก็บประวัติเดิม');
 let earliest='';for(let i=0;i<60;i++){await page.request.post(base+'/conversations/'+room.id+'/messages',{headers,data:{text:`กาแฟ ${101+i} จากเงินสด`}});if(i===0){const rows=(await(await page.request.get(base+'/conversations/'+room.id+'/messages/page')).json()).items;earliest=rows.find((m:any)=>m.content==='กาแฟ 101 จากเงินสด').id;}}
 await page.reload();await expect(page.locator('.message')).toHaveCount(50);expect(await page.locator('#chat-message-'+earliest).count()).toBe(0);
 const log=page.getByRole('log',{name:'ข้อความในบทสนทนา'});await log.evaluate(el=>{el.scrollTop=0;});await expect(page.locator('.message')).toHaveCount(100);await log.evaluate(el=>{el.scrollTop=0;});await expect(page.locator('#chat-message-'+earliest)).toHaveCount(1);expect(await total()).toBe(1);
 // Polling for new replies must not discard already loaded history.
 await page.waitForTimeout(2800);await expect(page.locator('#chat-message-'+earliest)).toHaveCount(1);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
