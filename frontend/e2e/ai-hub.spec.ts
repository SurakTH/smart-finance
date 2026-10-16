import {test,expect,type Page} from '@playwright/test';
import {signIn} from './auth';
const headers={'X-SF-Request':'1'};
async function prepare(page:Page){
 await signIn(page);
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'ศูนย์ AI '+crypto.randomUUID()}})).json();
 const base='/api/workspaces/'+ws.id;
 await page.request.put(base+'/ai/settings',{headers,data:{cloud_enabled:false}});
 for(const p of [{name:'Cloud หลัก',kind:'compatible',model:'cloud-model',endpoint:'http://192.168.1.30:8081/v1',priority:0},{name:'Local หลัก',kind:'ollama',model:'local-model',priority:1},{name:'Local สำรอง',kind:'ollama',model:'backup-model',priority:2},{name:'พักไว้',kind:'ollama',model:'disabled-model',priority:3,enabled:false}]){
  expect((await page.request.post(base+'/providers',{headers,data:{...p,task:'chat'}})).ok()).toBe(true);
 }
 await page.goto('/ai-settings?workspace='+ws.id);
 await expect(page.getByRole('tab',{name:'โมเดลและลำดับ',exact:true})).toHaveAttribute('aria-selected','true');
 await expect(page.locator('.ai-provider')).toHaveCount(4);
 return base;
}
test('five panels separate shared settings from personal memory and preserve unsaved fields without automatic AI calls',async({page})=>{
 let probes=0,labStarts=0;
 page.on('request',r=>{if(r.method()==='POST'&&/\/providers\/[^/]+\/test$/.test(r.url()))probes++;if(r.method()==='POST'&&r.url().endsWith('/ai/tests'))labStarts++;});
 await prepare(page);
 await expect(page.getByRole('tablist',{name:'ศูนย์ตั้งค่า AI'}).getByRole('tab')).toHaveCount(5);
 await expect(page.getByRole('heading',{name:'ความจำส่วนตัว',exact:true})).toHaveCount(0);
 await expect(page.locator('.ai-provider').filter({hasText:'Cloud หลัก'})).toContainText('พักเพราะปิด Cloud');
 await expect(page.locator('.ai-provider').filter({hasText:'Local หลัก'})).toContainText('ตัวหลัก');
 await expect(page.locator('.ai-provider').filter({hasText:'Local สำรอง'})).toContainText('ตัวสำรอง');
 await expect(page.locator('.ai-provider').filter({hasText:'พักไว้'})).toContainText('ปิดไว้');
 await page.getByRole('tab',{name:'ความจำของฉัน',exact:true}).click();
 await page.getByRole('button',{name:'เพิ่มกฎ',exact:true}).click();await page.getByLabel('คำจับคู่ 1',{exact:true}).fill('ยังไม่บันทึก');
 await page.getByRole('tab',{name:'การใช้งานและงบ',exact:true}).click();
 await expect(page.getByRole('heading',{name:'การใช้งานและงบ AI',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'ความจำส่วนตัว',exact:true})).toBeHidden();
 await page.getByRole('tab',{name:'ความจำของฉัน',exact:true}).click();await expect(page.getByLabel('คำจับคู่ 1',{exact:true})).toHaveValue('ยังไม่บันทึก');
 await page.getByRole('tablist',{name:'ศูนย์ตั้งค่า AI',exact:true}).getByRole('tab',{name:'ห้องทดสอบ',exact:true}).click();await expect(page.getByRole('region',{name:'ทดสอบและวิเคราะห์ AI'})).toBeVisible();
 expect(probes).toBe(0);expect(labStarts).toBe(0);
 await page.reload();await expect(page.getByRole('tablist',{name:'ศูนย์ตั้งค่า AI',exact:true}).getByRole('tab',{name:'ห้องทดสอบ',exact:true})).toHaveAttribute('aria-selected','true');
 await page.getByRole('tab',{name:'การเชื่อมต่อ',exact:true}).click();
 await expect(page.getByRole('checkbox',{name:'อนุญาต Cloud AI',exact:true})).not.toBeChecked();
 await expect(page.getByRole('region',{name:'ทดสอบและวิเคราะห์ AI'})).toBeHidden();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
test('save-and-test is explicit, probes the saved model, and reports failed tests without losing saved settings',async({page})=>{
 const base=await prepare(page);let probes=0,pass=true;
 await page.route('**'+base+'/providers/*/test',async route=>{probes++;await route.fulfill(pass?{json:{ok:true,message:'เชื่อมต่อและเรียกโมเดลได้แล้ว'}}:{status:422,json:{detail:'โมเดลทดสอบไม่รองรับค่าที่เลือก'}});});
 const card=page.locator('.ai-provider').filter({hasText:'Local หลัก'});
 await card.getByRole('button',{name:'ปรับโมเดล',exact:true}).click();let dialog=page.getByRole('dialog');
 await dialog.getByLabel('ชื่อเรียก',{exact:true}).fill('Local ปรับแล้ว');
 expect(probes).toBe(0);
 await dialog.getByRole('button',{name:'บันทึกและทดสอบ',exact:true}).click();await expect(dialog).toHaveCount(0);
 const saved=page.locator('.ai-provider').filter({hasText:'Local ปรับแล้ว'});
 await expect(saved).toContainText('ทดสอบผ่าน');expect(probes).toBe(1);
 pass=false;await saved.getByRole('button',{name:'ปรับโมเดล',exact:true}).click();dialog=page.getByRole('dialog');
 await dialog.getByLabel('ชื่อเรียก',{exact:true}).fill('Local ยังบันทึกได้');
 await dialog.getByRole('button',{name:'บันทึกและทดสอบ',exact:true}).click();await expect(dialog).toHaveCount(0);
 await expect(page.locator('.ai-provider').filter({hasText:'Local ยังบันทึกได้'})).toContainText('ทดสอบไม่ผ่าน');
 expect((await(await page.request.get(base+'/providers')).json()).some((p:{name:string})=>p.name==='Local ยังบันทึกได้')).toBe(true);
 expect(probes).toBe(2);
});
