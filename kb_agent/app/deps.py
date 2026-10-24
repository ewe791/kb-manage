"""依赖注入：当前用户 + require_permission 中间件依赖。"""
from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.permission_engine import get_permission_codes
from app.services.security import decode_token
from app.utils.response import BizError


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise BizError("未提供登录凭证", code=401, status_code=401)
    payload = decode_token(authorization.split(" ", 1)[1].strip())
    user_id = payload.get("sub")
    if not user_id:
        raise BizError("登录状态无效，请重新登录", code=401, status_code=401)
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise BizError("账号不存在或已停用", code=401, status_code=401)
    return user


def require_permission(code: str):
    """中间件：require_permission("knowledge:permission")，无权限返回 403。"""

    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if code not in set(get_permission_codes(db, user.id)):
            raise BizError(f"缺少权限：{code}", code=403, status_code=403)
        return user

    return checker
