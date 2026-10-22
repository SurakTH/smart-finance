export type ReceiptInfo={version:number;paid_satang:number|null;gross_satang?:number|null;subsidy_satang?:number|null;fee_satang?:number|null;occurred_on?:string|null;warnings?:string[]};
const money=(n:number)=>new Intl.NumberFormat('th-TH',{style:'currency',currency:'THB'}).format(n/100);
const warnings:Record<string,string>={paid_unreadable:'ยังอ่านยอดจ่ายจริงไม่ได้ กรุณาตรวจจากรูป',invalid_amount:'ตัวเลขบางช่องอ่านไม่ชัด',conflicting_amounts:'ยอดและส่วนลดไม่สอดคล้องกัน กรุณาตรวจจากรูป',not_thb_receipt:'ยังยืนยันไม่ได้ว่าเป็นสลิปเงินบาท',date_unreadable:'ยังอ่านวันที่ไม่ได้ กรุณาระบุวันที่',check_direction:'กรุณาตรวจว่าเป็นรายรับหรือรายจ่าย',check_fee:'ตรวจว่าค่าธรรมเนียมรวมในยอดแล้วหรือยัง',zero_paid:'ยอดจ่ายจริงเป็นศูนย์ ไม่ควรเพิ่มรายจ่าย'};
export function ReceiptDetails({receipt}:{receipt?:ReceiptInfo|null}){
 if(!receipt)return null;
 const parts=[receipt.gross_satang!=null?'ราคาก่อนสิทธิ/ส่วนลด '+money(receipt.gross_satang):'',receipt.subsidy_satang!=null?'สิทธิ/ส่วนลด '+money(receipt.subsidy_satang):'',receipt.fee_satang?'ค่าธรรมเนียม '+money(receipt.fee_satang):''].filter(Boolean);
 const notices=[...new Set((receipt.warnings||[]).map(key=>warnings[key]).filter(Boolean))];
 return <div className="receipt-details">{parts.length>0&&<p>{parts.join(' · ')}<br/>ยอดรายการใช้จำนวนที่จ่ายจริง</p>}{notices.length>0&&<p className="receipt-warning">{notices.join(' · ')}</p>}</div>;
}
