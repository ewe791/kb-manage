"""全部数据表定义（K1）。

10 张主表 + knowledge_chunks 补充表：
users / departments / roles / user_roles / role_permissions /
knowledge_units / unit_permissions / qa_access_logs / faqs / knowledge_gaps
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    department: Mapped[Department | None] = relationship(foreign_keys=[department_id], lazy="joined")
    user_roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    leader_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="user_roles")
    role: Mapped[Role] = relationship(lazy="joined")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("ix_role_perm_role_code", "role_id", "permission_code", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    permission_code: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_type: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    role: Mapped[Role] = relationship(back_populates="permissions")


class KnowledgeUnit(Base, TimestampMixin):
    __tablename__ = "knowledge_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    unit_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="未分类", index=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    creator_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )
    permissions: Mapped[list[UnitPermission]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base):
    """补充表：切片与向量（embedding 以 float32 字节串存储，FAISS 索引启动时重建）。"""

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_units.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    unit: Mapped[KnowledgeUnit] = relationship(back_populates="chunks")


class UnitPermission(Base):
    """四维权限：global / department / role / user，任一命中即授权（OR）。"""

    __tablename__ = "unit_permissions"
    __table_args__ = (Index("ix_unit_perm_unit", "unit_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    unit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_units.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    unit: Mapped[KnowledgeUnit] = relationship(back_populates="permissions")


class QaAccessLog(Base):
    __tablename__ = "qa_access_logs"
    __table_args__ = (Index("ix_qa_log_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recalled_unit_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    authorized_unit_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unauthorized_unit_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Faq(Base, TimestampMixin):
    __tablename__ = "faqs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    question: Mapped[str] = mapped_column(String(512), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="未分类")
    related_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_review", index=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeGap(Base, TimestampMixin):
    __tablename__ = "knowledge_gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    question_pattern: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sample_questions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ask_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved", index=True)
    resolved_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
