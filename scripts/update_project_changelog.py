#!/usr/bin/env python3
"""Deterministic journal of recent meaningful main commits; no runtime/trading claims."""
import os
from pathlib import Path
import re
import subprocess

DEFAULT_REPO = "oveaignerhaukenes-lgtm/PriceGauger"
JOURNAL = Path("docs/PROJECT_CHANGELOG.md")


def parse_commits(raw, limit=40):
    entries = []
    for line in raw.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        sha, day, title, author = parts
        if (author == "github-actions[bot]"
                or title.startswith("docs: refresh project continuity journal")
                or not re.fullmatch(r"[0-9a-f]{40}", sha)):
            continue
        entries.append((sha, day, title))
        if len(entries) >= limit:
            break
    return entries


def render_journal(raw, repo=DEFAULT_REPO):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository slug")
    entries = parse_commits(raw)
    tick = chr(96)
    lines = [
        "# PriceGauger — automatic repository journal", "",
        "Generated from recent non-bot main commits. This is Git history only;",
        "it does not verify Railway deployments, Saxo fills or trading outcomes.", "",
        f"Latest tracked main commit: {tick}{entries[0][0]}{tick}"
        if entries else "No matching commits found.", "",
        "## Recent main commits", "",
    ]
    for sha, day, title in entries:
        safe = title.replace("|", r"\|").replace("\r", " ").replace("\n", " ")
        lines.append(
            f"- {day} [{tick}{sha[:10]}{tick}](https://github.com/{repo}/commit/{sha}) — {safe}"
        )
    lines.extend(["", "For priorities and decisions, read [PROJECT_STATE.md](../PROJECT_STATE.md).", ""])
    return "\n".join(lines)


def main():
    raw = subprocess.check_output(
        ["git", "log", "-n", "160", "--date=short",
         "--pretty=format:%H%x09%ad%x09%s%x09%an"], text=True
    ).strip()
    text = render_journal(raw, os.getenv("GITHUB_REPOSITORY", DEFAULT_REPO))
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    if not JOURNAL.exists() or JOURNAL.read_text(encoding="utf-8") != text:
        JOURNAL.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
