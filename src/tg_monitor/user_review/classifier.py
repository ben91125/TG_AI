from __future__ import annotations

from dataclasses import dataclass


ACTIONABLE_KEYWORDS = {
    "\u5df2\u8655\u7406",
    "\u5df2\u66f4\u65b0",
    "\u5df2\u78ba\u8a8d",
    "\u5df2\u4fee\u6b63",
    "\u5df2\u5b8c\u6210",
    "\u8655\u7406\u4e2d",
    "\u6392\u67e5",
    "\u78ba\u8a8d",
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
    "\u6536\u5230",
    "\u597d",
    "\u55ef",
    "\u4e86\u89e3",
    "thanks",
    "thx",
    "done",
}


@dataclass(slots=True)
class UserReplyResult:
    response_type: str
    response_type_reason: str
    quality_score: int
    quality_reason: str


def analyze_user_reply(text: str, is_reply: bool) -> UserReplyResult:
    normalized = (text or "").strip()
    lowered = normalized.lower()

    response_type, response_type_reason = classify_response_type(normalized, lowered, is_reply)
    quality_score, quality_reason = score_reply_quality(normalized, lowered, is_reply)

    return UserReplyResult(
        response_type=response_type,
        response_type_reason=response_type_reason,
        quality_score=quality_score,
        quality_reason=quality_reason,
    )


def classify_response_type(text: str, lowered: str, is_reply: bool) -> tuple[str, str]:
    if not text:
        return "empty", "empty message"
    if lowered in LOW_SIGNAL_PHRASES:
        return "low_signal", "short acknowledgement only"
    if any(token in text or token in lowered for token in ("\u8655\u7406", "\u4fee\u6b63", "fixed", "done", "updated")):
        return "action_update", "contains action or completion wording"
    if any(token in text or token in lowered for token in ("\u539f\u56e0", "\u5f71\u97ff", "because", "root cause")):
        return "explanation", "contains cause or impact wording"
    if "?" in text or "\uff1f" in text:
        return "question", "asks a question"
    if is_reply:
        return "reply_other", "reply without stronger type signal"
    return "message_other", "non-reply message without stronger type signal"


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

    if lowered in LOW_SIGNAL_PHRASES:
        score -= 25
        reasons.append("very low-signal reply")

    if any(marker in text for marker in (":", "-", "1.", "2.", "3.")):
        score += 10
        reasons.append("structured response")

    if "?" in text or "\uff1f" in text:
        score += 5
        reasons.append("asks clarifying question")

    if any(token in text or token in lowered for token in ("because", "\u539f\u56e0", "\u5f71\u97ff", "\u9810\u8a08", "\u98a8\u96aa", "\u65b9\u6848")):
        score += 10
        reasons.append("includes explanation or impact")

    score = max(0, min(score, 100))
    if not reasons:
        reasons.append("neutral signal")

    return score, ", ".join(reasons[:4])
