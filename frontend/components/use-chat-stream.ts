"use client";
import {useEffect,useRef,useState} from 'react';
type Draft={job:string;text:string;baseline:string};
export function useChatStream(wid:string,cid:string,enabled:boolean,lastAssistant:string,onDone:()=>Promise<void>){
 const [draft,setDraft]=useState<Draft|null>(null),[notice,setNotice]=useState('');
 const done=useRef(onDone),latest=useRef(lastAssistant);done.current=onDone;latest.current=lastAssistant;
 useEffect(()=>{if(draft&&lastAssistant!==draft.baseline)setDraft(null);},[lastAssistant,draft]);
 useEffect(()=>{
  setDraft(null);setNotice('');if(!enabled||!wid||!cid)return;
  let active=true;const source=new EventSource(`/api/workspaces/${encodeURIComponent(wid)}/conversations/${encodeURIComponent(cid)}/events`);
  source.onmessage=event=>{if(!active)return;try{
   const value=JSON.parse(event.data);
   if(value.kind==='ready'){setNotice('');}
   else if(value.kind==='start'){setNotice('');setDraft({job:value.job_id,text:'',baseline:latest.current});}
   else if(value.kind==='delta'&&typeof value.text==='string'){setDraft(old=>value.snapshot===true?{job:value.job_id,text:value.text.slice(0,16000),baseline:old&&old.job===value.job_id?old.baseline:latest.current}:old&&old.job===value.job_id?{...old,text:(old.text+value.text).slice(0,16000)}:null);}
   else if(value.kind==='done'){void done.current().catch(()=>{if(active)setNotice('กำลังตรวจคำตอบล่าสุด…');}).finally(()=>{if(active)setDraft(old=>old?.job===value.job_id?null:old);});}
   else if(value.kind==='failed'){setDraft(null);setNotice('เตรียมคำตอบไม่สำเร็จ กรุณาลองส่งข้อความอีกครั้ง');}
   else if(value.kind==='closed'){setDraft(null);setNotice('ห้องหมดอายุหรือสิทธิ์เปลี่ยน กรุณาเปิดบทสนทนาใหม่');source.close();}
   else if(value.kind==='unavailable'){setDraft(null);setNotice('แสดงคำตอบเมื่อพร้อม ระบบยังตรวจคำตอบให้อยู่');}
  }catch{}};
  source.onerror=()=>{if(active){setDraft(null);setNotice('การเชื่อมต่อสะดุด ระบบกำลังเชื่อมต่อและตรวจคำตอบล่าสุด');}};
  return()=>{active=false;source.close();};
 },[wid,cid,enabled]);
 return {draft,streamNotice:notice};
}
