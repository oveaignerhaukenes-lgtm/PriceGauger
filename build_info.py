from __future__ import annotations

import inspect
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


@dataclass(frozen=True, slots=True)
class BuildInfo:
    commit: str
    branch: str
    commit_time: str


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


@st.cache_resource(show_spinner=False)
def get_build_info() -> BuildInfo:
    """Keep build metadata available to explicit diagnostics without showing it in product UI."""
    commit = os.getenv("GITHUB_SHA") or os.getenv("COMMIT_SHA") or _git("rev-parse", "HEAD") or "unknown"
    branch = os.getenv("GITHUB_REF_NAME") or os.getenv("BRANCH") or _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    raw_time = _git("show", "-s", "--format=%cI", "HEAD")
    try:
        parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00")) if raw_time else None
        commit_time = parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if parsed else "time unknown"
    except ValueError:
        commit_time = "time unknown"
    return BuildInfo(commit=commit[:7], branch=branch, commit_time=commit_time)


def _calling_page_name() -> str | None:
    frame = inspect.currentframe()
    caller = frame.f_back.f_back if frame is not None and frame.f_back is not None else None
    if caller is None:
        return None
    return Path(caller.f_code.co_filename).name


def _render_page_chrome(page: str | None) -> None:
    """Mount useful page chrome only; migration/debug chrome is intentionally not product UI."""
    if page != "0_TradingDesk.py":
        return
    try:
        from market_watchlist_v2 import render_market_watchlist_v2

        render_market_watchlist_v2(show_settings=False)
    except Exception:
        # The read-only watchlist must never prevent TradingDesk from loading.
        pass


def render_build_badge() -> None:
    """Compatibility entrypoint for shared UI chrome; the old visible build badge is retired."""
    page = _calling_page_name()
    st.markdown(
        """
        <style>
        [data-testid="stMetric"] { min-width: 0 !important; }
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] > div,
        [data-testid="stMetricValue"] p,
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] > div,
        [data-testid="stMetricLabel"] p {
            min-width: 0 !important;
            max-width: 100% !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            overflow-wrap: anywhere !important;
            word-break: normal !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.08rem !important;
            line-height: 1.28 !important;
            font-weight: 600 !important;
        }
        [data-testid="stMetricValue"] > div,
        [data-testid="stMetricValue"] p {
            font-size: inherit !important;
            line-height: inherit !important;
            font-weight: inherit !important;
        }
        [data-testid="stMetricLabel"] { line-height: 1.25 !important; }
        /* Product polish: separators should express structure, not decorate every section. */
        hr { margin: .55rem 0 !important; opacity: .32; }
        @media (max-width: 700px) {
            [data-testid="stMetricValue"] { font-size: 0.98rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _render_page_chrome(page)
