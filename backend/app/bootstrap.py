import getpass
from sqlalchemy import select
from .db import SessionLocal
from .models import User
from .security import hasher
from .ledger import initialize_workspace

def create_user(db, email, password):
    email = email.strip().lower()
    if '@' not in email or len(email) > 254: raise ValueError('Invalid email')
    if len(password) < 12 or len(password) > 200: raise ValueError('Password must contain 12–200 characters')
    if db.scalar(select(User).where(User.email == email)): raise ValueError('User exists')
    user = User(email=email, password=hasher.hash(password))
    db.add(user); db.flush()
    initialize_workspace(db, user.id, 'การเงินส่วนตัว')
    return user

if __name__ == '__main__':
    email = input('Email: ')
    password = getpass.getpass('Password (12+ characters): ')
    with SessionLocal.begin() as db:
        create_user(db, email, password)
    print('User created. You can sign in now.')
