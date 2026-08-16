from __future__ import annotations

import html
import inspect
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from migration_debug_ui import render_migration_badge


@dataclass(frozen=True, slots=True)
class BuildInfo:
    commit: str
    branch: str
    commit_time: str


_MIGRATION_BY_PAGE: dict[str, tuple[str, str]] = {
    "0_Oversikt.py": (
        "MIXED",
        "V2: markedskort/Technical Core/forecast. Legacy/V1: nyhets-, Telegram- og Information State-kontekst.",
    ),
    "0_TradingDesk.py": (
        "V2",
        "V2 identity/workspace/Companion/execution context. Canonical 1m-bars bruker fortsatt den kontrollerte storage-broen.",
    ),
    "2_Direct_Technical.py": (
        "LEGACY/V1",
        "Eldre direkte teknisk analyseflate; ikke den autoritative Technical Core v2-read-pathen.",
    ),
    "6_AutoTrader_POC.py": (
        "V2",
        "Product Explorer/onboarding bruker canonical v2 registry; ordreutførelse går gjennom separat Saxo SIM safety-path.",
    ),
}


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
    commit = (
        os.getenv("GITHUB_SHA")
        or os.getenv("COMMIT_SHA")
        or _git("rev-parse", "HEAD")
        or "unknown"
    )
    branch = (
        os.getenv("GITHUB_REF_NAME")
        or os.getenv("BRANCH")
        or _git("rev-parse", "--abbrev-ref", "HEAD")
        or "unknown"
    )
    raw_time = _git("show", "-s", "--format=%cI", "HEAD")
    try:
        parsed = datetime.fromisoformat(raw_time.replace("Z", "+00:00")) if raw_time else None
        commit_time = parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if parsed else "time unknown"
    except ValueError:
        commit_time = "time unknown"
    return BuildInfo(commit=commit[:7], branch=branch, commit_time=commit_time)


def _render_page_migration_marker() -> None:
    frame = inspect.currentframe()
    caller = frame.f_back.f_back if frame is not None and frame.f_back is not None else None
    if caller is None:
        return
    page = Path(caller.f_code.co_filename).name
    marker = _MIGRATION_BY_PAGE.get(page)
    if marker is None:
        return
    authority, detail = marker
    render_migration_badge(authority, detail=detail)


def render_build_badge() -> None:
    build = get_build_info()
    label = f"Build {build.commit} · {build.branch} · {build.commit_time}"
    compact = f"{build.commit} · {build.branch}"

    st.markdown(
        f"""
        <style>
        [data-testid="stMetric"] {{
            min-width: 0 !important;
        }}
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] > div,
        [data-testid="stMetricValue"] p,
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] > div,
        [data-testid="stMetricLabel"] p {{
            min-width: 0 !important;
            max-width: 100% !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            overflow-wrap: anywhere !important;
            word-break: normal !important;
        }}
        [data-testid="stMetricValue"] {{
            font-size: 1.08rem !important;
            line-height: 1.28 !important;
            font-weight: 600 !important;
        }}
        [data-testid="stMetricValue"] > div,
        [data-testid="stMetricValue"] p {{
            font-size: inherit !important;
            line-height: inherit !important;
            font-weight: inherit !important;
        }}
        [data-testid="stMetricLabel"] {{
            line-height: 1.25 !important;
        }}
        .pricegauger-build-badge {{
            position: fixed;
            top: 0.55rem;
            right: 4.35rem;
            z-index: 999999;
            padding: 0.16rem 0.42rem;
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 0.45rem;
            background: rgba(255, 255, 255, 0.82);
            backdrop-filter: blur(6px);
            color: rgba(49, 51, 63, 0.68);
            font-size: 0.64rem;
            line-height: 1.1;
            white-space: nowrap;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        .pricegauger-aggregate-link {{
            position: fixed;
            top: 2.55rem;
            right: 4.35rem;
            z-index: 999998;
            padding: 0.24rem 0.52rem;
            border: 1px solid rgba(255, 75, 75, 0.45);
            border-radius: 0.55rem;
            background: rgba(255, 75, 75, 0.10);
            color: inherit !important;
            text-decoration: none !important;
            font-size: 0.72rem;
            line-height: 1.1;
            white-space: nowrap;
            backdrop-filter: blur(6px);
        }}
        .pricegauger-aggregate-link:hover {{
            background: rgba(255, 75, 75, 0.20);
            border-color: rgba(255, 75, 75, 0.75);
        }}
        @media (prefers-color-scheme: dark) {{
            .pricegauger-build-badge {{
                background: rgba(14, 17, 23, 0.82);
                color: rgba(250, 250, 250, 0.68);
            }}
            .pricegauger-aggregate-link {{
                background: rgba(255, 75, 75, 0.12);
                color: rgba(250, 250, 250, 0.88) !important;
            }}
        }}
        @media (max-width: 700px) {{
            [data-testid="stMetricValue"] {{
                font-size: 0.98rem !important;
            }}
            .pricegauger-build-badge {{
                top: 0.48rem;
                right: 4.2rem;
                max-width: 36vw;
                overflow: hidden;
                text-overflow: ellipsis;
                font-size: 0.58rem;
            }}
            .pricegauger-aggregate-link {{
                top: 2.25rem;
                right: 4.2rem;
                font-size: 0.66rem;
                padding: 0.22rem 0.45rem;
            }}
        }}
        </style>
        <div class="pricegauger-build-badge" title="{html.escape(label)}">{html.escape(compact)}</div>
        <a class="pricegauger-aggregate-link" href="/Signalaggregat" target="_self" title="Åpne Signalaggregat">∑ Signalaggregat</a>
        """,
        unsafe_allow_html=True,
    )

    _render_page_migration_marker()

    try:
        with st.sidebar:
            st.page_link("pages/2_Signalaggregat.py", label="∑ Signalaggregat")
    except Exception:
        pass
