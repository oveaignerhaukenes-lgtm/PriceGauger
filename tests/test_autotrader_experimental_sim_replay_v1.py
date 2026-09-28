from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from autotrader_experimental_sim_replay_v1 import replay_macd_a_variants


def test_macd_a_sim_variants_share_closed_canonical_clock():
    start = datetime(2026, 9, 27, tzinfo=timezone.utc)
    bars = [
        SimpleNamespace(
            bar_time=(start + timedelta(minutes=i)).isoformat(),
            close=20000 + i * .8 + (i % 13) * 1.5,
        )
        for i in range(180)
    ]
    result = replay_macd_a_variants(bars)
    assert set(result) == {
        "MACD-A", "MACD-A-PYR", "MACD-A(1-30)", "MACD-A-PYR(1-30)",
    }
    assert all(len(frame) == 180 and frame["TARGET"].notna().all() for frame in result.values())
    assert result["MACD-A"]["TARGET"].equals(result["MACD-A(1-30)"]["TARGET"])
    for name in ("MACD-A-PYR", "MACD-A-PYR(1-30)"):
        assert result[name]["TARGET"].abs().max() <= 1.0
