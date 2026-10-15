import {signIn} from './auth';
import {test,expect} from '@playwright/test';
test('stop before first token, discard late output, preserve stopping state and send again',async({page},info)=>{
 await page.addInitScript(()=>{class Source{static all:Source[]=[];onmessage:any;closed=false;constructor(public url:string){Source.all.push(this);}close(){this.closed=true;}emit(value:object){this.onmessage?.({data:JSON.stringify(value)});}};(window as any).EventSource=Source;});
 await signIn(page);const headers={'X-SF-Request':'1'};
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'หยุด AI '+Date.now()}})).json();const base=`/api/workspaces/${ws.id}`;
 const room=await(await page.request.post(base+'/conversations',{headers,data:{title:'ทดสอบหยุดคำตอบ'}})).json();
 let status='pending',stopping=false;
 await page.route('**'+base+'/jobs',route=>route.fulfill({json:[{id:'stop-test',task:'chat',status,error:null,created_at:1,conversation_id:room.id,stopping}]}));
 await page.route('**'+base+'/conversations/'+room.id+'/messages/page*',route=>route.fulfill({json:{items:status==='cancelled'?[{id:'stop-message',role:'assistant',content:'หยุดคำตอบแล้วค่ะ ยังไม่ได้บันทึกหรือแก้ข้อมูลจากคำขอนี้',attachment_id:null}]:[],has_older:false,has_newer:false}}));
 let requests=0;
 await page.route('**'+base+'/conversations/'+room.id+'/jobs/stop-test/stop',async route=>{expect(route.request().method()).toBe('POST');requests++;stopping=true;await route.fulfill({json:{job_id:'stop-test',status:'stopping'}});});
 await page.goto('/assistant');const mobile=(page.viewportSize()?.width||1440)<=900;
 async function history(){if(mobile&&await page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true}).getAttribute('aria-expanded')!=='true')await page.getByRole('button',{name:'เปิดประวัติการสนทนา',exact:true}).click();}
 await history();await page.getByLabel('เลือก workspace ในแชท',{exact:true}).selectOption(ws.id);await history();await page.locator('.rooms button').filter({hasText:'ทดสอบหยุดคำตอบ'}).click();
 const button=page.getByRole('button',{name:'หยุด AI',exact:true});await expect(button).toBeVisible();await expect(page.locator('.live-answer')).toHaveCount(0);
 await button.click();await expect(button).toBeDisabled();await expect(button).toContainText('กำลังหยุด');expect(requests).toBe(1);
 await expect.poll(()=>page.evaluate(()=>((window as any).EventSource.all as any[]).filter(s=>!s.closed).length)).toBe(1);
 async function emit(data:object){await page.evaluate(d=>(window as any).EventSource.all.at(-1).emit(d),data);}
 await emit({kind:'delta',job_id:'stop-test',snapshot:true,text:'คำตอบมาช้า ห้ามแสดง'});await expect(page.locator('.live-answer')).toHaveCount(0);
 await page.locator('.chat-composer-dock').screenshot({path:`../artifacts/chat-stop-${info.project.name}.png`});
 status='cancelled';stopping=false;await emit({kind:'cancelled',job_id:'stop-test'});
 await expect(page.locator('.message.assistant')).toContainText('หยุดคำตอบแล้ว');await expect(button).toHaveCount(0);
 await page.getByRole('textbox',{name:'ข้อความถึง AI',exact:true}).fill('คุยใหม่ได้เลย');await expect(page.getByRole('button',{name:'ส่งข้อความ',exact:true})).toBeEnabled();
 await emit({kind:'start',job_id:'next'});await emit({kind:'delta',job_id:'next',text:'คำตอบรอบใหม่'});await expect(page.locator('.live-answer')).toContainText('คำตอบรอบใหม่');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
