import enum
from datetime import datetime
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Boolean, Enum as SQLEnum, ARRAY
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from .database import Base

# ── Enums ──────────────────────────────────────────────────────────────────

class UserRole(enum.Enum):
    admin = "admin"
    manager = "manager"
    developer = "developer"
    tester = "tester"

class ProjectType(enum.Enum):
    software = "software"
    marketing = "marketing"
    research = "research"
    other = "other"

class Priority(enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"

class TicketType(enum.Enum):
    bug = "bug"
    feature = "feature"
    task = "task"
    story = "story"

class ActivityType(enum.Enum):
    created = "created"
    updated = "updated"
    commented = "commented"
    status_changed = "status_changed"
    priority_changed = "priority_changed"
    assigned = "assigned"
    attachment_added = "attachment_added"

class TimeUnit(enum.Enum):
    minutes = "minutes"
    hours = "hours"
    days = "days"

class MemberRole(enum.Enum):
    admin = "admin"
    member = "member"
    viewer = "viewer"

# ── Models ──────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.developer)
    is_active = Column(Boolean, default=True)
    
    # Agent/API specific
    agent_db_api_key_hash = Column(String, nullable=True)
    agent_db_api_key_encrypted = Column(Text, nullable=True)
    agent_db_api_key_enabled = Column(Boolean, default=False)
    agent_db_api_key_mode = Column(String, default="read_only")
    agent_db_api_key_created_at = Column(DateTime, nullable=True)
    agent_db_api_key_last_used_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    contact_person = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    company = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SLA(Base):
    __tablename__ = "slas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(SQLEnum(Priority), default=Priority.medium)
    response_time = Column(Integer, nullable=False)
    resolution_time = Column(Integer, nullable=False)
    time_unit = Column(SQLEnum(TimeUnit), default=TimeUnit.hours)
    business_hours = Column(JSONB, nullable=False)
    working_days = Column(ARRAY(Integer), default=[1, 2, 3, 4, 5])
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active")
    category = Column(String(100), nullable=False)
    type = Column(SQLEnum(ProjectType), default=ProjectType.software)
    priority = Column(SQLEnum(Priority), default=Priority.medium)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    settings = Column(JSONB, default={})

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_number = Column(String(100), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(50), default="todo")
    priority = Column(SQLEnum(Priority), default=Priority.medium)
    type = Column(SQLEnum(TicketType), default=TicketType.task)
    
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    reporter_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assignee_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True)
    sla_id = Column(UUID(as_uuid=True), ForeignKey("slas.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    story_points = Column(Integer, nullable=True)
    due_date = Column(DateTime, nullable=True)
    labels = Column(ARRAY(String), default=[])
    paused_time = Column(DateTime, nullable=True)
    total_paused_time = Column(Integer, default=0)
    reason_for_delay = Column(Text, nullable=True)
    branch = Column(String, nullable=True)
    on_site_support_required = Column(Boolean, default=False)
    resolved_methods = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Comment(Base):
    __tablename__ = "comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content = Column(Text, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Activity(Base):
    __tablename__ = "activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(SQLEnum(ActivityType), nullable=False)
    field = Column(String(100), nullable=True)
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=True)
    description = Column(Text, nullable=True)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role = Column(SQLEnum(MemberRole), default=MemberRole.member)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class TicketWatcher(Base):
    __tablename__ = "ticket_watchers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id = Column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    path = Column(Text, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

class CommentAttachment(Base):
    __tablename__ = "comment_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comment_id = Column(UUID(as_uuid=True), ForeignKey("comments.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size = Column(Integer, nullable=False)
    path = Column(Text, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    permissions = Column(JSONB, nullable=False, default=[])
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Analytics Specific Tables ──────────────────────────────────────────────

class TicketAnalytics(Base):
    __tablename__ = "ticket_analytics"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String, unique=True, index=True, nullable=False)

    # Analysis fields
    category = Column(String, nullable=True)
    priority = Column(String, nullable=True)           # CRITICAL / HIGH / MEDIUM / LOW
    resolution_summary = Column(Text, nullable=True)   # AI-generated summary
    resolved_methods = Column(Text, nullable=True)     # Real-world resolution from the source API
    escalate_to = Column(String, nullable=True)        # L1 / L2 / L3 / Security Team
    time_to_resolve_estimate = Column(String, nullable=True)
    sentiment = Column(String, nullable=True)
    key_symptoms = Column(JSON, nullable=True)         # list of strings

    # Raw data for audit
    raw_context = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentSecret(Base):
    __tablename__ = "agent_secrets"

    id = Column(Integer, primary_key=True, index=True)
    key_name = Column(String, unique=True, index=True, nullable=False)
    secret_value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
