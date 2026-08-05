from __future__ import annotations

import html
from collections.abc import Iterable


_STATUS_ICON = {
    "COMPLETE": "✓",
    "RUNNING": "↻",
    "PENDING": "·",
    "SKIPPED": "–",
    "FAILED": "×",
}

_STATUS_LABEL = {
    "COMPLETE": "Ferdig",
    "RUNNING": "Arbeider",
    "PENDING": "Venter",
    "SKIPPED": "Hoppet over",
    "FAILED": "Feilet",
}


def render_analysis_status(steps: Iterable[object]) -> str:
    """Return compact HTML without Markdown-indented code blocks."""
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
            '<div class="pg-step pg-step-{status}" title="{detail}" aria-label="{label}: {status_label}. {detail}">'
            '<div class="pg-step-icon">{icon}</div>'
            '<div class="pg-step-copy">'
            '<div class="pg-step-label">{label}</div>'
            '<div class="pg-step-state">{status_label}</div>'
            '</div>'
            '<div class="pg-step-time">{time}</div>'
            '</div>'.format(
                status=html.escape(status.lower()),
                detail=html.escape(detail),
                icon=html.escape(icon),
                label=html.escape(label),
                status_label=html.escape(status_label),
                time=html.escape(updated_at[11:16] if len(updated_at) >= 16 else ""),
            )
        )

    return (
        '<section class="pg-progress-card">'
        '<div class="pg-progress-head"><strong>Analyseflyt</strong><span>Vedvarende workerstatus</span></div>'
        '<div class="pg-progress-grid">'
        + "".join(cards)
        + "</div></section>"
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
.pg-step-running {border-color:rgba(36,112,181,.5); background:rgba(36,112,181,.055);}
.pg-step-running .pg-step-icon {background:rgba(36,112,181,.18); color:#2470b5;}\n.pg-step-running .pg-step-icon::before {content:""; width:.72rem; height:.72rem; border:.13rem solid rgba(36,112,181,.24); border-top-color:#2470b5; border-radius:50%; animation:pg-spin .9s linear infinite;}\n.pg-step-running .pg-step-icon {font-size:0;}
.pg-step-running .pg-step-state {color:#2470b5; opacity:1; font-weight:720;}
.pg-step-failed {border-color:rgba(204,45,45,.72); background:rgba(204,45,45,.075);}
.pg-step-failed .pg-step-icon {background:#c92f2f; color:#fff; font-size:.9rem;}
.pg-step-failed .pg-step-state {color:#c92f2f; opacity:1; font-weight:800;}
.pg-step-skipped,.pg-step-pending {opacity:.7;}
@keyframes pg-spin {from{transform:rotate(0deg)} to{transform:rotate(360deg)}}
@media(max-width:1000px){.pg-progress-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:700px){.pg-progress-grid{grid-template-columns:1fr}.pg-progress-head{display:block}.pg-progress-head span{display:block;margin-top:.15rem}}
"""
