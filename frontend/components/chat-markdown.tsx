"use client";
import {memo,useRef,useState,type ComponentPropsWithoutRef} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';

// Only turn text nodes into marks. Code, HTML and URLs remain untouched.
type Node={type:string;value?:string;children?:Node[];data?:{hName:string}};
function remarkHighlight(){
 return (tree:Node)=>{
  function walk(node:Node){
   if(!node.children||['code','inlineCode','html','link','linkReference'].includes(node.type))return;
   node.children=node.children.flatMap(child=>{
    if(child.type!=='text'||!child.value){walk(child);return [child];}
    const result:Node[]=[];let start=0;
    for(const match of child.value.matchAll(/==([^=\n]+)==/g)){
     const index=match.index!;
     if(index>start)result.push({type:'text',value:child.value.slice(start,index)});
     result.push({type:'emphasis',data:{hName:'mark'},children:[{type:'text',value:match[1]}]});start=index+match[0].length;
    }
    if(!start)return [child];
    if(start<child.value.length)result.push({type:'text',value:child.value.slice(start)});
    return result;
   });
  }
  walk(tree);
 };
}
function safeUrl(value:string){
 // Explicit destinations only; no relative endpoints, data, javascript or file URLs.
 if(!/^(https?:\/\/|mailto:|#)/i.test(value))return '';
 return value;
}
function CodeBlock({children,...props}:ComponentPropsWithoutRef<'pre'>){
 const ref=useRef<HTMLPreElement>(null),[copied,setCopied]=useState(false);
 async function copy(){try{await navigator.clipboard.writeText(ref.current?.textContent||'');setCopied(true);}catch{setCopied(false);}}
 return <div className="chat-code-block"><div className="chat-code-toolbar"><span>โค้ด / ข้อความ</span><button type="button" onClick={copy} aria-label="คัดลอกโค้ด">{copied?'คัดลอกแล้ว':'คัดลอก'}</button></div><pre {...props} ref={ref} tabIndex={0}>{children}</pre></div>;
}
const components={
 a:({href,children}:ComponentPropsWithoutRef<'a'>)=>href?<a href={href} target={href.startsWith('#')?undefined:'_blank'} rel="noopener noreferrer" referrerPolicy="no-referrer">{children}</a>:<span>{children}</span>,
 // Markdown from a model must never fetch tracking images. Uploaded evidence
 // still uses the authenticated attachment component in the chat shell.
 img:({alt}:ComponentPropsWithoutRef<'img'>)=><span className="chat-image-reference">[รูป: {alt||'รูปจากข้อความ'}]</span>,
 pre:({children}:ComponentPropsWithoutRef<'pre'>)=><CodeBlock>{children}</CodeBlock>,
 table:({children}:ComponentPropsWithoutRef<'table'>)=><div className="chat-table-scroll" role="region" aria-label="ตารางในข้อความ" tabIndex={0}><table>{children}</table></div>,
};
export const ChatMarkdown=memo(function ChatMarkdown({text}:{text:string}){
 // Financial review must show literal names/descriptions so Markdown characters
 // cannot hide any part of the exact data the user is being asked to approve.
 if(text.startsWith('กรุณาตรวจสอบ — ยังไม่บันทึก\n')||text.startsWith('ทวนความจำส่วนตัว — ยังไม่บันทึก\n'))return <p className="chat-review-text">{text}</p>;
 return <div className="chat-markdown"><Markdown remarkPlugins={[remarkGfm,remarkBreaks,remarkHighlight]} skipHtml urlTransform={safeUrl} components={components}>{text}</Markdown></div>;
});
