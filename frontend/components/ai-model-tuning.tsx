"use client";
import {useState} from 'react';
import {BrainCircuit,SlidersHorizontal,Timer,ImagePlus} from 'lucide-react';
export type ModelTuning={kind:string;model:string;task:string;reasoning_effort:string;supports_images:boolean;max_tokens:number;temperature:number;timeout_seconds:number;retries:number};
export const thinkingLabels:Record<string,string>={default:'อัตโนมัติตามโมเดล',none:'ปิด Thinking',minimal:'น้อยที่สุด',low:'น้อย',medium:'ปานกลาง',high:'มาก',xhigh:'มากที่สุด'};
export function temperatureAvailable(p:Pick<ModelTuning,'kind'|'model'|'reasoning_effort'>){
 return !(p.kind==='openai'&&(p.reasoning_effort!=='default'||/^(?:o\d|gpt-[56])/i.test(p.model)))&&!(p.kind==='groq'&&p.reasoning_effort!=='default');
}
export function AIModelTuning({draft,change,busy}:{draft:ModelTuning;change:<K extends keyof ModelTuning>(key:K,value:ModelTuning[K])=>void;busy:boolean}){
 // Editable text is separate from the saved value. Emptying a numeric field must
 // never turn it into the sentinel 0 (provider default) or disable the field.
 const [tokens,setTokens]=useState(String(draft.max_tokens||8192)),[temperature,setTemperature]=useState((draft.temperature/100).toString());
 const custom=draft.max_tokens!==0,canSample=temperatureAvailable(draft);
 function chooseTokens(value:number){setTokens(String(value));change('max_tokens',value);}
 return <>
  <section className="model-editor-section"><div className="model-section-title"><BrainCircuit size={20}/><div><h3>วิธีคิดและการตอบ</h3><p>Thinking กับ Temperature ปรับแยกกันตามความสามารถของ API</p></div></div>
   <div className="form-grid model-thinking-grid"><label>โหมด Thinking<select aria-label="โหมด Thinking" disabled={busy} value={draft.reasoning_effort} onChange={e=>change('reasoning_effort',e.target.value)}>{Object.entries(thinkingLabels).filter(([key])=>!(draft.kind==='gemini'&&key==='xhigh')&&!(draft.kind==='groq'&&['minimal','xhigh'].includes(key))).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select><small>คิดมากขึ้นอาจใช้เวลาและ tokens เพิ่ม แต่ API ต้องรองรับระดับที่เลือก</small></label>
   <label>Temperature (0–2)<input aria-label="Temperature (0–2)" type="number" min={0} max={2} step={0.01} required disabled={busy||!canSample} value={temperature} onChange={e=>{setTemperature(e.target.value);if(e.target.value!==''&&Number.isFinite(Number(e.target.value)))change('temperature',Math.round(Number(e.target.value)*100));}}/><small>{canSample?'ค่าต่ำตอบสม่ำเสมอขึ้น · ค่าสูงมีความหลากหลายขึ้น':'API กลุ่มนี้ใช้ค่าการสุ่มของโมเดล แอปจึงไม่ส่ง Temperature; ค่าที่เก็บไว้ยังอยู่'}</small></label></div>
   <label className="model-vision ai-clear-key"><ImagePlus size={19}/><span>รับรูปภาพในแชทและ Inbox<small>เปิดเฉพาะโมเดลที่อ่านภาพได้จริง ไม่ได้เพิ่มความสามารถให้โมเดลข้อความ</small></span><input type="checkbox" checked={draft.supports_images} disabled={busy} onChange={e=>change('supports_images',e.target.checked)}/></label>
  </section>
  <section className="model-editor-section"><div className="model-section-title"><SlidersHorizontal size={20}/><div><h3>ความยาวคำตอบ</h3><p>เลือกโหมดก่อน แล้วกำหนดตัวเลขได้โดยไม่สลับโหมดเอง</p></div></div>
   <div className="model-budget-mode" role="radiogroup" aria-label="วิธีจำกัดคำตอบ"><button type="button" role="radio" aria-checked={custom} disabled={busy} onClick={()=>chooseTokens(Number(tokens)>=64?Number(tokens):8192)}><strong>กำหนดเอง</strong><span>ตั้งงบ tokens ต่อคำขอ</span></button><button type="button" role="radio" aria-checked={!custom} disabled={busy} onClick={()=>change('max_tokens',0)}><strong>ให้ผู้ให้บริการกำหนด</strong><span>ไม่ส่งค่าจำกัดจากแอป</span></button></div>
   <label className="model-token-field">จำนวน tokens สูงสุด<input type="number" min={64} max={2147483647} step={1} required disabled={busy||!custom} value={tokens} onChange={e=>{const raw=e.target.value;setTokens(raw);if(raw!==''&&Number(raw)>0&&Number.isSafeInteger(Number(raw)))change('max_tokens',Number(raw));}}/></label>
   <div className="model-token-presets" aria-label="ค่าลัด tokens">{[2048,8192,32000,65536,131072].map(value=><button type="button" key={value} disabled={busy} aria-label={value.toLocaleString('en-US')+' tokens'} aria-pressed={custom&&draft.max_tokens===value} onClick={()=>chooseTokens(value)}>{value.toLocaleString('en-US')}</button>)}</div>
   <p className="model-field-help">{custom?`ส่งเพดาน ${Number(tokens||0).toLocaleString()} tokens ต่อคำขอ ไม่ได้บังคับให้โมเดลตอบเต็มจำนวน`:'ใช้ค่าเริ่มต้นของผู้ให้บริการ ซึ่งอาจต่ำกว่าเพดานสูงสุดของโมเดล ไม่ได้หมายถึงไม่จำกัด'}</p>
   <p className="muted small">นี่คือ tokens สำหรับคำตอบ และบางโมเดลนับ Thinking รวมด้วย ไม่ใช่ขนาดบริบทหรือความจำแชท หากตั้งวงเงิน Cloud รายเดือน ให้กำหนดตัวเลขเพื่อสำรองงบได้</p>
   {draft.task==='extract'&&<p className="notice small">เฉพาะอ่านรูปใน Inbox ใช้งบคำตอบไม่เกิน 4,096 tokens ส่วนการอ่านข้อความใช้ค่าที่ตั้งไว้</p>}
  </section>
  <section className="model-editor-section model-reliability"><details className="ai-advanced"><summary><Timer size={18}/> เวลารอและการลองซ้ำ</summary><div className="form-grid"><label>Timeout (วินาที)<input type="number" min={5} max={60} required disabled={busy} value={draft.timeout_seconds} onChange={e=>change('timeout_seconds',Number(e.target.value))}/></label><label>ลองซ้ำเมื่อไม่สำเร็จ<input type="number" min={0} max={2} required disabled={busy} value={draft.retries} onChange={e=>change('retries',Number(e.target.value))}/></label></div><p className="muted small">ลองซ้ำใช้ tokens เพิ่มได้เมื่อส่งคำขอไปแล้ว แต่ละงานมีเวลาลองโมเดลรวมประมาณ 90 วินาที โมเดลที่คิดนานอาจต้องเพิ่มเวลารอ</p></details></section>
  <div className="model-effective"><strong>ค่าที่จะใช้</strong><span>Thinking: {thinkingLabels[draft.reasoning_effort]}</span><span>{canSample?'Temperature: '+temperature:'Temperature: ตามโมเดล'}</span><span>{custom?'คำตอบ ≤ '+Number(tokens||0).toLocaleString()+' tokens':'คำตอบ: ตามผู้ให้บริการ'}</span></div>
 </>;
}
