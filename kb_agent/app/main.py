"""知识库 Agent 服务入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import BASE_DIR, settings
from app.database import SessionLocal, create_all
from app.services.cache import cache
from app.services.faq import warm_cache
from app.services.vector_store import store
from app.utils.response import BizError, error_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.AUTO_CREATE_TABLES:
        create_all()
        logger.info("数据表已就绪：%s", settings.DATABASE_URL)
    with SessionLocal() as db:
        try:
            count = warm_cache(db)
            logger.info("FAQ 缓存预热完成：%s 条（backend=%s）", count, cache.backend)
        except Exception:  # noqa: BLE001
            logger.exception("FAQ 缓存预热失败")
        try:
            store.ensure(db)
        except Exception:  # noqa: BLE001
            logger.exception("向量索引初始化失败")
    yield


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BizError)
async def biz_error_handler(_request: Request, exc: BizError):
    return error_response(exc.code, exc.message, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    detail = exc.errors()
    message = "参数校验失败"
    if detail:
        first = detail[0]
        loc = ".".join(str(x) for x in first.get("loc", [])[1:])
        message = f"参数校验失败：{loc} {first.get('msg', '')}".strip()
    return error_response(422, message, 422)


@app.get("/api/health", tags=["健康检查"])
def health():
    return {"code": 0, "message": "success", "data": {"status": "ok", "cache": cache.backend}}


app.include_router(api_router, prefix=settings.API_PREFIX)

# 若前端已构建，同源直接托管（前后端同域部署时无需再开 5173）
_dist = BASE_DIR.parent / "kb_agent_web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="web")
    logger.info("已挂载前端静态资源：%s", _dist)
