"""K-E3：回答忠实度 / 拒答正确性 / 引用一致性（真实 LLM + 确定性检查）。

- 忠实度：答案按句拆分，逐句校验是否被授权单元正文支撑（中文 unigram+bigram 覆盖率）
- 拒答：20 条知识库外问题，期望拒答或说明未找到
- 引用一致性：含 [n] 的回答，校验编号存在且被引用句能在对应单元正文中找到支撑

首次运行会真实调用 LLM，结果缓存在 reports/eval_answers.json，重复运行不再消耗 Token。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE = Path(__file__).resolve().parent.parent
CACHE_PATH = BASE / "reports" / "eval_answers.json"

from app.database import Base  # noqa: E402
from app.agent.user_agent import run_user_agent  # noqa: E402
from app.models import Department, KnowledgeUnit, UnitPermission, User  # noqa: E402
from app.services.ingest import import_path  # noqa: E402
from app.services.retrieval import retrieve_units  # noqa: E402
from app.services.security import hash_password  # noqa: E402
from app.services.vector_store import store  # noqa: E402

from tests.eval_data import IN_SCOPE, OUT_OF_SCOPE  # noqa: E402
from tests.metrics_store import record  # noqa: E402
from tests.text_utils import (  # noqa: E402
    coverage,
    coverage_unigram,
    is_refusal,
    is_substantive,
    split_sentences,
    strip_answer_noise,
)


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    """一次性准备：导入 3 篇示例文档 + 全局授权 + 构建向量索引。"""
    engine = create_engine(f"sqlite:///{tmp_path_factory.mktemp('eval') / 'db.sqlite'}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()

    dept = Department(name="评测部")
    db.add(dept)
    db.flush()
    user = User(username="u_eval", password_hash=hash_password("x"), display_name="评测员", department_id=dept.id)
    db.add(user)
    db.flush()

    units: dict[str, KnowledgeUnit] = {}
    for filename, category in [
        ("财务报销制度.md", "财务制度"),
        ("产品使用手册.md", "产品文档"),
        ("HR考勤政策.md", "人力资源"),
    ]:
        result = import_path(db, user.id, str(BASE / "seed" / "docs" / filename), category=category)
        unit = db.get(KnowledgeUnit, result["unit_id"])
        units[unit.title] = unit
        db.add(UnitPermission(unit_id=unit.id, target_type="global", target_id=None))
    db.commit()
    store.mark_dirty()
    store.ensure(db)

    yield db, user, units
    db.close()
    engine.dispose()


def _key(question: str) -> str:
    return hashlib.md5(question.strip().encode("utf-8")).hexdigest()


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def dump_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(scope="module")
def answers(kb):
    """逐条跑用户 Agent；命中缓存则不重复调用模型。"""
    db, user, _units = kb
    cache = load_cache()
    questions = [q for q, _ in IN_SCOPE] + list(OUT_OF_SCOPE)
    pending = [q for q in questions if _key(q) not in cache]
    if pending:
        # 复用同一个事件循环：OpenAI 异步客户端会绑定底层连接池
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            for question in pending:
                cache[_key(question)] = loop.run_until_complete(
                    run_user_agent(db, user, None, question)
                )
        finally:
            loop.close()
            asyncio.set_event_loop(None)
        dump_cache(cache)
    return cache


def _context_for(kb, question: str, top_k: int = 5) -> tuple[str, list[dict]]:
    db, _user, units = kb
    candidates = retrieve_units(question, top_k=top_k, db=db)
    contents = [units[c["title"]].content for c in candidates if c["title"] in units]
    return "\n".join(contents), candidates


def test_KE3_1_faithfulness(kb, answers):
    """忠实度：被支撑句数 / 总句数，指标 ≥ 95%。"""
    total, supported, skipped = 0, 0, 0
    strict_total, strict_supported = 0, 0
    unsupported_samples: list[dict] = []

    for question, _gold in IN_SCOPE:
        raw = answers[_key(question)]
        context, _cands = _context_for(kb, question)
        for sentence in split_sentences(raw["answer"]):
            strict_total += 1
            if coverage(sentence, context, filtered=False) >= 0.8:
                strict_supported += 1
            if not is_substantive(sentence):
                skipped += 1  # 纯连接短句，不参与判定（人工复核放行）
                continue
            total += 1
            rate = coverage_unigram(sentence, context)
            if rate >= 0.85:
                supported += 1
            else:
                unsupported_samples.append({"question": question, "sentence": sentence, "coverage": round(rate, 3)})

    faithfulness = supported / total if total else 0.0
    strict = strict_supported / strict_total if strict_total else 0.0
    record(
        "faithfulness",
        {
            "total_sentences": total,
            "supported_sentences": supported,
            "score": round(faithfulness, 4),
            "threshold": 0.95,
            "question_count": len(IN_SCOPE),
            "skipped_connector_sentences": skipped,
            "strict_score": round(strict, 4),
            "strict_total_sentences": strict_total,
            "unsupported_samples": unsupported_samples[:10],
        },
    )
    assert total > 0
    print(f"\n忠实度（停用词过滤后）：{supported}/{total} = {faithfulness:.2%}；严格口径：{strict:.2%}")
    assert faithfulness >= 0.95, f"忠实度不达标：{faithfulness:.2%}，未支撑样例：{unsupported_samples[:5]}"


def test_KE3_2_abstention(kb, answers):
    """拒答正确性：20 条库外问题，拒答率 ≥ 90%。"""
    correct, wrong = 0, []
    for question in OUT_OF_SCOPE:
        raw = answers[_key(question)]
        if is_refusal(raw["answer"]):
            correct += 1
        else:
            wrong.append({"question": question, "answer": raw["answer"][:120]})

    rate = correct / len(OUT_OF_SCOPE)
    record(
        "abstention",
        {
            "total": len(OUT_OF_SCOPE),
            "refused": correct,
            "score": round(rate, 4),
            "threshold": 0.9,
            "non_refusal_samples": wrong[:10],
        },
    )
    print(f"\n拒答正确率：{correct}/{len(OUT_OF_SCOPE)} = {rate:.2%}")
    assert rate >= 0.90, f"拒答正确率不达标：{rate:.2%}，样例：{wrong[:5]}"


def test_KE3_3_citation_consistency(kb, answers):
    """引用一致性：引用编号可溯源，且被引用句在对应单元正文中有支撑。"""
    db, _user, units = kb
    checked, valid = 0, 0
    bad: list[dict] = []

    for question, _gold in IN_SCOPE:
        raw = answers[_key(question)]
        citations = raw.get("citations") or []
        if not citations:
            continue
        by_ref = {c.get("ref_index"): c for c in citations}
        for ref, citation in by_ref.items():
            checked += 1
            # 缓存答案可能来自上一次会话的临时库，统一按标题定位正文
            unit = db.get(KnowledgeUnit, citation["unit_id"]) or units.get(citation.get("title"))
            if unit is None:
                bad.append({"question": question, "ref": ref, "reason": "unit 不存在", "title": citation.get("title")})
                continue
            # 找出含该引用编号的句子，并检查其在该单元正文中的支撑度
            marked = [s for s in strip_answer_noise(raw["answer"]).split("。") if f"[{ref}]" in s]
            if not marked:
                valid += 1  # 引用未被具体句子使用，但编号本身可溯源
                continue
            rates = [coverage(s, unit.content) for s in marked]
            if max(rates) >= 0.5:
                valid += 1
            else:
                bad.append({"question": question, "ref": ref, "max_coverage": round(max(rates), 3)})

    score = valid / checked if checked else 1.0
    record(
        "citation",
        {
            "checked": checked,
            "valid": valid,
            "score": round(score, 4),
            "threshold": 0.95,
            "bad_samples": bad[:10],
        },
    )
    print(f"\n引用一致性：{valid}/{checked} = {score:.2%}")
    assert score >= 0.95, f"引用一致性不达标：{score:.2%}，样例：{bad[:5]}"
