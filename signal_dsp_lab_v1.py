"""Causal return-domain signal processors for research only.
No broker, settings persistence, order authority, or LIVE strategy integration.
The signal is observed midpoint change per elapsed second, in index points/s.
No interpolation across gaps. Each stage has its own envelope and gate latch.
"""
from dataclasses import dataclass
from math import exp,isfinite

KINDS=("gate","compressor","expander")

@dataclass(frozen=True)
class Stage:
    kind:str
    threshold:float=1.
    ratio:float=3.
    attack_s:float=1.
    release_s:float=5.
    hysteresis:float=.2

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError("unknown processor")
        vals=(self.threshold,self.ratio,self.attack_s,self.release_s,self.hysteresis)
        if not all(isfinite(x) for x in vals) or not (
            self.threshold>0 and 1<=self.ratio<=20 and self.attack_s>0
            and self.release_s>0 and 0<=self.hysteresis<1):
            raise ValueError("invalid processor parameters")

@dataclass
class State:
    envelope:float=0.
    opened:bool=False

def process_sample(value,dt,stage,state):
    """One causal detector and gain computer; audio-style dynamics in linear units."""
    if not isfinite(value) or not isfinite(dt) or dt<=0:
        raise ValueError("invalid signal")
    level=abs(value)
    tau=stage.attack_s if level>state.envelope else stage.release_s
    state.envelope=level+(state.envelope-level)*exp(-dt/tau)
    e=state.envelope
    t=stage.threshold
    if stage.kind=="gate":
        if e>=t:
            state.opened=True
        elif e<t*(1-stage.hysteresis):
            state.opened=False
        gain=1. if state.opened else 0.
    elif stage.kind=="compressor":
        gain=(t/e)**(1-1/stage.ratio) if e>t else 1.
    else:
        # Downward expander: attenuate below threshold; never boost large moves.
        gain=(e/t)**(stage.ratio-1) if e<t and stage.ratio>1 else 1.
    return value*gain,gain

def process_quotes(quotes,stages,*,max_gap_s=4.):
    """Use only preceding and current genuine quotes; return trace, not prices for execution."""
    stages=tuple(stages)
    if len(stages)>8 or not isfinite(max_gap_s) or max_gap_s<=0:
        raise ValueError("invalid chain")
    states=[State() for _ in stages]
    previous=None
    for q in quotes:
        if q.at.tzinfo is None or not isfinite(q.mid) or q.mid<=0:
            raise ValueError("invalid quote")
        dt=(q.at-previous.at).total_seconds() if previous else None
        if dt is not None and dt<=0:
            raise ValueError("unordered quotes")
        if previous is None or dt>max_gap_s:
            states=[State() for _ in stages]
            yield dict(at=q.at,mid=q.mid,raw=None,processed=None,gains=(),envelopes=(),gap=True)
        else:
            value=(q.mid-previous.mid)/dt
            raw=value
            gains=[]
            envelopes=[]
            for stage,state in zip(stages,states):
                value,gain=process_sample(value,dt,stage,state)
                gains.append(gain)
                envelopes.append(state.envelope)
            yield dict(at=q.at,mid=q.mid,raw=raw,processed=value,gains=tuple(gains),
                       envelopes=tuple(envelopes),gap=False)
        previous=q
