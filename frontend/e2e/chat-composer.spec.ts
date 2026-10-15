import {test,expect,type Page} from '@playwright/test';
import {signIn} from './auth';
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMImFAAAAKEAVGsDQL6AAAAAElFTkSuQmCC';
const headers={'X-SF-Request':'1'};
async function prepare(page:Page){
 await signIn(page);
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'แชท UX '+crypto.randomUUID()}})).json();
 const base='/api/workspaces/'+ws.id;
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'ทดสอบวางรูป'}})).json();
 await page.goto(`/assistant?workspace=${ws.id}&conversation=${room.id}`);
 await expect(page.getByLabel('ข้อความถึง AI',{exact:true})).toBeVisible();
 await expect(page.locator('.rooms button.selected')).toHaveCount(1);
 return {ws,room,base};
}
async function transfer(page:Page,event:string,files:{name:string;type:string;size?:number}[],text=''){
 await page.locator(event==='paste'?'.composer':'.chat').evaluate((node,{event,files,png,text})=>{
  const data=new DataTransfer();
  for(const file of files){const bytes=file.size?new Uint8Array(file.size):Uint8Array.from(atob(png),c=>c.charCodeAt(0));data.items.add(new File([bytes],file.name,{type:file.type}));}
  if(text)data.setData('text/plain',text);
  node.dispatchEvent(event==='paste'?new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}):new DragEvent(event,{dataTransfer:data,bubbles:true,cancelable:true}));
 },{event,files,png,text});
}

test('native clipboard image stays local, preserves text, and sends only on explicit submit',async({page},info)=>{
 const {base,room}=await prepare(page);let uploads=0,body='';
 await page.route('**'+base+'/conversations/'+room.id+'/images',async route=>{uploads++;body=route.request().postDataBuffer()?.toString('latin1')||'';await route.fulfill({json:{job_id:null}});});
 const input=page.getByLabel('ข้อความถึง AI',{exact:true});await input.fill('ค่าหนังสือ');
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);
 await page.evaluate(async encoded=>{const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));await navigator.clipboard.write([new ClipboardItem({'image/png':new Blob([bytes],{type:'image/png'})})]);},png);
 await input.focus();await page.keyboard.press(process.platform==='darwin'?'Meta+V':'Control+V');
 await expect(page.getByRole('img',{name:'ตัวอย่างรูปก่อนส่ง',exact:true})).toBeVisible();
 await expect(input).toHaveValue('ค่าหนังสือ');expect(uploads).toBe(0);
 await expect(page.locator('.chat-attachment-preview')).toContainText('ยังไม่ส่ง');
 await page.screenshot({path:`../artifacts/chat-paste-${info.project.name}.png`,fullPage:true});
 await page.getByRole('button',{name:'ส่งข้อความ',exact:true}).click();
 await expect.poll(()=>uploads).toBe(1);expect(body).toContain('Content-Type: image/png');
 await expect(page.locator('.chat-attachment-preview')).toHaveCount(0);
 expect((await(await page.request.get(base+'/transaction-report')).json()).total).toBe(0);
});

test('paste and drop share validation, keep the previous attachment on errors, and clear on room changes',async({page})=>{
 const {base,ws}=await prepare(page);let uploads=0;
 page.on('request',r=>{if(r.url().includes('/images')&&r.method()==='POST')uploads++;});
 const input=page.getByLabel('ข้อความถึง AI',{exact:true});await input.fill('เดิม');
 await input.evaluate(node=>(node as HTMLTextAreaElement).setSelectionRange(0,0));
 await transfer(page,'paste',[{name:'pasted.png',type:'image/png'}],'เพิ่มเติม ');
 await expect(input).toHaveValue('เพิ่มเติม เดิม');await expect(page.locator('.chat-attachment-preview')).toContainText('pasted.png');
 await transfer(page,'paste',[{name:'bad.svg',type:'image/svg+xml'}]);await expect(page.locator('.chat-upload-error')).toContainText('JPG, PNG และ WebP');
 await expect(page.locator('.chat-attachment-preview')).toContainText('pasted.png');
 await transfer(page,'paste',[{name:'big.png',type:'image/png',size:8*1024*1024+1}]);await expect(page.locator('.chat-upload-error')).toContainText('8 MB');
 await transfer(page,'paste',[{name:'a.png',type:'image/png'},{name:'b.png',type:'image/png'}]);await expect(page.locator('.chat-upload-error')).toContainText('ครั้งละ 1 รูป');
 await transfer(page,'dragenter',[{name:'dropped.png',type:'image/png'}]);await expect(page.locator('.chat-drop-overlay')).toContainText('วางรูปที่นี่');
 await transfer(page,'drop',[{name:'dropped.png',type:'image/png'}]);await expect(page.locator('.chat-drop-overlay')).toHaveCount(0);
 await expect(page.locator('.chat-attachment-preview')).toContainText('dropped.png');await expect(page.locator('.chat-upload-error')).toHaveCount(0);
 await page.getByRole('button',{name:'นำรูปออก',exact:true}).click();await expect(page.locator('.chat-attachment-preview')).toHaveCount(0);await expect(input).toHaveValue('เพิ่มเติม เดิม');
 await transfer(page,'paste',[{name:'again.png',type:'image/png'}]);
 const other=await(await page.request.post(base+'/conversations',{headers,data:{title:'อีกห้อง'}})).json();
 await page.goto(`/assistant?workspace=${ws.id}&conversation=${other.id}`);await expect(input).toBeVisible();await expect(page.locator('.chat-attachment-preview')).toHaveCount(0);
 expect(uploads).toBe(0);
});

test('retention buttons apply to new rooms and remain compact and keyboard accessible',async({page},info)=>{
 const {base}=await prepare(page),mobile=info.project.name==='mobile';
 async function history(){const toggle=page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true});if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();}
 await history();const picker=page.getByRole('group',{name:'ประเภทแชทใหม่',exact:true});
 await expect(picker.getByRole('button',{name:'เก็บประวัติ',exact:true})).toHaveAttribute('aria-pressed','true');
 await picker.getByRole('button',{name:'ชั่วคราว',exact:true}).click();await expect(page.locator('.temporary-banner')).toHaveCount(0);
 if(mobile){await page.getByLabel('ค้นหาประวัติแชท').focus();await page.keyboard.press('Tab');await expect.poll(()=>page.evaluate(()=>!!document.activeElement?.closest('#chat-history'))).toBe(true);}
 const created=page.waitForResponse(r=>r.url().endsWith(base+'/conversations')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'บทสนทนาใหม่',exact:true}).click();expect((await created).request().postDataJSON().temporary).toBe(true);
 await expect(page.locator('.temporary-banner')).toBeVisible();await expect(page.locator('.privacy-pill')).toContainText('ชั่วคราว');
 await history();await picker.getByRole('button',{name:'เก็บประวัติ',exact:true}).click();await expect(page.locator('.temporary-banner')).toBeVisible();
 await expect(page.locator('.new-chat')).toBeInViewport();await expect(page.getByLabel('ค้นหาประวัติแชท')).toBeInViewport();
 await expect(page.locator('.chat-history')).not.toContainText('Local AI');
 await page.screenshot({path:`../artifacts/chat-sidebar-${info.project.name}.png`,fullPage:true});
 await page.getByRole('button',{name:'บทสนทนาใหม่',exact:true}).click();await expect(page.locator('.temporary-banner')).toHaveCount(0);
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('jump to latest and copy visible answer work without changing ledger data',async({page})=>{
 const {ws,room,base}=await prepare(page);
 const visible='สรุปจากข้อมูลที่บันทึกแล้วค่ะ';
 const rows=Array.from({length:40},(_,i)=>({id:'display-'+i,role:'assistant',content:i===39?visible+'\n\nรหัสทางเลือก:\nยืนยัน ABCDEF12\n':`ข้อความตัวอย่าง ${i}\nรายละเอียดเพิ่มเติม\nอีกหนึ่งบรรทัด`,attachment_id:null}));
 await page.route('**'+base+'/conversations/'+room.id+'/messages/page*',r=>r.fulfill({json:{items:rows,has_older:false,has_newer:false}}));
 await page.goto(`/assistant?workspace=${ws.id}&conversation=${room.id}`);
 await expect(page.locator('.message.assistant')).toHaveCount(40);
 await page.locator('.messages').evaluate(node=>{node.scrollTop=0;node.dispatchEvent(new Event('scroll'));});
 await page.getByRole('button',{name:'ข้อความล่าสุด',exact:true}).click();
 await expect(page.locator('.message.assistant').last()).toBeInViewport();
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);
 await page.getByRole('button',{name:'คัดลอกคำตอบ',exact:true}).last().click();
 await expect(page.getByRole('button',{name:'คัดลอกคำตอบแล้ว',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe(visible);
 expect((await(await page.request.get(base+'/transaction-report')).json()).total).toBe(0);
});
