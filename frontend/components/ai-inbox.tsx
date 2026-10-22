"use client";
import {useEffect,useRef,useState} from 'react';
import Link from 'next/link';
import {ImagePlus,Inbox,Search,ShieldCheck,Sparkles,X,RefreshCw,FileCheck2} from 'lucide-react';
import {Button} from './ui/button';
import {ReceiptDetails,type ReceiptInfo} from './receipt-details';
import {imageInputError,transferredFiles} from '../lib/chat-images';

type Draft={id:string;description:string;amount:number|null;kind:string;source:string;attachment_id?:string|null;occurred_on?:string|null;receipt?:ReceiptInfo|null};
type Work={id:string;task?:string;status:string;message?:string|null;error:string|null};
const money=(n:number)=>new Intl.NumberFormat('th-TH',{style:'currency',currency:'THB'}).format(n/100);
export function AIInbox({base,drafts,jobs,busy,onSubmit,onReview,onReject,onRefresh,onManual}:{base:string;drafts:Draft[];jobs:Work[];busy:boolean;onSubmit:(text:string,file:File|null)=>Promise<boolean>;onReview:(p:Draft)=>void;onReject:(id:string)=>void;onRefresh:()=>void;onManual:()=>void}){
 const [text,setText]=useState(''),[file,setFile]=useState<File|null>(null),[preview,setPreview]=useState(''),[error,setError]=useState(''),[query,setQuery]=useState(''),[filter,setFilter]=useState('all'),[dragging,setDragging]=useState(false),[dismissed,setDismissed]=useState<string[]>([]);
 const submitting=useRef(false),depth=useRef(0),input=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(!file){setPreview('');return;}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 const select=(files:File[])=>{const issue=imageInputError(files);if(issue){setError(issue);return;}setError('');setFile(files[0]);};
 const work=jobs.filter(j=>j.task==='extract'),active=work.filter(j=>j.status==='pending'),failed=work.filter(j=>j.status==='failed'&&!dismissed.includes(j.id));
 const shown=drafts.filter(p=>(filter==='all'||(filter==='image'?!!p.attachment_id:p.amount===null))&&p.description.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
 return <div className="inbox-page">
  <section className={'panel inbox-compose'+(dragging?' is-dragging':'')} aria-label="เพิ่มรายการเข้า Inbox"
   onDragEnter={e=>{if(!Array.from(e.dataTransfer.types).includes('Files'))return;e.preventDefault();depth.current++;setDragging(true);}}
   onDragOver={e=>{if(Array.from(e.dataTransfer.types).includes('Files'))e.preventDefault();}}
   onDragLeave={e=>{e.preventDefault();if(--depth.current<=0){depth.current=0;setDragging(false);}}}
   onDrop={e=>{depth.current=0;setDragging(false);const files=transferredFiles(e.dataTransfer);if(!files.length)return;e.preventDefault();if(!busy)select(files);}}>
   <div className="inbox-compose-heading"><span className="inbox-symbol"><Sparkles size={23}/></span><div><h2>จากสลิป เป็นรายการพร้อมตรวจ</h2><p className="muted">แนบรูปแล้วเล่าเพิ่มได้ หรือพิมพ์รายการอย่างเดียวก็ได้</p></div></div>
   <form onSubmit={async e=>{e.preventDefault();if(busy||submitting.current||(!file&&!text.trim()))return;submitting.current=true;try{if(await onSubmit(text.trim(),file)){setText('');setFile(null);setError('');}}finally{submitting.current=false;}}}
    onPaste={e=>{const files=transferredFiles(e.clipboardData);if(!files.length)return;e.preventDefault();if(busy)return;select(files);const caption=e.clipboardData.getData('text/plain');if(caption)setText(old=>(old+(old?'\n':'')+caption).slice(0,4000));}}>
    <div className={'inbox-inputs'+(file?' with-image':'')}>
     {preview&&<div className="inbox-preview"><img src={preview} alt="ตัวอย่างสลิปก่อนส่ง"/><button type="button" className="icon-button" aria-label="นำสลิปออก" disabled={busy} onClick={()=>setFile(null)}><X size={18}/></button><span>{file?.name}</span></div>}
     <label className="inbox-caption">{file?'รายละเอียดเพิ่มเติม (ไม่บังคับ)':'เล่าให้ฟังว่าใช้เงินกับอะไร'}<textarea aria-label="ข้อความรายการเงิน" value={text} onChange={e=>setText(e.target.value)} maxLength={4000} disabled={busy} placeholder={file?'เช่น ค่าหนังสือ จ่ายจากเงินสด ช่วยอ่านยอดจากรูปให้หน่อย':'เช่น ข้าว 75 น้ำ 25 หรือวางรูปสลิปตรงนี้'}/><span className="muted small">{text.length.toLocaleString()} / 4,000</span></label>
    </div>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="inbox-compose-actions"><Button type="button" variant="outline" disabled={busy} onClick={()=>input.current?.click()}><ImagePlus size={18}/>{file?'เปลี่ยนรูป':'แนบสลิป'}</Button><span className="inbox-file-hint muted">วางรูป / ลากมาวาง · JPG, PNG, WebP ≤ 8 MB</span><Button disabled={busy||(!file&&!text.trim())}><Sparkles size={17}/>{busy?'กำลังส่ง…':file?'อ่านสลิปและสร้างร่าง':'สร้างข้อเสนอ'}</Button></div>
    <input ref={input} hidden tabIndex={-1} aria-label="อัปโหลดสลิป" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e=>{if(e.target.files?.length)select(Array.from(e.target.files));e.target.value='';}}/>
   </form>
   <div className="inbox-privacy"><ShieldCheck size={17}/><span>ใช้ AI ตามการตั้งค่าของ workspace นี้</span><Link href="/ai-settings">ตั้งค่า AI</Link><span>ตรวจร่างก่อนบันทึกเสมอ</span></div>
  </section>
  {active.length>0&&<div className="inbox-progress" role="status"><RefreshCw size={18}/><div><strong>กำลังอ่าน {active.length} งาน</strong><p>อ่านเสร็จแล้วร่างจะปรากฏด้านล่าง ออกจากหน้านี้ได้</p></div></div>}
  {failed.length>0&&<div className="inbox-failures"><details><summary>มีงานอ่านไม่สำเร็จ {failed.length} งาน</summary>{failed.map(j=><div key={j.id}><p>{j.message||'อ่านข้อมูลไม่สำเร็จ ลองแนบรูปใหม่ หรือกรอกรายการเองได้'}</p><Button size="sm" variant="ghost" onClick={()=>setDismissed(old=>[...old,j.id])}>รับทราบ</Button></div>)}<p className="small muted">หากยังไม่มีร่าง ส่งรูปเดิมพร้อมรายละเอียดอีกครั้งได้</p><Link href="/ai-settings">ตรวจการตั้งค่า AI สำหรับอ่านสลิป</Link></details></div>}
  <section className="panel inbox-review"><div className="panel-heading"><div><h2>รอตรวจสอบ <span className="inbox-count">{drafts.length}</span></h2><p className="muted small">ยอดเงินยังไม่เปลี่ยน จนกว่าคุณจะตรวจและยืนยัน</p></div><Button variant="ghost" size="sm" disabled={busy} onClick={onRefresh}><RefreshCw size={16}/>รีเฟรช</Button></div>
   {drafts.length>0&&<div className="inbox-filters"><div role="group" aria-label="กรองร่าง"><button aria-pressed={filter==='all'} onClick={()=>setFilter('all')}>ทั้งหมด</button><button aria-pressed={filter==='image'} onClick={()=>setFilter('image')}>มีสลิป</button><button aria-pressed={filter==='missing'} onClick={()=>setFilter('missing')}>ยังไม่มียอด</button></div><label><Search size={17}/><input aria-label="ค้นหาร่าง" value={query} onChange={e=>setQuery(e.target.value)} placeholder="ค้นหารายการ…"/></label></div>}
   {drafts.length>=100&&<p className="notice small">แสดงสูงสุด 100 ร่าง ตรวจรายการแล้วรีเฟรชเพื่อดูรายการถัดไป</p>}
   {shown.map(p=><article className="proposal inbox-draft" key={p.id}>{p.attachment_id?<a href={'/api'+base+'/attachments/'+p.attachment_id} target="_blank" rel="noreferrer" aria-label={'เปิดสลิป '+p.description}><img loading="lazy" src={'/api'+base+'/attachments/'+p.attachment_id} alt={'สลิป '+p.description}/></a>:<span className="inbox-draft-icon"><FileCheck2 size={22}/></span>}<div className="inbox-draft-detail"><span className="tag">{p.source==='demo'?'สาธิต · ตรวจข้อมูลด้วยตนเอง':p.source==='recurring'?'รายการประจำ · รอยืนยัน':p.attachment_id?'อ่านจากสลิป':'ร่างรายการ'}</span><h3>{p.description}</h3><p className="muted small">{p.kind==='income'?'รายรับ':'รายจ่าย'}{p.occurred_on?' · '+p.occurred_on:''}</p><ReceiptDetails receipt={p.receipt}/></div><strong className={p.amount===null?'inbox-missing':'inbox-amount'}>{p.amount===null?'กรอกยอดก่อนบันทึก':money(p.amount)}</strong><div className="inbox-draft-actions"><Button variant="ghost" size="sm" disabled={busy} onClick={()=>onReject(p.id)}>ยกเลิก</Button><Button size="sm" disabled={busy} onClick={()=>onReview(p)}>ตรวจสอบ</Button></div></article>)}
   {!shown.length&&<div className="inbox-empty"><span><Inbox size={30}/></span><h3>{drafts.length?'ไม่พบร่างที่ตรงกับตัวกรอง':'พร้อมช่วยจดรายการถัดไป'}</h3><p className="muted">{drafts.length?'ลองเปลี่ยนคำค้นหาหรือตัวกรอง':'แนบสลิปพร้อมรายละเอียดด้านบน แล้วตรวจยอด บัญชี และหมวดหมู่ก่อนบันทึก'}</p>{!drafts.length&&<Button variant="outline" onClick={onManual}>กรอกรายการเอง</Button>}</div>}
  </section>
  <p className="muted small inbox-footnote">AI อาจอ่านผิดได้ · การอ่านสลิปไม่ใช่การตรวจสอบว่าสลิปแท้</p>
 </div>;
}
