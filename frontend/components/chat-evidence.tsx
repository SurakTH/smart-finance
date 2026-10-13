"use client";
import Link from 'next/link';
import {ArrowUpRight,ReceiptText} from 'lucide-react';
export type Evidence={type:string;label:string;amount?:number;income?:number;expense?:number;date?:string;filters:Record<string,string>};
const money=(v:number)=>new Intl.NumberFormat('th-TH',{style:'currency',currency:'THB'}).format(v/100);
export function ChatEvidence({wid,items}:{wid:string;items?:Evidence[]|null}){
 if(!items?.length)return null;
 return <aside className="chat-evidence" aria-label="ข้อมูลต้นทางจากบัญชี"><strong><ReceiptText size={17}/> ข้อมูลจริงจากบัญชี</strong><div>{items.map((item,i)=>{const params=new URLSearchParams({...item.filters,workspace:wid});return <Link key={i} href={'/transactions?'+params}><span>{item.label}<small>{item.type==='summary'?(item.filters.kind==='expense'?`รายจ่าย ${money(item.expense||0)}`:item.filters.kind==='income'?`รายรับ ${money(item.income||0)}`:`รายรับ ${money(item.income||0)} · รายจ่าย ${money(item.expense||0)}`):[item.date,item.amount!==undefined?money(item.amount):''].filter(Boolean).join(' · ')}</small></span><ArrowUpRight size={17}/></Link>;})}</div><small>เปิดรายการต้นทางเพื่อตรวจรายละเอียด · ยอด ณ เวลาที่ตอบ</small></aside>;
}
