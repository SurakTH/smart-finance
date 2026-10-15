import {expect,type Page,type BrowserContext} from '@playwright/test';
import fs from 'node:fs';
// Reuse a valid test session in memory only. Never weaken production throttling
// or write authenticated state to disk. The finance scenario still tests login/logout.
let cookies:Awaited<ReturnType<BrowserContext['cookies']>>|null=null;
async function openDemo(page:Page){
 // Other scenarios create newer workspaces, including fake AI endpoints. Never
 // let list ordering choose the data or provider used by the next scenario.
 const response=await page.request.get('/api/workspaces');
 expect(response.ok()).toBe(true);
 const spaces: {id:string;name:string}[]=await response.json();
 const demo=spaces.find(space=>space.name==='การเงินส่วนตัว');
 expect(demo,'The seeded demo workspace must exist').toBeDefined();
 await page.goto('/?workspace='+demo!.id);
 await expect(page.getByRole('heading',{name:'การเงินของคุณ',exact:true})).toBeVisible();
 const label=(page.viewportSize()?.width||1440)<=900?'เลือก workspace บนมือถือ':'เลือก workspace';
 await expect(page.getByLabel(label,{exact:true})).toHaveValue(demo!.id);
}
export async function signIn(page:Page,forceLogin=false){
 if(!forceLogin&&cookies){
  await page.context().addCookies(cookies);
  if((await page.request.get('/api/auth/me')).ok()){
   await openDemo(page);return;
  }
 }
 const credentials=JSON.parse(fs.readFileSync(process.env.SF_DEMO_CREDENTIALS||'../artifacts/demo-access.json','utf8'));
 await page.goto('/');
 await page.getByLabel('อีเมล',{exact:true}).fill(credentials.email);
 await page.getByLabel('รหัสผ่าน',{exact:true}).fill(credentials.password);
 await page.getByRole('button',{name:'เข้าสู่ระบบ',exact:true}).click();
 await expect(page.getByRole('heading',{name:'การเงินของคุณ',exact:true})).toBeVisible().catch(async error=>{
  // Playwright captures the page on failure; never retain a password in that snapshot.
  const password=page.getByLabel('รหัสผ่าน',{exact:true});
  if(await password.isVisible())await password.fill('');
  throw error;
 });
 cookies=await page.context().cookies();
 await openDemo(page);
}
