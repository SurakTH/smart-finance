from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator

class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)

class Named(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class AccountInput(Named):
    kind: Literal['asset','liability','income','expense']

class TransactionInput(BaseModel):
    kind: Literal['opening','income','expense','transfer','card_payment']
    account_id: str
    other_account_id: str | None = None
    category_id: str | None = None
    amount: int = Field(strict=True, gt=0, le=100_000_000_000)
    description: str = Field(min_length=1, max_length=300)
    occurred_on: date
    idempotency_key: UUID

class ChatInput(BaseModel):
    review_message_id: UUID | None = None
    text: str = Field(min_length=1, max_length=4000)

class CaptureInput(ChatInput):
    # Omitted follows current workspace routes; explicit legacy clients remain supported.
    privacy: Literal['private','standard'] | None = None

class ChatRetentionInput(BaseModel):
    retention_days: Literal[0,7,30,90]

class ConversationInput(BaseModel):
    temporary: bool = Field(default=False,strict=True)
    title: str = Field(default='บทสนทนาใหม่', min_length=1, max_length=100)
    privacy: Literal['private','standard'] = Field(default='private',description='Legacy metadata only; Web Chat follows workspace AI settings and routes.')

class ProposalInput(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    amount: int | None = Field(default=None, strict=True, gt=0, le=100_000_000_000)
    kind: Literal['income','expense'] = 'expense'

class ProviderInput(BaseModel):
    kind: Literal['gemini','openrouter','groq','openai','compatible','ollama']
    model: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_./:@-]+$')
    task: Literal['chat','extract']
    priority: int = Field(default=10, ge=0, le=100)
    api_key: str = Field(default='', max_length=500)
    clear_key: bool = False
    name: str = Field(default='', max_length=100)
    endpoint: str = Field(default='', max_length=500)
    enabled: bool = True
    timeout_seconds: int = Field(default=20, ge=5, le=60)
    retries: int = Field(default=1, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=0, le=2_147_483_647, strict=True)
    temperature: int = Field(default=10, ge=0, le=200)
    reasoning_effort: Literal['default','none','minimal','low','medium','high','xhigh'] = 'default'
    supports_images: bool = False

    @field_validator('max_tokens')
    @classmethod
    def output_budget(cls,value):
        if 0 < value < 64:raise ValueError('Use model default or at least64 tokens')
        return value

class AISettingsInput(BaseModel):
    cloud_enabled: bool = False
    demo_fallback: bool = True
    max_attempted_providers: int = Field(default=3, ge=1, le=5)

class AIRoutesInput(BaseModel):
    task: Literal['chat','extract']
    provider_ids: list[str] = Field(max_length=30)


class BudgetInput(BaseModel):
    amount: int = Field(strict=True, gt=0, le=100_000_000_000)

class RevisionInput(BaseModel):
    reason: str = Field(min_length=1, max_length=300)
    idempotency_key: UUID
    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip(): raise ValueError('กรุณาระบุเหตุผล')
        return value.strip()

class CorrectionInput(RevisionInput):
    transaction: TransactionInput

class GoalInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    target: int = Field(strict=True,gt=0,le=100_000_000_000)
    due_on: date | None = None
    @field_validator('name')
    @classmethod
    def goal_name(cls,value):
        if not value.strip(): raise ValueError('กรุณาระบุชื่อเป้าหมาย')
        return value.strip()

class GoalCreate(GoalInput):
    idempotency_key: UUID

class GoalEdit(GoalInput):
    version: int = Field(strict=True,ge=1)

class GoalArchive(BaseModel):
    archived: bool = Field(strict=True)
    version: int = Field(strict=True,ge=1)

class GoalAllocation(BaseModel):
    kind: Literal['add','remove']
    amount: int = Field(strict=True,gt=0,le=100_000_000_000)
    note: str = Field(min_length=1,max_length=300)
    occurred_on: date
    idempotency_key: UUID
    @field_validator('note')
    @classmethod
    def allocation_note(cls,value):
        if not value.strip(): raise ValueError('กรุณาระบุรายละเอียด')
        return value.strip()


class RecurringDetails(BaseModel):
    description: str = Field(min_length=1,max_length=300)
    kind: Literal['income','expense']
    amount: int = Field(strict=True,gt=0,le=100_000_000_000)
    account_id: UUID
    category_id: UUID
    @field_validator('description')
    @classmethod
    def recurring_description(cls,value):
        if not value.strip():raise ValueError('กรุณาระบุรายละเอียด')
        return value.strip()

class RecurringCreate(RecurringDetails):
    frequency: Literal['daily','weekly','monthly']
    start_on: date
    end_on: date | None = None
    idempotency_key: UUID

class RecurringEdit(RecurringDetails):
    version: int = Field(strict=True,ge=1)

class RecurringPause(BaseModel):
    paused: bool = Field(strict=True)
    version: int = Field(strict=True,ge=1)


class InviteEmail(BaseModel):
    email: str = Field(min_length=3,max_length=254)
    @field_validator('email')
    @classmethod
    def invitation_email(cls,value):
        import re
        value=value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):raise ValueError('กรุณาระบุอีเมลให้ถูกต้อง')
        return value

class InviteToken(BaseModel):
    token: str = Field(min_length=40,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')

class InvitePreview(InviteEmail,InviteToken):pass

class InviteRegister(InvitePreview):
    password: str = Field(min_length=12,max_length=200)

class MemberRole(BaseModel):
    role: Literal['owner','member']


class ChatSearchInput(BaseModel):
    q: str = Field(default='',max_length=100)
    page: int = Field(default=1,ge=1,le=10000,strict=True)

class ChatRenameInput(BaseModel):
    title: str = Field(min_length=1,max_length=100)
    @field_validator('title')
    @classmethod
    def clean_title(cls,v):
        v=v.strip()
        if not v:raise ValueError('Title cannot be blank')
        return v


class ProfileInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('กรุณาระบุชื่อที่ไม่มีอักขระควบคุม')
        return value

class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1,max_length=200)
    new_password: str = Field(min_length=12,max_length=200)
    confirm_password: str = Field(min_length=12,max_length=200)
    @field_validator('new_password')
    @classmethod
    def nonblank_password(cls,value):
        if not value.strip(): raise ValueError('รหัสผ่านต้องไม่เป็นช่องว่างทั้งหมด')
        return value

class WorkspaceRename(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    version: int = Field(strict=True,ge=1)
    @field_validator('name')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if not value:raise ValueError('กรุณาระบุชื่อพื้นที่')
        return value

class WorkspaceConfirm(BaseModel):
    version: int = Field(strict=True,ge=1)
    confirm_name: str = Field(min_length=1,max_length=100)

class WorkspaceArchive(WorkspaceConfirm):
    archived: bool = Field(strict=True)


class PublicRegister(InviteEmail):
    name: str = Field(default='',max_length=100)
    password: str = Field(min_length=12,max_length=200)
    confirm_password: str = Field(min_length=12,max_length=200)
    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        return value.strip()
