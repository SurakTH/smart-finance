"use client";
import {useEffect,useRef,useState} from 'react';
import {History,X,ChevronLeft,ChevronRight} from 'lucide-react';
import {memberRequest} from './members';
type Result={items:{id:string;summary:string;created_at:number;actor:string}[];has_more:boolean;page:number};
export function AssistantHistory({wid}:{wid:string}){
 const [open,setOpen]=useState(false),[page,setPage]=useState(1),[data,setData]=useState<Result|null>(null),[error,setError]=useState('');
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{if(open)dialog.current?.showModal();else dialog.current?.close();},[open]);
 useEffect(()=>{if(!open)return;const abort=new AbortController();setData(null);setError('');memberRequest<Result>(`/workspaces/${wid}/assistant-changes?page=${page}`,'GET',undefined,abort.signal).then(d=>{if(!abort.signal.aborted)setData(d);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[wid,page,open]);
 return <><button className="rename-chat" onClick={()=>{setPage(1);setOpen(true);}}><History size={16}/>ประวัติงานผู้ช่วย</button><dialog className="assistant-history-dialog" ref={dialog} aria-labelledby="assistant-history-title" onCancel={()=>setOpen(false)} onClick={e=>{if(e.target===e.currentTarget)setOpen(false);}}><div className="panel-heading"><h2 id="assistant-history-title">งานที่ผู้ช่วยทำแล้ว</h2><button className="icon-button" aria-label="ปิดประวัติงานผู้ช่วย" onClick={()=>setOpen(false)}><X size={20}/></button></div><p className="muted">แผนบัญชี หมวด งบ เป้าออม และรายการประจำที่ผู้ใช้ยืนยันแล้ว สมาชิกพื้นที่ดูร่วมกันได้ ประวัตินี้ยังอยู่เมื่อลบแชท</p>{error?<p role="alert">{error}</p>:!data?<p role="status">กำลังโหลด…</p>:data.items.length?data.items.map(item=><article key={item.id} className="assistant-change"><small>{new Intl.DateTimeFormat('th-TH',{dateStyle:'medium',timeStyle:'short'}).format(new Date(item.created_at*1000))} · ยืนยันโดย {item.actor}</small><p>{item.summary}</p></article>):<p>ยังไม่มีแผนที่ยืนยันแล้ว รายการเงินดูประวัติจากหน้ารายการเงินได้</p>}<div className="assistant-history-pages"><button disabled={page===1||!data} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={16}/>ก่อนหน้า</button><span>หน้า {page}</span><button disabled={!data?.has_more} onClick={()=>setPage(p=>p+1)}>ถัดไป<ChevronRight size={16}/></button></div></dialog></>;
}
