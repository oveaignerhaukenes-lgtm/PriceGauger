from __future__ import annotations

from pathlib import Path

from context_adapter_v2 import adapt_context_snapshot_v2
from context_runtime_v2 import publish_context_snapshot_v2
from context_snapshot_store_v2 import ContextSnapshotStoreV2
from news_context_store import NewsContextStore
from telegram_flow_store import TelegramFlowStore


def publish_latest_context_v2(
    *,
    db_path: str | Path,
    scope_key: str = "global",
) -> tuple[object | None, bool]:
    """Publish the latest independent semantic engines into canonical Context v2.

    This bridge reads only outputs already produced by Telegram Flow / News Context.
    It does not invoke semantic generation, Technical Core, legacy Decision/
    Recommendation runtime, Composer, or execution.
    """
    flow_store = TelegramFlowStore(db_path)
    flow = flow_store.load_latest_snapshot()
    if flow is None:
        return None, False

    news = NewsContextStore(db_path).load_latest()
    posts = flow_store.load_posts(limit=500)
    snapshot = adapt_context_snapshot_v2(
        flow=flow,
        news=news,
        posts=posts,
        scope_key=scope_key,
    )
    return publish_context_snapshot_v2(
        snapshot,
        store=ContextSnapshotStoreV2(db_path),
    )
