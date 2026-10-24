"""评测指标收集：测试过程写入内存，会话结束时由 conftest 落盘为 JSON。"""
from __future__ import annotations

METRICS: dict[str, dict] = {}


def record(section: str, data: dict) -> None:
    METRICS.setdefault(section, {}).update(data)
    METRICS[section] = {**METRICS.get(section, {}), **data}


def append(section: str, key: str, value) -> None:
    METRICS.setdefault(section, {}).setdefault(key, []).append(value)


def snapshot() -> dict:
    return {k: dict(v) for k, v in METRICS.items()}
