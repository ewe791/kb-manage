"""K-E4：检索质量评测（Precision@k 与命中率）。

说明：当前示例语料只有 3 篇文档，每个问题标注 1 个 gold 单元，
严格 P@5（相关数 / 5）上限即为 0.2，因此本报告同时给出：
  - Hit@5（gold 是否出现在 top-5 结果中，即 Recall@5）
  - Precision@returned（返回结果中有多少是相关的）
  - Strict P@5（严格口径，仅作参考）
"""
from __future__ import annotations

import pytest

from app.services.retrieval import retrieve_units

from tests.eval_data import IN_SCOPE  # noqa: E402
from tests.metrics_store import record  # noqa: E402


def test_KE4_retrieval_quality(seed_kb):
    db = seed_kb["db"]
    units = seed_kb["units"]

    hits = 0
    returned_total = 0
    relevant_total = 0
    strict_p_at_5 = 0.0
    reciprocal_rank = 0.0
    misses: list[dict] = []

    for question, gold_title in IN_SCOPE:
        results = retrieve_units(question, top_k=5, db=db)
        titles = [r["title"] for r in results]
        gold_id = units[gold_title].id

        returned_total += len(results)
        relevant = sum(1 for t in titles if t == gold_title)
        relevant_total += relevant
        strict_p_at_5 += relevant / 5

        if gold_id in [r["unit_id"] for r in results]:
            hits += 1
            rank = [r["unit_id"] for r in results].index(gold_id) + 1
            reciprocal_rank += 1 / rank
        else:
            misses.append({"question": question, "gold": gold_title, "got": titles})

    n = len(IN_SCOPE)
    hit_rate = hits / n
    precision_returned = relevant_total / returned_total if returned_total else 0.0
    mrr = reciprocal_rank / n

    record(
        "retrieval",
        {
            "questions": n,
            "hit_at_5": round(hit_rate, 4),
            "precision_returned": round(precision_returned, 4),
            "strict_p_at_5": round(strict_p_at_5 / n, 4),
            "mrr": round(mrr, 4),
            "returned_units_total": returned_total,
            "misses": misses[:10],
        },
    )

    print(
        f"\n检索：Hit@5={hit_rate:.2%} · Precision@returned={precision_returned:.2%} · "
        f"MRR={mrr:.3f} · 严格P@5={strict_p_at_5 / n:.3f}（3 篇语料下上限 0.2）"
    )

    assert hit_rate >= 0.8, f"Hit@5 不达标：{hit_rate:.2%}，未命中：{misses[:5]}"
    assert precision_returned >= 0.9, f"Precision@returned 不达标：{precision_returned:.2%}"
