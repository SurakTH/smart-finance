import {signIn} from './auth';
import {test,expect} from '@playwright/test';
import fs from 'node:fs';

test('CSV download follows filters across pages and exports correction history',async({page},info)=>{
 await signIn(page);await expect(page.locator('.overview-hero')).toBeVisible();
 const headers={'X-SF-Request':'1'};
 const created=await page.request.post('/api/workspaces',{headers,data:{name:'ทดสอบส่งออก '+info.project.name+' '+Date.now()}});expect(created.ok()).toBe(true);const workspace=await created.json();const base=`/api/workspaces/${workspace.id}`;
 const accounts=await (await page.request.get(base+'/accounts')).json();const wallet=accounts.find((a:any)=>a.kind==='asset'),category=accounts.find((a:any)=>a.kind==='expense');
 const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());const month=today.slice(0,7);
 const transactions=[];
 for(let i=0;i<32;i++){
  const data={kind:'expense',account_id:wallet.id,category_id:category.id,amount:100+i,description:i===0?'=1+1':`กาแฟส่งออก ${String(i).padStart(2,'0')}`,occurred_on:month+'-01',idempotency_key:crypto.randomUUID()};
  const posted=await page.request.post(base+'/transactions',{headers,data});expect(posted.ok()).toBe(true);transactions.push(await posted.json());
 }
 await page.goto('/transactions');const compact=(page.viewportSize()?.width||1440)<=900;await page.getByLabel(compact?'เลือก workspace บนมือถือ':'เลือก workspace',{exact:true}).selectOption(workspace.id);await expect(page.locator('.ledger-row')).toHaveCount(30);await expect(page.locator('.filtered-totals')).toContainText('32 รายการ');
 async function download(label:string){const event=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();const result=await event;expect(result.suggestedFilename()).toMatch(/^smart-finance-(transactions|history)\.csv$/);const path=await result.path();expect(path).toBeTruthy();const bytes=fs.readFileSync(path!);expect(bytes.subarray(0,3)).toEqual(Buffer.from([0xef,0xbb,0xbf]));return bytes.toString('utf8').replace(/^\uFEFF/,'');}
 await page.getByRole('button',{name:'ตัวกรอง',exact:true}).click();
 const all=await download('ส่งออก CSV');expect(all.trim().split(/\r?\n/)).toHaveLength(33);expect(all).toContain("'=1+1");expect(all).toContain('กาแฟส่งออก 31');
 await page.getByLabel('ค้นหารายการ',{exact:true}).fill('กาแฟส่งออก 31');await expect(page.locator('.ledger-row')).toHaveCount(1);const filtered=await download('ส่งออก CSV');expect(filtered.trim().split(/\r?\n/)).toHaveLength(2);expect(filtered).toContain('1.31');expect(filtered).not.toContain("'=1+1");
 const old=transactions[31];await page.getByRole('button',{name:'รายละเอียด กาแฟส่งออก 31',exact:true}).click();const dialog=page.locator('dialog[open]');await dialog.getByRole('button',{name:'แก้ไขรายการ',exact:true}).click();await dialog.getByLabel('แก้จำนวนเงิน',{exact:true}).fill('76.54');await dialog.getByLabel('เหตุผลการเปลี่ยนรายการ',{exact:true}).fill('ตรวจยอดก่อนส่งออก');await dialog.getByRole('button',{name:'ยืนยันแก้ไขรายการ',exact:true}).click();await expect(page.locator('dialog[open]')).toHaveCount(0);await expect(page.locator('.filtered-totals')).toContainText('฿76.54');
 const corrected=await download('ส่งออก CSV');expect(corrected).toContain('76.54');expect(corrected).not.toContain(old.id);
 const balances=await (await page.request.get(base+'/accounts')).json();
 await page.getByRole('button',{name:'ประวัติการแก้ไข',exact:true}).click();await expect(dialog.locator('.revision-card')).toHaveCount(1);
 // Date inputs refetch independently. Check each committed filter and its response
 // before continuing, so a failure identifies the request rather than an empty DOM.
 async function filterHistory(label:string,params:Record<string,string>){
  const response=page.waitForResponse(r=>{
   const url=new URL(r.url());return url.pathname===base+'/transaction-history'&&Object.entries(params).every(([key,value])=>url.searchParams.get(key)===value);
  });
  const input=dialog.getByLabel(label,{exact:true});await input.fill(today);await expect(input).toHaveValue(today);
  const result=await response;expect(result.status(),result.url()).toBe(200);
  const data=await result.json();expect(data.total,JSON.stringify({filters:params,history:data})).toBe(1);
  await expect(dialog.locator('.revision-card')).toHaveCount(1);
 }
 await filterHistory('ประวัติตั้งแต่',{start:today});
 await filterHistory('ประวัติถึง',{start:today,end:today});
 const history=await download('ส่งออกประวัติ CSV');expect(history).toContain('ตรวจยอดก่อนส่งออก');expect(history).toContain(old.id);expect(history).toContain('1.31');expect(history).toContain('76.54');expect(history).toContain('+07:00');
 await page.screenshot({path:`../artifacts/exports-history-${info.project.name}.png`,fullPage:true});
 await dialog.getByRole('button',{name:'ปิดประวัติการแก้ไข',exact:true}).click();await page.getByLabel('ค้นหารายการ',{exact:true}).fill('');await page.getByLabel('วันเริ่มต้น',{exact:true}).fill(month+'-02');await page.getByLabel('วันสิ้นสุด',{exact:true}).fill(month+'-02');await expect(page.getByRole('heading',{name:'ไม่พบรายการในช่วงนี้',exact:true})).toBeVisible();const empty=await download('ส่งออก CSV');expect(empty.trim().split(/\r?\n/)).toHaveLength(1);
 await page.route('**/exports/transactions.csv?**',route=>route.fulfill({status:413,contentType:'application/json',body:JSON.stringify({detail:'ส่งออกได้ไม่เกิน 10,000 รายการ กรุณาลดช่วงวัน'})}));await page.getByRole('button',{name:'ส่งออก CSV',exact:true}).click();await expect(page.locator('.export-error')).toContainText('10,000');
 expect(await (await page.request.get(base+'/accounts')).json()).toEqual(balances);await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
