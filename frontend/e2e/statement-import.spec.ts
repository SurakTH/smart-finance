import {test,expect} from '@playwright/test';
import {signIn} from './auth';
const headers={'X-SF-Request':'1'};
async function workspace(page:any){await signIn(page);const r=await page.request.post('/api/workspaces',{headers,data:{name:'นำเข้า '+crypto.randomUUID()}});expect(r.ok()).toBe(true);const {id}=await r.json();return id as string;}

test('CSV review maps columns, confirms the complete ledger batch, and skips repeated uploads',async({page},info)=>{
 const wid=await workspace(page);const accounts=await(await page.request.get(`/api/workspaces/${wid}/accounts`)).json();const wallet=accounts.find((a:any)=>a.kind==='asset');
 const file={name:'example.csv',mimeType:'text/csv',buffer:Buffer.from('วันที่,รายละเอียด,เงินออก,เงินเข้า,หมวดหมู่\n20/10/2569,กาแฟทดสอบ,80,,อาหารและเครื่องดื่ม\n20/10/2569,เงินเดือนทดสอบ,,11000,เงินเดือน\n')};
 await page.goto('/imports?workspace='+wid);
 await page.getByLabel('บัญชีสำหรับนำเข้า').selectOption(wallet.id);
 await page.locator('input[type=file]').setInputFiles(file);
 await expect(page.getByRole('heading',{name:'2. จับคู่คอลัมน์ · 2 รายการ',exact:true})).toBeVisible();
 await expect(page.getByLabel('รูปแบบวันที่',{exact:true})).toHaveValue('dmy');
 await page.getByRole('button',{name:'ตรวจรายการก่อนบันทึก',exact:true}).click();
 await expect(page.getByRole('heading',{name:'3. ตรวจรายการก่อนบันทึก',exact:true})).toBeVisible();
 expect((await(await page.request.get(`/api/workspaces/${wid}/transaction-report`)).json()).total).toBe(0);
 await expect(page.getByLabel('นำเข้าแถว 2',{exact:true})).toBeChecked();
 await expect(page.getByLabel('หมวดแถว 2',{exact:true})).not.toHaveValue('');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`../artifacts/statement-import-${info.project.name}.png`,fullPage:true});
 await page.getByRole('button',{name:'ทวนก่อนบันทึก 2 รายการ',exact:true}).click();
 await expect(page.getByRole('heading',{name:'ยืนยันนำเข้า 2 รายการ?',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'ยืนยันและบันทึกทั้งชุด',exact:true}).click();
 await expect(page.getByRole('heading',{name:'บันทึกแล้ว 2 รายการ',exact:true})).toBeVisible();
 const report=await(await page.request.get(`/api/workspaces/${wid}/transaction-report`)).json();expect(report.total).toBe(2);
 await page.getByRole('button',{name:'นำเข้าไฟล์ถัดไป',exact:true}).click();
 await page.locator('input[type=file]').setInputFiles(file);
 await page.getByRole('button',{name:'ตรวจรายการก่อนบันทึก',exact:true}).click();
 await expect(page.getByText('เคยนำเข้าแล้ว · ข้าม',{exact:true})).toHaveCount(2);
 await expect(page.getByRole('button',{name:'ทวนก่อนบันทึก 0 รายการ',exact:true})).toBeDisabled();
});

test('today insights request uses Bangkok date for both bounds and compares yesterday',async({page})=>{
 const wid=await workspace(page);await page.goto('/insights?workspace='+wid);
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
 const request=page.waitForRequest(r=>r.url().includes('/insights?')&&new URL(r.url()).searchParams.get('start')===today&&new URL(r.url()).searchParams.get('end')===today);
 await page.getByRole('button',{name:'วันนี้',exact:true}).click();await request;
 await expect(page.getByRole('button',{name:'วันนี้',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(page.locator('.insight-compare-note')).toContainText('1 วัน');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('one connection creates chat and receipt profiles and edits their endpoint together',async({page})=>{
 const wid=await workspace(page),base=`/api/workspaces/${wid}`;
 await page.goto('/ai-settings?workspace='+wid+'&section=connections');
 await page.getByRole('button',{name:'เพิ่มการเชื่อมต่อ',exact:true}).click();
 await page.getByLabel('ชื่อการเชื่อมต่อ',{exact:true}).fill('Ollama ทดสอบ');
 await page.getByLabel('Base URL',{exact:true}).fill('http://192.168.1.20:11434');
 await page.getByRole('button',{name:'บันทึกการเชื่อมต่อ',exact:true}).click();
 await expect(page.getByText('บันทึกการเชื่อมต่อแล้ว โมเดลที่ผูกไว้ใช้ค่านี้ร่วมกัน',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'เพิ่มโมเดลจากการเชื่อมต่อนี้',exact:true}).click();
 let dialog=page.getByRole('dialog');await dialog.getByLabel('ชื่อโมเดล',{exact:true}).fill('model-chat');
 await expect(dialog.getByLabel('API key',{exact:true})).toHaveCount(0);
 await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 await page.getByRole('tab',{name:'การเชื่อมต่อ',exact:true}).click();
 await page.getByRole('button',{name:'เพิ่มโมเดลจากการเชื่อมต่อนี้',exact:true}).click();
 dialog=page.getByRole('dialog');await dialog.getByLabel('ชื่อโมเดล',{exact:true}).fill('model-vision');
 await dialog.getByLabel('งานที่ใช้',{exact:true}).selectOption('extract');
 await dialog.getByRole('button',{name:'บันทึกโมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 await page.getByRole('tab',{name:'การเชื่อมต่อ',exact:true}).click();
 await expect(page.locator('.shared-connections')).toContainText('ใช้กับ 2 โมเดล');
 await page.locator('.shared-connections').getByRole('button',{name:'แก้ไข',exact:true}).click();
 await page.getByLabel('Base URL',{exact:true}).fill('http://192.168.1.21:11434');
 await page.getByRole('button',{name:'บันทึกการเชื่อมต่อ',exact:true}).click();
 await expect(page.getByText('บันทึกการเชื่อมต่อแล้ว โมเดลที่ผูกไว้ใช้ค่านี้ร่วมกัน',{exact:true})).toBeVisible();
 const models=await(await page.request.get(base+'/providers')).json();expect(models).toHaveLength(2);
 expect(new Set(models.map((m:any)=>m.connection_id)).size).toBe(1);
 expect(models.every((m:any)=>m.endpoint==='http://192.168.1.21:11434/v1')).toBe(true);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
