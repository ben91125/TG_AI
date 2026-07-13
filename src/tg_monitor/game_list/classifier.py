from __future__ import annotations

import re
from dataclasses import dataclass


GAME_LIST_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\u904a\u6232\u6e05\u55ae", "contains game-list wording"),
    (r"\bgame\s*list\b", "contains game list keyword"),
    (r"\bgame\s*code\b", "contains game code keyword"),
    (r"\bprovider\b", "contains provider keyword"),
    (r"\bplatform\b", "contains platform keyword"),
    (r"\bupdate\b", "contains update keyword"),
    (r"\bremove\b", "contains remove keyword"),
    (r"\u65b0\u589e", "contains add keyword"),
    (r"\u4e0a\u67b6", "contains listing keyword"),
    (r"\u4e0b\u67b6", "contains delisting keyword"),
    (r"\u522a\u9664", "contains delete keyword"),
    (r"\u7dad\u8b77", "contains maintenance keyword"),
    (r"\u958b\u653e", "contains enable keyword"),
    (r"\u95dc\u9589", "contains disable keyword"),
)


@dataclass(slots=True)
class GameListResult:
    is_related: bool
    reason: str


def analyze_game_list_message(text: str) -> GameListResult:
    normalized = (text or "").strip()
    lowered = normalized.lower()
    hits = [reason for pattern, reason in GAME_LIST_PATTERNS if re.search(pattern, lowered, re.IGNORECASE)]

    return GameListResult(
        is_related=bool(hits),
        reason=", ".join(hits[:3]) if hits else "no game-list signal",
    )
