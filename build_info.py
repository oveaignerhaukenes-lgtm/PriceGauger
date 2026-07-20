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
    st.markdown(
        f"""
        <style>
        .pricegauger-build-badge {{
            position: fixed;
            top: 0.65rem;
            right: 4.25rem;
            z-index: 999999;
            padding: 0.18rem 0.48rem;
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 0.45rem;
            background: rgba(255, 255, 255, 0.82);
            backdrop-filter: blur(6px);
            color: rgba(49, 51, 63, 0.68);
            font-size: 0.67rem;
            line-height: 1.1;
            white-space: nowrap;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        }}
        @media (prefers-color-scheme: dark) {{
            .pricegauger-build-badge {{
                background: rgba(14, 17, 23, 0.82);
                color: rgba(250, 250, 250, 0.68);
            }}
        }}
        @media (max-width: 700px) {{
            .pricegauger-build-badge {{
                top: 0.72rem;
                right: 3.6rem;
                max-width: 52vw;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
        }}
        </style>
        <div class="pricegauger-build-badge" title="{html.escape(label)}">{html.escape(label)}</div>
        """,
        unsafe_allow_html=True,
    )
