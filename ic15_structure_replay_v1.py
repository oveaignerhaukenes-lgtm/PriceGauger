"""Common executable-quote comparison of three predeclared research modes.
Only the next observed bid/ask can fill. No real order calls, account P&L,
commission, funding, extra slippage or assumed immediate trigger-tick fill.
"""
from dataclasses import dataclass
from autotrader_impulse_catcher_v14 import ImpulseCatcherV14
from ic15_structure_v1 import Structure

MODES=("IC14","STRUCTURE","STRUCTURE_HOLD")

@dataclass(frozen=True)
class Result:
    mode:str
    signals:int
    trades:int
    points:float
    unfinished:int
    missed:int
    warmup:int
    drawdown_points:float

def compare(quotes,config,structure_config,*,start,delay_s=1.):
    q=tuple(quotes)
    if not 0<delay_s<=10 or config.side!=structure_config.side or getattr(config,"research_unclamped_entry",False):
        raise ValueError("invalid replay config")
    if any(a.at>=b.at for a,b in zip(q,q[1:])):
        raise ValueError("unordered observations")
    return [run(q,config,structure_config,mode,start,delay_s) for mode in MODES]

def run(quotes,cfg,sc,mode,start,delay_s):
    geometry=Structure(sc)
    model=ImpulseCatcherV14(config=cfg)
    sign=1 if cfg.side=="LONG" else -1
    pending=None;opened=None;signals=trades=missed=warmup=0
    points=peak=drawdown=0.
    previous=None
    for q in quotes:
        s=geometry.update(q.at,q.mid)
        gap=previous is not None and (q.at-previous).total_seconds()>4
        previous=q.at
        if q.at<start:
            # Identical prehistory, all candidates remain FLAT.
            model.on_quote(q.at,q.bid,q.ask,allow_entry=False)
            continue
        if s["focus"]=="WARMUP":warmup+=1
        if gap and pending is not None:
            missed+=1;pending=None
            if opened is None:
                model=ImpulseCatcherV14(config=cfg)
        if pending is not None:
            kind,t=pending
            elapsed=(q.at-t).total_seconds()
            if elapsed>=delay_s:
                pending=None
                if elapsed>delay_s+3:
                    missed+=1
                    if kind=="EXIT" and opened is not None:break
                    model=ImpulseCatcherV14(config=cfg)
                elif kind=="ENTRY":
                    opened=q.ask if sign==1 else q.bid
                    if mode!="IC14":
                        model.target=cfg.side;model.entry_mid=model.extreme=q.mid
                        model.entered_at=model.last_extreme_at=q.at
                elif opened is not None:
                    points+=sign*((q.bid if sign==1 else q.ask)-opened)
                    peak=max(peak,points);drawdown=max(drawdown,peak-points)
                    trades+=1;opened=None
        if opened is not None:
            equity=points+sign*((q.bid if sign==1 else q.ask)-opened)
            peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
        if mode=="IC14":
            d=model.on_quote(q.at,q.bid,q.ask,allow_entry=opened is None and pending is None)
            if pending is None:
                if d is not None and d.target==cfg.side and opened is None:
                    pending=("ENTRY",q.at);signals+=1
                elif d is not None and d.target=="FLAT" and opened is not None:
                    pending=("EXIT",q.at)
        else:
            # Keep original IC14 exits for hybrid, not a second entry engine.
            d=model.on_quote(q.at,q.bid,q.ask,allow_entry=False)
            if pending is None:
                if opened is not None and (gap or (mode=="STRUCTURE" and s["exit"]) or
                        (d is not None and d.target=="FLAT" and (mode=="STRUCTURE_HOLD" or d.reason=="URGENT_REVERSAL"))):
                    pending=("EXIT",q.at)
                elif opened is None and s["entry"] and q.ask-q.bid<=cfg.maximum_spread_points:
                    pending=("ENTRY",q.at);signals+=1
    return Result(mode,signals,trades,round(points,3),int(opened is not None),
                  missed+int(pending is not None),warmup,round(drawdown,3))
