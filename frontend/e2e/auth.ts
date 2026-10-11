import {expect,type Page,type BrowserContext} from '@playwright/test';
import fs from 'node:fs';
// Reuse a valid test session in memory only. Never weaken production throttling
// or write authenticated state to disk. The finance scenario still tests login/logout.
let cookies:Awaited<ReturnType<BrowserContext['cookies']>>|null=null;
export async function signIn(page:Page,forceLogin=false){
 if(!forceLogin&&cookies){
  await page.context().addCookies(cookies);
  if((await page.request.get('/api/auth/me')).ok()){
   await page.goto('/');await expect(page.getByRole('heading',{name:'การเงินของคุณ',exact:true})).toBeVisible();return;
  }
 }
 const credentials=JSON.parse(fs.readFileSync(process.env.SF_DEMO_CREDENTIALS||'../artifacts/demo-access.json','utf8'));
 await page.goto('/');
 await page.getByLabel('อีเมล',{exact:true}).fill(credentials.email);
 await page.getByLabel('รหัสผ่าน',{exact:true}).fill(credentials.password);
 await page.getByRole('button',{name:'เข้าสู่ระบบ',exact:true}).click();
 await expect(page.getByRole('heading',{name:'การเงินของคุณ',exact:true})).toBeVisible();
 cookies=await page.context().cookies();
}
