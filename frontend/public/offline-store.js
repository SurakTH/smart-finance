// Explicit opt-in encrypted device vault. Never store session cookies or API keys.
export const VAULT_KEY='sf-offline-v1';
const encode=bytes=>{let s='';for(const b of bytes)s+=String.fromCharCode(b);return btoa(s);};
const decode=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function key(password,salt){const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);return crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:210000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);}
export function hasVault(){return !!localStorage.getItem(VAULT_KEY);}
export async function saveVault(data,password){
 if(password.length<12||password.length>200)throw new Error('รหัสออฟไลน์ต้องมี 12–200 ตัวอักษร');
 const epoch=localStorage.getItem('sf-offline-epoch');
 const salt=crypto.getRandomValues(new Uint8Array(16)),iv=crypto.getRandomValues(new Uint8Array(12));
 const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv},await key(password,salt),new TextEncoder().encode(JSON.stringify(data)));
 if(localStorage.getItem('sf-offline-epoch')!==epoch)throw new Error('ข้อมูลออฟไลน์ถูกล้างแล้ว กรุณาลองใหม่');
 localStorage.setItem(VAULT_KEY,JSON.stringify({version:1,salt:encode(salt),iv:encode(iv),cipher:encode(new Uint8Array(ciphertext))}));
}
export async function unlockVault(password){
 const raw=localStorage.getItem(VAULT_KEY);if(!raw)throw new Error('ยังไม่มีข้อมูลออฟไลน์ ไปที่ตั้งค่าเพื่อเลือกเก็บข้อมูลก่อน');
 try{const v=JSON.parse(raw);if(v.version!==1)throw new Error();const bytes=await crypto.subtle.decrypt({name:'AES-GCM',iv:decode(v.iv)},await key(password,decode(v.salt)),decode(v.cipher));const data=JSON.parse(new TextDecoder().decode(bytes));if(data.version!==1||!Array.isArray(data.drafts)||!data.user_id||!data.workspace_id)throw new Error();return data;}catch{throw new Error('รหัสออฟไลน์ไม่ถูกต้อง หรือข้อมูลบนเครื่องเสียหาย');}
}
export function clearVault(){localStorage.setItem('sf-offline-epoch',Date.now()+'-'+Math.random().toString(36).slice(2));localStorage.removeItem(VAULT_KEY);window.dispatchEvent(new Event('sf-vault-cleared'));}
