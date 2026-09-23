from pathlib import Path

def test_v3_heartbeat_precedes_broker_setup_and_failures_are_persisted():
    s=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    heartbeat=s.index('_record_runtime(e.pilot_key,"RUNNING","worker cycle entered"')
    broker=s.index("configured_live_pilot_client_v3()")
    assert heartbeat < broker
    assert '_record_runtime(e.pilot_key,"FAILED"' in s
