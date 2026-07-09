from __future__ import annotations

import re
from dataclasses import dataclass


GAME_LIST_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"遊戲清單", "contains Chinese phrase for game list"),
    (r"\bgame\s*list\b", "contains game list keyword"),
    (r"\bupdate\b", "contains update keyword"),
    (r"新增", "contains add keyword"),
    (r"上架", "contains listing keyword"),
    (r"下架", "contains delisting keyword"),
    (r"刪除", "contains delete keyword"),
    (r"\bremove\b", "contains remove keyword"),
    (r"\bprovider\b", "contains provider keyword"),
    (r"\bplatform\b", "contains platform keyword"),
    (r"\bgame\s*code\b", "contains game code keyword"),
    (r"維護", "contains maintenance keyword"),
    (r"開放", "contains enable keyword"),
    (r"關閉", "contains disable keyword"),
)

ACTIONABLE_KEYWORDS = {
    "已處理",
    "已更新",
    "已確認",
    "已修正",
    "已完成",
    "處理中",
    "排查",
    "確認",
    "update",
    "updated",
    "fixed",
    "done",
    "eta",
    "need",
    "next step",
    "blocked",
    "root cause",
}

LOW_SIGNAL_PHRASES = {
    "ok",
    "收到",
    "好",
    "嗯",
    "了解",
    "thanks",
    "thx",
    "done",
}


@dataclass(slots=True)
class AnalysisResult:
    is_game_list_related: bool
    game_list_reason: str
    quality_score: int
    quality_reason: str


def analyze_message(text: str, is_reply: bool) -> AnalysisResult:
    normalized = (text or "").strip()
    lowered = normalized.lower()

    game_hits = [reason for pattern, reason in GAME_LIST_PATTERNS if re.search(pattern, lowered, re.IGNORECASE)]
    is_game_list_related = len(game_hits) > 0
    game_list_reason = ", ".join(game_hits[:3]) if game_hits else "no game-list signal"

    quality_score, quality_reason = score_reply_quality(normalized, lowered, is_reply)

    return AnalysisResult(
        is_game_list_related=is_game_list_related,
        game_list_reason=game_list_reason,
        quality_score=quality_score,
        quality_reason=quality_reason,
    )


def score_reply_quality(text: str, lowered: str, is_reply: bool) -> tuple[int, str]:
    if not text:
        return 0, "empty message"

    score = 20 if is_reply else 10
    reasons: list[str] = []
    length = len(text)

    if length >= 12:
        score += 15
        reasons.append("has enough detail")
    else:
        score -= 10
        reasons.append("too short")

    if length >= 40:
        score += 15
        reasons.append("contains fuller context")

    if any(keyword in text or keyword in lowered for keyword in ACTIONABLE_KEYWORDS):
        score += 25
        reasons.append("contains actionable wording")

    if any(phrase == lowered for phrase in LOW_SIGNAL_PHRASES):
        score -= 25
        reasons.append("very low-signal reply")

    if any(marker in text for marker in (":", "-", "1.", "2.", "3.")):
        score += 10
        reasons.append("structured response")

    if "?" in text:
        score += 5
        reasons.append("asks clarifying question")

    if any(token in lowered for token in ("because", "原因", "影響", "預計", "風險", "方案")):
        score += 10
        reasons.append("includes explanation or impact")

    score = max(0, min(score, 100))
    if not reasons:
        reasons.append("neutral signal")

    return score, ", ".join(reasons[:4])
