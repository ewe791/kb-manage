"""FAQ 缓存：Redis 优先，未安装/未启动时自动退化为进程内 TTL 缓存。"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class _MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expire_at, value = item
            if expire_at and expire_at < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl if ttl else 0.0, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def keys(self, prefix: str) -> list[str]:
        with self._lock:
            return [k for k in self._data if k.startswith(prefix)]


class CacheClient:
    def __init__(self) -> None:
        self._memory = _MemoryCache()
        self._redis = None
        self.backend = "memory"
        try:
            import redis  # 延迟导入

            client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=1.5)
            client.ping()
            self._redis = client
            self.backend = "redis"
            logger.info("FAQ 缓存使用 Redis：%s", settings.REDIS_URL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis 不可用（%s），FAQ 缓存退化为进程内缓存", exc)

    def get_json(self, key: str) -> Any | None:
        raw = None
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
            except Exception:  # noqa: BLE001
                raw = self._memory.get(key)
        else:
            raw = self._memory.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        raw = json.dumps(value, ensure_ascii=False)
        if self._redis is not None:
            try:
                self._redis.set(key, raw, ex=ttl)
                return
            except Exception:  # noqa: BLE001
                pass
        self._memory.set(key, raw, ttl)

    def delete(self, key: str) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(key)
            except Exception:  # noqa: BLE001
                pass
        self._memory.delete(key)

    def remember_faq_keys(self, key: str) -> None:
        """记录已写入的 FAQ key，便于启动时预热/清理。"""
        self.set_json("faq:__keys__", sorted(set(self.keys("faq:")) | {key}))

    def keys(self, prefix: str = "") -> list[str]:
        if self._redis is not None:
            try:
                keys = self._redis.keys(f"{prefix}*")
                return [k for k in keys if not k.endswith("__keys__")]
            except Exception:  # noqa: BLE001
                pass
        return [k for k in self._memory.keys(prefix) if not k.endswith("__keys__")]


cache = CacheClient()
