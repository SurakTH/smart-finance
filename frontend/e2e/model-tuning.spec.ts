import {test,expect,type Page} from '@playwright/test';
import {signIn} from './auth';
const headers={'X-SF-Request':'1'};
async function prepare(page:Page){
 await signIn(page);
 const created=await page.request.post('/api/workspaces',{headers,data:{name:'ปรับโมเดล '+crypto.randomUUID()}});
 expect(created.ok()).toBe(true);const {id:wid}=await created.json();const base='/api/workspaces/'+wid;
 const model=await page.request.post(base+'/providers',{headers,data:{name:'ผู้ช่วยทดสอบ','kind':'compatible',endpoint:'http://192.168.1.30:8081/v1',model:'qwen-test',task:'chat',max_tokens:8192,temperature:30}});
 expect(model.ok()).toBe(true);
 await page.goto('/ai-settings?workspace='+wid);
 const card=page.locator('.ai-provider').filter({hasText:'ผู้ช่วยทดสอบ'});
 await card.getByRole('button',{name:'ปรับโมเดล',exact:true}).click();
 return {base,card,dialog:page.locator('dialog[open]')};
}
test('empty then type 32000 stays in custom mode, thinking and temperature persist, provider default is explicit',async({page})=>{
 const {base,card,dialog}=await prepare(page);
 await dialog.getByRole('combobox',{name:'โหมด Thinking',exact:true}).selectOption('high');
 const temperature=dialog.getByLabel('Temperature (0–2)',{exact:true});await expect(temperature).toBeEnabled();
 await temperature.fill('');await expect(temperature).toBeEnabled();await temperature.pressSequentially('0.7');
 const tokens=dialog.getByLabel('จำนวน tokens สูงสุด',{exact:true});await tokens.fill('');
 await expect(tokens).toBeEnabled();await expect(dialog.getByRole('radio',{name:/^กำหนดเอง/})).toHaveAttribute('aria-checked','true');
 // Empty and out-of-range values block submission, rather than becoming 0.
 await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toBeVisible();
 await tokens.pressSequentially('32000');await expect(tokens).toHaveValue('32000');
 await dialog.getByRole('button',{name:'131,072 tokens',exact:true}).click();await expect(tokens).toHaveValue('131072');
 await dialog.getByRole('button',{name:'32,000 tokens',exact:true}).click();
 await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 const rows=await(await page.request.get(base+'/providers')).json();expect(rows[0]).toMatchObject({max_tokens:32000,temperature:70,reasoning_effort:'high'});
 await page.reload();await card.getByRole('button',{name:'ปรับโมเดล',exact:true}).click();
 await expect(tokens).toHaveValue('32000');await expect(temperature).toHaveValue('0.7');
 await expect(dialog.getByRole('combobox',{name:'โหมด Thinking',exact:true})).toHaveValue('high');
 await dialog.getByRole('radio',{name:/^ให้ผู้ให้บริการกำหนด/}).click();await expect(tokens).toBeDisabled();
 await dialog.getByRole('radio',{name:/^กำหนดเอง/}).click();await expect(tokens).toHaveValue('32000');
 await dialog.getByRole('radio',{name:/^ให้ผู้ให้บริการกำหนด/}).click();
 await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 await page.reload();await expect(card).toContainText('ให้ผู้ให้บริการกำหนด');
 expect((await(await page.request.get(base+'/providers')).json())[0].max_tokens).toBe(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
test('sampling availability follows the provider, and changing provider does not erase temperature',async({page})=>{
 const {dialog}=await prepare(page);
 const temperature=dialog.getByLabel('Temperature (0–2)',{exact:true});
 await dialog.getByRole('combobox',{name:'โหมด Thinking',exact:true}).selectOption('high');
 await temperature.fill('0.65');
 await dialog.getByRole('combobox',{name:'ผู้ให้บริการ',exact:true}).selectOption('openai');
 await dialog.getByLabel('ชื่อโมเดล',{exact:true}).fill('o3');await expect(temperature).toBeDisabled();
 await dialog.getByRole('combobox',{name:'ผู้ให้บริการ',exact:true}).selectOption('ollama');
 await dialog.getByRole('combobox',{name:'โหมด Thinking',exact:true}).selectOption('high');
 await expect(temperature).toBeEnabled();await expect(temperature).toHaveValue('0.65');
 await dialog.getByRole('button',{name:'ยกเลิก',exact:true}).click();await expect(dialog).toHaveCount(0);
});
