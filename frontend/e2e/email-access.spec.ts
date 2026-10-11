import {test,expect} from '@playwright/test';
test('email recovery page and disabled SMTP are clear',async({page})=>{
 await page.goto('/');await page.getByRole('link',{name:'ลืมรหัสผ่าน?',exact:true}).click();
 await expect(page.getByRole('heading',{name:'ลืมรหัสผ่าน',exact:true})).toBeVisible();
 await expect(page.getByText('ผู้ดูแลยังไม่ได้เปิดการส่งอีเมล กรุณาติดต่อผู้ดูแลเพื่อกู้บัญชี',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'ส่งลิงก์ตั้งรหัสผ่านใหม่'})).toBeDisabled();
 await expect(page.locator('body')).toHaveJSProperty('scrollWidth',await page.evaluate(()=>document.documentElement.clientWidth));
 if(test.info().project.name==='mobile')await page.screenshot({path:'../artifacts/email-recovery-mobile.png',fullPage:true});
});
test('email link fragment is removed and needs explicit confirmation',async({page})=>{
 let submitted=0;
 await page.route('**/api/auth/verify-email',async route=>{submitted++;expect(route.request().postDataJSON()).toEqual({token:'synthetic-verification-token'});await route.fulfill({json:{ok:true}});});
 await page.goto('/verify-email#token=synthetic-verification-token');
 await expect(page).toHaveURL(/\/verify-email$/);
 expect(submitted).toBe(0);
 await page.getByRole('button',{name:'ยืนยันอีเมล',exact:true}).click();
 await expect(page.getByRole('status')).toHaveText('ยืนยันอีเมลแล้ว');expect(submitted).toBe(1);
});
test('reset form keeps token private and checks matching passwords',async({page})=>{
 let submitted=0;
 await page.route('**/api/auth/reset-password',async route=>{submitted++;expect(route.request().postDataJSON().token).toBe('synthetic-reset-token');await route.fulfill({json:{ok:true}});});
 await page.goto('/reset-password#token=synthetic-reset-token');await expect(page).toHaveURL(/\/reset-password$/);
 await page.getByLabel('รหัสผ่านใหม่',{exact:true}).fill('synthetic-password-123');
 await page.getByLabel('ยืนยันรหัสผ่านใหม่',{exact:true}).fill('different-password-123');
 await page.getByRole('button',{name:'บันทึกรหัสผ่านใหม่'}).click();
 await expect(page.getByRole('main').getByRole('alert')).toHaveText('รหัสผ่านและการยืนยันไม่ตรงกัน');expect(submitted).toBe(0);
 await page.getByLabel('ยืนยันรหัสผ่านใหม่',{exact:true}).fill('synthetic-password-123');
 await page.getByRole('button',{name:'บันทึกรหัสผ่านใหม่'}).click();
 await expect(page.getByRole('status')).toHaveText('ตั้งรหัสผ่านใหม่แล้ว กรุณาเข้าสู่ระบบใหม่ทุกอุปกรณ์');expect(submitted).toBe(1);
});
