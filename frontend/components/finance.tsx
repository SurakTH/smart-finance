"use client";
import {imageInputError,transferredFiles} from "../lib/chat-images";
import {ChatEvidence,type Evidence} from "./chat-evidence";
import {ChatMarkdown} from "./chat-markdown";
import {useChatStream} from "./use-chat-stream";
import {WorkspaceManager} from "./workspaces";
import {PwaSettings} from "./pwa";
import {clearVault} from "../public/offline-store.js";
import {AssistantHistory} from "./assistant-history";
import {InsightsPage} from "./insights";
import {AISettingsPage} from "./ai-settings";
import {AccountSettings} from "./account-settings";
import {
  useState,
  useEffect,
  useLayoutEffect,
  useCallback,
  useRef,
  type FormEvent,
  type ClipboardEvent,
  type DragEvent,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2,
  LayoutDashboard,
  ArrowLeftRight,
  Wallet,
  Sparkles,
  Inbox,
  Settings,
  Plus,
  LogOut,
  ShieldCheck,
  ArrowUpRight,
  ArrowDownRight,
  X,
  Send,
  Square,
  Paperclip,
  ChevronRight,
  ChartNoAxesCombined,
  Menu,
  ArrowLeft,
  MessageSquare,
  Trash2,
  Tags,
  Grid2X2,
  ChartPie,
  Target,
  Repeat2,
  Users,
  Pencil,
  Copy,
  Check,
  Ghost,
  ChevronDown,
} from "lucide-react";
import { Button } from "./ui/button";
import { ChatHistory } from "./chat-history";
import { ChatRetention } from "./chat-retention";
import { MembersPage } from "./members";
import { RecurringPage } from "./recurring";
import { GoalsPage } from "./goals";
import { BudgetsPage } from "./budgets";
import { ServicesHub, AccountManager } from "./services";
import { DashboardView, TransactionsExplorer, type DashboardSummary } from "./reports";

type Account = { id: string; name: string; kind: string; balance: number };
type Entry = {
  id: string;
  kind: string;
  description: string;
  amount: number;
  occurred_on: string;
};
type Proposal = {
  id: string;
  kind: string;
  description: string;
  amount: number | null;
  status: string;
  source: string;
  attachment_id?: string | null;
  occurred_on?: string | null;
  account_id?: string | null;
  category_id?: string | null;
};
type Conversation = { id: string; title: string; privacy: string; temporary?:boolean };
type Message = { references?:Evidence[]|null; id: string; role: string; content: string; attachment_id?: string | null };
type Job = { id: string; status: string; error: string | null; conversation_id?:string|null; stopping?:boolean; message?:string|null };
function isReviewCommand(text:string) {
  return /^(?:(?:ยืนยัน|ยกเลิก)(?:\s+[a-fA-F0-9]{8})?|ทวนอีกที|ทวนหน่อย|ทวนรายการ|สรุปที่จะบันทึก|ยกเลิกการกรอก|เริ่มใหม่)$/.test(text.trim());
}
type Summary = DashboardSummary;
type Workspace = { id: string; name: string; role: string };
const money = (n: number) =>
  new Intl.NumberFormat("th-TH", { style: "currency", currency: "THB" }).format(
    n / 100,
  );
const kinds: Record<string, string> = {
  income: "รายรับ",
  expense: "รายจ่าย",
  transfer: "โอนเงิน",
  opening: "ยอดตั้งต้น",
  card_payment: "จ่ายบัตรเครดิต",
  asset: "บัญชีเงิน",
  liability: "บัตรเครดิต / หนี้สิน",
  equity: "ทุนตั้งต้น",
};
const nav = [
  { path: "/", label: "ภาพรวม", icon: LayoutDashboard },
  { path: "/transactions", label: "รายการเงิน", icon: ArrowLeftRight },
  { path: "/assistant", label: "ผู้ช่วย AI", icon: Sparkles },
  { path: "/inbox", label: "AI Inbox", icon: Inbox },
  { path: "/insights", label: "วิเคราะห์", icon: ChartNoAxesCombined },
  { path: "/services", label: "บริการทั้งหมด", icon: Grid2X2 },
  { path: "/budgets", label: "งบประมาณ", icon: ChartPie },
  { path: "/goals", label: "เป้าหมายออม", icon: Target },
  { path: "/recurring", label: "รายการประจำ", icon: Repeat2 },
  { path: "/workspaces", label: "จัดการพื้นที่ทำงาน", icon: Building2 },
  { path: "/members", label: "สมาชิก", icon: Users },
  { path: "/accounts", label: "บัญชี", icon: Wallet },
  { path: "/categories", label: "หมวดหมู่", icon: Tags },
  { path: "/settings", label: "ตั้งค่า", icon: Settings },
];
async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const form = body instanceof FormData;
  const r = await fetch("/api" + path, {
    method: method || (body ? "POST" : "GET"),
    headers: {
      "X-SF-Request": "1",
      ...(!form && body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? (form ? body : JSON.stringify(body)) : undefined,
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : r.status === 422
          ? "กรุณาตรวจสอบข้อมูลที่กรอก"
          : `คำขอไม่สำเร็จ (${r.status})`,
    );
  return data as T;
}
function today() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
function satang(value: string) {
  if (!/^\d+(\.\d{1,2})?$/.test(value))
    throw new Error("จำนวนเงินต้องมีทศนิยมไม่เกิน 2 ตำแหน่ง");
  const [baht, dec = ""] = value.split(".");
  const n = Number(baht) * 100 + Number(dec.padEnd(2, "0"));
  if (!Number.isSafeInteger(n) || n <= 0 || n > 100_000_000_000)
    throw new Error("จำนวนเงินไม่ถูกต้อง");
  return n;
}

export default function Finance() {
  const [focusMessage,setFocusMessage]=useState(''),[renaming,setRenaming]=useState(false),[roomTitle,setRoomTitle]=useState('');

  const path = usePathname();
  const isChat = path === "/assistant";
  const [historyOpen, setHistoryOpen] = useState(false);
  const [compact, setCompact] = useState(true);
  const chatInput = useRef<HTMLTextAreaElement>(null);
  const [chatText,setChatText] = useState("");
  const chatScroll = useRef<HTMLDivElement>(null);
  const selectedCid=useRef('');
  const messageRows=useRef<Message[]>([]);
  const olderLock=useRef(false),followBottom=useRef(true);
  const olderAnchor=useRef<{id:string;offset:number;context:string}|null>(null);
  const [hasOlder,setHasOlder]=useState(false),[loadingOlder,setLoadingOlder]=useState(false);

  const historyToggle = useRef<HTMLButtonElement>(null);
  const historyClose = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const update = () => { setCompact(media.matches); setHistoryOpen(!media.matches); };
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!isChat) return;
    const viewport = window.visualViewport;
    const resize = () => document.documentElement.style.setProperty("--chat-height", `${Math.round(viewport?.height || window.innerHeight)}px`);
    resize(); viewport?.addEventListener("resize", resize);
    return () => { viewport?.removeEventListener("resize", resize); document.documentElement.style.removeProperty("--chat-height"); };
  }, [isChat]);
  useEffect(() => {
    if (!historyOpen || !compact || !isChat) return;
    historyClose.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setHistoryOpen(false); historyToggle.current?.focus(); }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [historyOpen, compact, isChat]);
  const [allowRegistration,setAllowRegistration]=useState(false);
  useEffect(()=>{api<{allow_registration:boolean}>('/auth/options').then(o=>setAllowRegistration(o.allow_registration===true)).catch(()=>{});},[]);
  const [user, setUser] = useState<{ email: string; name?: string } | null>(null),
    [ready, setReady] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]),
    [wid, setWid] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]),
    [entries, setEntries] = useState<Entry[]>([]),
    [proposals, setProposals] = useState<Proposal[]>([]),
    [summary, setSummary] = useState<Summary | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]),
    [cid, setCid] = useState(""),
    [messages, setMessages] = useState<Message[]>([]),
    [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState<Proposal | "new" | null>(null);
  const [ledgerVersion, setLedgerVersion] = useState(0);
  const [month, setMonth] = useState(today().slice(0, 7)),
    [capturePrivacy, setCapturePrivacy] = useState("private"),
    [linkCode, setLinkCode] = useState("");
  const [chatFile, setChatFile] = useState<File | null>(null);
  const [chatPreview, setChatPreview] = useState("");
  const [chatUploadError,setChatUploadError]=useState("");
  const [draggingImage,setDraggingImage]=useState(false),[showLatest,setShowLatest]=useState(false),[copiedMessage,setCopiedMessage]=useState("");
  const imageDragDepth=useRef(0),copyTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>()=>{if(copyTimer.current)clearTimeout(copyTimer.current);},[]);
  function attachChatFiles(files:File[]) {
    if(!files.length)return false;
    const problem=busy?'กำลังส่งข้อความอยู่ รอสักครู่แล้วแนบรูปอีกครั้งค่ะ':imageInputError(files);
    if(problem){setChatUploadError(problem);return false;}
    setChatUploadError('');setChatFile(files[0]);return true;
  }
  function pasteChatImage(event:ClipboardEvent<HTMLFormElement>) {
    const files=transferredFiles(event.clipboardData);
    if(!files.length)return; // Plain text keeps native selection, undo and paste behavior.
    event.preventDefault();
    if(!attachChatFiles(files))return;
    const text=event.clipboardData.getData('text/plain'),input=chatInput.current;
    if(input&&text){const start=input.selectionStart,end=input.selectionEnd;input.value=(input.value.slice(0,start)+text+input.value.slice(end)).slice(0,4000);setChatText(input.value);input.style.height='auto';input.style.height=Math.min(input.scrollHeight,144)+'px';input.setSelectionRange(Math.min(start+text.length,4000),Math.min(start+text.length,4000));}
    input?.focus();
  }
  function dropChatImage(event:DragEvent<HTMLElement>) {
    if(!event.dataTransfer.types.includes('Files'))return;
    event.preventDefault();imageDragDepth.current=0;setDraggingImage(false);
    if(attachChatFiles(transferredFiles(event.dataTransfer)))chatInput.current?.focus();
  }
  async function copyAnswer(message:Message) {
    try {await navigator.clipboard.writeText(message.content.replace(/\n\nรหัสทางเลือก:\nยืนยัน [A-F0-9]{8}\n$/,''));setCopiedMessage(message.id);if(copyTimer.current)clearTimeout(copyTimer.current);copyTimer.current=setTimeout(()=>setCopiedMessage(''),2000);}
    catch {setChatUploadError('คัดลอกไม่สำเร็จ ลองเลือกข้อความแล้วคัดลอกด้วยตัวเองค่ะ');}
  }

  useEffect(() => {
    if (!chatFile) { setChatPreview(""); return; }
    const url = URL.createObjectURL(chatFile);
    setChatPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [chatFile]);
  useEffect(() => { setChatFile(null);setChatUploadError("");setDraggingImage(false);imageDragDepth.current=0;setShowLatest(false);setCopiedMessage(""); }, [cid, wid, path]);
  selectedCid.current=cid;messageRows.current=messages;
  useLayoutEffect(()=>{const anchor=olderAnchor.current;if(!anchor)return;olderAnchor.current=null;if(anchor.context!==wid+cid+focusMessage)return;const element=document.getElementById('chat-message-'+anchor.id),el=chatScroll.current;if(element&&el)el.scrollTop+=element.getBoundingClientRect().top-anchor.offset;},[messages,wid,cid,focusMessage]);
  const latestMessage = messages.at(-1)?.id;
  useEffect(() => {
    if (isChat && chatScroll.current && followBottom.current && !focusMessage) chatScroll.current.scrollTop = chatScroll.current.scrollHeight;
  }, [latestMessage, cid, isChat]);
  useEffect(()=>{if(focusMessage&&messages.some(m=>m.id===focusMessage))document.getElementById("chat-message-"+focusMessage)?.scrollIntoView({block:"center"});},[focusMessage,latestMessage]);
  useEffect(() => {
    if (!isChat || !notice) return;
    const timer = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice, isChat]);
  useEffect(()=>{
    if(path!=="/settings" || !user || !wid) return;
    const frame=requestAnimationFrame(()=>{const id=window.location.hash.slice(1);if(id)document.getElementById(id)?.scrollIntoView({block:"start"});});
    return()=>cancelAnimationFrame(frame);
  },[path,user,wid,workspaces]);
  useEffect(()=>{if(wid){try{sessionStorage.setItem("sf-workspace",wid);}catch{}}},[wid]);
  function selectWorkspace(id:string) {
    try {sessionStorage.setItem("sf-workspace",id);} catch {}
    setWid(id);
  }
  const base = "/workspaces/" + wid;
  const activeMonth = useRef(month);
  activeMonth.current = month;
  const activeWid = useRef(wid);
  activeWid.current = wid;
  const [temporary,setTemporary]=useState(false),[temporaryRoom,setTemporaryRoom]=useState<Conversation|null>(null);
  useEffect(()=>{setTemporaryRoom(null);},[wid]);
  useEffect(()=>{setFocusMessage('');setRenaming(false);},[wid]);
  const selectedRoom=temporaryRoom?.id===cid?temporaryRoom:conversations.find(c=>c.id===cid);
  const requestedConsumed=useRef(false);
  useEffect(()=>{if(!isChat||cid||requestedConsumed.current)return;const requested=new URLSearchParams(window.location.search).get('conversation');if(requested&&conversations.some(c=>c.id===requested)){requestedConsumed.current=true;selectedCid.current=requested;setCid(requested);}},[isChat,cid,conversations]);
  const loadWorkspaces = useCallback(async () => {
    const list = await api<Workspace[]>("/workspaces");
    setWorkspaces(list);
    const requestedWorkspace=new URLSearchParams(window.location.search).get("workspace")||"";
    let preferred="";
    try {preferred=requestedWorkspace||sessionStorage.getItem("sf-workspace")||"";} catch {}
    setWid((old) => (list.some((w) => w.id === old) ? old : list.some(w=>w.id===preferred)?preferred:list[0]?.id || ""));
  }, []);
  useEffect(()=>{
    if(!user)return;
    const update=()=>{loadWorkspaces().catch(()=>{});};
    const visible=()=>{if(document.visibilityState==='visible')update();};
    const timer=setInterval(visible,30000);
    window.addEventListener('focus',update);document.addEventListener('visibilitychange',visible);
    return()=>{clearInterval(timer);window.removeEventListener('focus',update);document.removeEventListener('visibilitychange',visible);};
  },[user,loadWorkspaces]);
  const refresh = useCallback(async () => {
    if (!wid) return;
    const b = "/workspaces/" + wid;
    const [a, t, p, s, c, j] = await Promise.all([
      api<Account[]>(b + "/accounts"),
      api<Entry[]>(b + "/transactions"),
      api<Proposal[]>(b + "/proposals"),
      api<Summary>(b + "/dashboard?month=" + month),
      api<Conversation[]>(b + "/conversations"),
      api<Job[]>(b + "/jobs"),
    ]);
    if (activeWid.current !== wid || activeMonth.current !== month) return;
    setAccounts(a);
    setEntries(t);
    setProposals(p);
    setSummary(s);
    setConversations(c);
    setJobs(j);
  }, [wid, month]);
  useEffect(() => {
    api<{ email: string; name?: string }>("/auth/me")
      .then(async (u) => {
        setUser(u);
        await loadWorkspaces();
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, [loadWorkspaces]);
  useEffect(() => {
    setCid("");
    setMessages([]);
    setLinkCode("");
    setAccounts([]);
    setEntries([]);
    setProposals([]);
    setSummary(null);
    setConversations([]);
    setJobs([]);
    setEditing(null);
  }, [wid]);
  useEffect(() => {
    refresh().catch((e) => {setError(e.message);loadWorkspaces().catch(()=>{});});
  }, [refresh,loadWorkspaces]);
  async function loadChat(room:string,replace=false){
    const context=wid+room+focusMessage;
    if(focusMessage){
      const rows=await api<Message[]>(base+'/conversations/'+room+'/messages?focus_id='+encodeURIComponent(focusMessage));
      if(liveContext.current===context){setMessages(rows);setHasOlder(false);}return;
    }
    const last=!replace?messageRows.current.at(-1)?.id:undefined;
    const data=await api<{items:Message[];has_older:boolean}>(base+'/conversations/'+room+'/messages/page'+(last?'?after='+last:''));
    if(selectedCid.current!==room||activeWid.current!==wid||liveContext.current!==context)return;
    if(replace||!last){setMessages(data.items);setHasOlder(data.has_older);}else setMessages(old=>{const known=new Set(old.map(m=>m.id));return [...old,...data.items.filter(m=>!known.has(m.id))];});
  }
  async function loadOlder(){
    const first=messageRows.current[0]?.id,room=cid,context=wid+cid+focusMessage;
    if(!first||!hasOlder||olderLock.current||focusMessage)return;
    olderLock.current=true;setLoadingOlder(true);
    try{
      const data=await api<{items:Message[];has_older:boolean}>(base+'/conversations/'+room+'/messages/page?before='+first);
      if(liveContext.current!==context)return;
      const element=document.getElementById('chat-message-'+first);
      if(element)olderAnchor.current={id:first,offset:element.getBoundingClientRect().top,context};
      setHasOlder(data.has_older);
      setMessages(old=>{const known=new Set(old.map(m=>m.id));return [...data.items.filter(m=>!known.has(m.id)),...old];});
    }catch(e){if(liveContext.current===context)setError((e as Error).message);}finally{olderLock.current=false;setLoadingOlder(false);}
  }
  useEffect(()=>{
    setMessages([]);setHasOlder(false);followBottom.current=true;
    if(wid&&cid)loadChat(cid,true).catch(e=>{if(selectedCid.current===cid)setError(e.message);});
  },[wid,cid,focusMessage]);
  const liveContext=useRef('');liveContext.current=wid+cid+focusMessage;
  const {draft:liveDraft,streamNotice,stopPreview}=useChatStream(wid,cid,isChat&&!focusMessage,messages.filter(m=>m.role==='assistant').at(-1)?.id||'',async()=>{await loadChat(cid);});
  useLayoutEffect(()=>{const el=chatScroll.current;if(el&&liveDraft&&followBottom.current&&!focusMessage)el.scrollTop=el.scrollHeight;},[liveDraft?.text,focusMessage]);
  const [stoppingJob,setStoppingJob]=useState('');
  const chatJob=jobs.find(j=>j.conversation_id===cid);
  const activeJob=chatJob?.status==='pending'?chatJob.id:liveDraft?.job;
  const chatPending=Boolean(activeJob);
  const stopping=Boolean(activeJob&&(chatJob?.stopping||stoppingJob===wid+':'+cid+':'+activeJob));
  async function stopAI(){
    const job=activeJob,context=wid+':'+cid;if(!job||stopping)return;
    setStoppingJob(context+':'+job);setError('');
    try{const result=await api<{status:string}>(base+'/conversations/'+cid+'/jobs/'+job+'/stop',{});if(activeWid.current+':'+selectedCid.current!==context)return;
      if(result.status==='stopping'||result.status==='cancelled'){stopPreview(job);setJobs(old=>old.map(j=>j.id===job?{...j,stopping:result.status==='stopping',status:result.status==='cancelled'?'cancelled':j.status}:j));}
      if(result.status!=='stopping'){await loadChat(cid);await refresh();}
    }catch(e){if(activeWid.current+':'+selectedCid.current===context)setError((e as Error).message);}
    finally{setStoppingJob(old=>old===context+':'+job?'':old);}
  }
  const hasPendingJobs = jobs.some((j) => j.status === "pending");
  useEffect(() => {
    // A fast worker can finish between the first history fetch and job refresh.
    // Keep the open room current even when no pending job was observed.
    if (!hasPendingJobs && !(path === "/assistant" && cid) && path !== "/inbox") return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        await refresh();
        if (cid) {
          if (!cancelled) await loadChat(cid);
        }
      } catch {}
    }, path === "/inbox" && !hasPendingJobs ? 10000 : 2500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [hasPendingJobs, refresh, cid, base, path, focusMessage]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "เกิดข้อผิดพลาด");
    } finally {
      setBusy(false);
    }
  }
  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    await run(async () => {
      const u = await api<{ email: string; name?: string }>(
        "/auth/login",
        Object.fromEntries(form),
      );
      setUser(u);
      await loadWorkspaces();
    });
  }
  async function newChat() {
    setFocusMessage("");setRenaming(false);setChatText("");if(chatInput.current){chatInput.current.value="";chatInput.current.style.height="";}
    await run(async () => {
      const c = await api<Conversation>(base + "/conversations", {
        title: "บทสนทนา " + new Date().toLocaleDateString("th-TH"),
        temporary,
      });
      setTemporaryRoom(c.temporary?c:null);
      setCid(c.id);
      setMessages([]);
      if (compact) setHistoryOpen(false);
      chatInput.current?.focus();
      await refresh();
    });
  }
  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    setFocusMessage("");setRenaming(false);
    const form = e.currentTarget;
    const text = String(new FormData(form).get("text")).trim();
    if (!text && !chatFile) return;
    // These commands are handled synchronously by the backend, never by a model.
    // A receipt/chat job elsewhere in the workspace must not lock confirmation.
    const reviewControl = !chatFile && isReviewCommand(text);
    if (chatPending && !reviewControl) {
      setNotice("กำลังเตรียมคำตอบอยู่ แต่ยังพิมพ์ ยืนยัน ยกเลิก หรือ ทวนอีกที ได้ค่ะ");
      return;
    }
    await run(async () => {
      let room = cid||selectedCid.current;
      const requested=new URLSearchParams(window.location.search).get('conversation');
      if(!room&&requested&&!requestedConsumed.current){
        if(!conversations.some(c=>c.id===requested)){const rooms=await api<Conversation[]>(base+'/conversations');if(!rooms.some(c=>c.id===requested))throw new Error('ไม่พบห้องสนทนานี้ในพื้นที่ที่เลือก');}
        requestedConsumed.current=true;room=requested;
      }
      if (!room) {
        const c = await api<Conversation>(base + "/conversations", { temporary });
        setTemporaryRoom(c.temporary?c:null);
        room = c.id;
      }
      if (chatFile) {
        const upload = new FormData();
        upload.append("file", chatFile);
        upload.append("text", text);
        const queued=await api<{job_id:string|null}>(base + "/conversations/" + room + "/images", upload);
        if(queued.job_id)setJobs(old=>[{id:queued.job_id!,status:"pending",error:null,conversation_id:room},...old.filter(j=>j.id!==queued.job_id)]);
        setChatFile(null);
        setNotice("ส่งรูปแล้ว ผู้ช่วยจะอ่านพร้อมข้อความของคุณ แล้วทวนให้ยืนยันในแชท");
      } else {
        const queued=await api<{job_id:string|null}>(base + "/conversations/" + room + "/messages", { text, review_message_id: messages.filter(m=>m.role==='assistant').at(-1)?.id });
        if(queued.job_id)setJobs(old=>[{id:queued.job_id!,status:"pending",error:null,conversation_id:room},...old.filter(j=>j.id!==queued.job_id)]);
      }
      setCid(room);
      form.reset();setChatText("");
      if (chatInput.current) chatInput.current.style.height = "";
      followBottom.current=true;selectedCid.current=room;
      liveContext.current=wid+room;
      await loadChat(room,room!==cid);
      await refresh();
    });
  }
  async function capture(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const text = String(new FormData(form).get("text"));
    await run(async () => {
      await api(base + "/capture", { text, privacy: capturePrivacy });
      form.reset();
      setNotice("ส่งเข้าคิวแล้ว ตรวจสอบรายการก่อนยืนยัน");
      await refresh();
    });
  }
  async function upload(file: File) {
    await run(async () => {
      const form = new FormData();
      form.append("file", file);
      form.append("privacy", capturePrivacy);
      const result = await api<{ duplicate: boolean }>(
        base + "/attachments",
        form,
      );
      setNotice(
        result.duplicate
          ? "พบรูปนี้ใน workspace แล้ว ไม่สร้างรายการซ้ำ"
          : "รับรูปแล้ว เข้าคิวอ่านสลิปตามโหมดที่เลือก",
      );
      await refresh();
    });
  }
  async function logout() {
    await run(async () => {
      await api("/auth/logout", {});
      clearVault();
      setUser(null);
      setWid("");
    });
  }
  const pending = proposals.filter((p) => p.status === "pending");
  if (!ready)
    return <main className="loading">กำลังเปิดพื้นที่การเงินของคุณ…</main>;
  if (!user)
    return (
      <main className="auth">
        <div className="auth-card">
          <div className="brand-mark">
            <ChartNoAxesCombined size={26} />
          </div>
          <p className="eyebrow">YOUR MONEY. YOUR SPACE.</p>
          <h1>Smart Finance</h1>
          <p className="muted">เริ่มดูแลการเงิน ในพื้นที่ส่วนตัวของคุณ</p>
          <form onSubmit={login}>
            <label>
              อีเมล
              <input
                name="email"
                type="email"
                autoComplete="username"
                required
              />
            </label>
            <label>
              รหัสผ่าน
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={200}
              />
            </label>
            <Button disabled={busy} className="w-full">
              {busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
              <ArrowUpRight size={17} />
            </Button>
          </form>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <Link className="members-join" href="/forgot-password">ลืมรหัสผ่าน?</Link>
          {allowRegistration&&<Link className="members-join" href="/register">ยังไม่มีบัญชี? สมัครใช้งาน <ArrowUpRight size={16}/></Link>}
          <Link className="members-join" href="/join">มีรหัสเชิญ? สร้างบัญชีหรือเข้าร่วมพื้นที่ <ArrowUpRight size={16}/></Link>
          <p className="privacy-note">
            <ShieldCheck size={16} /> Self-hosted · {allowRegistration?"สร้างพื้นที่ส่วนตัวได้ด้วยตัวเอง":"สมัครผ่านคำเชิญจากผู้ดูแล"}
          </p>
          <p className="muted small">
            {allowRegistration?"แต่ละบัญชีมีพื้นที่การเงินส่วนตัวของตัวเอง":"ครั้งแรก: สร้างผู้ใช้ตามขั้นตอนใน README บนเซิร์ฟเวอร์"}
          </p>
        </div>
      </main>
    );
  return (
    <div className={isChat ? "shell assistant-shell" : "shell finance-shell"}>
      {!isChat && <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">
            <ChartNoAxesCombined size={22} />
          </span>
          <span>
            Smart Finance<small>พื้นที่การเงินส่วนตัว</small>
          </span>
        </Link>
        <label className="workspace-label">
          WORKSPACE
          <select
            aria-label="เลือก workspace"
            value={wid}
            onChange={(e) => selectWorkspace(e.target.value)}
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        <nav aria-label="เมนูหลัก">
          {[{label:'ใช้ทุกวัน',paths:['/','/transactions','/insights','/assistant','/inbox']},{label:'วางแผนและจัดการ',paths:['/budgets','/goals','/recurring','/accounts','/categories']},{label:'พื้นที่ของคุณ',paths:['/workspaces','/members','/settings']}].map(group=><div className="nav-group" key={group.label}><span>{group.label}</span>{group.paths.map(href=>{const n=nav.find(n=>n.path===href)!;return <Link key={n.path} href={n.path} aria-current={(path===n.path||(n.path==='/settings'&&path==='/ai-settings'))?'page':undefined} className={'nav-item'+((path===n.path||(n.path==='/settings'&&path==='/ai-settings'))?' active':'')}><n.icon size={19}/>{n.label}{n.path==='/inbox'&&pending.length>0&&<span className="count">{pending.length}</span>}</Link>;})}</div>)}
        </nav>
        <div className="sidebar-bottom">
          <Link href="/services" aria-current={path==="/services"?"page":undefined} className={"nav-item pinned-services"+(path==="/services"?" active":"")}><Grid2X2 size={19}/>บริการทั้งหมด</Link>
          <div className="local-badge">
            <ShieldCheck size={16} /> ข้อมูลอยู่บนเซิร์ฟเวอร์ของคุณ
          </div>
          <div className="profile">
            <span className="avatar">{(user.name || user.email)[0].toUpperCase()}</span>
            <span className="profile-name">
              {user.name || user.email}
              <small>บัญชีส่วนตัว</small>
            </span>
            <button aria-label="ออกจากระบบ" onClick={logout}>
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>}
      <main className="main">
        {!isChat && <header className="topbar">
          <Link href="/" className="mobile-brand"><span className="brand-mark"><ChartNoAxesCombined size={20} /></span><strong>Smart Finance</strong></Link>
          <span className="muted">
            พื้นที่ของคุณ <ChevronRight size={14} />{" "}
            <span className="text-slate-700">
              {(path==="/ai-settings"?"ตั้งค่า AI":nav.find((n) => n.path === path)?.label) || "ภาพรวม"}
            </span>
          </span>
          <div className="topbar-actions">
            <select aria-label="เลือก workspace บนมือถือ" className="mobile-workspace" value={wid} onChange={(e) => selectWorkspace(e.target.value)}>{workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>
            <span className="status-dot">พื้นที่ส่วนตัว</span>
            <Link href="/settings" className="icon-button" aria-label="ตั้งค่า"><Settings size={21} /></Link>
          </div>
          <button
            className="mobile-logout"
            aria-label="ออกจากระบบ"
            onClick={logout}
          >
            <LogOut size={16} />
          </button>
        </header>}
        <div className={isChat ? "content assistant-content" : "content"}>
          {error && (
            <div className="error" role="alert">
              {error}
              <button aria-label="ปิดข้อผิดพลาด" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          {!isChat && <div className="page-heading">
            <div>
              <p className="eyebrow">
                {path === "/" ? "YOUR EVERYDAY FINANCES" : "SMART FINANCE"}
              </p>
              <h1>
                {path === "/"
                  ? "การเงินของคุณ"
                  : (path==="/ai-settings"?"ตั้งค่า AI":nav.find((n) => n.path === path)?.label)}
              </h1>
              <p className="muted">
                {path === "/"
                  ? "รู้ว่าเงินอยู่ที่ไหน และใช้ไปกับอะไร"
                  : path === "/assistant"
                    ? "คุยเรื่องเงิน ตรวจสอบข้อมูล และตัดสินใจด้วยตัวคุณเอง"
                    : path === "/insights"
                      ? "ดูว่าเงินไปกับอะไร เปรียบเทียบ และมองแนวโน้มได้ง่าย ๆ"
                    : path === "/services"
                      ? "ทุกบริการของคุณ เลือกใช้งานได้จากที่เดียว"
                    : path === "/accounts"
                      ? "เงินของคุณอยู่ที่ไหน ดูยอดและจัดการบัญชีที่นี่"
                    : path === "/budgets"
                      ? "วางแผนรายเดือน แล้วติดตามยอดใช้จริงตามหมวด"
                    : path === "/members"
                      ? "พื้นที่ร่วมกัน กับสิทธิ์ที่คุณจัดการได้"
                    : path === "/recurring"
                      ? "ให้ระบบช่วยจำ แล้วคุณตรวจสอบก่อนบันทึก"
                    : path === "/goals"
                      ? "ค่อย ๆ เก็บ เพื่อสิ่งที่สำคัญกับคุณ"
                    : path === "/categories"
                      ? "แยกรายรับและรายจ่าย ให้เห็นว่าเงินไปกับอะไร"
                    : path === "/inbox"
                      ? "ทุกข้อเสนอจะรอให้คุณตรวจสอบและยืนยันก่อนบันทึก"
                      : "ข้อมูลจริงจาก workspace ที่คุณเลือก"}
              </p>
            </div>
            {!["/insights","/budgets","/goals","/recurring","/members","/workspaces"].includes(path) && <Button onClick={() => {
              if(["/accounts","/categories"].includes(path)) {document.getElementById("management-create")?.scrollIntoView({block:"center"});document.querySelector<HTMLInputElement>("#management-create input")?.focus({preventScroll:true});}
              else setEditing("new");
            }} disabled={!wid}>
              <Plus size={17} />
              {path==="/categories"?"เพิ่มหมวดหมู่":path==="/accounts"?"เพิ่มบัญชี":"เพิ่มรายการ"}
            </Button>}
          </div>}
          {path === "/workspaces" && <WorkspaceManager onChanged={loadWorkspaces} onSelect={id=>{try{sessionStorage.setItem('sf-workspace',id);}catch{}setWid(id);}}/>}
          {!wid&&path!=="/workspaces"&&<section className="panel report-empty"><h2>ยังไม่มีพื้นที่ที่กำลังใช้งาน</h2><p>สร้างพื้นที่ใหม่ หรือกู้คืนพื้นที่จากคลังได้ ข้อมูลบัญชีผู้ใช้ของคุณยังอยู่</p><Link href="/workspaces">ไปจัดการพื้นที่ทำงาน <ArrowUpRight size={16}/></Link></section>}
          {path === "/" && wid && <DashboardView summary={summary?.month===month?summary:null} month={month} onMonthChange={setMonth} />}
          {path === "/insights" && wid && <InsightsPage key={wid} wid={wid} accounts={accounts} refreshKey={ledgerVersion}/>}
          {path === "/transactions" && wid && <TransactionsExplorer key={wid} wid={wid} accounts={accounts} refreshKey={ledgerVersion} onChanged={() => { setLedgerVersion(v => v + 1); refresh(); }} />}
          {path === "/budgets" && wid && (summary ? <BudgetsPage key={wid+month} wid={wid} accounts={accounts} month={month} onMonthChange={setMonth}/> : <div className="report-loading" role="status">กำลังเปิดงบประมาณ…</div>)}
          {path === "/members" && wid && <MembersPage key={wid} wid={wid} owner={workspaces.find(w=>w.id===wid)?.role==="owner"} onChanged={loadWorkspaces}/>}
          {path === "/recurring" && wid && (summary ? <RecurringPage key={wid} wid={wid} accounts={accounts} onGenerated={refresh}/> : <div className="report-loading" role="status">กำลังเปิดรายการประจำ…</div>)}
          {path === "/goals" && wid && (wid ? <GoalsPage key={wid} wid={wid}/> : <div className="report-loading" role="status">กำลังเปิดเป้าหมาย…</div>)}
          {path === "/services" && wid && (summary ? <ServicesHub accounts={accounts} pending={pending.length} owner={workspaces.find(w=>w.id===wid)?.role==="owner"} onAdd={()=>setEditing("new")} /> : <div className="report-loading" role="status">กำลังเปิดบริการของคุณ…</div>)}
          {(path === "/accounts" || path === "/categories") && wid && (summary ? <AccountManager key={path+wid} accounts={accounts} categories={path==="/categories"} busy={busy} onCreate={async data=>{
            let success=false;
            await run(async()=>{await api(base+"/accounts",data); await refresh();setNotice(path==="/categories"?"เพิ่มหมวดหมู่เรียบร้อยแล้ว":"เพิ่มบัญชีเรียบร้อยแล้ว");success=true;});
            return success;
          }}/> : <div className="report-loading" role="status">กำลังเปิดข้อมูลของคุณ…</div>)}
          {path === "/inbox" && wid && (
            <>
              <div className="toolbar">
                <label className="capture-mode">
                  การประมวลผลข้อความและสลิป
                  <select
                    value={capturePrivacy}
                    onChange={(e) => setCapturePrivacy(e.target.value)}
                  >
                    <option value="private">Private · Local AI เท่านั้น</option>
                    <option value="standard">Standard · อนุญาต Cloud AI</option>
                  </select>
                </label>
              </div>
              {capturePrivacy === "standard" && (
                <p className="notice">
                  ข้อความและรูปสลิปจะส่งไปยัง Cloud provider ที่ตั้งค่าไว้
                  หากเซิร์ฟเวอร์อนุญาต
                </p>
              )}
              <div className="capture-grid">
                <section className="panel">
                  <h3>เล่าให้ฟังว่าใช้เงินกับอะไร</h3>
                  <form onSubmit={capture}>
                    <label className="sr-only" htmlFor="capture">
                      ข้อความรายการเงิน
                    </label>
                    <textarea
                      id="capture"
                      name="text"
                      placeholder="เช่น ข้าว 75 น้ำ 25"
                      required
                      maxLength={4000}
                    />
                    <div className="flex justify-between items-center gap-3">
                      <span className="muted small">
                        {capturePrivacy === "private"
                          ? "Local-only"
                          : "Cloud allowed"}{" "}
                        · ใช้ demo parser หากยังไม่มีโมเดล
                      </span>
                      <Button disabled={busy}>
                        <Sparkles size={16} />
                        สร้างข้อเสนอ
                      </Button>
                    </div>
                  </form>
                </section>
                <section className="panel upload">
                  <Paperclip size={24} />
                  <h3>อัปโหลดสลิป</h3>
                  <p className="muted small">
                    JPEG / PNG / WebP ไม่เกิน 8 MB
                    <br />
                    {capturePrivacy === "private"
                      ? "อ่านแบบ local-only"
                      : "อนุญาตส่งรูปไป Cloud AI"}{" "}
                    · ไม่ตรวจยืนยันว่าสลิปแท้
                  </p>
                  <label className="file-button">
                    เลือกรูปภาพ
                    <input
                      aria-label="อัปโหลดสลิป"
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      disabled={busy}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) upload(f);
                        e.target.value = "";
                      }}
                    />
                  </label>
                </section>
              </div>
              {jobs.some((j) => j.status === "pending") && (
                <p className="notice" role="status">
                  กำลังประมวลผลใน worker… หน้านี้จะอัปเดตอัตโนมัติ
                </p>
              )}
              {jobs.some((j) => j.status === "failed") && (
                <p className="error">
                  มีงานอ่านข้อมูลไม่สำเร็จ คุณสามารถกรอกรายการเองได้
                </p>
              )}
              <section className="panel">
                <div className="panel-heading">
                  <h3>
                    รอตรวจสอบ <span className="muted">{pending.length}</span>
                  </h3>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => run(refresh)}
                  >
                    รีเฟรช
                  </Button>
                </div>
                {pending.length >= 100 && <p className="notice small">แสดงรายการรอตรวจสอบสูงสุด 100 รายการ เมื่อตรวจสอบแล้วให้รีเฟรชเพื่อดูรายการถัดไป</p>}
                {pending.length ? (
                  pending.map((p) => (
                    <div className="proposal" key={p.id}>
                      <div>
                        <span className="tag">
                          {p.source === "recurring" ? "รายการประจำ · รอยืนยัน" : p.source === "demo"
                            ? "สาธิต · กรุณาตรวจสอบ"
                            : "ข้อเสนอ · ยังไม่บันทึก"}
                        </span>
                        <h3>{p.description}</h3>
                        <p className="muted small">
                          {kinds[p.kind]} ·{" "}
                          {p.amount ? money(p.amount) : "ยังไม่ทราบจำนวนเงิน"}{p.occurred_on ? " · รอบวันที่ " + p.occurred_on : ""}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await api(
                                base + "/proposals/" + p.id + "/reject",
                                {},
                              );
                              await refresh();
                            })
                          }
                        >
                          ยกเลิก
                        </Button>
                        <Button size="sm" onClick={() => setEditing(p)}>
                          ตรวจสอบ
                        </Button>
                      </div>
                    </div>
                  ))
                ) : (
                  <Empty text="ไม่มีรายการรอยืนยัน ยอดเงินจะเปลี่ยนเมื่อคุณกดยืนยันเท่านั้น" />
                )}
              </section>
            </>
          )}
          {isChat && wid && (
            <div className={"chat-layout" + (historyOpen ? " history-open" : "")}>
              {historyOpen && compact && <button className="history-scrim" aria-label="ปิดประวัติการสนทนา" onClick={() => { setHistoryOpen(false); historyToggle.current?.focus(); }} />}
              <aside id="chat-history" className="chat-history" aria-label="ประวัติการสนทนา" role={compact ? "dialog" : undefined} aria-modal={compact ? true : undefined} onKeyDown={(e) => {
                if (!compact || e.key !== "Tab") return;
                const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),summary,[tabindex="0"]')).filter((el) => el.getClientRects().length);
                const first = items[0], last = items.at(-1);
                if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
                else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
              }}>
                <div className="history-brand"><span className="brand-mark"><Sparkles size={21} /></span><strong>Finance AI</strong><button ref={historyClose} className="icon-button" aria-label="ปิดประวัติ" onClick={() => { setHistoryOpen(false); historyToggle.current?.focus(); }}><X size={20} /></button></div>
                <Link href="/" className="back-finance"><ArrowLeft size={17} /> กลับหน้าการเงิน</Link>
                <div className="chat-mode-picker"><span>สำหรับบทสนทนาใหม่</span><div role="group" aria-label="ประเภทแชทใหม่"><button type="button" aria-pressed={!temporary} onClick={()=>setTemporary(false)}><MessageSquare size={16}/>เก็บประวัติ</button><button type="button" aria-pressed={temporary} onClick={()=>setTemporary(true)}><Ghost size={16}/>ชั่วคราว</button></div><p>{temporary?'ไม่อยู่ในประวัติ · หมดอายุใน 24 ชม.':'เก็บไว้ในประวัติ สำหรับคุยต่อ'}</p></div>
                <Button className="new-chat" disabled={busy} onClick={newChat}><Plus size={19} /> บทสนทนาใหม่</Button>
                <ChatHistory key={wid} wid={wid} selected={cid} revision={JSON.stringify(conversations.map(c=>[c.id,c.title]))+latestMessage} onSelect={c=>{setTemporaryRoom(null);setRenaming(false);setMessages([]);setFocusMessage(c.message_id||'');setCid(c.id);if(compact)setHistoryOpen(false);}}/>
                <div className="history-settings"><div className="history-utilities"><AssistantHistory key={wid} wid={wid}/><Link href="/ai-settings" className="icon-button" aria-label="ตั้งค่า AI และความเป็นส่วนตัว" title="ตั้งค่า AI"><Settings size={18}/></Link></div>
                  <label>Workspace<select aria-label="เลือก workspace ในแชท" value={wid} onChange={(e) => { selectWorkspace(e.target.value); if (compact) setHistoryOpen(false); }}>{workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
                  <div className="history-room-tools">{cid&&!selectedRoom?.temporary&&<button title="เปลี่ยนชื่อบทสนทนา" className="rename-chat" onClick={()=>{setRoomTitle(selectedRoom?.title||'');setRenaming(true);if(compact)setHistoryOpen(false);}}><Pencil size={16}/>เปลี่ยนชื่อบทสนทนา</button>}
                  {cid && <button className="delete-chat" onClick={() => run(async () => { await api(base + "/conversations/" + cid, undefined, "DELETE"); setCid(""); setMessages([]); await refresh(); })}><Trash2 size={16} /> ลบบทสนทนานี้</button>}
                  </div>
                </div>
              </aside>
              <section className={"chat"+(draggingImage?" image-dragging":"")} onDragEnter={e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();imageDragDepth.current++;setDraggingImage(true);}}} onDragOver={e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}}} onDragLeave={e=>{if(e.dataTransfer.types.includes('Files')){imageDragDepth.current=Math.max(0,imageDragDepth.current-1);if(!imageDragDepth.current)setDraggingImage(false);}}} onDrop={dropChatImage}>
                {draggingImage&&<div className="chat-drop-overlay" role="status"><Paperclip size={30}/><strong>วางรูปที่นี่</strong><span>ดูตัวอย่างก่อนส่ง · ครั้งละ 1 รูป</span></div>}
                <header className="chat-topbar">
                  <div><Link href="/" className="icon-button chat-back" aria-label="กลับหน้าการเงิน"><ArrowLeft size={21} /></Link><button ref={historyToggle} className="icon-button" aria-label="เปิดประวัติการสนทนา" aria-expanded={historyOpen} aria-controls="chat-history" onClick={() => setHistoryOpen(!historyOpen)}><Menu size={22} /></button><strong>Finance AI<span>{workspaces.find(w=>w.id===wid)?.name || 'ผู้ช่วยการเงินของคุณ'}</span></strong></div>
                  <div><span className={"privacy-pill"+((selectedRoom?.temporary||(!cid&&temporary))?" is-temporary":"")}>{(selectedRoom?.temporary||(!cid&&temporary))?<><Ghost size={15}/>ชั่วคราว</>:<><MessageSquare size={15}/>เก็บประวัติ</>}</span><button className="icon-button" aria-label="เริ่มบทสนทนาใหม่" disabled={busy} onClick={newChat}><Plus size={23} /></button></div>
                </header>
                {renaming&&<form className="chat-rename-form" onSubmit={e=>{e.preventDefault();run(async()=>{await api(base+'/conversations/'+cid+'/rename',{title:roomTitle.trim()});setRenaming(false);await refresh();});}}><label>ชื่อบทสนทนา<input aria-label="ชื่อบทสนทนา" value={roomTitle} onChange={e=>setRoomTitle(e.target.value)} maxLength={100} required autoFocus disabled={busy}/></label><Button type="submit" size="sm" disabled={busy||!roomTitle.trim()}>บันทึกชื่อ</Button><button className="icon-button" aria-label="ยกเลิกเปลี่ยนชื่อแชท" type="button" disabled={busy} onClick={()=>setRenaming(false)}><X size={18}/></button></form>}
                {focusMessage&&<div className="chat-focus-banner"><span>ส่วนของบทสนทนาที่ตรงคำค้น</span><button onClick={()=>setFocusMessage('')}>ดูข้อความล่าสุด</button></div>}
                {selectedRoom?.temporary&&<div className="temporary-banner" role="status"><span>แชทชั่วคราว · หมดอายุใน 24 ชม. แล้วระบบทยอยล้าง รูปที่เข้า Inbox จะยังอยู่</span><button disabled={busy} onClick={()=>run(async()=>{await api(base+'/conversations/'+cid,undefined,'DELETE');setCid('');setMessages([]);setTemporaryRoom(null);await refresh();})}>จบและล้างแชท</button></div>}<div className="messages" ref={chatScroll} onWheel={e=>{if(e.deltaY<0)followBottom.current=false;}} onTouchMove={()=>{followBottom.current=false;}} onScroll={()=>{const el=chatScroll.current;if(el){followBottom.current=el.scrollHeight-el.scrollTop-el.clientHeight<=24;setShowLatest(el.scrollHeight-el.scrollTop-el.clientHeight>180);if(el.scrollTop<64)loadOlder();}}} role="log" aria-label="ข้อความในบทสนทนา" aria-live="polite">
                  <div className={"message-stream"+(!messages.length&&!liveDraft?" welcome-stream":"")}>
                    {hasOlder&&!focusMessage&&<button className="load-older-chat" disabled={loadingOlder} onClick={loadOlder}>{loadingOlder?'กำลังโหลดข้อความเก่า…':'โหลดข้อความก่อนหน้า'}</button>}
                    {messages.length ? messages.map((m) => <div id={"chat-message-"+m.id} className={"message " + m.role+(focusMessage===m.id?" search-focus":"")} key={m.id}>
                      <span className="message-author">{m.role === "user" ? "คุณ" : <><Sparkles size={17} /> Finance AI{m.content&&<button className="copy-chat-answer" type="button" aria-label={copiedMessage===m.id?"คัดลอกคำตอบแล้ว":"คัดลอกคำตอบ"} title="คัดลอกคำตอบ" onClick={()=>void copyAnswer(m)}>{copiedMessage===m.id?<><Check size={15}/><span>คัดลอกแล้ว</span></>:<Copy size={15}/>}</button>}</>}</span>
                      {m.attachment_id && <a href={"/api" + base + "/attachments/" + m.attachment_id} target="_blank" rel="noreferrer"><img className="chat-image" src={"/api" + base + "/attachments/" + m.attachment_id} alt="รูปที่แนบในบทสนทนา" loading="lazy" onLoad={() => { const el = chatScroll.current; if (el && followBottom.current && !focusMessage) el.scrollTop = el.scrollHeight; }} /></a>}
                      {m.content && <ChatMarkdown text={m.role==='assistant'?m.content.replace(/\n\nรหัสทางเลือก:\nยืนยัน [A-F0-9]{8}\n$/,''):m.content}/>}
                      {m.role==='assistant'&&<ChatEvidence wid={wid} items={m.references}/>}
                      {m.role === "assistant" && m.content.includes("AI Inbox") && <Link className="inbox-result" href="/inbox">เปิด AI Inbox เพื่อตรวจสอบ <ArrowUpRight size={16} /></Link>}
                    </div>) : liveDraft ? null : <div className="chat-welcome">
                      <div className="ai-orb"><Sparkles size={32} /></div><p className="eyebrow">ผู้ช่วยการเงินของคุณ</p><h1>วันนี้ อยากคุย<br className="mobile-break" />เรื่องอะไร?</h1><p className="muted">มองภาพรวมเงินของคุณ หรือส่งสลิป<br />ให้ช่วยเตรียมรายการและยืนยันที่นี่</p>
                      <div className="chat-suggestions">{[{icon: Wallet, text: "ตอนนี้ฉันมีเงินเท่าไร?", detail: "ดูยอดสะสมจากบัญชีของคุณ"}, {icon: Paperclip, text: "อยากบันทึกจากสลิป", detail: "แนบรูป แล้วตรวจร่างก่อนยืนยัน"}, {icon: ChartNoAxesCombined, text: "เดือนนี้ใช้กับอะไรเยอะสุด?", detail: "ให้ช่วยอ่านและอธิบายข้อมูล"}, {icon: ArrowLeftRight, text: "เทียบรายจ่ายกับเดือนก่อนให้หน่อย", detail: "ดูว่าอะไรเพิ่มขึ้นหรือลดลง"}].map((prompt) => <button key={prompt.text} onClick={() => { if (chatInput.current) { chatInput.current.value = prompt.text; setChatText(prompt.text); chatInput.current.focus(); } }}><prompt.icon size={22} /><strong>{prompt.text}</strong><span>{prompt.detail}</span><ArrowUpRight size={16} /></button>)}</div>
                    </div>}
                    {liveDraft?.text&&<div className="message assistant live-answer" aria-label="คำตอบที่กำลังทยอยแสดง"><span className="message-author"><Sparkles size={17}/> Finance AI <small>กำลังตอบ · ยังไม่สมบูรณ์</small></span><ChatMarkdown text={liveDraft.text}/></div>}
                    {streamNotice&&<p className="stream-notice" role="status">{streamNotice}</p>}
                    {(busy || chatPending || liveDraft) && !liveDraft?.text && messages.length > 0 && <div className="thinking" role="status"><span /><span /><span /> กำลังเตรียมคำตอบ</div>}
                  </div>
                </div>
                <div className="chat-composer-dock">
                {showLatest&&<button type="button" className="chat-jump-latest" onClick={()=>{followBottom.current=true;setFocusMessage('');setShowLatest(false);chatScroll.current?.scrollTo({top:chatScroll.current.scrollHeight,behavior:'smooth'});}}><ChevronDown size={17}/>ข้อความล่าสุด</button>}
                {chatUploadError&&<div className="chat-upload-error" role="alert"><span>{chatUploadError}</span><button type="button" aria-label="ปิดข้อความแนบรูป" onClick={()=>setChatUploadError('')}><X size={16}/></button></div>}
                <details className="chat-action-help"><summary>ให้ผู้ช่วยจัดการอะไรได้บ้าง?</summary><p>คุยทั่วไป จดจากข้อความหรือรูป ค้นหาแล้วแก้รายการ วิเคราะห์รายเดือนและเสนอปรับงบ สร้าง/เปลี่ยนชื่อบัญชีและหมวด ตั้งงบ สร้างเป้าออม หรือตั้งรายการประจำ สั่งเป็นชุดได้ ฉันจะทวนทั้งชุดก่อนให้พิมพ์ ยืนยัน ดูงานที่ทำแล้วได้ในเมนูแชท → ประวัติงานผู้ช่วย</p><p>เช่น “กาแฟ 75 จากเงินสด” หรือ “รับเงินเดือน 30,000” ถ้าขาดอะไร ฉันจะถามเพิ่ม แล้วทวนให้ตรวจ พิมพ์แค่ ยืนยัน เพื่อบันทึก หรือ ยกเลิก ถ้าไม่เอาค่ะ</p><button type="button" onClick={()=>{if(chatInput.current){chatInput.current.value="กาแฟ 75 จากเงินสด";setChatText("กาแฟ 75 จากเงินสด");chatInput.current.style.height="auto";chatInput.current.focus();}}}>ใส่ตัวอย่างคำขอบันทึก</button><p>ยังไม่ยืนยันก็แก้ยอดได้ เช่น “จริง ๆ 90 บาท” ถ้าบันทึกไปแล้ว บอก “ค่ากาแฟเมื่อวานที่ลง 90 จริง ๆ 75” ได้เมื่อเชื่อมโมเดล ถ้าเจอหลายรายการฉันจะถามให้เลือกก่อน หรือใช้ “แก้รายการล่าสุดเป็น 90 บาท” / คำขอแก้จากหน้ารายการ</p><p>จดหลายรายการจากข้อความหรือรูปเดียวได้สูงสุด 10 รายการต่อชุด แล้วพิมพ์ ยืนยัน ครั้งเดียว เช่น “จดกาแฟ 75 กับข้าว 80 จากเงินสด” แก้ก่อนบันทึกด้วย “แก้ยอดรายการที่ 2 เป็น 90 บาท” หรือ “ลบรายการที่ 2” ระบบจะเตือนถ้าคล้ายรายการที่ลงแล้ว กรุณาตรวจสอบก่อนยืนยัน</p><small>ข้อเสนอรอยืนยันได้ 15 นาทีในห้องนี้ ถ้าหาข้อความทวนไม่เจอ พิมพ์ ทวนอีกที แนบรูปพร้อมคำอธิบายได้ เมื่อโมเดลแชทรองรับภาพ ฉันจะทวนให้ยืนยันในห้องนี้</small></details>
                {chatPreview && <div className="chat-attachment-preview">
                  <img src={chatPreview} alt="ตัวอย่างรูปก่อนส่ง" />
                  <div><strong>{chatFile?.name}</strong><p className="small muted">{chatFile?`${(chatFile.size/1024/1024).toFixed(2)} MB · `:""}แนบไว้ในเครื่อง ยังไม่ส่งจนกว่าจะกดส่ง</p></div>
                  <Button variant="ghost" type="button" aria-label="นำรูปออก" disabled={busy} onClick={() => {setChatFile(null);setChatUploadError("");}}><X size={20} /></Button>
                </div>}
                {chatJob?.status==='failed'&&chatJob.message&&<p role="alert" className="error">{chatJob.message}</p>}
                <form onSubmit={send} onPaste={pasteChatImage} className="composer" aria-label="เขียนข้อความและแนบรูป">
                  <label className="chat-attach-button" title="แนบรูปสลิป">
                    <Paperclip size={22} />
                    <span className="sr-only">แนบรูปสลิปในแชท</span>
                    <input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (!file) return;
                      attachChatFiles([file]);
                    }} />
                  </label>
                  <label className="sr-only" htmlFor="chat-text">
                    ข้อความถึง AI
                  </label>
                  <textarea
                    ref={chatInput}
                    rows={1}
                    onInput={(e) => { setChatText(e.currentTarget.value); e.currentTarget.style.height = "auto"; e.currentTarget.style.height = Math.min(e.currentTarget.scrollHeight, 144) + "px"; }}
                    onKeyDown={(e) => {
                      if(e.key==="Escape"&&chatFile&&!busy){e.preventDefault();setChatFile(null);setChatUploadError("");return;}
                      if (!compact && e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); }
                    }}
                    id="chat-text"
                    name="text"
                    placeholder={chatFile ? "เพิ่มข้อความประกอบรูป (ไม่บังคับ)…" : "ถามเรื่องเงิน หรือวางรูปสลิปที่นี่…"}
                    required={!chatFile}
                    maxLength={4000}
                  />
                  {activeJob&&<Button type="button" className="chat-stop" variant="outline" aria-label="หยุด AI" disabled={stopping} onClick={()=>void stopAI()}><Square size={17}/><span>{stopping?"กำลังหยุด…":"หยุด"}</span></Button>}
                  <Button
                    disabled={busy || (!chatText.trim()&&!chatFile) || (chatPending && (!!chatFile || !isReviewCommand(chatText)))}
                    aria-label="ส่งข้อความ"
                  >
                    <Send size={18} />
                  </Button>
                </form>

                  <p className="chat-input-hint">{compact?"แนบหรือวางรูปได้ · ครั้งละ 1 รูป":"วางรูปด้วย ⌘V / Ctrl+V หรือลากมาที่นี่ · Enter ส่ง · Shift+Enter ขึ้นบรรทัดใหม่"}</p>
                  <div className="composer-meta"><span><ShieldCheck size={13} />ใช้ AI ตามการตั้งค่าของ workspace นี้</span><details><summary>เกี่ยวกับรูปและข้อมูล</summary><p>รูปสลิปจะเข้า AI Inbox ของ workspace สมาชิกจะเห็นข้อเสนอและรูปหลักฐานเมื่ออ่านเสร็จ คุณต้องตรวจสอบและยืนยันเองทุกครั้ง AI อาจให้ข้อมูลผิดพลาด ประวัติเก็บบนเซิร์ฟเวอร์ของคุณ โหมดสาธิตยังอ่านยอดจากรูปไม่ได้</p></details></div>
                </div>
              </section>
            </div>
          )}
          {path === "/ai-settings" && wid && <AISettingsPage key={wid} wid={wid} owner={workspaces.find(w=>w.id===wid)?.role==="owner"}/> }
          {path === "/settings" && (
            <div className="settings-grid">
              <AccountSettings user={user} onUpdate={setUser}/>
              {wid&&<PwaSettings key={'offline-'+wid} wid={wid} name={workspaces.find(w=>w.id===wid)?.name||''}/>}
              {wid&&<>
              {wid&&<ChatRetention key={wid} wid={wid}/>}
              <section className="panel" id="workspace-settings">
                <div className="settings-profile"><div><span className="small muted">บัญชีของคุณ</span><strong>{user.email}</strong></div><Button variant="outline" size="sm" onClick={logout}><LogOut size={16} /> ออกจากระบบ</Button></div><hr />
                <h3>
                  <ShieldCheck size={20} /> ความเป็นส่วนตัวและ Workspace
                </h3>
                <p className="muted">
                  แชทใช้ลำดับ AI ของ workspace ที่เลือกอยู่ทุกห้อง
                  เปิดหรือปิด Cloud AI ได้จากศูนย์ตั้งค่า AI ของพื้นที่
                  ไม่ต้องเลือกโหมดเมื่อสร้างห้อง
                </p>
                <p className="muted small">
                  รหัสผ่านและ API key ไม่ถูกเก็บในเบราว์เซอร์ แชทชั่วคราวเลือกได้จากเมนูในหน้าแชท
                </p>
                <Link className="workspace-open" href="/workspaces">จัดการพื้นที่ทำงาน · สร้าง เปลี่ยนชื่อ หรือเก็บเข้าคลัง <ArrowUpRight size={16}/></Link>
                <hr />
                <h3 id="telegram-settings">เชื่อม Telegram</h3>
                <p className="muted small">
                  ข้อความและรูปผ่านเซิร์ฟเวอร์ Telegram
                  คุยกับ AI และส่งรูปพร้อมคำบรรยายได้ บอตจะทวนก่อนให้พิมพ์ ยืนยัน รหัสเชื่อมต่อใช้ครั้งเดียว หมดอายุใน 10 นาที
                </p>
                <div className="flex gap-2 flex-wrap">
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        const r = await api<{ code: string }>(
                          base + "/telegram/link-code",
                          {},
                        );
                        setLinkCode("/start " + r.code);
                      })
                    }
                  >
                    สร้างรหัสเชื่อมต่อ
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await api(base + "/telegram/link", undefined, "DELETE");
                        setLinkCode("");
                        setNotice("ยกเลิกการเชื่อมต่อแล้ว");
                      })
                    }
                  >
                    ยกเลิกการเชื่อมต่อ
                  </Button>
                </div>
                {linkCode && <code className="link-code">{linkCode}</code>}
              </section>
              {wid && (
                <section className="panel" id="ai-provider-settings"><h3><Sparkles size={20}/> ตั้งค่า AI</h3><p className="muted">จัดการความจำส่วนตัว บัญชีเริ่มต้น และกฎหมวดหมู่ · เจ้าของพื้นที่จัดการโมเดล Cloud AI และงบใช้งานได้ที่นี่</p><Link className="workspace-open" href="/ai-settings">เปิดศูนย์ตั้งค่า AI <ArrowUpRight size={16}/></Link></section>
              )}
              </>}
            </div>
          )}
          {!isChat && <footer>
            Smart Finance{" "}
            <span>
              THB · Asia/Bangkok · คุณควบคุมข้อมูลและการยืนยันทุกครั้ง
            </span>
          </footer>}
        </div>
      </main>
      {!isChat && <nav className="bottom-nav" aria-label="เมนูหลักบนมือถือ">
        {['/','/transactions','/assistant','/insights','/services'].map(href=>nav.find(n=>n.path===href)!).map((item) => <Link key={item.path} href={item.path} aria-current={(path === item.path || (item.path==="/services" && ["/accounts","/categories","/budgets","/goals","/recurring","/members","/workspaces","/settings","/ai-settings","/inbox"].includes(path))) ? "page" : undefined} className={(path === item.path || (item.path==="/services" && ["/accounts","/categories","/budgets","/goals","/recurring","/members","/workspaces","/settings","/ai-settings","/inbox"].includes(path))) ? "active" : ""}><item.icon size={22} /><span>{item.path === "/services" ? "ทั้งหมด" : item.path === "/transactions" ? "รายการ" : item.path === "/assistant" ? "แชท AI" : item.label}</span>{item.path === "/inbox" && pending.length > 0 && <i>{pending.length}</i>}</Link>)}
      </nav>}
      {editing && (
        <TransactionDialog
          proposal={editing}
          accounts={accounts}
          wid={wid}
          busy={busy}
          close={() => setEditing(null)}
          submit={async (body) => {
            await run(async () => {
              const endpoint =
                editing === "new"
                  ? "/transactions"
                  : "/proposals/" + editing.id + "/confirm";
              await api(base + endpoint, body);
              setEditing(null);
              setNotice("บันทึกรายการเรียบร้อยแล้ว");
              setLedgerVersion(v => v + 1);
              await refresh();
            });
          }}
        />
      )}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
      <Wallet size={25} />
      <p>{text}</p>
    </div>
  );
}
function TransactionDialog({
  proposal,
  accounts,
  wid,
  busy,
  close,
  submit,
}: {
  proposal: Proposal | "new";
  accounts: Account[];
  wid: string;
  busy: boolean;
  close: () => void;
  submit: (body: unknown) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    key = useRef(crypto.randomUUID());
  const [kind, setKind] = useState(
    proposal === "new" ? "expense" : proposal.kind,
  );
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  const wallets = accounts.filter(
    (a) =>
      a.kind === "asset" ||
      (a.kind === "liability" && ["expense", "opening"].includes(kind)),
  );
  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    let amount;
    try {
      amount = satang(String(f.get("amount")));
    } catch (err) {
      (
        e.currentTarget.elements.namedItem("amount") as HTMLInputElement
      ).setCustomValidity((err as Error).message);
      e.currentTarget.reportValidity();
      return;
    }
    await submit({
      kind,
      account_id: f.get("account_id"),
      other_account_id: f.get("other_account_id") || null,
      category_id: f.get("category_id") || null,
      amount,
      description: f.get("description"),
      occurred_on: f.get("occurred_on"),
      idempotency_key: key.current,
    });
  }
  return (
    <dialog
      ref={dialog}
      className="entry-dialog"
      onCancel={close}
      aria-labelledby="entry-title"
    >
      <div className="panel-heading">
        <h2 id="entry-title">
          {proposal === "new" ? "เพิ่มรายการเงิน" : "ตรวจสอบก่อนยืนยัน"}
        </h2>
        <button aria-label="ปิด" onClick={close}>
          <X size={22} />
        </button>
      </div>
      {proposal !== "new" && (
        <p className="notice small">
          {proposal.source === "recurring" ? "รายการจากตารางประจำ กรุณาตรวจสอบยอดจริง วันที่ บัญชี และหมวดหมู่ก่อนยืนยัน" : "ข้อมูล AI อาจผิดพลาด ตรวจสอบจำนวนเงิน บัญชี และหมวดหมู่ก่อนบันทึก"}
        </p>
      )}
      <form onSubmit={onSubmit}>
        {proposal !== "new" && proposal.attachment_id && (
          <img
            className="receipt-preview"
            alt="ภาพสลิปสำหรับตรวจสอบ"
            src={
              "/api/workspaces/" +
              wid +
              "/attachments/" +
              proposal.attachment_id
            }
          />
        )}
        <label>
          ประเภทรายการ
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {(proposal === "new"
              ? ["expense", "income", "transfer", "card_payment", "opening"]
              : ["expense", "income"]
            ).map((k) => (
              <option key={k} value={k}>
                {kinds[k]}
              </option>
            ))}
          </select>
        </label>
        <div className="form-grid">
          <label>
            จำนวนเงิน (บาท)
            <input
              name="amount"
              inputMode="decimal"
              defaultValue={
                proposal !== "new" && proposal.amount
                  ? (proposal.amount / 100).toFixed(2)
                  : ""
              }
              onInput={(e) => e.currentTarget.setCustomValidity("")}
              placeholder="0.00"
              required
            />
          </label>
          <label>
            วันที่
            <input
              name="occurred_on"
              type="date"
              defaultValue={proposal !== "new" && proposal.occurred_on ? proposal.occurred_on : today()}
              required
            />
          </label>
        </div>
        <label>
          รายละเอียด
          <input
            name="description"
            required
            maxLength={300}
            defaultValue={proposal === "new" ? "" : proposal.description}
          />
        </label>
        <label>
          {kind === "income"
            ? "บัญชีรับเงิน"
            : kind === "opening"
              ? "บัญชีที่ตั้งยอด"
              : "บัญชีจ่ายเงิน"}
          <select name="account_id" required key={"account-" + kind} defaultValue={proposal !== "new" && proposal.kind===kind ? proposal.account_id||"" : ""}>
            <option value="">เลือกบัญชี</option>
            {wallets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {kinds[a.kind]}
              </option>
            ))}
          </select>
        </label>
        {["expense", "income"].includes(kind) && (
          <label>
            หมวดหมู่
            <select name="category_id" required key={kind} defaultValue={proposal !== "new" && proposal.kind===kind ? proposal.category_id||"" : ""}>
              <option value="">เลือกหมวดหมู่</option>
              {accounts
                .filter((a) => a.kind === kind)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
        )}
        {["transfer", "card_payment"].includes(kind) && (
          <label>
            บัญชีปลายทาง
            <select name="other_account_id" required key={kind}>
              <option value="">เลือกบัญชี</option>
              {accounts
                .filter(
                  (a) =>
                    a.kind === (kind === "transfer" ? "asset" : "liability"),
                )
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
        )}
        {kind === "opening" && (
          <p className="small muted">
            ใช้ได้ครั้งเดียวก่อนมีรายการอื่น ยอดบัตรเครดิตคือหนี้ที่ค้างชำระ
          </p>
        )}
        <div className="dialog-actions">
          <Button type="button" variant="outline" onClick={close}>
            ยกเลิก
          </Button>
          <Button disabled={busy}>
            {busy
              ? "กำลังบันทึก…"
              : proposal === "new"
                ? "บันทึกรายการ"
                : "ยืนยันและบันทึก"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
