"use client";
import {useEffect,useRef,useState} from 'react';
import {Trash2,X} from 'lucide-react';
import {Button} from './ui/button';
import {memberRequest as request} from './members';
type Plan={id:string;name:string;models:{id:string;name:string;model:string;task:string}[]};
export function AIConnectionDelete({base,id,onClose,onDeleted}:{base:string;id:string;onClose:()=>void;onDeleted:(count:number)=>void}){
 const dialog=useRef<HTMLDialogElement>(null);
 const [plan,setPlan]=useState<Plan|null>(null),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 useEffect(()=>{dialog.current?.showModal();return()=>dialog.current?.close();},[]);
 useEffect(()=>{const abort=new AbortController();setLoading(true);setPlan(null);setError('');request<Plan>(base+'/ai/connections/'+id+'/deletion-preview','GET',undefined,abort.signal).then(p=>{if(!abort.signal.aborted)setPlan(p);}).catch(e=>{if(!abort.signal.aborted)setError(e.message);}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();},[base,id,revision]);
 async function remove(){if(!plan)return;setBusy(true);setError('');try{const result=await request<{deleted_models:number}>(base+'/ai/connections/'+id,'DELETE',{expected_model_ids:plan.models.map(p=>p.id)});onDeleted(result.deleted_models);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <dialog ref={dialog} className="entry-dialog ai-editor connection-delete-dialog" aria-labelledby="connection-delete-title" onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
  <div className="connection-delete-titlebar"><h2 id="connection-delete-title"><Trash2 size={22}/>ลบผู้ให้บริการ AI?</h2><Button variant="ghost" className="connection-delete-close" aria-label="ปิดหน้าต่างลบผู้ให้บริการ" disabled={busy} onClick={onClose}><X size={20}/></Button></div>
  {loading?<p role="status">กำลังตรวจโมเดลที่ใช้ผู้ให้บริการนี้…</p>:plan&&<>
   <p>ลบ <strong>{plan.name}</strong> และคีย์ที่เก็บไว้ในพื้นที่นี้</p>
   {plan.models.length>0?<><p>โมเดลต่อไปนี้จะถูกลบออกจากลำดับ AI ด้วย ({plan.models.length} โมเดล)</p><ul className="connection-delete-models">{plan.models.map(p=><li key={p.id}><div><strong>{p.name||p.model}</strong>{p.name&&<small>{p.model}</small>}</div><span>{p.task==='chat'?'แชท AI':'อ่านข้อความและสลิป'}</span></li>)}</ul></>:<p className="muted">ไม่มีโมเดลผูกกับผู้ให้บริการนี้</p>}
   <p className="muted small">ประวัติแชท ข้อมูลการเงิน และประวัติการใช้ AI ยังคงอยู่ หากลบโมเดลสุดท้ายของงานนั้น จะต้องเพิ่มโมเดลใหม่เพื่อใช้ AI ต่อ</p>
  </>}
  {error&&<div role="alert" className="error">{error}<Button variant="outline" disabled={busy} onClick={()=>setRevision(v=>v+1)}>โหลดรายการล่าสุด</Button></div>}
  <div className="ai-editor-actions"><Button variant="outline" disabled={busy} onClick={onClose}>ยกเลิก</Button><Button className="connection-delete-button" disabled={busy||loading||!plan||!!error} onClick={remove}>{busy?'กำลังลบ…':plan?.models.length?`ยืนยันลบผู้ให้บริการและ ${plan.models.length} โมเดล`:'ยืนยันลบผู้ให้บริการ'}</Button></div>
 </dialog>;
}
