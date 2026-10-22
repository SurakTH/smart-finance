import {test,expect} from '@playwright/test';
import {signIn} from './auth';

test('receipt evidence preserves paid amount and date, and unreadable dates require input',async({page})=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'Receipt UI '+Date.now()}})).json();const base='/api/workspaces/'+ws.id;
 const a=await(await page.request.post(base+'/proposals',{headers,data:{description:'Synthetic receipt paid amount',amount:1800,kind:'expense'}})).json();
 const b=await(await page.request.post(base+'/proposals',{headers,data:{description:'Synthetic unreadable receipt',amount:null,kind:'expense'}})).json();
 const receipt={version:1,paid_satang:1800,gross_satang:4500,subsidy_satang:2700,fee_satang:null,occurred_on:'2026-10-20',warnings:[]};
 // The document/ledger contract is exercised in backend tests and live model
 // evaluation. This response fixture isolates presentation and form behavior.
 await page.route('**/workspaces/'+ws.id+'/proposals',async route=>{
  if(route.request().method()!=='GET')return route.continue();
  await route.fulfill({json:[{...a,description:'Synthetic receipt paid amount',amount:1800,kind:'expense',status:'pending',source:'ai',occurred_on:'2026-10-20',receipt},{...b,description:'Synthetic unreadable receipt',amount:null,kind:'expense',status:'pending',source:'ai',receipt:{...receipt,paid_satang:null,occurred_on:null,warnings:['paid_unreadable','date_unreadable']}}]});
 });
 await page.goto('/inbox?workspace='+ws.id);
 const paid=page.locator('.inbox-draft').filter({hasText:'Synthetic receipt paid amount'});
 await expect(paid).toContainText('18.00');await expect(paid).toContainText('45.00');await expect(paid).toContainText('27.00');
 await expect(paid).toContainText('2026-10-20');
 await paid.getByRole('button',{name:'ตรวจสอบ',exact:true}).click();
 const dialog=page.locator('dialog[open]');await expect(dialog.getByLabel('จำนวนเงิน (บาท)',{exact:true})).toHaveValue('18.00');
 await expect(dialog.locator('input[name=occurred_on]')).toHaveValue('2026-10-20');
 expect((await(await page.request.get(base+'/transaction-report')).json()).total).toBe(0);
 await dialog.getByRole('button',{name:'ปิด',exact:true}).click();
 await page.locator('.inbox-draft').filter({hasText:'Synthetic unreadable receipt'}).getByRole('button',{name:'ตรวจสอบ',exact:true}).click();
 await expect(dialog.getByLabel('จำนวนเงิน (บาท)',{exact:true})).toHaveValue('');
 await expect(dialog.locator('input[name=occurred_on]')).toHaveValue('');
 await expect(dialog).toContainText('ยังอ่านวันที่ไม่ได้');
 await dialog.getByRole('button',{name:'ยืนยันและบันทึก',exact:true}).click();
 expect((await(await page.request.get(base+'/transaction-report')).json()).total).toBe(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
