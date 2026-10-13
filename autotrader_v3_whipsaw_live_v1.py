"""LIVE whipsaw safety overlay: closed 1m only, no trade execution authority.

The modifier can only suppress *increases* or force an opposite target FLAT.
Normal strategy reductions, exits, and loss resets are always allowed.
The detector is persistent/monotonic by canonical 1m bar, with a three-bar
quiet hysteresis. Unknown or stale observations block risk increases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import math

from database import connect
from autotrader_v3_domain import TargetInventoryV3


def _utc(value):
    stamp=value if isinstance(value,datetime) else datetime.fromisoformat(
        str(value).replace("Z","+00:00"))
    if stamp.tzinfo is None:
        stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


@dataclass(frozen=True,slots=True)
class WhipsawEvidenceV3:
    active: bool
    data_ok: bool
    last_bar_time: str | None
    changes: int | None
    efficiency: float | None
    quiet_bars: int
    reason: str


@dataclass(frozen=True,slots=True)
class WhipsawLiveModifierV3:
    actual_inventory: float
    evidence: WhipsawEvidenceV3
    key: str = "whipsaw"

    def apply(self,trader,target:TargetInventoryV3):
        current=float(self.actual_inventory)
        wanted=float(target.amount)
        if self.evidence.data_ok and not self.evidence.active:
            return target,"whipsaw clear; allow strategy"
        cause=("whipsaw active" if self.evidence.active
               else "whipsaw evidence missing/stale")
        # Exit or reduce risk is never blocked. An opposite direction while
        # holding an existing side first goes FLAT, not straight into a flip.
        if abs(current)>1e-12 and wanted*current < -1e-12:
            return TargetInventoryV3(0.0),cause+"; opposite target -> FLAT"
        if abs(wanted)<=abs(current)+1e-10 and (
            abs(wanted)<1e-12 or wanted*current>=0):
            return target,cause+"; risk reduction/exit allowed"
        return TargetInventoryV3(current),cause+"; new entry/ADD blocked"


def ensure_whipsaw_live_schema_v3(db_path="pricegauger.db"):
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS autotrader_v3_whipsaw_live_state(
            trader_id TEXT PRIMARY KEY,
            last_bar_time TEXT,
            active INTEGER NOT NULL DEFAULT 0,
            quiet_bars INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")


def evaluate_whipsaw_live_v3(*,trader_id,bars,now=None,
                             lookback_bars=12,max_direction_changes=6,
                             cooldown_bars=3,db_path="pricegauger.db"):
    """Feed fully closed canonical 1m bars, never quote ticks or forming bars.

    max_direction_changes=6 means seven sign flips in 12 returns triggers
    (the established Live-Sim WHIPSAW rule). A full 30-minute contiguous
    warmup is required. A missed/stale/gapped feed blocks *new* exposure,
    but doesn't stop strategy exits. Only one closed minute advances cooldown.
    """
    lookback=int(lookback_bars)
    threshold=int(max_direction_changes)
    quiet_required=int(cooldown_bars)
    if not (6<=lookback<=30 and 2<=threshold<lookback and 1<=quiet_required<=12):
        raise ValueError("unsafe LIVE whipsaw settings")
    moment=_utc(now or datetime.now(timezone.utc))
    cleaned=[]
    for bar in bars:
        try:
            stamp=_utc(bar.bar_time)
            close=float(bar.close)
        except (TypeError,ValueError,OverflowError,AttributeError):
            continue
        if (math.isfinite(close) and close>0 and
            stamp+timedelta(minutes=1)<=moment):
            cleaned.append((stamp,close))
    cleaned.sort()
    by_time={}
    for stamp,close in cleaned:
        by_time[stamp]=close
    recent=sorted(by_time.items())[-max(31,lookback+1):]
    enough=len(recent)>=max(31,lookback+1)
    recent=recent[-max(31,lookback+1):]
    continuous=(enough and all(
        b[0]-a[0]==timedelta(minutes=1) for a,b in zip(recent,recent[1:])))
    fresh=(bool(recent) and
           timedelta(seconds=0)<=moment-(recent[-1][0]+timedelta(minutes=1))
           <=timedelta(minutes=3))
    if not continuous or not fresh:
        return WhipsawEvidenceV3(
            False,False,recent[-1][0].isoformat() if recent else None,
            None,None,0,"stale/gapped or insufficient 1m closed bars")
    returns=[b[1]/a[1]-1 for a,b in zip(recent[-(lookback+1):],
                                         recent[-lookback:])]
    changes=sum(a*b<0 for a,b in zip(returns,returns[1:]))
    efficiency=abs(sum(returns))/max(1e-12,sum(abs(x) for x in returns))
    raw=changes>threshold and efficiency<0.35
    last_time=recent[-1][0].isoformat()
    ensure_whipsaw_live_schema_v3(db_path)
    with connect(db_path) as db:
        row=db.execute("""
            SELECT last_bar_time,active,quiet_bars
            FROM autotrader_v3_whipsaw_live_state WHERE trader_id=?
        """,(str(trader_id),)).fetchone()
        old_time=str(row["last_bar_time"]) if row and row["last_bar_time"] else None
        active=bool(row["active"]) if row else False
        quiet=int(row["quiet_bars"]) if row else 0
        if old_time is not None and _utc(old_time)>_utc(last_time):
            return WhipsawEvidenceV3(
                active,False,last_time,changes,efficiency,quiet,
                "older bar replay; new entries blocked")
        if old_time!=last_time:
            if raw:
                active=True
                quiet=0
            elif active:
                # Gaps are never counted as multiple quiet bars.
                consecutive=(old_time is not None and
                              _utc(last_time)-_utc(old_time)==timedelta(minutes=1))
                quiet=quiet+1 if consecutive else 0
                if quiet>=quiet_required:
                    active=False
                    quiet=0
            db.execute("""
                INSERT INTO autotrader_v3_whipsaw_live_state(
                    trader_id,last_bar_time,active,quiet_bars)
                VALUES(?,?,?,?)
                ON CONFLICT(trader_id) DO UPDATE SET
                    last_bar_time=excluded.last_bar_time,
                    active=excluded.active,quiet_bars=excluded.quiet_bars,
                    updated_at=CURRENT_TIMESTAMP
            """,(str(trader_id),last_time,int(active),quiet))
    return WhipsawEvidenceV3(
        active,True,last_time,changes,round(efficiency,6),quiet,
        "whipsaw active" if active else "clear")
