from __future__ import annotations

from telegram_query_builder import build_search_plan, plans_from_telegram_html


def test_attack_on_energy_infrastructure_builds_focused_query() -> None:
    plan = build_search_plan(
        message_id="123",
        message_url="https://t.me/Middle_East_Spectator/123",
        text="Drone strike reported at the South Pars gas field in Iran.",
    )

    assert plan.event_type == "attack"
    assert plan.target == "energy infrastructure"
    assert plan.country == "Iran"
    assert plan.domain == "INFRASTRUCTURE"
    assert plan.search == "attack energy infrastructure Iran"
    assert plan.signal_score == 3


def test_low_signal_commentary_is_not_selected_from_telegram_html() -> None:
    html = """
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="Middle_East_Spectator/10"></div>
      <div class="tgme_widget_message_text">General commentary with no concrete event.</div>
    </div>
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="Middle_East_Spectator/11"></div>
      <div class="tgme_widget_message_text">Missile attack on an Iranian refinery near Isfahan.</div>
    </div>
    """

    plans = plans_from_telegram_html(html)

    assert len(plans) == 1
    assert plans[0].message_id == "11"
    assert plans[0].search == "attack energy infrastructure Iran"


def test_flow_mode_keeps_low_signal_posts_for_ai_scoring() -> None:
    html = """
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="Middle_East_Spectator/12"></div>
      <div class="tgme_widget_message_text">General commentary with no concrete event.</div>
      <time datetime="2026-07-30T18:00:00+00:00"></time>
    </div>
    """

    plans = plans_from_telegram_html(html, minimum_signal=0)

    assert len(plans) == 1
    assert plans[0].message_id == "12"
    assert plans[0].signal_score < 2


def test_telegram_plans_are_sorted_chronologically_not_by_html_order() -> None:
    html = """
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="Middle_East_Spectator/22"></div>
      <div class="tgme_widget_message_text">Missile attack on an Iranian refinery.</div>
      <time datetime="2026-07-30T19:00:00+00:00"></time>
    </div>
    <div class="tgme_widget_message_wrap">
      <div class="tgme_widget_message" data-post="Middle_East_Spectator/21"></div>
      <div class="tgme_widget_message_text">Missile attack on an Iranian refinery.</div>
      <time datetime="2026-07-30T18:00:00+00:00"></time>
    </div>
    """

    plans = plans_from_telegram_html(html)

    assert [plan.message_id for plan in plans] == ["21", "22"]


def test_shipping_blockade_maps_to_infrastructure_domain() -> None:
    plan = build_search_plan(
        message_id="200",
        message_url="https://t.me/Middle_East_Spectator/200",
        text="Shipping halted after a blockade near the Strait of Hormuz, Iran.",
    )

    assert plan.event_type == "blockade"
    assert plan.target == "shipping"
    assert plan.country == "Iran"
    assert plan.domain == "INFRASTRUCTURE"
    assert plan.search == "blockade shipping Iran"
