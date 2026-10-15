import {test,expect} from '@playwright/test';
import {signIn} from './auth';

test('simple insights aggregate all entries, filter, compare and drill through on both sizes',async({page},info)=>{
 await signIn(page);
 const headers={'X-SF-Request':'1'};
 const created=await page.request.post('/api/workspaces',{headers,data:{name:'วิเคราะห์ทดสอบ '+info.project.name+' '+Date.now()}});
 expect(created.ok()).toBe(true);const {id}=await created.json(),base=`/api/workspaces/${id}`;
 const accounts=await (await page.request.get(base+'/accounts')).json();
 const wallet=accounts.find((a:any)=>a.kind==='asset'),expense=accounts.find((a:any)=>a.kind==='expense'),income=accounts.find((a:any)=>a.kind==='income');
 for(const [kind,amount,day,description] of [['expense',1000,'2026-10-01','อาหารหนึ่ง'],['expense',5000,'2026-10-02','อาหารสอง'],['income',20000,'2026-10-02','เงินเข้า'],['expense',3000,'2026-09-30','ช่วงก่อน']] as const){
  const r=await page.request.post(base+'/transactions',{headers,data:{kind,amount,occurred_on:day,description,account_id:wallet.id,category_id:kind==='expense'?expense.id:income.id,idempotency_key:crypto.randomUUID()}});expect(r.ok()).toBe(true);
 }
 await page.goto('/insights?workspace='+id);
 await expect(page.getByRole('heading',{name:'วิเคราะห์',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'เลือกวัน',exact:true}).click();
 await page.getByLabel('วันเริ่มวิเคราะห์',{exact:true}).fill('2026-10-01');
 await page.getByLabel('วันสิ้นสุดวิเคราะห์',{exact:true}).fill('2026-10-03');
 await expect(page.locator('.insight-metrics').getByRole('link').first()).toContainText('฿60.00');
 await expect(page.locator('.insight-metrics')).toContainText('฿200.00');
 await expect(page.locator('.insight-metrics')).toContainText('฿20.00');
 await expect(page.locator('.insight-story')).toContainText('2 รายการจ่าย');
 await expect(page.locator('.insight-largest a')).toHaveCount(2);
 await page.getByRole('button',{name:'ใช้กับอะไร',exact:true}).click();
 await expect(page.locator('.insight-category-changes')).toContainText('เพิ่มขึ้น ฿30.00');
 await page.getByRole('button',{name:'ใช้บัญชีไหน',exact:true}).click();
 await expect(page.locator('.insight-ranking')).toContainText(wallet.name);
 await page.getByRole('button',{name:'แนวโน้ม',exact:true}).click();
 await expect(page.locator('.insight-months')).toContainText('จ่าย ฿60.00');
 await expect(page.locator('.insight-weekdays>div')).toHaveCount(7);
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`../artifacts/insights-${info.project.name}.png`,fullPage:true});
 await page.getByRole('button',{name:'สรุปง่าย ๆ',exact:true}).click();
 await page.getByRole('button',{name:'ตัวกรอง',exact:true}).click();
 await page.getByLabel('หมวดที่วิเคราะห์').selectOption(expense.id);
 await expect(page.locator('.insight-metrics')).toContainText('฿60.00');
 await expect(page.locator('.insight-metrics').getByRole('link').nth(1)).toContainText('฿0.00');
 await page.getByRole('link',{name:/ดูรายการหมวดนี้/}).click();
 await expect(page).toHaveURL(/transactions\?.*category_id=/);
 await expect(page.locator('.ledger-row')).toHaveCount(2);
 await expect(page.getByLabel('วันเริ่มต้น')).toHaveValue('2026-10-01');
 await expect(page.locator('.filtered-totals')).toContainText('฿60.00');
});

test('default transaction controls leave room for real rows and retain advanced options',async({page})=>{
 await signIn(page);await page.goto('/transactions');
 await expect(page.locator('.ledger-row').first()).toBeVisible();
 await expect(page.getByLabel('วันเริ่มต้น')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'ส่งออก CSV',exact:true})).toHaveCount(0);
 await expect(page.locator('.ledger-row').first()).toBeInViewport();
 await page.getByRole('button',{name:'ตัวกรอง',exact:true}).click();
 await expect(page.getByLabel('วันเริ่มต้น')).toBeVisible();
 await expect(page.getByRole('button',{name:'ส่งออก CSV',exact:true})).toBeVisible();
});
