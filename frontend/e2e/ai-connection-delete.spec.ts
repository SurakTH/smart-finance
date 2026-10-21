import {test,expect,type Page} from '@playwright/test';
import {signIn} from './auth';
const headers={'X-SF-Request':'1'};
async function prepare(page:Page){
 await signIn(page);
 const ws=await(await page.request.post('/api/workspaces',{headers,data:{name:'ลบผู้ให้บริการ '+crypto.randomUUID()}})).json();
 const base='/api/workspaces/'+ws.id;
 const addConnection=async(name:string)=>(await page.request.post(base+'/ai/connections',{headers,data:{name,kind:'ollama'}})).json();
 const target=await addConnection('ผู้ให้บริการเก่า'),spare=await addConnection('ผู้ให้บริการที่เก็บไว้');
 for(const [connection_id,model,task] of [[target.id,'old-chat','chat'],[target.id,'old-reader','extract'],[spare.id,'keep-model','chat']]){
  const r=await page.request.post(base+'/providers',{headers,data:{connection_id,kind:'ollama',model,task}});expect(r.ok()).toBe(true);
 }
 await page.goto('/ai-settings?workspace='+ws.id+'&section=connections');
 await expect(page.getByRole('button',{name:'ลบผู้ให้บริการ ผู้ให้บริการเก่า',exact:true})).toBeVisible();
 return {base,target,spare};
}

test('owner can review, cancel and remove a used provider together with its chat and receipt models',async({page},info)=>{
 const {base,target,spare}=await prepare(page);
 await page.getByRole('button',{name:'ลบผู้ให้บริการ ผู้ให้บริการเก่า',exact:true}).click();
 let dialog=page.getByRole('dialog',{name:'ลบผู้ให้บริการ AI?',exact:true});
 await expect(dialog).toContainText('old-chat');await expect(dialog).toContainText('old-reader');
 await expect(dialog).toContainText('ประวัติแชท ข้อมูลการเงิน และประวัติการใช้ AI ยังคงอยู่');
 await dialog.getByRole('button',{name:'ยกเลิก',exact:true}).click();await expect(dialog).toHaveCount(0);
 expect((await(await page.request.get(base+'/providers')).json()).length).toBe(3);
 await page.getByRole('button',{name:'ลบผู้ให้บริการ ผู้ให้บริการเก่า',exact:true}).click();
 dialog=page.getByRole('dialog',{name:'ลบผู้ให้บริการ AI?',exact:true});
 await expect(dialog.getByRole('button',{name:'ยืนยันลบผู้ให้บริการและ 2 โมเดล',exact:true})).toBeEnabled();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`../artifacts/ai-connection-delete-${info.project.name}.png`});
 await dialog.getByRole('button',{name:'ยืนยันลบผู้ให้บริการและ 2 โมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 await expect(page.getByRole('status')).toContainText('ลบผู้ให้บริการและคีย์แล้ว พร้อม 2 โมเดล');
 await expect(page.getByRole('button',{name:'ลบผู้ให้บริการ ผู้ให้บริการเก่า',exact:true})).toHaveCount(0);
 const connections=await(await page.request.get(base+'/ai/connections')).json();expect(connections.map((c:any)=>c.id)).toEqual([spare.id]);
 const profiles=await(await page.request.get(base+'/providers')).json();expect(profiles.map((p:any)=>p.model)).toEqual(['keep-model']);
});

test('a new linked model invalidates a deletion preview and must be reviewed before removal',async({page})=>{
 const {base,target}=await prepare(page);
 await page.getByRole('button',{name:'ลบผู้ให้บริการ ผู้ให้บริการเก่า',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'ลบผู้ให้บริการ AI?',exact:true});
 await expect(dialog.getByRole('button',{name:'ยืนยันลบผู้ให้บริการและ 2 โมเดล',exact:true})).toBeEnabled();
 expect((await page.request.post(base+'/providers',{headers,data:{connection_id:target.id,kind:'ollama',model:'added-later',task:'chat'}})).ok()).toBe(true);
 await dialog.getByRole('button',{name:'ยืนยันลบผู้ให้บริการและ 2 โมเดล',exact:true}).click();
 await expect(dialog.getByRole('alert')).toContainText('รายการโมเดลเปลี่ยนแล้ว');
 expect((await(await page.request.get(base+'/providers')).json()).length).toBe(4);
 await dialog.getByRole('button',{name:'โหลดรายการล่าสุด',exact:true}).click();
 await expect(dialog).toContainText('added-later');
 await dialog.getByRole('button',{name:'ยืนยันลบผู้ให้บริการและ 3 โมเดล',exact:true}).click();await expect(dialog).toHaveCount(0);
 expect((await(await page.request.get(base+'/providers')).json()).length).toBe(1);
});
