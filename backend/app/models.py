import time
import uuid
from sqlalchemy import String, Integer, BigInteger, Text, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, LargeBinary, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def uid(): return str(uuid.uuid4())
def now(): return int(time.time())

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    email_verified_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

class EmailToken(Base):
    __tablename__ = 'email_tokens'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    purpose: Mapped[str] = mapped_column(String(12))
    expires: Mapped[int] = mapped_column(BigInteger)
    used: Mapped[bool] = mapped_column(default=False)
    # Durable encrypted outbox: raw tokens never enter database columns or logs.
    delivery: Mapped[str] = mapped_column(String(12), default='pending')
    encrypted_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[int] = mapped_column(BigInteger, default=now)
    __table_args__ = (CheckConstraint("purpose IN ('reset','verify')"), CheckConstraint("delivery IN ('pending','sent','failed','cancelled')"))

class Workspace(Base):
    __tablename__ = 'workspaces'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    archived_at: Mapped[int|None] = mapped_column(BigInteger,nullable=True)
    version: Mapped[int] = mapped_column(Integer,default=1,server_default='1')

class Membership(Base):
    __tablename__ = 'memberships'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), default='owner')
    __table_args__ = (CheckConstraint("role IN ('owner','member')"),)

class Session(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[int] = mapped_column(BigInteger)

class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(12))
    __table_args__ = (UniqueConstraint('id','workspace_id'), CheckConstraint("kind IN ('asset','liability','income','expense','equity')"))

class Entry(Base):
    __tablename__ = 'entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(300))
    amount: Mapped[int] = mapped_column(BigInteger)
    occurred_on: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[int] = mapped_column(BigInteger, default=now)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    __table_args__ = (UniqueConstraint('id','workspace_id'), UniqueConstraint('workspace_id','idempotency_key'), CheckConstraint('amount > 0'), CheckConstraint("kind IN ('opening','income','expense','transfer','card_payment')"))

class Line(Base):
    __tablename__ = 'lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    entry_id: Mapped[str] = mapped_column(String(36))
    account_id: Mapped[str] = mapped_column(String(36))
    signed_amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (ForeignKeyConstraint(['entry_id','workspace_id'], ['entries.id','entries.workspace_id']), ForeignKeyConstraint(['account_id','workspace_id'], ['accounts.id','accounts.workspace_id']), CheckConstraint('signed_amount != 0'))

class Proposal(Base):
    __tablename__ = 'proposals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    source: Mapped[str] = mapped_column(String(20), default='web')
    description: Mapped[str] = mapped_column(String(300))
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default='expense')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now)
    __table_args__ = (UniqueConstraint('id','workspace_id'),ForeignKeyConstraint(['entry_id','workspace_id'], ['entries.id','entries.workspace_id']), ForeignKeyConstraint(['attachment_id','workspace_id'], ['attachments.id','attachments.workspace_id'],name='fk_proposal_attachment_workspace'))

class Attachment(Base):
    __tablename__ = 'attachments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    __table_args__ = (UniqueConstraint('id','workspace_id'), UniqueConstraint('workspace_id','digest'))

class ChatPreference(Base):
    __tablename__='chat_preferences'
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
    workspace_id: Mapped[str]=mapped_column(ForeignKey('workspaces.id'),primary_key=True)
    retention_days: Mapped[int]=mapped_column(Integer,default=0)
    __table_args__=(CheckConstraint('retention_days IN (0,7,30,90)'),)

class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    capture_context: Mapped[dict | None] = mapped_column(JSON,nullable=True)
    title: Mapped[str] = mapped_column(String(100), default='บทสนทนาใหม่')
    temporary: Mapped[int] = mapped_column(Integer,default=0)
    created_at: Mapped[int] = mapped_column(BigInteger,default=now)
    updated_at: Mapped[int] = mapped_column(BigInteger,default=now)
    privacy: Mapped[str] = mapped_column(String(15), default='private')
    __table_args__ = (UniqueConstraint('id','workspace_id'), CheckConstraint("privacy IN ('private','standard')"),CheckConstraint('temporary IN (0,1)',name='ck_conversation_temporary'))

class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(15))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: time.time_ns()//1_000_000)
    attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (ForeignKeyConstraint(['conversation_id','workspace_id'], ['conversations.id','conversations.workspace_id']), ForeignKeyConstraint(['attachment_id','workspace_id'], ['attachments.id','attachments.workspace_id'], name='fk_message_attachment_workspace'))

class AISettings(Base):
    __tablename__ = 'ai_settings'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    cloud_enabled: Mapped[bool] = mapped_column(default=False)
    demo_fallback: Mapped[bool] = mapped_column(default=True)
    max_attempted_providers: Mapped[int] = mapped_column(Integer, default=3)

class Provider(Base):
    __tablename__ = 'providers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    task: Mapped[str] = mapped_column(String(15))
    priority: Mapped[int] = mapped_column(Integer, default=10)
    encrypted_key: Mapped[str] = mapped_column(Text, default='')
    name: Mapped[str] = mapped_column(String(100), default='', server_default='')
    endpoint: Mapped[str] = mapped_column(String(500), default='', server_default='')
    enabled: Mapped[bool] = mapped_column(default=True, server_default='true')
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=20, server_default='20')
    retries: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    max_tokens: Mapped[int] = mapped_column(Integer, default=1200, server_default='1200')
    temperature: Mapped[int] = mapped_column(Integer, default=10, server_default='10')
    reasoning_effort: Mapped[str] = mapped_column(String(12), default='default', server_default='default')
    supports_images: Mapped[bool] = mapped_column(default=False, server_default='false')


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    task: Mapped[str] = mapped_column(String(15))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(15), default='pending', index=True)
    error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: time.time_ns()//1_000_000)

class TelegramLink(Base):
    __tablename__ = 'telegram_links'
    telegram_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))

class LinkCode(Base):
    __tablename__ = 'link_codes'
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[int] = mapped_column(BigInteger)

class Budget(Base):
    __tablename__ = 'budgets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    category_id: Mapped[str] = mapped_column(String(36))
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        ForeignKeyConstraint(['category_id','workspace_id'], ['accounts.id','accounts.workspace_id'], name='fk_budget_category_workspace'),
        UniqueConstraint('workspace_id','month','category_id', name='uq_budget_month_category'),
        CheckConstraint('amount > 0 AND amount <= 100000000000', name='ck_budget_amount'),
    )

class EntryRevision(Base):
    __tablename__ = 'entry_revisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    original_id: Mapped[str] = mapped_column(String(36), unique=True)
    reversal_id: Mapped[str] = mapped_column(String(36), unique=True)
    replacement_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    reason: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: time.time_ns()//1_000_000)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        ForeignKeyConstraint(['original_id','workspace_id'], ['entries.id','entries.workspace_id']),
        ForeignKeyConstraint(['reversal_id','workspace_id'], ['entries.id','entries.workspace_id']),
        ForeignKeyConstraint(['replacement_id','workspace_id'], ['entries.id','entries.workspace_id']),
        UniqueConstraint('workspace_id','idempotency_key'),
        CheckConstraint('original_id != reversal_id AND (replacement_id IS NULL OR (replacement_id != original_id AND replacement_id != reversal_id))'),
    )

class Goal(Base):
    __tablename__ = 'goals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    target: Mapped[int] = mapped_column(BigInteger)
    due_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    archived: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('id','workspace_id'),UniqueConstraint('workspace_id','idempotency_key'),
        CheckConstraint('target > 0 AND target <= 100000000000'),CheckConstraint('archived IN (0,1)'),CheckConstraint('version > 0'))

class GoalMovement(Base):
    __tablename__ = 'goal_movements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    goal_id: Mapped[str] = mapped_column(String(36))
    signed_amount: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(String(300))
    occurred_on: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[int] = mapped_column(BigInteger, default=lambda: time.time_ns()//1_000_000)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    __table_args__ = (ForeignKeyConstraint(['goal_id','workspace_id'],['goals.id','goals.workspace_id']),
        UniqueConstraint('workspace_id','idempotency_key'),CheckConstraint('signed_amount != 0 AND signed_amount BETWEEN -100000000000 AND 100000000000'))


class RecurringRule(Base):
    __tablename__ = 'recurring_rules'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'),index=True)
    description: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[str] = mapped_column(String(36))
    category_id: Mapped[str] = mapped_column(String(36))
    frequency: Mapped[str] = mapped_column(String(10))
    start_on: Mapped[str] = mapped_column(String(10))
    next_on: Mapped[str] = mapped_column(String(10))
    end_on: Mapped[str | None] = mapped_column(String(10),nullable=True)
    paused: Mapped[int] = mapped_column(Integer,default=0)
    version: Mapped[int] = mapped_column(Integer,default=1)
    checked_at: Mapped[int] = mapped_column(BigInteger,default=0)
    created_at: Mapped[int] = mapped_column(BigInteger,default=now)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('id','workspace_id'),UniqueConstraint('workspace_id','idempotency_key'),
        ForeignKeyConstraint(['account_id','workspace_id'],['accounts.id','accounts.workspace_id']),
        ForeignKeyConstraint(['category_id','workspace_id'],['accounts.id','accounts.workspace_id']),
        CheckConstraint("kind IN ('income','expense')"),CheckConstraint("frequency IN ('daily','weekly','monthly')"),
        CheckConstraint('amount > 0 AND amount <= 100000000000'),CheckConstraint('paused IN (0,1)'),CheckConstraint('version > 0'))

class RecurringOccurrence(Base):
    __tablename__ = 'recurring_occurrences'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'),index=True)
    rule_id: Mapped[str] = mapped_column(String(36))
    proposal_id: Mapped[str] = mapped_column(String(36),unique=True)
    scheduled_on: Mapped[str] = mapped_column(String(10))
    account_id: Mapped[str] = mapped_column(String(36))
    category_id: Mapped[str] = mapped_column(String(36))
    __table_args__ = (UniqueConstraint('rule_id','scheduled_on'),
        ForeignKeyConstraint(['rule_id','workspace_id'],['recurring_rules.id','recurring_rules.workspace_id']),
        ForeignKeyConstraint(['proposal_id','workspace_id'],['proposals.id','proposals.workspace_id']),
        ForeignKeyConstraint(['account_id','workspace_id'],['accounts.id','accounts.workspace_id']),
        ForeignKeyConstraint(['category_id','workspace_id'],['accounts.id','accounts.workspace_id']))


class Invitation(Base):
    mode: Mapped[str]=mapped_column(String(10),default='shared',server_default='shared')
    __tablename__ = 'invitations'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'),index=True)
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64),unique=True)
    status: Mapped[str] = mapped_column(String(12),default='pending')
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    accepted_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger,default=now)
    expires: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint('id','workspace_id'),CheckConstraint("status IN ('pending','accepted','revoked')"))

class MembershipEvent(Base):
    __tablename__ = 'membership_events'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'),index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    target_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'),nullable=True)
    email: Mapped[str] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(25))
    previous_role: Mapped[str | None] = mapped_column(String(10),nullable=True)
    next_role: Mapped[str | None] = mapped_column(String(10),nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger,default=lambda:time.time_ns()//1_000_000)
    __table_args__ = (CheckConstraint("action IN ('invited','invite_revoked','joined','role_changed','removed','left')"),)

class ChatAction(Base):
    __tablename__='chat_actions'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    workspace_id: Mapped[str]=mapped_column(String(36),index=True)
    conversation_id: Mapped[str]=mapped_column(String(36))
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    code: Mapped[str]=mapped_column(String(8))
    payload: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    expires: Mapped[int]=mapped_column(BigInteger)
    created_at: Mapped[int]=mapped_column(BigInteger,default=now)
    entry_id: Mapped[str|None]=mapped_column(String(36),nullable=True)
    __table_args__=(
        ForeignKeyConstraint(['conversation_id','workspace_id'],['conversations.id','conversations.workspace_id']),
        ForeignKeyConstraint(['entry_id','workspace_id'],['entries.id','entries.workspace_id']),
        UniqueConstraint('conversation_id','code'),
        CheckConstraint("status IN ('pending','confirmed','cancelled','superseded','expired','conflict')"),
    )

def message_time(db,wid,cid):
    # Millisecond timestamps can tie within synchronous review/confirm responses.
    # Serialize the visible order under the caller's workspace lock.
    from sqlalchemy import select,func
    latest=db.scalar(select(func.max(Message.created_at)).where(Message.workspace_id==wid,Message.conversation_id==cid)) or 0
    return max(time.time_ns()//1_000_000,latest+1)


class AssistantChange(Base):
    __tablename__='assistant_changes'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    workspace_id: Mapped[str]=mapped_column(ForeignKey('workspaces.id'),index=True)
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    action_id: Mapped[str]=mapped_column(String(36),unique=True)
    summary: Mapped[str]=mapped_column(String(12000))
    payload: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[int]=mapped_column(BigInteger,default=now)
