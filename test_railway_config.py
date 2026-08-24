from pathlib import Path
import tomllib


ROOT = Path(__file__).parent


def _load(name: str) -> dict:
    with (ROOT / name).open("rb") as config_file:
        return tomllib.load(config_file)


def test_streamlit_service_has_web_start_and_healthcheck():
    deploy = _load("railway.streamlit.toml")["deploy"]

    assert deploy["startCommand"] == (
        "streamlit run app.py --server.address 0.0.0.0 "
        "--server.port $PORT --server.headless true"
    )
    assert deploy["healthcheckPath"] == "/_stcore/health"


def test_worker_service_runs_without_sqlite_volume_path():
    deploy = _load("railway.worker.toml")["deploy"]

    assert deploy["startCommand"] == "python telegram_multi_worker.py --interval 60"
    assert "/data" not in deploy["startCommand"]


def test_realtime_stream_service_is_isolated_and_requests_one_second_updates():
    deploy = _load("railway.stream.toml")["deploy"]

    assert deploy["startCommand"] == (
        "python realtime_worker.py --refresh-ms 1000 "
        "--autotrader-risk-control-seconds 10 "
        "--autotrader-managed-risk-reaction-seconds 2 "
        "--autotrader-live-close-seconds 2"
    )
    assert "/data" not in deploy["startCommand"]
    assert deploy["restartPolicyType"] == "ON_FAILURE"


def test_legacy_single_service_config_is_removed():
    assert not (ROOT / "railway.toml").exists()
