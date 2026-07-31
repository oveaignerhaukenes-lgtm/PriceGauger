from __future__ import annotations

from telegram_content_filter import classify_telegram_content
from telegram_flow_engine import AssetPostScore, ScoredTelegramPost
from telegram_flow_store import TelegramFlowStore


def _post(message_id: str, text: str) -> ScoredTelegramPost:
    return ScoredTelegramPost(
        message_id=message_id,
        channel="Middle_East_Spectator",
        published_at="2026-07-31T21:04:00+00:00",
        text=text,
        event_key=f"event:{message_id}",
        relation="new",
        novelty=0.7,
        source_quality=0.6,
        scores=(
            AssetPostScore(
                asset="Brent",
                direction=1.0,
                impact=0.8,
                confidence=0.7,
                horizon_hours=4.0,
                rationale="Supply risk.",
            ),
        ),
    )


def test_recruitment_post_is_filtered():
    text = """A drone attack targeted LNG vessels yesterday.

During geopolitical unrest, Bitcoin attracts many traders wondering how to spot crypto trading opportunities.

Join: https://chat.whatsapp.com/example"""

    result = classify_telegram_content(text)

    assert result.eligible is False
    assert result.promotional_score >= 0.7
    assert "external_group_link" in result.reason


def test_normal_news_post_remains_eligible():
    result = classify_telegram_content(
        "Two LNG tankers were hit by drones at Damietta Port. Oil and gas prices moved higher afterward."
    )

    assert result.eligible is True
    assert result.reason == "eligible"


def test_store_keeps_filtered_post_for_audit_but_excludes_it_from_flow(tmp_path):
    store = TelegramFlowStore(tmp_path / "flow.sqlite3")
    news = _post("1", "Fresh attack on an LNG terminal raises immediate supply risk.")
    promotion = _post(
        "2",
        "Old LNG attack headline. Wondering how to find crypto trading opportunities? "
        "Join https://chat.whatsapp.com/example",
    )
    store.save_posts([news, promotion])

    production_posts = store.load_posts(limit=10)
    audit_posts = store.load_posts(limit=10, include_filtered=True)

    assert [post.message_id for post in production_posts] == ["1"]
    assert {post.message_id for post in audit_posts} == {"1", "2"}
