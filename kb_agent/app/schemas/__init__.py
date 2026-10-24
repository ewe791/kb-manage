"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PermissionTarget(BaseModel):
    target_type: Literal["global", "department", "role", "user"]
    target_id: str | None = None


class UnitUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    content: str | None = None
    summary: str | None = Field(default=None, max_length=512)
    category: str | None = Field(default=None, max_length=64)
    status: Literal["active", "archived"] | None = None


class UnitPermissionsRequest(BaseModel):
    targets: list[PermissionTarget]


class DeleteUnitsRequest(BaseModel):
    unit_ids: list[str]


class CheckPermissionsRequest(BaseModel):
    unit_ids: list[str]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None


class AdminChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    history: list[dict] | None = None


class FaqReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    edited_answer: str | None = None


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parent_id: str | None = None
    leader_id: str | None = None
    sort_order: int = 0


class RoleCreateRequest(BaseModel):
    role_name: str = Field(min_length=1, max_length=64)
    role_code: str = Field(min_length=1, max_length=64)
    description: str = ""
    permissions: list[str] = Field(default_factory=list)


class RolePermissionsRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    role_name: str | None = Field(default=None, max_length=64)
    description: str | None = None
    permissions: list[str] | None = None


class DepartmentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    parent_id: str | None = None
    leader_id: str | None = None
    sort_order: int | None = None


class GapCreateUnitRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    category: str = "未分类"
    summary: str | None = None
    targets: list[PermissionTarget] = Field(default_factory=list)



class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    department_id: str | None = None
    role_ids: list[str] = Field(default_factory=list)
    status: str = "active"


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    department_id: str | None = None
    role_ids: list[str] | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    status: str | None = None
