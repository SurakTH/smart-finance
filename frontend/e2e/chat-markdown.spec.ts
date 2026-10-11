import {test,expect} from '@playwright/test';
import {signIn} from './auth';
test('safe Markdown formats history and streaming without hiding financial review data',async({page},info)=>{
 await page.addInitScript(()=>{class Source{static all:Source[]=[];onmessage:any;onerror:any;closed=false;constructor(public url:string){Source.all.push(this);}close(){this.closed=true;}emit(value:object){this.onmessage?.({data:JSON.stringify(value)});}};(window as any).EventSource=Source;(window as any).__markdownXss=false;});
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'รูปแบบแชท '+crypto.randomUUID()}})).json(),base='/api/workspaces/'+ws.id;
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'Markdown'}})).json();
 const code='const total = 75; // ==ไม่ใช่ไฮไลต์==\n'+ 'x'.repeat(180);
 const text=['## ภาพรวมเดือนนี้','**ยอดใช้จ่าย** *หมายเหตุ* ~~ข้อมูลเดิม~~ ==ตรวจสอบยอด==','บรรทัดแรก\nบรรทัดที่สอง','- อาหาร\n- เดินทาง','1. ตรวจรายการ\n2. ยืนยัน','- [x] ตรวจแล้ว\n- [ ] รอยืนยัน','> บันทึกเมื่อพร้อมเท่านั้น','| หมวด | จำนวน |\n| --- | ---: |\n| อาหาร | 75 |','`ยอด = 75`','```javascript\n'+code+'\n```','[เอกสาร](https://example.invalid/docs)','[อันตราย](javascript:alert(1)) [ข้อมูล](data:text/html,test) [ภายใน](/api/auth/logout)','![ไม่โหลดรูป](https://example.invalid/tracker.png)','<img src=x onerror="window.__markdownXss=true"><script>window.__markdownXss=true</script>'].join('\n\n');
 const rows=[{id:'markdown-user',role:'user',content:'**ข้อความของฉัน**',attachment_id:null},{id:'markdown-answer',role:'assistant',content:text,attachment_id:null},{id:'literal-review',role:'assistant',content:'กรุณาตรวจสอบ — ยังไม่บันทึก\n\nบัญชี: **ชื่อบัญชีจริง**\nรายละเอียด: ==ชื่อจริง==\nจำนวน: ฿75.00',attachment_id:null}];
 let remoteRequests=0;await page.route('https://example.invalid/**',route=>{remoteRequests++;return route.abort();});
 await page.route('**/conversations/'+room.id+'/messages/page*',route=>route.fulfill({json:{items:rows,has_older:false,has_newer:false}}));
 await page.evaluate(wid=>sessionStorage.setItem('sf-workspace',wid),ws.id);await page.goto('/assistant?conversation='+room.id);
 const answer=page.locator('#chat-message-markdown-answer');await expect(answer.locator('h2')).toHaveText('ภาพรวมเดือนนี้');await expect(answer.locator('strong')).toHaveText('ยอดใช้จ่าย');await expect(answer.locator('em')).toHaveText('หมายเหตุ');await expect(answer.locator('del')).toHaveText('ข้อมูลเดิม');await expect(answer.locator('mark')).toHaveText('ตรวจสอบยอด');
 await expect(answer.locator('blockquote')).toContainText('บันทึกเมื่อพร้อม');await expect(answer.locator('table tbody td')).toHaveCount(2);await expect(answer.locator('input[type=checkbox]')).toHaveCount(2);await expect(answer.locator('input[type=checkbox]').first()).toBeDisabled();await expect(answer.locator('br')).toHaveCount(1);
 await expect(answer.locator('pre code')).toHaveText(code);await expect(answer.locator('pre mark')).toHaveCount(0);await expect(answer.locator('img,script,iframe')).toHaveCount(0);
 await expect(answer.locator('a[href="https://example.invalid/docs"]')).toHaveAttribute('rel','noopener noreferrer');await expect(answer.locator('a[href^="javascript:"],a[href^="data:"],a[href^="/api/"]')).toHaveCount(0);
 expect(await page.evaluate(()=>(window as any).__markdownXss)).toBe(false);expect(remoteRequests).toBe(0);
 await expect(page.locator('#chat-message-markdown-user strong')).toHaveText('ข้อความของฉัน');await expect(page.locator('#chat-message-literal-review')).toContainText('**ชื่อบัญชีจริง**');await expect(page.locator('#chat-message-literal-review strong,#chat-message-literal-review mark')).toHaveCount(0);
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);await answer.getByRole('button',{name:'คัดลอกโค้ด',exact:true}).click();await expect(answer.getByRole('button',{name:'คัดลอกโค้ด',exact:true})).toHaveText('คัดลอกแล้ว');expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe(code+'\n');
 await expect.poll(()=>page.evaluate(()=>((window as any).EventSource.all as any[]).filter(s=>!s.closed).length)).toBe(1);
 async function emit(data:object){await page.evaluate(value=>(window as any).EventSource.all.at(-1).emit(value),data);}
 await emit({kind:'start',job_id:'markdown-stream'});await emit({kind:'delta',job_id:'markdown-stream',snapshot:true,text:'### กำลังสรุป\n\n**ยอด'});await expect(page.locator('.live-answer h3')).toHaveText('กำลังสรุป');
 await emit({kind:'delta',job_id:'markdown-stream',snapshot:true,text:'### กำลังสรุป\n\n**ยอดรวม** ==ตรวจอีกครั้ง=='});await expect(page.locator('.live-answer strong')).toHaveText('ยอดรวม');await expect(page.locator('.live-answer mark')).toHaveText('ตรวจอีกครั้ง');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await answer.screenshot({path:`../artifacts/chat-markdown-${info.project.name}.png`});
});
