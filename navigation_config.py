from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PAGE_GROUPS: dict[str, tuple[dict[str, Any], ...]] = {
    "": (
        {
            "page": "pages/0_Oversikt.py",
            "title": "Oversikt",
            "icon": "📡",
            "default": True,
        },
    ),
    "Oppgaver": (
        {
            "page": "pages/1_Kjerneflyt.py",
            "title": "Historisk motor",
            "icon": "🔗",
            "url_path": "Historisk_motor",
        },
        {
            "page": "pages/2_Direct_Technical.py",
            "title": "Teknisk analyse",
            "icon": "📈",
            "url_path": "Direct_Technical",
        },
        {
            "page": "pages/3_News_Context.py",
            "title": "Nyhetsanalyse",
            "icon": "📰",
            "url_path": "News_Context",
        },
        {
            "page": "pages/4_Telegram_Flow.py",
            "title": "Telegram-vurdering",
            "icon": "📨",
            "url_path": "Telegram_Flow",
        },
        {
            "page": "pages/5_AI_Market_Assessment.py",
            "title": "AI-markedsvurdering",
            "icon": "🧠",
            "url_path": "AI_Market_Assessment",
        },
    ),
    "Resultater": (
        {
            "page": "pages/2_Signalaggregat.py",
            "title": "Signalaggregat",
            "icon": "📶",
            "url_path": "Signalaggregat",
        },
        {
            "page": "pages/Market_State.py",
            "title": "Market State",
            "icon": "🧭",
            "url_path": "Market_State",
        },
        {
            "page": "pages/Signal_History.py",
            "title": "Signalhistorikk",
            "icon": "📊",
            "url_path": "Signal_History",
        },
    ),
    "Tilkoblinger og drift": (
        {
            "page": "pages/1_Saxo_OpenAPI.py",
            "title": "Saxo",
            "icon": "🔌",
            "url_path": "Saxo_OpenAPI",
        },
        {
            "page": "pages/6_AutoTrader_POC.py",
            "title": "AutoTrader POC",
            "icon": "🧪",
            "url_path": "AutoTrader_POC",
        },
        {
            "page": "pages/Worker_Status.py",
            "title": "Workerstatus",
            "icon": "🟢",
            "url_path": "Worker_Status",
        },
        {
            "page": "pages/99_Runtime_Diagnostics.py",
            "title": "Database og runtime",
            "icon": "🛠️",
            "url_path": "Runtime_Diagnostics",
        },
    ),
    "Utviklerverktøy": (
        {
            "page": "pages/1_Historical_Event_Lab.py",
            "title": "Historisk hendelsessøk (legacy)",
            "icon": "🧪",
            "url_path": "Historical_Event_Lab",
        },
    ),
}


def build_navigation(streamlit_module: Any) -> Mapping[str, list[Any]]:
    """Build the explicit Streamlit navigation while keeping config testable."""
    return {
        section: [streamlit_module.Page(**page) for page in pages]
        for section, pages in PAGE_GROUPS.items()
    }
