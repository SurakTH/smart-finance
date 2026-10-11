import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('assistant capabilities and scoped work history paginate safely on desktop and mobile',async({page},info)=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'เลขาส่วนตัว '+Date.now()}})).json();
 // Backend plan/confirmation/atomicity are covered against PostgreSQL. This fixture checks history presentation.
 await page.route(`**/api/workspaces/${ws.id}/assistant-changes*`,async route=>{
  const second=new URL(route.request().url()).searchParams.get('page')==='2';
  await route.fulfill({json:{items:[{id:second?'second':'first',summary:second?'ตั้งงบ · อาหาร · ฿3,000.00':'1. สร้างหมวดรายจ่าย · สัตว์เลี้ยง\n\n2. ตั้งงบ · ฿2,000.00\n<img src=x onerror=alert(1)>',created_at:Math.floor(Date.now()/1000),actor:'คุณ'}],has_more:!second,page:second?2:1}});
 });
 await page.goto('/assistant');const mobile=info.project.name==='mobile';
 async function history(){const toggle=page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true});if(mobile&&await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();}
 await history();await page.getByLabel('เลือก workspace ในแชท',{exact:true}).selectOption(ws.id);await history();
 await page.getByRole('button',{name:'ประวัติงานผู้ช่วย',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'งานที่ผู้ช่วยทำแล้ว'});
 await expect(dialog).toContainText('สัตว์เลี้ยง');await expect(dialog).toContainText('<img src=x onerror=alert(1)>');await expect(dialog.locator('img')).toHaveCount(0);
 await expect(dialog.getByRole('button',{name:'ก่อนหน้า',exact:true})).toBeDisabled();
 await dialog.screenshot({path:`../artifacts/assistant-management-history-${info.project.name}.png`});
 await dialog.getByRole('button',{name:'ถัดไป',exact:true}).click();await expect(dialog).toContainText('฿3,000.00');await expect(dialog.getByRole('button',{name:'ถัดไป',exact:true})).toBeDisabled();
 await dialog.getByRole('button',{name:'ก่อนหน้า',exact:true}).click();await expect(dialog).toContainText('สัตว์เลี้ยง');
 expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
 await dialog.getByRole('button',{name:'ปิดประวัติงานผู้ช่วย',exact:true}).click();await expect(dialog).not.toBeVisible();
 if(mobile)await page.getByRole('button',{name:'ปิดประวัติ',exact:true}).click();
 await page.locator('.chat-action-help summary').click();await expect(page.locator('.chat-action-help')).toContainText('สั่งเป็นชุดได้');
});
