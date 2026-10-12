"""One-second canonical bar wakeup with bounded Saxo API safety cadence."""
from datetime import datetime,timedelta,timezone
import sqlite3
from pathlib import Path

import autotrader_v3_live_bar_watcher_v1 as watcher
import worker


BASE=datetime(2026,10,12,20,0,tzinfo=timezone.utc)


def test_canonical_watcher_detects_only_closed_bars_by_instrument(tmp_path):
    db=str(tmp_path/"bars.db")
    with sqlite3.connect(db) as con:
        con.execute("""CREATE TABLE pg_v2_market_bars_1m(
            instrument_id INTEGER,bar_time TEXT,PRIMARY KEY(instrument_id,bar_time))""")
        for instrument,at in [
            (4912,BASE-timedelta(minutes=3)),
            (4912,BASE-timedelta(minutes=1)),
            (4912,BASE),  # forming, MUST NEVER trigger decisions
            (5020,BASE-timedelta(minutes=2)),
        ]:
            con.execute("INSERT INTO pg_v2_market_bars_1m VALUES (?,?)",
                        (instrument,at.isoformat()))
    current=watcher.closed_instrument_cursors_v3(db_path=db,now=BASE)
    assert current==(
        (4912,(BASE-timedelta(minutes=1)).isoformat()),
        (5020,(BASE-timedelta(minutes=2)).isoformat()),
    )
    assert watcher.has_new_closed_bar_v3((),current)
    assert not watcher.has_new_closed_bar_v3(current,current)
    newer=watcher.closed_instrument_cursors_v3(db_path=db,
                                                now=BASE+timedelta(minutes=1))
    assert watcher.has_new_closed_bar_v3(current,newer)
    assert newer[0][1]==BASE.isoformat()


def test_expired_bars_or_market_close_do_not_create_phantom_triggers():
    earlier=((1,"2026-10-12T20:01:00+00:00"),(2,"2026-10-12T20:01:00+00:00"))
    assert not watcher.has_new_closed_bar_v3(earlier,())
    assert not watcher.has_new_closed_bar_v3(earlier,earlier[:1])
    assert watcher.has_new_closed_bar_v3(earlier,earlier+((3,"2026-10-12T20:02:00+00:00"),))


class StopAfter:
    def __init__(self,samples):
        self.samples=samples
        self.ticks=0
        self.waits=[]
    def is_set(self):
        return self.ticks>=len(self.samples)
    def wait(self,duration):
        self.waits.append(duration)
        self.ticks+=1


def test_v3_full_cycle_on_new_bars_but_not_each_second(monkeypatch):
    bar1=((7,"2026-10-12T20:00:00+00:00"),)
    bar2=((7,"2026-10-12T20:01:00+00:00"),)
    timeline=[(),(),bar1,bar1,bar1,bar2]+[bar2]*32
    stop=StopAfter(timeline)
    cycles=[]
    monkeypatch.setattr(worker.time,"monotonic",lambda:float(stop.ticks))
    monkeypatch.setattr(
        watcher,"closed_instrument_cursors_v3",
        lambda **_: timeline[stop.ticks],
    )
    monkeypatch.setattr(worker,"run_v3_live_cycle_v1",
                        lambda **kwargs:cycles.append(stop.ticks) or 0)
    worker.run_v3_live_fast_loop_v1(
        db_path="unused.db",stop_event=stop,interval_seconds=1,
    )
    # Initial reconcile immediately, new bar on ticks 2 and 5, then
    # 30-second Saxo reconciliation heartbeat even if no new bars.
    assert cycles==[0,2,5,35]
    assert len(stop.waits)==len(timeline)
    assert min(stop.waits)>=0.1


def test_market_stale_still_reconciles_manual_positions_every_30s(monkeypatch):
    stop=StopAfter([()] * 66)
    cycles=[]
    monkeypatch.setattr(worker.time,"monotonic",lambda:float(stop.ticks))
    monkeypatch.setattr(watcher,"closed_instrument_cursors_v3",lambda **_:())
    monkeypatch.setattr(worker,"run_v3_live_cycle_v1",
                        lambda **kwargs:cycles.append(stop.ticks) or 0)
    worker.run_v3_live_fast_loop_v1(
        db_path="unused.db",stop_event=stop,interval_seconds=1)
    assert cycles==[0,30,60]


def test_probe_failure_does_not_hot_loop_saxo(monkeypatch):
    stop=StopAfter([()] * 33)
    cycles=[]
    monkeypatch.setattr(worker.time,"monotonic",lambda:float(stop.ticks))
    def broken(**_):
        raise RuntimeError("database unreachable")
    monkeypatch.setattr(watcher,"closed_instrument_cursors_v3",broken)
    monkeypatch.setattr(worker,"run_v3_live_cycle_v1",
                        lambda **kwargs:cycles.append(stop.ticks) or 0)
    worker.run_v3_live_fast_loop_v1(
        db_path="unavailable.db",stop_event=stop,interval_seconds=1)
    assert cycles==[0,30]


def test_no_tick_based_order_execution_added_and_the_feed_is_streaming():
    source=Path("worker.py").read_text()
    stream=Path("saxo_streaming.py").read_text()
    assert "V3_LIVE_INTERVAL_SECONDS = 1" in source
    assert "V3_LIVE_RECONCILE_SECONDS = 30" in source
    assert "closed_instrument_cursors_v3" in source
    assert "DEFAULT_REFRESH_MS = 1000" in stream
    # Same guarded, single-threaded LIVE mutation chain as before.
    assert "run_v3_live_cycle_v1(db_path=str(db_path))" in source
    assert "include_v3_live=False" in source
