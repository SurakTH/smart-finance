import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('chat follows the selected workspace across navigation and reload without a room mode picker',async({page})=>{
 await signIn(page);const headers={'X-SF-Request':'1'},mobile=(page.viewportSize()?.width||1440)<=900;
 const create=async(name:string)=>(await(await page.request.post('/api/workspaces',{headers,data:{name}})).json());
 const a=await create('พื้นที่ปัจจุบัน '+('ชื่อยาว'.repeat(8))+' '+Date.now()),b=await create('เปลี่ยนเอง '+Date.now());
 const globalLabel=mobile?'เลือก workspace บนมือถือ':'เลือก workspace';
 await page.reload();await page.getByLabel(globalLabel,{exact:true}).selectOption(a.id);
 await page.goto('/assistant');
 async function history(){if(mobile&&await page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true}).getAttribute('aria-expanded')!=='true')await page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true}).click();}
 await history();await expect(page.getByLabel('เลือก workspace ในแชท',{exact:true})).toHaveValue(a.id);
 await expect(page.getByText('โหมดของห้องใหม่',{exact:true})).toHaveCount(0);
 await expect(page.locator('option[value="private"],option[value="standard"]')).toHaveCount(0);
 await page.getByRole('button',{name:'บทสนทนาใหม่',exact:true}).click();
 await expect(page.locator('.chat-topbar strong')).toContainText(a.name);
 await expect(page.locator('.privacy-pill')).toContainText('เก็บประวัติ');
 await expect(page.locator('.composer-meta')).toContainText('ใช้ AI ตามการตั้งค่าของ workspace นี้');
 async function send(text:string){const input=page.getByLabel('ข้อความถึง AI',{exact:true});await input.fill(text);await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();await expect(input).toHaveValue('');}
 await send('กาแฟ 75 จากเงินสด');await expect(page.locator('.message.assistant').last()).toContainText('กรุณาตรวจสอบ');
 expect((await(await page.request.get(`/api/workspaces/${a.id}/conversations`)).json()).length).toBe(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await history();await page.getByLabel('เลือก workspace ในแชท',{exact:true}).selectOption(b.id);
 await expect(page.locator('.chat-topbar strong')).toContainText(b.name);await expect(page.locator('.message')).toHaveCount(0);
 await send('กาแฟ 75 จากเงินสด');await expect(page.locator('.message.assistant').last()).toContainText('กรุณาตรวจสอบ');
 await send('ยืนยัน');await expect(page.locator('.message.assistant').last()).toContainText('บันทึกรายการเรียบร้อย');
 expect((await(await page.request.get(`/api/workspaces/${a.id}/transaction-report`)).json()).total).toBe(0);
 expect((await(await page.request.get(`/api/workspaces/${b.id}/transaction-report`)).json()).expense).toBe(7500);
 await page.goto('/');await expect(page.getByLabel(globalLabel,{exact:true})).toHaveValue(b.id);
 await page.goto('/assistant');await page.reload();await history();await expect(page.getByLabel('เลือก workspace ในแชท',{exact:true})).toHaveValue(b.id);
});
