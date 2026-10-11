import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('personal memory, one-field clarification, ledger evidence and AI budget settings work together',async({page},info)=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'เลขาส่วนตัว '+crypto.randomUUID()}})).json(),base='/api/workspaces/'+ws.id;
 const accounts=await(await page.request.get(base+'/accounts')).json(),travel=accounts.find((a:any)=>a.name==='เดินทาง');
 const bank=await(await page.request.post(base+'/accounts',{headers,data:{name:'ธนาคารหลัก',kind:'asset'}})).json();
 const provider=await(await page.request.post(base+'/providers',{headers,data:{name:'โมเดลสำรอง',kind:'compatible',model:'test-model',task:'chat',endpoint:'https://example.invalid/v1',enabled:false}})).json();
 await page.evaluate(wid=>sessionStorage.setItem('sf-workspace',wid),ws.id);await page.goto('/ai-settings');
 await page.getByLabel('บัญชีเริ่มต้นexpense',{exact:true}).selectOption(bank.id);
 await page.getByRole('button',{name:'เพิ่มกฎ',exact:true}).click();await page.getByLabel('คำจับคู่ 1',{exact:true}).fill('กาแฟ');await page.getByLabel('หมวดที่แนะนำ 1',{exact:true}).selectOption(travel.id);
 await page.getByRole('button',{name:'บันทึกความชอบ',exact:true}).click();await expect(page.getByText('บันทึกความชอบส่วนตัวแล้ว',{exact:true})).toBeVisible();
 await page.reload();await expect(page.getByLabel('บัญชีเริ่มต้นexpense',{exact:true})).toHaveValue(bank.id);await expect(page.getByLabel('คำจับคู่ 1',{exact:true})).toHaveValue('กาแฟ');
 await page.locator('#ai-memory').scrollIntoViewIfNeeded();await page.screenshot({path:`../artifacts/ai-memory-${info.project.name}.png`});
 await page.getByLabel('วงเงิน AI',{exact:true}).fill('10');await page.getByLabel('test-model input',{exact:true}).fill('1');await page.getByLabel('test-model output',{exact:true}).fill('2');
 await page.getByRole('button',{name:'บันทึกราคาและวงเงิน',exact:true}).click();await expect(page.getByText('บันทึกราคาและงบ AI แล้ว',{exact:true})).toBeVisible();
 const usage=await(await page.request.get(base+'/ai/usage')).json();expect(usage.policy.monthly_limit).toBe(10000000);expect(usage.policy.prices[provider.id]).toEqual({input:1000000,output:2000000});
 await page.route('**/ai/usage?month=*',route=>route.fulfill({json:{...usage,requests:3,cost:420,items:[{provider_id:provider.id,model:'test-model',task:'chat',requests:3,input_tokens:120,output_tokens:150,cost:420,estimated_requests:1,unpriced_requests:0,failed_requests:1}]}}));
 await page.getByRole('button',{name:'รีเฟรชยอด',exact:true}).click();await expect(page.locator('.ai-usage-list')).toContainText('เข้า 120 / ออก 150 tokens');await expect(page.locator('.ai-usage-list')).toContainText('ประมาณการ 1 คำขอ');
 await page.locator('#ai-usage').scrollIntoViewIfNeeded();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:`../artifacts/ai-usage-${info.project.name}.png`});
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'เลขาทดลอง'}})).json();await page.goto('/assistant?conversation='+room.id);
 const input=page.getByPlaceholder('คุยเรื่องเงิน หรือบอกสิ่งที่อยากจด…');
 async function send(text:string){await input.fill(text);await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();}
 await send('ซื้อกาแฟ');await expect(page.locator('.message.assistant').last()).toContainText('ยอดเท่าไหร่');await send('80');
 await expect(page.locator('.message.assistant').last()).toContainText('กรุณาตรวจสอบ');await expect(page.locator('.message.assistant').last()).toContainText('ธนาคารหลัก');await expect(page.locator('.message.assistant').last()).toContainText('เดินทาง');
 let result=await(await page.request.get(base+'/transaction-report')).json();expect(result.total).toBe(0);
 await send('ยืนยัน');await expect(page.locator('.message.assistant').last()).toContainText('บันทึกรายการเรียบร้อย');
 await send('เดือนนี้ใช้เท่าไหร่ มีอะไรบ้าง');const evidence=page.getByRole('complementary',{name:'ข้อมูลต้นทางจากบัญชี'});await expect(evidence).toBeVisible({timeout:20000});await expect(evidence).toContainText('฿80.00');
 const summary=evidence.getByRole('link').filter({hasText:'ยอดจริงจากบัญชี'});await expect(summary).toHaveAttribute('href',new RegExp('workspace='+ws.id));await summary.click();
 await expect(page.getByLabel('วันเริ่มต้น',{exact:true})).toHaveValue(/^\d{4}-\d{2}-01$/);await expect(page.locator('.filtered-totals')).toContainText('฿80.00');
 await page.goto('/assistant?conversation='+room.id);await send('จำไว้ว่า กาแฟลงหมวดอาหารและเครื่องดื่ม');await expect(page.locator('.message.assistant').last()).toContainText('ทวนความจำส่วนตัว');await send('ยืนยัน');await expect(page.locator('.message.assistant').last()).toContainText('จำความชอบนี้แล้ว');
 const preferences=await(await page.request.get(base+'/ai/preferences')).json();expect(preferences.rules[0].category_id).not.toBe(travel.id);
 result=await(await page.request.get(base+'/transaction-report')).json();expect(result.total).toBe(1);expect(result.expense).toBe(8000);
 // UI member mode; backend authorization/isolation is tested with distinct real users in pytest.
 const workspaces=await(await page.request.get('/api/workspaces')).json();await page.route('**/api/workspaces',route=>route.fulfill({json:workspaces.map((w:any)=>w.id===ws.id?{...w,role:'member'}:w)}));
 await page.goto('/settings');await page.getByRole('link',{name:'เปิดศูนย์ตั้งค่า AI',exact:false}).click();await expect(page.getByRole('heading',{name:'ความจำส่วนตัว',exact:true})).toBeVisible();await expect(page.locator('#ai-usage')).toHaveCount(0);await expect(page.getByRole('button',{name:'เพิ่มโมเดลแชท',exact:true})).toHaveCount(0);

});
