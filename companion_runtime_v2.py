from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import uuid4

from analyst_companion_v2 import (
    CompanionAnalysisV2,
    build_companion_payload_v2,
    validate_companion_analysis_v2,
)


class CompanionProviderV2(Protocol):
    def analyze(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def answer(self, payload: Mapping[str, Any], question: str) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class CompanionTurnV2:
    kind: str
    text: str
    as_of: str


@dataclass(slots=True)
class CompanionSessionV2:
    session_id: str
    market: str
    activated_at: str
    active: bool = True
    last_snapshot_as_of: str | None = None
    analysis: CompanionAnalysisV2 | None = None
    turns: list[CompanionTurnV2] = field(default_factory=list)
    last_error: str | None = None

    @classmethod
    def activate(cls, market: str) -> "CompanionSessionV2":
        return cls(
            session_id=str(uuid4()),
            market=str(market),
            activated_at=datetime.now(timezone.utc).isoformat(),
        )

    def end(self) -> None:
        self.active = False

    def append_turn(self, kind: str, text: str, *, as_of: str) -> None:
        self.turns.append(CompanionTurnV2(kind=str(kind), text=str(text), as_of=str(as_of)))
        if len(self.turns) > 12:
            del self.turns[:-12]


def refresh_companion_session_v2(
    session: CompanionSessionV2,
    *,
    view,
    provider: CompanionProviderV2,
    force: bool = False,
) -> bool:
    """Refresh a live Companion only when its observed technical snapshot changes."""
    if not session.active:
        return False
    if str(view.market) != session.market:
        raise ValueError("Companion session is bound to one market; end it before switching markets")
    if not force and session.last_snapshot_as_of == str(view.as_of):
        return False

    payload = build_companion_payload_v2(view, previous_analysis=session.analysis)
    try:
        raw = provider.analyze(payload)
        analysis = validate_companion_analysis_v2(payload, raw)
    except Exception as exc:
        session.last_error = f"{type(exc).__name__}: {exc}"
        raise

    session.analysis = analysis
    session.last_snapshot_as_of = str(view.as_of)
    session.last_error = None
    session.append_turn("analysis", analysis.commentary, as_of=str(view.as_of))
    return True


def ask_companion_v2(
    session: CompanionSessionV2,
    *,
    view,
    provider: CompanionProviderV2,
    question: str,
) -> tuple[str, float]:
    if not session.active:
        raise ValueError("Companion session is not active")
    if str(view.market) != session.market:
        raise ValueError("question market does not match active Companion session")
    cleaned = str(question).strip()
    if not cleaned:
        raise ValueError("question is required")
    if len(cleaned) > 800:
        raise ValueError("question must remain concise")

    payload = build_companion_payload_v2(view, previous_analysis=session.analysis)
    payload["recent_session_turns"] = [
        {"kind": turn.kind, "text": turn.text, "as_of": turn.as_of}
        for turn in session.turns[-6:]
    ]
    raw = provider.answer(payload, cleaned)
    answer = str(raw.get("answer", "")).strip()
    confidence = float(raw.get("confidence", 0.0))
    if not answer or len(answer) > 1200:
        raise ValueError("Companion answer is missing or too long")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("Companion answer confidence must be between 0 and 1")
    session.append_turn("question", cleaned, as_of=str(view.as_of))
    session.append_turn("answer", answer, as_of=str(view.as_of))
    return answer, confidence
