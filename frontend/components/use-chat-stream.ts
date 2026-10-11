"use client";
import {useEffect,useRef,useState} from 'react';
type Draft={job:string;text:string;baseline:string;context:string};
export function useChatStream(wid:string,cid:string,enabled:boolean,lastAssistant:string,onDone:()=>Promise<void>){
 const [draft,setDraft]=useState<Draft|null>(null),[notice,setNotice]=useState('');
 const done=useRef(onDone),latest=useRef(lastAssistant),retired=useRef(new Set<string>());done.current=onDone;latest.current=lastAssistant;
 const context=wid+':'+cid;
 function retire(job:string){retired.current.add(job);if(retired.current.size>100)retired.current.delete(retired.current.values().next().value!);}
 useEffect(()=>{if(draft&&draft.context===context&&lastAssistant!==draft.baseline){retire(draft.job);setDraft(null);}},[lastAssistant,draft,context]);
 useEffect(()=>{
  setDraft(null);setNotice('');retired.current.clear();if(!enabled||!wid||!cid)return;
  let active=true;const source=new EventSource(`/api/workspaces/${encodeURIComponent(wid)}/conversations/${encodeURIComponent(cid)}/events`);
  source.onmessage=event=>{if(!active)return;try{
   const value=JSON.parse(event.data);
   if((value.kind==='start'||value.kind==='delta')&&retired.current.has(value.job_id))return;
   if(value.kind==='ready'){setNotice('');}
   else if(value.kind==='start'){setNotice('');setDraft({job:value.job_id,text:'',baseline:latest.current,context});}
   else if(value.kind==='delta'&&typeof value.text==='string'){setDraft(old=>value.snapshot===true?{job:value.job_id,text:value.text.slice(0,16000),baseline:old&&old.job===value.job_id?old.baseline:latest.current,context}:old&&old.job===value.job_id?{...old,text:(old.text+value.text).slice(0,16000)}:null);}
   else if(value.kind==='done'){retire(value.job_id);void done.current().catch(()=>{if(active)setNotice('กำลังตรวจคำตอบล่าสุด…');}).finally(()=>{if(active)setDraft(old=>old?.job===value.job_id?null:old);});}
   else if(value.kind==='failed'){retire(value.job_id);setDraft(old=>old?.job===value.job_id?null:old);setNotice('เตรียมคำตอบไม่สำเร็จ กรุณาลองส่งข้อความอีกครั้ง');}
   else if(value.kind==='closed'){setDraft(null);setNotice('ห้องหมดอายุหรือสิทธิ์เปลี่ยน กรุณาเปิดบทสนทนาใหม่');source.close();}
   else if(value.kind==='unavailable'){setDraft(null);setNotice('แสดงคำตอบเมื่อพร้อม ระบบยังตรวจคำตอบให้อยู่');}
  }catch{}};
  source.onerror=()=>{if(active){setDraft(null);setNotice('การเชื่อมต่อสะดุด ระบบกำลังเชื่อมต่อและตรวจคำตอบล่าสุด');}};
  return()=>{active=false;source.close();};
 },[wid,cid,enabled]);
 // Hide immediately when persisted history arrives; effects run after paint.
 return {draft:draft?.context===context&&draft.baseline===lastAssistant?draft:null,streamNotice:notice};
}
