"""文本评测工具：句子切分、中文 bigram 覆盖率（确定性检查，不依赖 LLM）。"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"[。！？；!\?;\n]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_TOKEN = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]")
_CITE = re.compile(r"\[\d{1,2}\]")
_PERM_NOTE = re.compile(r"（另有\s*\d+\s*条相关知识您暂无访问权限）")


MD_EMPHASIS = re.compile(r"[*`#>|]+")

# 纯连接/句式词：不承载事实信息，不参与支撑度计算
STOPWORDS = set(
    """
    的 了 是 在 和 与 及 为 按 根据 现行 请 可以 需要 应 应该 以下 如下 补充 说明
    具体 相关 进行 通过 对于 关于 其中 以及 或者 如果 由于 因此 所以 但是 并且
    详见 参见 上述 本题 回答 问题 分别 等 情况 如下 目前 一般 通常 建议 注意
    """.split()
)


def strip_answer_noise(text: str) -> str:
    """去掉引用编号、Markdown 强调符号与权限缺失提示，只保留需要判定支撑度的正文。"""
    text = _PERM_NOTE.sub("", text or "")
    text = _CITE.sub("", text)
    text = MD_EMPHASIS.sub("", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(strip_answer_noise(text)) if s and s.strip()]


def content_tokens(text: str) -> list[str]:
    tokens = _TOKEN.findall((text or "").lower())
    bigrams = [tokens[i] + tokens[i + 1] for i in range(len(tokens) - 1)]
    return tokens + bigrams


STOPWORD_CHARS = set("".join(STOPWORDS))


def _is_functional(token: str) -> bool:
    if token in STOPWORDS:
        return True
    # 完全由连接词用字组成的 token（如"补充说明""如下"）同样视为句式词
    return bool(token) and all(ch in STOPWORD_CHARS for ch in token)


def content_tokens_filtered(sentence: str) -> list[str]:
    """去掉纯连接词后的内容词（承载事实信息）。"""
    return [t for t in content_tokens(sentence) if not _is_functional(t)]


def content_chars(text: str) -> list[str]:
    """内容字符级 token：汉字 + 数字/字母串（对中文改写更稳健）。"""
    out: list[str] = []
    buf = ""
    for ch in text or "":
        if _CJK.match(ch):
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
        elif ch.isalnum():
            buf += ch.lower()
        elif buf:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def coverage_unigram(sentence: str, context: str) -> float:
    """字符级覆盖率：句子中的实义字/数字在 context 中出现的比例。"""
    units = [u for u in content_chars(sentence) if not _is_functional(u)]
    if not units:
        return 1.0
    ctx = set(content_chars(context))
    hit = sum(1 for u in units if u in ctx)
    return hit / len(units)


def coverage(sentence: str, context: str, filtered: bool = True) -> float:
    """句子内容词在 context 中的覆盖率（unigram + bigram）。

    filtered=True 时忽略连接词/句式词（评测文档允许对合理改写做人工复核放行）。
    """
    tokens = content_tokens_filtered(sentence) if filtered else content_tokens(sentence)
    if not tokens:
        return 1.0
    ctx = set(content_tokens(context))
    hit = sum(1 for t in tokens if t in ctx)
    return hit / len(tokens)


def is_substantive(sentence: str, min_tokens: int = 3) -> bool:
    """是否是需要判定支撑度的实义句（排除"补充说明："这类纯连接短句）。"""
    return len(content_tokens_filtered(sentence)) >= min_tokens


def is_supported(sentence: str, context: str, threshold: float = 0.8) -> bool:
    """判定句子是否被 context 支撑。

    说明：中文同义改写频繁，单纯用词覆盖容易误判，这里采用
    unigram + bigram 的整体覆盖率，并对短句（≤6 个内容词）放宽到 0.5。
    """
    tokens = content_tokens(sentence)
    if len(tokens) <= 6:
        threshold = min(threshold, 0.5)
    return coverage(sentence, context) >= threshold


def refusal_markers() -> list[str]:
    return [
        "根据现有资料，暂未找到明确答案",
        "暂未找到",
        "未找到",
        "无法回答",
        "没有找到",
        "知识库中暂未找到",
        "不足以",
        "没有相关",
    ]


def is_refusal(answer: str) -> bool:
    text = answer or ""
    return any(m in text for m in refusal_markers())
