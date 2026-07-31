from __future__ import annotations

import html
from collections.abc import Iterable


_STATUS_ICON = {
    "COMPLETE": "✓",
    "RUNNING": "↻",
    "PENDING": "·",
    "SKIPPED": "–",
    "FAILED": "!",
}

_STATUS_LABEL = {
    "COMPLETE": "Ferdig",
    "RUNNING": "Kjører",
    "PENDING": "Venter",
    "SKIPPED": "Hoppet over",
    "FAILED": "Feil",
}


def render_analysis_status(steps: Iterable[object]) -> str:
    """Return a compact, audit-friendly worker progress strip."""
    rows = list(steps)
    if not rows:
        return ""

    cards: list[str] = []
    for step in rows:
        status = str(getattr(step, "status", "PENDING")).upper()
        label = str(getattr(step, "label", getattr(step, "step_key", "Analyse")))
        detail = str(getattr(step, "detail", ""))
        updated_at = str(getattr(step, "updated_at", ""))
        icon = _STATUS_ICON.get(status, "·")
        status_label = _STATUS_LABEL.get(status, status.title())
        cards.append(
            f"""
            <div class="pg-step pg-step-{html.escape(status.lower())}" title="{html.escape(detail)}">
              <div class="pg-step-icon">{html.escape(icon)}</div>
              <div class="pg-step-copy">
                <div class="pg-step-label">{html.escape(label)}</div>
                <div class="pg-step-state">{html.escape(status_label)}</div>
              </div>
              <div class="pg-step-time">{html.escape(updated_at[11:16] if len(updated_at) >= 16 else "")}</div>
            </div>
            """
        )

    return (
        '<section class="pg-progress-card">'
        '<div class="pg-progress-head"><strong>Analyseflyt</strong><span>Vedvarende workerstatus</span></div>'
        f'<div class="pg-progress-grid">{"".join(cards)}</div>'
        "</section>"
    )


ANALYSIS_STATUS_CSS = """
.pg-progress-card {border:1px solid rgba(128,128,128,.24); border-radius:.8rem; padding:.72rem .85rem; margin:.15rem 0 .9rem; background:rgba(128,128,128,.025);}
.pg-progress-head {display:flex; justify-content:space-between; gap:1rem; align-items:center; margin-bottom:.55rem; font-size:.78rem;}
.pg-progress-head span {opacity:.62; font-size:.7rem;}
.pg-progress-grid {display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:.42rem;}
.pg-step {display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:.42rem; align-items:center; min-height:2.55rem; padding:.42rem .5rem; border:1px solid rgba(128,128,128,.18); border-radius:.58rem; background:rgba(128,128,128,.025);}
.pg-step-icon {width:1.22rem; height:1.22rem; display:grid; place-items:center; border-radius:50%; font-size:.73rem; font-weight:800; background:rgba(128,128,128,.16);}
.pg-step-label {font-size:.69rem; font-weight:720; line-height:1.15; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.pg-step-state {font-size:.61rem; opacity:.64; margin-top:.08rem;}
.pg-step-time {font-size:.58rem; opacity:.52;}
.pg-step-complete .pg-step-icon {background:rgba(46,139,87,.18); color:#2e8b57;}
.pg-step-running {border-color:rgba(36,74,124,.42);}
.pg-step-running .pg-step-icon {background:rgba(36,74,124,.18); color:#244a7c; animation:pg-spin 1.2s linear infinite;}
.pg-step-failed .pg-step-icon {background:rgba(178,74,74,.18); color:#b24a4a;}
.pg-step-skipped,.pg-step-pending {opacity:.7;}
@keyframes pg-spin {from{transform:rotate(0deg)} to{transform:rotate(360deg)}}
@media(max-width:1000px){.pg-progress-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:700px){.pg-progress-grid{grid-template-columns:1fr}.pg-progress-head{display:block}.pg-progress-head span{display:block;margin-top:.15rem}}
"""
