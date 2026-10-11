export type OfflineDraft={id:string;text:string;conversation_id?:string;review?:string};
export type VaultData={version:1;user_id:string;workspace_id:string;workspace_name:string;saved_at:number;accounts:{name:string;kind:string;balance:number}[];transactions:{id:string;description:string;kind:string;amount:number;occurred_on:string}[];drafts:OfflineDraft[]};
export const VAULT_KEY:string;
export function hasVault():boolean;
export function saveVault(data:VaultData,password:string):Promise<void>;
export function unlockVault(password:string):Promise<VaultData>;
export function clearVault():void;
