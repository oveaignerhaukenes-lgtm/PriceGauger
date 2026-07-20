from __future__ import annotations

import html
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

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


def render_build_badge() -> None:
    build = get_build_info()
    label = f"Build {build.commit} · {build.branch} · {build.commit_time}"
    compact_label = f"{build.commit} · {build.branch}"
    st.markdown(
        f"""
        <style>
        .pricegauger-build-badge {{
            position: fixed;
            top: 0.62rem;
            right: 4.4rem;
            z-index: 999999;
            padding: 0.16rem 0.44rem;
            border: 1px solid rgba(128, 128, 128, 0.24);
            border-radius: 0.42rem;
            background: rgba(255, 255, 255, 0.80);
            backdrop-filter: blur(6px);
            color: rgba(49, 51, 63, 0.65);
            font-size: 0.64rem;
            line-height: 1.1;
            white-space: nowrap;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            pointer-events: none;
        }}
        .pricegauger-build-badge-mobile {{ display: none; }}
        @media (prefers-color-scheme: dark) {{
            .pricegauger-build-badge {{
                background: rgba(14, 17, 23, 0.80);
                color: rgba(250, 250, 250, 0.66);
            }}
        }}
        @media (max-width: 700px) {{
            .pricegauger-build-badge {{
                top: 0.43rem;
                right: 3.65rem;
                padding: 0.11rem 0.34rem;
                max-width: 34vw;
                font-size: 0.56rem;
                opacity: 0.86;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .pricegauger-build-badge-desktop {{ display: none; }}
            .pricegauger-build-badge-mobile {{ display: inline; }}
        }}
        </style>
        <div class="pricegauger-build-badge" title="{html.escape(label)}">
            <span class="pricegauger-build-badge-desktop">{html.escape(label)}</span>
            <span class="pricegauger-build-badge-mobile">{html.escape(compact_label)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )