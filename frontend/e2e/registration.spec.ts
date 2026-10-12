import {test,expect} from '@playwright/test';
test('public signup follows server setting and keeps accounts isolated',async({page,browser})=>{
 const options=await(await page.request.get('/api/auth/options')).json();
 expect(options.allow_registration).toBe(process.env.SF_TEST_PUBLIC_REGISTRATION==='1');
 await page.goto('/');
 const link=page.getByRole('link',{name:'ยังไม่มีบัญชี? สมัครใช้งาน'});
 if(!options.allow_registration){
  await expect(link).toHaveCount(0);await page.goto('/register');await expect(page.getByText('ขณะนี้ปิดการสมัครบัญชีใหม่',{exact:true})).toBeVisible();
  expect((await page.request.post('/api/auth/register',{headers:{'X-SF-Request':'1'},data:{email:crypto.randomUUID()+'@example.test',password:'Closed-signup-password',confirm_password:'Closed-signup-password'}})).status()).toBe(403);
 }else{
  await expect(link).toBeVisible();await link.click();await expect(page.getByRole('heading',{name:'เริ่มต้นพื้นที่ของคุณ'})).toBeVisible();
  const email=crypto.randomUUID()+'@example.test',password='Signup-'+crypto.randomUUID();
  await page.getByLabel('ชื่อที่แสดง',{exact:true}).fill('สมาชิกใหม่');await page.getByLabel('อีเมล',{exact:true}).fill(email);await page.getByLabel('ตั้งรหัสผ่าน',{exact:true}).fill(password);await page.getByLabel('ยืนยันรหัสผ่าน',{exact:true}).fill(password+'different');await page.getByRole('button',{name:'สร้างบัญชีส่วนตัว',exact:true}).click();await expect(page.locator('.error[role=alert]')).toHaveText('รหัสผ่านและการยืนยันไม่ตรงกัน');
  await page.getByLabel('ยืนยันรหัสผ่าน',{exact:true}).fill(password);await page.getByRole('button',{name:'สร้างบัญชีส่วนตัว',exact:true}).click();await expect(page.getByRole('heading',{name:'การเงินของคุณ',exact:true})).toBeVisible();
  const spaces=await(await page.request.get('/api/workspaces')).json();expect(spaces).toHaveLength(1);const wid=spaces[0].id;expect((await(await page.request.get(`/api/workspaces/${wid}/transactions`)).json())).toEqual([]);
  const friend=await browser.newContext();try{
   const response=await friend.request.post((process.env.SF_BASE_URL||'http://localhost:8080')+'/api/auth/register',{headers:{'X-SF-Request':'1'},data:{email:crypto.randomUUID()+'@example.test',password,confirm_password:password}});expect(response.status()).toBe(201);const own=await response.json();expect(own.workspace_id).not.toBe(wid);
   expect((await friend.request.get(`${process.env.SF_BASE_URL||'http://localhost:8080'}/api/workspaces/${wid}/accounts`)).status()).toBe(404);expect((await page.request.get(`/api/workspaces/${own.workspace_id}/accounts`)).status()).toBe(404);
  }finally{await friend.close();}
  await page.request.post('/api/auth/logout',{headers:{'X-SF-Request':'1'}});await page.goto('/');await page.getByLabel('อีเมล',{exact:true}).fill(email);await page.getByLabel('รหัสผ่าน',{exact:true}).fill(password);await page.getByRole('button',{name:'เข้าสู่ระบบ',exact:true}).click();await expect(page.getByRole('heading',{name:'การเงินของคุณ',exact:true})).toBeVisible();
 }
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
