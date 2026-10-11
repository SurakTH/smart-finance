import {signIn} from './auth';
import {test,expect} from '@playwright/test';
test('AI settings persist, keys stay hidden and model routes work on desktop and mobile',async({page},info)=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const created=await page.request.post('/api/workspaces',{headers,data:{name:'AI settings '+info.project.name+' '+Date.now()}});expect(created.ok()).toBe(true);const {id:wid}=await created.json();
 expect((await page.request.put(`/api/workspaces/${wid}/ai/settings`,{headers,data:{cloud_enabled:false}})).ok()).toBe(true);
 const workspaceLabel=(page.viewportSize()?.width||1440)<=900?'เลือก workspace บนมือถือ':'เลือก workspace';
 await page.getByLabel(workspaceLabel,{exact:true}).selectOption(wid);await expect(page.getByLabel(workspaceLabel,{exact:true})).toHaveValue(wid);await page.goto('/settings');await page.getByRole('link',{name:'เปิดศูนย์ตั้งค่า AI'}).click();
 await expect(page.getByRole('heading',{name:'เลือก AI ที่เข้ากับคุณ',exact:true})).toBeVisible();
 const cloud=page.getByRole('checkbox',{name:'อนุญาต Cloud AI',exact:true});await expect(cloud).not.toBeChecked();await cloud.check();await expect(page.getByRole('status')).toContainText('บันทึกการตั้งค่า');
 async function add(name:string,model:string){
  await page.getByRole('button',{name:'เพิ่มโมเดลแชท',exact:true}).click();const dialog=page.locator('dialog[open]');
  await dialog.getByLabel('ชื่อเรียก',{exact:true}).fill(name);await dialog.getByRole('combobox',{name:'ผู้ให้บริการ',exact:true}).selectOption('compatible');await dialog.getByLabel(/^Custom API Base URL/).fill('https://api.example.com/v1');await dialog.getByLabel('ชื่อโมเดล',{exact:true}).fill(model);await dialog.getByLabel('API key',{exact:true}).fill('test-key-never-returned');await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 }
 await add('ผู้ช่วยหลัก','first-model');await add('ผู้ช่วยสำรอง','second-model');
 const cards=page.locator('.ai-provider');await expect(cards).toHaveCount(2);
 // Sorting is stable even when legacy priorities match. Save an explicit initial route.
 let rows=await(await page.request.get(`/api/workspaces/${wid}/providers`)).json();
 await page.request.put(`/api/workspaces/${wid}/ai/routes`,{headers,data:{task:'chat',provider_ids:['first-model','second-model'].map(model=>rows.find((p:{model:string;id:string})=>p.model===model).id)}});await page.reload();
 await expect(cards.first()).toContainText('ผู้ช่วยหลัก');await page.getByRole('button',{name:'เลื่อนขึ้น second-model',exact:true}).click();await expect(cards.first()).toContainText('ผู้ช่วยสำรอง');
 const first=cards.filter({hasText:'ผู้ช่วยหลัก'});await first.getByRole('button',{name:'แก้ไข',exact:true}).click();let dialog=page.locator('dialog[open]');await expect(dialog.getByLabel('API key',{exact:true})).toHaveValue('');await dialog.getByLabel('ชื่อเรียก',{exact:true}).fill('ผู้ช่วยหลักรุ่นใหม่');await dialog.locator('summary').click();await dialog.getByLabel('Timeout (วินาที)',{exact:true}).fill('35');await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 await page.getByRole('checkbox',{name:'เปิดใช้ ผู้ช่วยหลักรุ่นใหม่',exact:true}).uncheck();await expect.poll(async()=>{const values=await(await page.request.get(`/api/workspaces/${wid}/providers`)).json();return values.find((p:{name:string;enabled:boolean})=>p.name==='ผู้ช่วยหลักรุ่นใหม่')?.enabled;}).toBe(false);await page.reload();await expect(page.getByRole('checkbox',{name:'เปิดใช้ ผู้ช่วยหลักรุ่นใหม่',exact:true})).not.toBeChecked();await expect(cloud).toBeChecked();await expect(cards.first()).toContainText('ผู้ช่วยสำรอง');await expect(cards.last()).toContainText('รอ 35 วินาที');
 const response=await page.request.get(`/api/workspaces/${wid}/providers`);expect(await response.text()).not.toContain('test-key-never-returned');
 await page.screenshot({path:`../artifacts/ai-settings-${info.project.name}.png`,fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.getByRole('button',{name:'ลบโมเดล second-model',exact:true}).click();dialog=page.locator('dialog[open]');await dialog.getByRole('button',{name:'ยืนยันลบโมเดล',exact:true}).click();await expect(cards).toHaveCount(1);
 const blank=await(await page.request.post('/api/workspaces',{headers,data:{name:'AI empty '+crypto.randomUUID()}})).json();await page.request.put(`/api/workspaces/${blank.id}/ai/settings`,{headers,data:{cloud_enabled:false}});await page.reload();await page.getByLabel(workspaceLabel,{exact:true}).selectOption(blank.id);await expect(cards).toHaveCount(0);await expect(cloud).not.toBeChecked();
});
