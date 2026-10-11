"use client";
import {useEffect,useState} from 'react';
import {Download,WifiOff,LockKeyhole,Trash2} from 'lucide-react';
import {Button} from './ui/button';
import {memberRequest} from './members';
import {hasVault,saveVault,clearVault,unlockVault,type VaultData} from '../public/offline-store.js';
type InstallEvent=Event&{prompt:()=>Promise<void>;userChoice:Promise<{outcome:string}>};
declare global{interface Window{sfInstallPrompt?:InstallEvent}}
export function PwaBoot(){
 const [waiting,setWaiting]=useState<ServiceWorker|null>(null);
 useEffect(()=>{
  const install=(event:Event)=>{event.preventDefault();window.sfInstallPrompt=event as InstallEvent;window.dispatchEvent(new Event('sf-install-ready'));};
  window.addEventListener('beforeinstallprompt',install);
  if('serviceWorker' in navigator&&window.isSecureContext)navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(reg=>{if(reg.waiting)setWaiting(reg.waiting);reg.addEventListener('updatefound',()=>{const worker=reg.installing;worker?.addEventListener('statechange',()=>{if(worker.state==='installed'&&navigator.serviceWorker.controller)setWaiting(reg.waiting);});});}).catch(()=>{});
  return()=>window.removeEventListener('beforeinstallprompt',install);
 },[]);
 return waiting?<div className="pwa-update" role="status">มีแอปรุ่นใหม่ <button onClick={()=>{navigator.serviceWorker.addEventListener('controllerchange',()=>window.location.reload(),{once:true});waiting.postMessage('SKIP_WAITING');}}>อัปเดตเมื่อพร้อม</button></div>:null;
}
export function PwaSettings({wid,name}:{wid:string;name:string}){
 const [ready,setReady]=useState(false),[installed,setInstalled]=useState(false),[saved,setSaved]=useState(false),[busy,setBusy]=useState(false),[password,setPassword]=useState(''),[repeat,setRepeat]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState('');
 useEffect(()=>{setSaved(hasVault());setInstalled(matchMedia('(display-mode: standalone)').matches);const update=()=>setReady(!!window.sfInstallPrompt);update();window.addEventListener('sf-install-ready',update);return()=>window.removeEventListener('sf-install-ready',update);},[]);
 async function save(){setError('');setNotice('');setBusy(true);try{
  if(!window.isSecureContext)throw new Error('ข้อมูลออฟไลน์ต้องใช้ HTTPS หรือ localhost');
  if(password!==repeat)throw new Error('รหัสออฟไลน์และการยืนยันไม่ตรงกัน');
  if(password.length<12||password.length>200)throw new Error('รหัสออฟไลน์ต้องมี 12–200 ตัวอักษร');
  const user=await memberRequest<{id:string}>('/auth/me');
  let drafts:VaultData['drafts']=[];
  if(hasVault()){const old=await unlockVault(password);if(old.user_id!==user.id||old.workspace_id!==wid)throw new Error('มีข้อมูลของบัญชีหรือพื้นที่อื่นอยู่ กรุณาล้างข้อมูลออฟไลน์ก่อนเปลี่ยนพื้นที่');drafts=old.drafts;}
  const [spaces,accounts,transactions]=await Promise.all([memberRequest<{id:string;name:string}[]>('/workspaces'),memberRequest<VaultData['accounts']>(`/workspaces/${wid}/accounts`),memberRequest<VaultData['transactions']>(`/workspaces/${wid}/transactions?limit=100`)]);
  const workspace=spaces.find(w=>w.id===wid);if(!workspace)throw new Error('พื้นที่นี้ไม่พร้อมใช้งาน');
  await saveVault({version:1,user_id:user.id,workspace_id:wid,workspace_name:workspace.name,saved_at:Date.now(),accounts:accounts.map(a=>({name:a.name,kind:a.kind,balance:a.balance})),transactions:transactions.map(t=>({id:t.id,description:t.description,kind:t.kind,amount:t.amount,occurred_on:t.occurred_on})),drafts},password);
  setSaved(true);setPassword('');setRepeat('');setNotice('เก็บข้อมูลเข้ารหัสบนเครื่องนี้แล้ว เปิดหน้าออฟไลน์และใช้รหัสที่ตั้งไว้เพื่อดูข้อมูล');
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="panel pwa-settings" id="offline-settings"><div className="panel-title"><h3><Download size={20}/>ติดตั้งแอปและออฟไลน์</h3></div><p className="muted">เปิด Smart Finance จากหน้าจอหลัก และเตรียมร่างรายการได้เมื่อไม่มีอินเทอร์เน็ต</p>{installed?<p className="small">เปิดอยู่ในโหมดแอปแล้ว</p>:ready?<Button variant="outline" onClick={async()=>{const prompt=window.sfInstallPrompt;if(!prompt)return;await prompt.prompt();const choice=await prompt.userChoice;if(choice.outcome==='accepted')setInstalled(true);window.sfInstallPrompt=undefined;setReady(false);}}><Download size={17}/>ติดตั้ง Smart Finance</Button>:<p className="small muted">ติดตั้งผ่านเมนูเบราว์เซอร์ “ติดตั้งแอป / เพิ่มลงในหน้าจอหลัก” บน iPhone ใช้ Safari → แชร์ → เพิ่มลงในหน้าจอโฮม ต้องใช้ HTTPS หรือ localhost</p>}<hr/><h4><LockKeyhole size={18}/>ข้อมูลออฟไลน์บนเครื่องนี้</h4><p className="muted small">เลือกเก็บยอดบัญชีและ 100 รายการล่าสุดของ “{name}” พร้อมร่างข้อความ เข้ารหัสด้วยรหัสออฟไลน์แยกจากรหัสเข้าสู่ระบบ ไม่เก็บแชท รูปสลิป หรือ API key ยอดที่เก็บเป็นภาพ ณ เวลาบันทึก</p><form onSubmit={e=>{e.preventDefault();save();}}><label>รหัสปลดล็อกออฟไลน์<input type="password" autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} required minLength={12} maxLength={200} disabled={busy}/></label><label>ยืนยันรหัสออฟไลน์<input type="password" autoComplete="off" value={repeat} onChange={e=>setRepeat(e.target.value)} required minLength={12} maxLength={200} disabled={busy}/></label><Button disabled={busy}>{busy?'กำลังเก็บข้อมูล…':saved?'อัปเดตข้อมูลออฟไลน์':'เก็บข้อมูลไว้ใช้ออฟไลน์'}</Button></form>{saved&&<div className="offline-actions"><a href="/offline.html"><WifiOff size={17}/>เปิดพื้นที่ออฟไลน์</a><Button variant="ghost" disabled={busy} onClick={()=>{clearVault();setSaved(false);setNotice('ล้างข้อมูลออฟไลน์และร่างบนเครื่องนี้แล้ว');}}><Trash2 size={16}/>ล้างข้อมูลบนเครื่อง</Button></div>}<p className="small muted">ออกจากระบบจะล้างข้อมูลออฟไลน์รวมร่างบนเครื่องนี้ ร่างต้องส่งให้ทวนและพิมพ์ยืนยันเมื่อออนไลน์ ไม่มีการลงยอดหรือส่งอัตโนมัติ</p>{error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}</section>;
}
