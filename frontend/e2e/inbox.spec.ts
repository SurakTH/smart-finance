import {test,expect,type Page} from '@playwright/test';
import {signIn} from './auth';
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMImFAAAAKEAVGsDQL6AAAAAElFTkSuQmCC';
const headers={'X-SF-Request':'1'};
async function prepare(page:Page,beforeOpen?:(base:string)=>Promise<void>){
 await signIn(page);
 const response=await page.request.post('/api/workspaces',{headers,data:{name:'Inbox UX '+crypto.randomUUID()}});
 expect(response.ok()).toBe(true);const ws=await response.json();
 if(beforeOpen)await beforeOpen('/api/workspaces/'+ws.id);
 await page.goto('/inbox?workspace='+ws.id);
 await expect(page.getByRole('heading',{name:'จากสลิป เป็นรายการพร้อมตรวจ'})).toBeVisible();
 await expect(page.getByRole('combobox',{name:'การประมวลผลข้อความและสลิป'})).toHaveCount(0);
 await expect(page.getByText('ใช้ AI ตามการตั้งค่าของ workspace นี้',{exact:true})).toBeVisible();
 return '/api/workspaces/'+ws.id;
}
test('receipt and caption stay local until submitted, then create an unposted review draft',async({page})=>{
 const base=await prepare(page);let uploads=0;
 page.on('request',r=>{if(r.url().includes(base+'/attachments')&&r.method()==='POST'){uploads++;}});
 await page.getByLabel('อัปโหลดสลิป',{exact:true}).setInputFiles({name:'receipt.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
 await expect(page.getByAltText('ตัวอย่างสลิปก่อนส่ง')).toBeVisible();
 await page.getByRole('textbox',{name:'ข้อความรายการเงิน',exact:true}).fill('ค่าหนังสือ จ่ายไป 60 บาท');
 expect(uploads).toBe(0);
 await page.getByRole('button',{name:'อ่านสลิปและสร้างร่าง',exact:true}).click();
 await expect(page.getByAltText('ตัวอย่างสลิปก่อนส่ง')).toHaveCount(0);
 expect(uploads).toBe(1);
 await expect(page.locator('.proposal')).toHaveCount(1,{timeout:20000});
 await expect(page.locator('.proposal')).toContainText('สาธิต');
 const transactions=await(await page.request.get(base+'/transactions')).json();expect(transactions).toHaveLength(0);
 await page.locator('.proposal').getByRole('button',{name:'ตรวจสอบ',exact:true}).click();
 await expect(page.getByRole('dialog')).toBeVisible();
});
test('paste image with text, replace and remove; validation preserves a valid attachment',async({page})=>{
 await prepare(page);
 await page.getByRole('textbox',{name:'ข้อความรายการเงิน',exact:true}).fill('คำอธิบายเดิม');
 await page.locator('.inbox-compose form').evaluate((node,png)=>{
  const data=new DataTransfer();data.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],'pasted.png',{type:'image/png'}));data.setData('text/plain','ค่าหนังสือ');
  node.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));
 },png);
 await expect(page.getByAltText('ตัวอย่างสลิปก่อนส่ง')).toBeVisible();
 await expect(page.getByRole('textbox',{name:'ข้อความรายการเงิน',exact:true})).toHaveValue('คำอธิบายเดิม\nค่าหนังสือ');
 await page.getByLabel('อัปโหลดสลิป',{exact:true}).setInputFiles({name:'bad.svg',mimeType:'image/svg+xml',buffer:Buffer.from('<svg/>')});
 await expect(page.locator('.inbox-compose [role=alert]')).toBeVisible();
 await expect(page.getByAltText('ตัวอย่างสลิปก่อนส่ง')).toBeVisible();
 await page.getByRole('button',{name:'นำสลิปออก',exact:true}).click();
 await expect(page.getByAltText('ตัวอย่างสลิปก่อนส่ง')).toHaveCount(0);
 await expect(page.getByRole('textbox',{name:'ข้อความรายการเงิน',exact:true})).toHaveValue('คำอธิบายเดิม\nค่าหนังสือ');
 await expect(page.getByRole('button',{name:'สร้างข้อเสนอ',exact:true})).toBeEnabled();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
test('inbox status excludes unrelated chat failures and filters review drafts',async({page})=>{
 const base=await prepare(page,async base=>{
  // Install before navigation so the initial fetch cannot overwrite the mock.
  await page.route('**'+base+'/jobs',route=>route.fulfill({json:[{id:'chat',task:'chat',status:'failed',error:'processing_failed',message:'CHAT ERROR'},{id:'receipt',task:'extract',status:'pending',error:null}]}));
 });
 await page.getByRole('button',{name:'รีเฟรช',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'กำลังอ่าน 1 งาน'})).toBeVisible();
 await expect(page.getByText('CHAT ERROR')).toHaveCount(0);
 await page.request.post(base+'/proposals',{headers,data:{description:'ร่างรอตรวจยอด',amount:null}});
 await page.request.post(base+'/proposals',{headers,data:{description:'กาแฟ',amount:8000}});
 await page.getByRole('button',{name:'รีเฟรช',exact:true}).click();
 await expect(page.locator('.proposal')).toHaveCount(2);
 await page.getByRole('button',{name:'ยังไม่มียอด',exact:true}).click();
 await expect(page.locator('.proposal')).toHaveCount(1);
 await expect(page.locator('.proposal')).toContainText('ร่างรอตรวจยอด');
 await page.getByRole('button',{name:'ทั้งหมด',exact:true}).click();
 await page.getByRole('textbox',{name:'ค้นหาร่าง'}).fill('กาแฟ');
 await expect(page.locator('.proposal')).toHaveCount(1);
});
