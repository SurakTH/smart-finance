"""Opt-in live chat evaluation against a LOCAL development app, synthetic data only.

Requires backend Python dependencies, Pillow, running Compose API/worker and an
explicit Ollama URL. Does not use AI Lab, fallback models or production accounts.
Run with --help. Artifacts contain synthetic public replies and safe diagnostics,
never provider credentials, prompts or private reasoning. No automatic git push.
"""
import argparse
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import secrets
import statistics
import subprocess
import tempfile
import time
from urllib.parse import urlparse
import uuid
from zoneinfo import ZoneInfo
import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://localhost:8080/api')
    parser.add_argument('--ollama-url',required=True,help='Ollama root URL, e.g. http://host:11434')
    parser.add_argument('--model',default='qwen3.5:9b')
    parser.add_argument('--receipt',action='append',nargs=3,metavar=('PATH','PAID_BAHT','DATE'),help='Receipt-only evaluation; repeat for more images. Expected printed date is YYYY-MM-DD. Private image/reply content is not written to artifacts.')
    parser.add_argument('--thinking',choices=['none','default'],default='default')
    parser.add_argument('--extract-thinking',choices=['none','default'],help='Optional receipt Inbox profile override; chat keeps --thinking. Used only with --receipt.')
    parser.add_argument('--focus',choices=['full','tool-repair'],default='full',help='tool-repair runs balance, independently priced batches and explicit category choice only; not a full-suite result.')
    parser.add_argument('--temperature',type=float,default=0.1)
    parser.add_argument('--max-tokens',type=int,default=4096)
    parser.add_argument('--output',type=Path,default=Path(tempfile.gettempdir())/'smart-finance-live-eval.json')
    parser.add_argument('--credentials-file',type=Path,default=Path(tempfile.gettempdir())/'smart-finance-live-eval-user.json')
    args=parser.parse_args()
    if args.receipt:
        from decimal import Decimal
        from datetime import date
        for path,amount,day in args.receipt:
            if not Path(path).is_file():parser.error('Receipt image does not exist')
            try:
                value=Decimal(amount)*100
                if not value.is_finite() or value!=value.to_integral_value() or value<=0:raise ValueError()
                date.fromisoformat(day)
            except Exception:parser.error('Receipt expectations require positive baht with at most two decimals and a valid YYYY-MM-DD date')
    if urlparse(args.base_url).hostname not in ('localhost','127.0.0.1','::1'):
        parser.error('Only a local development app is allowed. Never evaluate against production.')
    if not 0<=args.temperature<=2 or not 128<=args.max_tokens<=131072:parser.error('Invalid sampling limits')
    credentials=args.credentials_file
    if not credentials.exists():
        values={'email':'sf-live-'+uuid.uuid4().hex+'@test.local','password':secrets.token_urlsafe(24)}
        code="import json,sys; from app.bootstrap import create_user; from app.db import SessionLocal; v=json.load(sys.stdin); db=SessionLocal(); create_user(db,v['email'],v['password']); db.commit(); db.close()"
        result=subprocess.run(['docker','compose','exec','-T','api','python','-c',code],input=json.dumps(values),text=True,cwd=ROOT,capture_output=True)
        if result.returncode:raise SystemExit('Could not create local synthetic test user. Check Docker context and the running API.')
        with os.fdopen(os.open(credentials,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as file:json.dump(values,file)
    else:values=json.loads(credentials.read_text())
    today=datetime.now(ZoneInfo('Asia/Bangkok')).date()
    client=httpx.Client(base_url=args.base_url,headers={'X-SF-Request':'1'},timeout=20,trust_env=False)
    def call(method,path,**kwargs):
        response=client.request(method,path,**kwargs)
        if not response.is_success:raise RuntimeError(f'{method} {path}: HTTP {response.status_code}')
        return response.json()
    call('POST','/auth/login',json=values)
    wid=call('POST','/workspaces',json={'name':'Small-model synthetic '+uuid.uuid4().hex[:8]})['id']
    base='/workspaces/'+wid
    accounts=call('GET',base+'/accounts')
    cash=next(a['id'] for a in accounts if a['name']=='เงินสด')
    food=next(a['id'] for a in accounts if a['name']=='อาหารและเครื่องดื่ม')
    travel=next(a['id'] for a in accounts if a['name']=='เดินทาง')
    salary=next(a['id'] for a in accounts if a['kind']=='income')
    bank=call('POST',base+'/accounts',json={'name':'ธนาคารทดสอบ','kind':'asset'})['id']
    last_monday=today-timedelta(days=today.weekday()+7)
    seed=[('opening',1000000,today.replace(day=1),'ยอดตั้งต้นทดสอบ',cash,None),('opening',500000,today.replace(day=1),'ยอดธนาคารตั้งต้น',bank,None),('expense',12000,today-timedelta(days=1),'ข้าวทดสอบ',cash,food),('expense',11500,today-timedelta(days=1),'กาแฟทดสอบ',cash,food),('expense',87600,last_monday+timedelta(days=1),'เดินทางทดสอบ',bank,travel),('expense',10000,today.replace(day=1),'อาหารต้นเดือน',cash,food),('income',200000,today-timedelta(days=2),'รายได้ทดสอบ',bank,salary)]
    for kind,amount,day,description,account,category in seed:
        call('POST',base+'/transactions',json=dict(kind=kind,amount=amount,occurred_on=day.isoformat(),description=description,account_id=account,category_id=category,idempotency_key=str(uuid.uuid4())))
    endpoint=args.ollama_url.rstrip('/').removesuffix('/v1')+'/v1'
    conn=call('POST',base+'/ai/connections',json={'name':'Synthetic live evaluation','kind':'ollama','endpoint':endpoint})
    provider=call('POST',base+'/providers',json=dict(connection_id=conn['id'],kind='ollama',model=args.model,task='chat',name='Synthetic model only',priority=0,timeout_seconds=60,retries=0,max_tokens=args.max_tokens,temperature=round(args.temperature*100),reasoning_effort=args.thinking,supports_images=True))
    call('PUT',base+'/ai/settings',json={'cloud_enabled':False,'demo_fallback':False,'max_attempted_providers':1})
    if args.receipt:
        call('POST',base+'/providers',json=dict(connection_id=conn['id'],kind='ollama',model=args.model,task='extract',name='Synthetic receipt profile',priority=0,timeout_seconds=60,retries=0,max_tokens=args.max_tokens,temperature=round(args.temperature*100),reasoning_effort=args.extract_thinking or args.thinking,supports_images=True))
    results=[];checks=[]
    def save():
        events=[e for r in results for e in r['diagnostics'].get('events',[]) if e['event']=='request']
        times=[r['seconds'] for r in results if r['status']!='direct']
        summary=dict(turns=len(results),passed=sum(c['passed'] for c in checks),checks=len(checks),model_requests=len(events),input_tokens=sum(e.get('input_tokens',0) for e in events),output_tokens=sum(e.get('output_tokens',0) for e in events),estimated_requests=sum(bool(e.get('estimated')) for e in events),median_seconds=round(statistics.median(times),2) if times else None)
        args.output.write_text(json.dumps(dict(model=args.model,thinking=args.thinking,extract_thinking=(args.extract_thinking or args.thinking) if args.receipt else None,focus=args.focus,temperature=args.temperature,workspace_id=wid,provider_id=provider['id'],date=today.isoformat(),summary=summary,checks=checks,results=results),ensure_ascii=False,indent=2))
        args.output.chmod(0o600)
        return summary
    def check(name,passed):checks.append(dict(name=name,passed=bool(passed)));save()
    def room():return call('POST',base+'/conversations',json={'title':'Synthetic live evaluation'})['id']
    def report():return call('GET',base+'/transaction-report')
    def say(cid,text,image=None):
        started=time.monotonic();before=report();path=base+'/conversations/'+cid
        if image:
            response=call('POST',path+'/images',files={'file':('synthetic.png',image,'image/png')},data={'text':text})
        else:response=call('POST',path+'/messages',json={'text':text})
        jid=response.get('job_id');status='direct';diagnostics={}
        while jid:
            job=call('GET',base+'/ai/diagnostics/'+jid);status=job['status']
            if status!='pending':diagnostics=job.get('diagnostics',{});break
            if time.monotonic()-started>125:
                call('POST',path+'/jobs/'+jid+'/stop');status='test_timeout';break
            time.sleep(.25)
        messages=call('GET',path+'/messages');reply=next((m['content'] for m in reversed(messages) if m['role']=='assistant'),'')
        after=report();row=dict(user=text,answer='[private receipt reply omitted]' if args.receipt else reply,status=status,seconds=round(time.monotonic()-started,2),before=before['total'],after=after['total'],diagnostics=diagnostics)
        results.append(row);save()
        print(json.dumps({k:row[k] for k in ('user','answer','seconds','status')},ensure_ascii=False),flush=True)
        if text not in ('ยืนยัน',):check('no automatic ledger posting: '+text,before['total']==after['total'])
        check('no runtime error: '+text,status in ('done','direct') and bool(reply) and 'API ' not in reply)
        return reply
    def has_money(text,satang):
        # Require a complete amount, not 235 matching an account/reference ID.
        import re
        amount=f'{satang/100:,.2f}'
        variants={amount,amount.replace(',','')}
        if satang%100==0:variants|={str(satang//100),f'{satang//100:,}'}
        return any(re.search(r'(?<![\d.,])'+re.escape(v)+r'(?![\d.,])',text) for v in variants)
    if args.receipt:
        from decimal import Decimal
        for filename,amount,day in args.receipt:
            expected=int(Decimal(amount)*100);data=Path(filename).read_bytes();label=Path(filename).name
            before=report()['total']
            cid=room();reply=say(cid,'ค่าใช้จ่าย จ่ายเงินสด ช่วยจดให้หน่อย',data)
            if 'จัดเข้าหมวดไหน' in reply:
                check('receipt options: '+label,'อื่น ๆ' in reply)
                reply=say(cid,'อื่น ๆ')
            check('chat review: '+label,'กรุณาตรวจสอบ' in reply and has_money(reply,expected) and day in reply)
            started=time.monotonic()
            upload=call('POST',base+'/attachments',files={'file':('private-receipt.jpg',data,'image/jpeg')},data={'text':'ค่าใช้จ่าย'})
            diagnostics={};status='direct'
            if upload.get('job_id'):
                while True:
                    job=call('GET',base+'/ai/diagnostics/'+upload['job_id']);status=job['status']
                    if status!='pending':diagnostics=job.get('diagnostics',{});break
                    if time.monotonic()-started>125:raise RuntimeError('Receipt evaluation timed out')
                    time.sleep(.25)
            proposal=next((p for p in call('GET',base+'/proposals') if p.get('attachment_id')==upload['id']),None)
            check('inbox paid/date: '+label,proposal is not None and proposal['amount']==expected and proposal.get('occurred_on')==day)
            check('no receipt auto-post: '+label,report()['total']==before)
            results.append(dict(user='Inbox receipt upload',answer='[private receipt details omitted]',status=status,seconds=round(time.monotonic()-started,2),before=before,after=report()['total'],diagnostics=diagnostics))
            save()
        print(json.dumps(save(),ensure_ascii=False),flush=True)
        client.close()
        raise SystemExit(0 if all(c['passed'] for c in checks) else 1)
    if args.focus=='tool-repair':
        check('current balances',has_money(say(room(),'ตอนนี้ฉันมีเงินเท่าไร'),1578900))
        for text,prices in [('จดข้าว 55 บาท กับน้ำ 20 บาท จ่ายเงินสดวันนี้',(5500,2000)),('จ่ายเงินสด ซื้อกาแฟ 42 บาท ขนม 18 บาท ช่วยลงแยกกันให้ที',(4200,1800))]:
            cid=room();reply=say(cid,text)
            ready=all(has_money(reply,p) for p in prices) and '2 รายการ' in reply
            check('separate batch: '+text,ready)
            if ready:
                before=report();say(cid,'ยืนยัน');after=report()
                check('confirmed batch: '+text,after['total']==before['total']+2 and after['expense']==before['expense']+sum(prices))
                say(cid,'ยืนยัน');check('batch replay: '+text,report()['total']==after['total'])
            else:say(cid,'ยกเลิก')
        cid=room();reply=say(cid,'ช่วยจดค่ากาแฟ75บาทจากเงินสด หมวดฉันเลือกเอง')
        check('explicit category choice respected','จัดเข้าหมวดไหน' in reply and 'อาหารและเครื่องดื่ม' in reply)
        reply=say(cid,'อาหารและเครื่องดื่ม')
        check('category answer retains price',has_money(reply,7500) and 'หมวด: อาหารและเครื่องดื่ม' in reply and 'กรุณาตรวจสอบ' in reply)
        say(cid,'ยกเลิก')
        print(json.dumps(save(),ensure_ascii=False),flush=True);client.close()
        raise SystemExit(0 if all(c['passed'] for c in checks) else 1)
    check('friendly general conversation','สวัสดี' in say(room(),'สวัสดี ช่วยอะไรฉันได้บ้าง'))
    check('current balances',has_money(say(room(),'ตอนนี้ฉันมีเงินเท่าไร'),1578900))
    yesterday=sum(s[1] for s in seed if s[0]=='expense' and s[2]==today-timedelta(days=1))
    weekly=sum(s[1] for s in seed if s[0]=='expense' and last_monday<=s[2]<=last_monday+timedelta(days=6))
    monthly=sum(s[1] for s in seed if s[0]=='expense' and today.replace(day=1)<=s[2]<=today)
    check('yesterday items and total',has_money(say(room(),'เมื่อวานเสียตังกับไรบ้าง'),yesterday))
    check('last week total',has_money(say(room(),'สัปดาห์ที่แล้วใช้ไปเท่าไหร่'),weekly))
    check('this month total',has_money(say(room(),'เดือนนี้ละ ใช้ตังเท่าไหร่'),monthly))
    cid=room();say(cid,'สัปดาห์ที่แล้วใช้ไปเท่าไหร่')
    check('short date followup',has_money(say(cid,'แล้วเมื่อวานละ'),yesterday))
    check('short account followup',has_money(say(cid,'แยกตามบัญชีให้หน่อย'),yesterday))
    month_wallets={aid:sum(s[1] for s in seed if s[0]=='expense' and s[4]==aid and today.replace(day=1)<=s[2]<=today) for aid in (cash,bank)}
    top=max(month_wallets,key=month_wallets.get);top_name='เงินสด' if top==cash else 'ธนาคารทดสอบ'
    reply=say(room(),'เดือนนี้บัญชีไหนใช้เงินเยอะที่สุด')
    check('rank by account with bound amount',top_name in reply and has_money(reply,month_wallets[top]))
    cid=room();reply=say(cid,'เมื่อกี้ซื้อกาแฟ 80 บาท จ่ายเงินสด ช่วยจดให้หน่อย')
    check('real draft', 'กรุณาตรวจสอบ' in reply and has_money(reply,8000))
    reply=say(cid,'เอาเป็น 85 บาทนะ');check('draft correction',has_money(reply,8500) and 'กรุณาตรวจสอบ' in reply)
    before=report();say(cid,'ยืนยัน');after=report()
    check('one confirmed entry',after['total']==before['total']+1 and after['expense']==before['expense']+8500)
    say(cid,'ยืนยัน');check('confirmation replay',report()['total']==after['total'])
    cid=room();reply=say(cid,'กินข้าวเมื่อกี้ ช่วยจดหน่อย');check('missing amount question','ยอดเท่าไหร่' in reply)
    reply=say(cid,'70 บาท จ่ายเงินสด');check('partial draft continued',has_money(reply,7000) and 'กรุณาตรวจสอบ' in reply)
    say(cid,'ยกเลิก')
    reply=say(room(),'จ่ายค่าซักรีด60บาทจากเงินสด จดให้หน่อย')
    check('clear service description suggests existing category',has_money(reply,6000) and 'กรุณาตรวจสอบ' in reply and 'หมวด: อื่น ๆ' in reply)
    # The typo is deliberately ambiguous. A genuine scoped clarification is
    # allowed by the product contract, but must still complete without a loop.
    cid=room();reply=say(cid,'ค่ารัดผ้า 60 บาท จ่ายเงินสด ช่วยจดให้หน่อย')
    check('ambiguous description reviewed or asks available category',('กรุณาตรวจสอบ' in reply and has_money(reply,6000)) or ('จัดเข้าหมวดไหน' in reply and 'อื่น ๆ' in reply))
    if 'จัดเข้าหมวดไหน' in reply:reply=say(cid,'อื่น ๆ')
    check('ambiguous description completes after choice',has_money(reply,6000) and 'กรุณาตรวจสอบ' in reply)
    say(cid,'ยกเลิก')
    cid=room();reply=say(cid,'จดข้าว 55 บาท กับน้ำ 20 บาท จ่ายเงินสดวันนี้')
    batch_ok=has_money(reply,5500) and has_money(reply,2000) and '2 รายการ' in reply
    check('separate batch items',batch_ok)
    if batch_ok:
        before=report();say(cid,'ยืนยัน');after=report()
        check('atomic confirmed batch',after['total']==before['total']+2 and after['expense']==before['expense']+7500)
        say(cid,'ยืนยัน');check('batch confirmation replay',report()['total']==after['total'])
    else:say(cid,'ยกเลิก')
    from PIL import Image,ImageDraw,ImageFont
    import io
    image=Image.new('RGB',(900,600),'white');draw=ImageDraw.Draw(image)
    draw.multiline_text((50,50),'SYNTHETIC TEST RECEIPT\nPAYMENT SUCCESS\n'+today.isoformat()+'\nBOOK STORE\nTOTAL THB 125.00\nNOT A REAL BANK RECEIPT',font=ImageFont.load_default(size=36),fill='black',spacing=20)
    raw=io.BytesIO();image.save(raw,format='PNG');cid=room()
    reply=say(cid,'ค่าหนังสือ จ่ายเงินสด ช่วยจดให้หน่อย',raw.getvalue())
    # This seeded workspace has food/travel/other, not a books category. The
    # receipt-reading assertion must not require a forced classification. If
    # the model legitimately asks, answer the actual missing field before
    # testing a later kind/category correction.
    if 'จัดเข้าหมวดไหน' in reply:
        check('receipt clarification lists scoped choices','อื่น ๆ' in reply)
        reply=say(cid,'อื่น ๆ')
    check('vision amount, caption and provenance',has_money(reply,12500) and 'ค่าหนังสือ' in reply and 'หลักฐาน:' in reply and 'กรุณาตรวจสอบ' in reply)
    reply=say(cid,'รายจ่ายนะ');check('receipt followup preserves amount and image',has_money(reply,12500) and 'หลักฐาน:' in reply and 'กรุณาตรวจสอบ' in reply)
    reply=say(cid,'เปลี่ยนหมวดเป็นเดินทาง')
    check('receipt category correction retains source',has_money(reply,12500) and 'หมวด: เดินทาง' in reply and 'หลักฐาน:' in reply and 'กรุณาตรวจสอบ' in reply)
    before=report();say(cid,'ยืนยัน');after=report()
    check('confirmed corrected receipt',after['total']==before['total']+1 and after['expense']==before['expense']+12500)
    cid=room();reply=say(cid,'ช่วยจดค่ากาแฟ75บาทจากเงินสด หมวดฉันเลือกเอง')
    check('explicit category choice respected','จัดเข้าหมวดไหน' in reply and 'อาหารและเครื่องดื่ม' in reply)
    reply=say(cid,'อาหารและเครื่องดื่ม')
    check('exact category fills current draft',has_money(reply,7500) and 'หมวด: อาหารและเครื่องดื่ม' in reply and 'กรุณาตรวจสอบ' in reply)
    say(cid,'ยกเลิก')
    summary=save();print(json.dumps(summary,ensure_ascii=False),flush=True)
    client.close()
    raise SystemExit(0 if all(c['passed'] for c in checks) else 1)


if __name__=='__main__':main()
