from pathlib import Path

from autotrader_health_v1 import _working_order_ids_v1, classify_instance_health_v1


def test_pending_order_escalates_from_yellow_to_red():
    severity, code, _ = classify_instance_health_v1(
        live_armed=True,
        runtime_status="PENDING",
        runtime_detail="waiting",
        runtime_age_seconds=20,
        pending_state="SUBMITTED",
        pending_age_seconds=20,
    )
    assert (severity, code) == ("YELLOW", "ORDER_PENDING")

    severity, code, message = classify_instance_health_v1(
        live_armed=True,
        runtime_status="PENDING",
        runtime_detail="waiting",
        runtime_age_seconds=70,
        pending_state="SUBMITTED",
        pending_age_seconds=70,
    )
    assert (severity, code) == ("RED", "ORDER_STUCK")
    assert "70 s" in message




def test_verified_working_order_stays_yellow_even_when_old():
    severity, code, message = classify_instance_health_v1(
        live_armed=True,
        runtime_status="PENDING",
        runtime_detail="actual=-5 expected=0 pending=waiting",
        runtime_age_seconds=7200,
        pending_state="SUBMITTED",
        pending_age_seconds=7200,
        broker_working=True,
    )
    assert (severity, code) == ("YELLOW", "ORDER_WORKING")
    assert "fortsatt aktiv hos Saxo" in message
    assert "venter på utførelse" in message


def test_working_order_read_uses_exact_saxo_order_ids_and_fails_unknown():
    class Client:
        def __init__(self, payload):
            self.payload = payload
        def _get(self, path, params=None):
            assert path == "port/v1/orders/me"
            assert params == {"$top": 1000}
            if isinstance(self.payload, Exception):
                raise self.payload
            return self.payload

    class Broker:
        def __init__(self, payload):
            self.client = Client(payload)

    assert _working_order_ids_v1(
        Broker({"Data": [{"OrderId": "5449985173"}, {"OrderId": "other"}]})
    ) == {"5449985173", "other"}
    assert _working_order_ids_v1(Broker(RuntimeError("broker unavailable"))) is None


def test_unknown_and_blocked_execution_are_immediately_red():
    unknown = classify_instance_health_v1(
        live_armed=True,
        runtime_status="PENDING",
        runtime_detail="",
        runtime_age_seconds=1,
        pending_state="UNKNOWN",
        pending_age_seconds=1,
    )
    blocked = classify_instance_health_v1(
        live_armed=True,
        runtime_status="BLOCKED",
        runtime_detail="precheck rejected",
        runtime_age_seconds=1,
        pending_state=None,
        pending_age_seconds=None,
    )
    assert unknown[:2] == ("RED", "ORDER_UNKNOWN")
    assert blocked[:2] == ("RED", "RUNTIME_BLOCKED")




def test_closed_saxo_market_is_yellow_waiting_not_failure():
    severity, code, message = classify_instance_health_v1(
        live_armed=True,
        runtime_status="MANAGING",
        runtime_detail="target=0 actual=0",
        runtime_age_seconds=5,
        pending_state=None,
        pending_age_seconds=None,
        market_open=False,
        market_state="Closed",
    )
    assert (severity, code) == ("YELLOW", "MARKET_CLOSED")
    assert "Markedet er stengt" in message
    assert "Closed" in message


def test_working_order_in_closed_market_is_explicitly_yellow():
    severity, code, message = classify_instance_health_v1(
        live_armed=True,
        runtime_status="PENDING",
        runtime_detail="waiting",
        runtime_age_seconds=7200,
        pending_state="SUBMITTED",
        pending_age_seconds=7200,
        broker_working=True,
        market_open=False,
        market_state="Closed",
    )
    assert (severity, code) == ("YELLOW", "ORDER_WORKING_MARKET_CLOSED")
    assert "venter på utførelse" in message


def test_healthy_live_instance_is_green():
    assert classify_instance_health_v1(
        live_armed=True,
        runtime_status="MANAGING",
        runtime_detail="target=0 actual=0",
        runtime_age_seconds=5,
        pending_state=None,
        pending_age_seconds=None,
    ) == ("GREEN", None, None)


def test_global_build_chrome_mounts_read_only_autotrader_widget():
    build = Path("build_info.py").read_text(encoding="utf-8")
    widget = Path("autotrader_status_widget_v1.py").read_text(encoding="utf-8")
    assert "render_autotrader_status_widget_v1()" in build
    assert 'run_every="10s"' in widget
    assert "position:fixed" in widget
    assert "localStorage" in widget
    assert "alert_fingerprint" in widget
    assert "conic-gradient" in widget
    assert "filter(x=>x.live_armed)" in widget
    assert "healthGradient" in widget
    assert "place_order(" not in widget
    assert "set_live_enabled_v3" not in widget
