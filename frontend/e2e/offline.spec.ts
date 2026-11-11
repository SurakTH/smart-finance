import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('encrypted offline snapshot and drafts require explicit online review and typed confirmation',async({page,context},info)=>{
 await signIn(page,true);const headers={'X-SF-Request':'1'},ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'พื้นที่ออฟไลน์ '+crypto.randomUUID()}})).json();
 const base='/api/workspaces/'+ws.id,accounts=await(await page.request.get(base+'/accounts')).json();
 await page.request.post(base+'/transactions',{headers,data:{kind:'expense',account_id:accounts.find((a:any)=>a.kind==='asset').id,category_id:accounts.find((a:any)=>a.kind==='expense').id,amount:2000,description:'ข้อมูลลับในภาพออฟไลน์',occurred_on:'2026-10-11',idempotency_key:crypto.randomUUID()}});
 await page.goto('/settings');await page.getByLabel((page.viewportSize()?.width||1440)<=900?'เลือก workspace บนมือถือ':'เลือก workspace',{exact:true}).selectOption(ws.id);
 const phrase='Offline-'+crypto.randomUUID();await page.getByLabel('รหัสปลดล็อกออฟไลน์',{exact:true}).fill(phrase);await page.getByLabel('ยืนยันรหัสออฟไลน์',{exact:true}).fill(phrase);await page.getByRole('button',{name:'เก็บข้อมูลไว้ใช้ออฟไลน์',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'เก็บข้อมูลเข้ารหัสบนเครื่องนี้แล้ว'})).toBeVisible();
 const encrypted=await page.evaluate(()=>localStorage.getItem('sf-offline-v1'));expect(encrypted).toBeTruthy();expect(encrypted).not.toContain(phrase);expect(encrypted).not.toContain('ข้อมูลลับในภาพออฟไลน์');
 await page.evaluate(async()=>{await navigator.serviceWorker.ready;if(!navigator.serviceWorker.controller)await new Promise<void>(resolve=>navigator.serviceWorker.addEventListener('controllerchange',()=>resolve(),{once:true}));});
 const cached=await page.evaluate(async()=>{const all=await caches.keys(),paths:string[]=[];for(const key of all){for(const req of await(await caches.open(key)).keys())paths.push(new URL(req.url).pathname);}return paths;});expect(cached).toContain('/offline.html');expect(cached.some(path=>path.startsWith('/api/'))).toBe(false);
 await context.setOffline(true);try{
  await page.goto('/transactions');await expect(page.getByRole('heading',{name:'พร้อมแม้ออฟไลน์'})).toBeVisible();await page.getByLabel('รหัสปลดล็อกออฟไลน์',{exact:true}).fill('Wrong-offline-password');await page.getByRole('button',{name:'ปลดล็อก',exact:true}).click();await expect(page.locator('#error')).toContainText('รหัสออฟไลน์ไม่ถูกต้อง');
  // A lock/background event during async decryption must not reopen the vault.
  await page.getByLabel('รหัสปลดล็อกออฟไลน์',{exact:true}).fill(phrase);
  await page.evaluate(()=>{const decrypt=crypto.subtle.decrypt.bind(crypto.subtle);(window as any).__unlockDone=false;(crypto.subtle as any).decrypt=async(...args:any[])=>{try{return await (decrypt as any)(...args);}finally{(window as any).__unlockDone=true;}};(document.getElementById('unlock-form') as HTMLFormElement).requestSubmit();document.getElementById('lock')!.click();});
  await expect.poll(()=>page.evaluate(()=>(window as any).__unlockDone)).toBe(true);await expect(page.locator('#workspace')).toBeHidden();
  await page.getByLabel('รหัสปลดล็อกออฟไลน์',{exact:true}).fill(phrase);await page.getByRole('button',{name:'ปลดล็อก',exact:true}).click();await expect(page.getByText('ข้อมูลลับในภาพออฟไลน์',{exact:true})).toBeVisible();
  await page.getByLabel('ข้อความร่างรายการ',{exact:true}).fill('กาแฟ 75 จากเงินสด');await page.getByRole('button',{name:'เก็บร่างบนเครื่อง',exact:true}).click();await expect(page.locator('.draft')).toHaveCount(1);await expect(page.getByRole('button',{name:'ส่งร่างให้ทวน',exact:true})).toBeDisabled();
  await page.locator('.panel:visible').first().screenshot({path:`../artifacts/offline-${info.project.name}.png`});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 }finally{await context.setOffline(false);}
 await page.getByRole('button',{name:'ตรวจการเชื่อมต่อ',exact:true}).click();await expect(page.getByRole('button',{name:'ส่งร่างให้ทวน',exact:true})).toBeEnabled();
 const total=async()=>(await(await page.request.get(base+'/transaction-report')).json()).total;expect(await total()).toBe(1);
 await page.route('**/api/auth/me',route=>route.fulfill({json:{id:'different-user'}}));await page.getByRole('button',{name:'ส่งร่างให้ทวน',exact:true}).click();await expect(page.locator('#error')).toContainText('บัญชีที่เข้าสู่ระบบไม่ตรง');expect(await total()).toBe(1);await page.unroute('**/api/auth/me');
 await page.getByRole('button',{name:'ส่งร่างให้ทวน',exact:true}).click();await expect(page.locator('.draft pre')).toContainText('กรุณาตรวจสอบ — ยังไม่บันทึก');expect(await total()).toBe(1);
 const code=(await page.locator('.draft pre').innerText()).match(/\nยืนยัน ([A-F0-9]{8})\n/)![1];await page.getByLabel('พิมพ์ยืนยันพร้อมรหัสจากข้อความทวน',{exact:true}).fill('ยืนยัน '+code);await page.getByRole('button',{name:'ส่งข้อความยืนยัน',exact:true}).click();await expect(page.locator('.draft')).toHaveCount(0);expect(await total()).toBe(2);
 await page.goto('/settings');await page.getByRole('button',{name:'ออกจากระบบ',exact:true}).last().click();await expect(page.getByLabel('อีเมล',{exact:true})).toBeVisible();expect(await page.evaluate(()=>localStorage.getItem('sf-offline-v1'))).toBeNull();
 // An encryption in progress cannot recreate a vault after logout/clear.
 const race=await page.evaluate(async()=>{const url='/offline-store.js';const module=await import(url);const promise=module.saveVault({version:1,user_id:'race',workspace_id:'race',drafts:[]},'Race-offline-password').then(()=>false,()=>true);module.clearVault();return {rejected:await promise,empty:!module.hasVault()};});expect(race).toEqual({rejected:true,empty:true});
});
