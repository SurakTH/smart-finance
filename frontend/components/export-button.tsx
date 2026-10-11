"use client";
import {useEffect,useRef,useState} from 'react';
import {Download} from 'lucide-react';
import {Button} from './ui/button';

export function ExportButton({url,filename,label='ส่งออก CSV',disabled=false}:{url:string;filename:string;label?:string;disabled?:boolean}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const active=useRef<AbortController|null>(null),current=useRef(url);current.current=url;
 useEffect(()=>{setError('');setBusy(false);return()=>active.current?.abort();},[url]);
 async function download(){if(busy||disabled)return;active.current?.abort();const controller=new AbortController();active.current=controller;const requested=url;setBusy(true);setError('');try{
  const response=await fetch('/api'+url,{cache:'no-store',signal:controller.signal});
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==='string'?body.detail:'ส่งออกไม่สำเร็จ กรุณาลองใหม่');}
  const blob=await response.blob();if(controller.signal.aborted||current.current!==requested)return;
  const objectUrl=URL.createObjectURL(blob);const link=document.createElement('a');link.href=objectUrl;link.download=filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
 }catch(e){if(!controller.signal.aborted)setError((e as Error).message);}finally{if(active.current===controller&&!controller.signal.aborted)setBusy(false);}}
 return <div className="export-control"><Button variant="outline" size="sm" disabled={disabled||busy} onClick={download}><Download size={16}/>{busy?'กำลังเตรียมไฟล์…':label}</Button>{error&&<p className="export-error" role="alert">{error}</p>}</div>;
}
