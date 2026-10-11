"""Optional isolated demo workspace. Credentials are read from stdin, never printed."""
import json
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .bootstrap import create_user
from .db import SessionLocal
from .models import User, Account, Membership
from .ledger import post
from .schemas import TransactionInput

if __name__=='__main__':
    values=json.load(sys.stdin)
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email==values['email'])):
            raise SystemExit('Demo already exists; refusing to overwrite credentials')
        user=create_user(db,values['email'],values['password'])
        wid=db.scalar(select(Membership.workspace_id).where(Membership.user_id==user.id))
        accounts=db.scalars(select(Account).where(Account.workspace_id==wid)).all()
        cash=next(a.id for a in accounts if a.kind=='asset')
        salary=next(a.id for a in accounts if a.kind=='income')
        food=next(a.id for a in accounts if a.name=='อาหารและเครื่องดื่ม')
        travel=next(a.id for a in accounts if a.name=='เดินทาง')
        bank=Account(workspace_id=wid,name='KBank',kind='asset');db.add(bank);db.flush()
        card=Account(workspace_id=wid,name='บัตรเครดิต',kind='liability');db.add(card);db.flush()
        month=datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m')
        rows=[('opening',cash,500000,None,None,'ยอดเงินสดตั้งต้น',1),('opening',bank.id,1250000,None,None,'ยอดบัญชีตั้งต้น',1),('income',bank.id,3500000,salary,None,'เงินเดือน',2),('transfer',bank.id,200000,None,cash,'เติมเงินสด',3),('expense',cash,18500,food,None,'มื้อกลางวัน',4),('expense',bank.id,120000,travel,None,'ค่าเดินทางประจำเดือน',5),('expense',card.id,245000,food,None,'ทานข้าวกับครอบครัว',6),('card_payment',bank.id,100000,None,card.id,'ชำระบัตรบางส่วน',7),('expense',cash,6500,food,None,'กาแฟเช้านี้',8)]
        for kind,account,amount,category,other,desc,day in rows:
            post(db,wid,user.id,TransactionInput(kind=kind,account_id=account,amount=amount,category_id=category,other_account_id=other,description=desc,occurred_on=f'{month}-{day:02}',idempotency_key=uuid.uuid4()))
    print('Created isolated demo user and sample ledger.')
