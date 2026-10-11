import {signIn} from './auth';
import {test,expect} from '@playwright/test';
test('AI lab explicitly starts synthetic tests and displays sanitized diagnostics',async({page},info)=>{
 await signIn(page);const headers={'X-SF-Request':'1'};
 const created=await page.request.post('/api/workspaces',{headers,data:{name:'AI lab '+info.project.name+' '+Date.now()}});expect(created.ok()).toBe(true);const {id:wid}=await created.json();
 const saved=await page.request.post(`/api/workspaces/${wid}/providers`,{headers,data:{kind:'ollama',model:'lab-model',task:'chat',name:'เลขาทดสอบ'}});expect(saved.ok()).toBe(true);const provider=await saved.json();
 let rows:any[]=[];let starts=0;let submitted:any=null;
 await page.route(`**/api/workspaces/${wid}/ai/diagnostics`,async route=>{
  if(route.request().method()==='DELETE'){rows=[];await route.fulfill({json:{ok:true}});return;}
  await route.fulfill({json:{items:rows,retention_days:30}});
 });
 await page.route(`**/api/workspaces/${wid}/ai/tests`,async route=>{
  starts++;submitted=route.request().postDataJSON();rows=[{id:'lab-job',task:'ai_test',status:'pending',created_at:Date.now(),diagnostics:{test:{case:submitted.case,status:'pending',reason:'',calls:0}}}];await route.fulfill({json:{job_id:'lab-job'}});
 });
 const label=(page.viewportSize()?.width||1440)<=900?'เลือก workspace บนมือถือ':'เลือก workspace';await page.reload();await page.getByLabel(label,{exact:true}).selectOption(wid);
 await page.goto('/settings');await page.getByRole('link',{name:'เปิดศูนย์ตั้งค่า AI'}).click();
 const lab=page.getByRole('region',{name:'ทดสอบและวิเคราะห์ AI'});await expect(lab).toBeVisible();expect(starts).toBe(0);
 await expect(lab.getByLabel('โจทย์ทดสอบ AI').locator('option')).toHaveCount(5);
 await lab.getByLabel('โจทย์ทดสอบ AI').selectOption('receipt');await lab.getByLabel('โมเดลที่ต้องการตรวจ').selectOption(provider.id);
 await lab.getByRole('button',{name:'เริ่มทดสอบ AI',exact:true}).click();await expect(lab.getByRole('button',{name:'กำลังทดสอบ…'})).toBeDisabled();expect(submitted).toEqual({case:'receipt',provider_id:provider.id});expect(starts).toBe(1);
 rows=[{id:'lab-job',task:'ai_test',status:'done',created_at:Date.now(),diagnostics:{duration_ms:1234,test:{case:'receipt',status:'passed',reason:'passed',calls:1,provider_id:provider.id},events:[{event:'request',status:'ok',provider_id:provider.id,duration_ms:1234,input_tokens:110,output_tokens:40,estimated:false},{event:'tool',tool:'lookup_workspace',status:'invalid',issues:[{field:'queries.q',code:'string_type'}]},{event:'tool',tool:'prepare_transaction',status:'ok'}]}}];
 await lab.getByRole('button',{name:'รีเฟรชผลตรวจ AI'}).click();await expect(lab.getByText('ผลลัพธ์หลังตรวจข้อมูลผ่านโจทย์ตัวอย่าง')).toBeVisible();await lab.getByRole('button',{name:'ดูขั้นตอน AI lab-job'}).click();await expect(lab.getByText('prepare_transaction',{exact:false})).toBeVisible();await expect(lab.getByText('เข้า 110 / ออก 40 tokens',{exact:false})).toBeVisible();await expect(lab.getByText('ช่อง queries.q: ต้องเป็นข้อความ',{exact:true})).toBeVisible();
 await lab.getByRole('tab',{name:'วิเคราะห์ปัญหา'}).click();await expect(lab.getByText('ดูขั้นตอนของงานแชท',{exact:false})).toBeVisible();
 await lab.screenshot({path:`../artifacts/ai-lab-${info.project.name}.png`});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await lab.getByRole('button',{name:'ล้างประวัติวิเคราะห์ที่เสร็จแล้ว'}).click();await expect(lab.getByText('ยังไม่มีผลตรวจ',{exact:false})).toBeVisible();expect(starts).toBe(1);
});
