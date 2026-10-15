// Read only the files supplied by a paste/drop gesture. Never fetch clipboard URLs.
export function transferredFiles(transfer:DataTransfer):File[] {
  if(transfer.files.length)return Array.from(transfer.files);
  return Array.from(transfer.items).filter(item=>item.kind==='file').map(item=>item.getAsFile()).filter((file):file is File=>!!file);
}
export function imageInputError(files:File[]):string|null {
  if(files.length!==1)return 'แนบได้ครั้งละ 1 รูป เลือกรูปที่ต้องการส่งก่อนค่ะ';
  const file=files[0];
  if(!['image/jpeg','image/png','image/webp'].includes(file.type))return 'รองรับรูป JPG, PNG และ WebP เท่านั้น';
  if(!file.size)return 'รูปนี้ไม่มีข้อมูล ลองคัดลอกหรือเลือกรูปใหม่ค่ะ';
  if(file.size>8*1024*1024)return 'รูปใหญ่เกิน 8 MB กรุณาลดขนาดก่อนแนบค่ะ';
  return null;
}
