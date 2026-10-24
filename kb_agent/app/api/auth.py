"""认证：登录返回 access_token + user_info + permissions。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginRequest
from app.services.permission_engine import get_permission_codes
from app.services.security import create_access_token, verify_password
from app.utils.response import BizError, ok
from app.utils.serializers import user_dict

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise BizError("用户名或密码错误", code=401, status_code=401)
    if user.status != "active":
        raise BizError("账号已停用，请联系管理员", code=403, status_code=403)
    permissions = get_permission_codes(db, user.id)
    token = create_access_token(user.id, {"username": user.username})
    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "user_info": user_dict(db, user),
            "permissions": permissions,
        }
    )


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(user_dict(db, user))


@router.get("/permission-codes")
def permission_codes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok({"permissions": get_permission_codes(db, user.id)})
