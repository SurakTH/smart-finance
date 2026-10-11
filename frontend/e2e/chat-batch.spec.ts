import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('batch drafts review, edit and warn about duplicates before one typed confirmation',async({page},info)=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'ชุดรายการ '+crypto.randomUUID()}})).json();const base='/api/workspaces/'+ws.id;
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'หลายรายการพร้อมกัน'}})).json();
 await page.evaluate(wid=>sessionStorage.setItem('sf-workspace',wid),ws.id);await page.goto('/assistant?conversation='+room.id);
 const input=page.getByLabel('ข้อความถึง AI',{exact:true});const last=()=>page.locator('.message.assistant').last();
 async function send(text:string){await input.fill(text);await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();await expect(input).toHaveValue('');}
 const command='บันทึกรายจ่าย กาแฟ 75 บาท บัญชี เงินสด หมวด อาหารและเครื่องดื่ม\nบันทึกรายจ่าย ข้าว 80 บาท บัญชี เงินสด หมวด อาหารและเครื่องดื่ม';
 const report=async()=>(await(await page.request.get(base+'/transaction-report')).json());
 await send(command);await expect(last()).toContainText('2 รายการ');expect((await report()).total).toBe(0);
 await send('แก้ยอดรายการที่ 2 เป็น 90 บาท');await expect(last()).toContainText('฿90.00');await expect(last()).toContainText('฿75.00');
 await last().screenshot({path:`../artifacts/chat-batch-${info.project.name}.png`});
 await send('ยืนยัน');await expect(last()).toContainText('ทั้งชุด 2 รายการ');expect((await report()).expense).toBe(16500);
 await send('ยืนยัน');await expect(last()).toContainText('ไม่มีการบันทึกซ้ำ');expect((await report()).total).toBe(2);
 await send(command);await expect(last()).toContainText('อาจซ้ำ');expect((await report()).total).toBe(2);
 await send('ยกเลิก');await expect(last()).toContainText('ยกเลิกข้อเสนอ');expect((await report()).total).toBe(2);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
