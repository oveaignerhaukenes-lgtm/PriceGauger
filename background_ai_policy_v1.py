"""Operator policy for unsolicited AI work; explicit UI/strategy opt-ins are separate.

The API key means calls are possible, not that background calls are authorized.
Background AI is disabled by default.  Existing user-controlled AI options must
continue to use their own persistent switches and feature flags.
"""
from __future__ import annotations

import os


BACKGROUND_AI_ENV = "PRICEGAUGER_BACKGROUND_AI_ENABLED"


def background_ai_enabled_v1() -> bool:
    return os.getenv(BACKGROUND_AI_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}
