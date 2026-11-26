"""Causal dynamic structure plugin. Research only; no broker or durable settings.
Scales are rolling elapsed-time windows, not candle intervals. Pivots confirmed
by a subsequent minimum reversal, never labelled tradable at their extreme time.
"""
from collections import deque
from dataclasses import dataclass
from math import isfinite
from statistics import median

@dataclass(frozen=True)
class StructureConfig:
    side:str="LONG"
    sensitivity:float=2.
    breakout:float=1.
    flatten_ratio:float=.4
    def __post_init__(self):
        if self.side not in ("LONG","SHORT") or not all(isfinite(v) for v in (self.sensitivity,self.breakout,self.flatten_ratio)) or not (0.5<=self.sensitivity<=8 and 0<=self.breakout<=20 and 0<=self.flatten_ratio<=1):
            raise ValueError("invalid structure config")

class Structure:
    def __init__(self,config):
        self.config=config
        self.sign=1 if config.side=="LONG" else -1
        self.reset()
    def reset(self):
        self.points=deque()
        self.last=None
        self.bucket=None
        self.direction=0
        self.extreme=None
        self.highs=deque(maxlen=3)
        self.lows=deque(maxlen=3)
        self.level=None
        self.used=None
        self.focus="WARMUP"
    def update(self,at,mid):
        if at.tzinfo is None or not isfinite(mid) or mid<=0:
            raise ValueError("invalid observation")
        t=at.timestamp();p=self.sign*mid
        if self.last is not None:
            dt=t-self.last
            if dt<=0:raise ValueError("unordered observations")
            if dt>4:self.reset()
        self.last=t
        # Last observed price of each completed 10-second bucket. No fill.
        bucket=int(t)//10
        if self.bucket is not None and bucket!=self.bucket[0]:
            self.points.append((self.bucket[0]*10+10,self.bucket[1]))
        self.bucket=(bucket,p)
        while self.points and self.points[0][0]<t-1820:self.points.popleft()
        pts=list(self.points)
        def slope(window):
            recent=[v for ts,v in pts if ts>t-window]
            if len(recent)<window//10-2:return None
            half=len(recent)//2
            a=recent[:half];b=recent[half:]
            return (a[-1]-a[0],b[-1]-b[0])
        slopes={w:slope(w*60) for w in (30,10,5,2)}
        noise=median(abs(b[1]-a[1]) for a,b in zip(pts[-30:-1],pts[-29:])) if len(pts)>=30 else None
        if noise is None or slopes[30] is None:
            self.focus="WARMUP"
            return self.trace(False,False,slopes,None)
        # 30/10 minute trend exhaustion, then 5/2 minute constructive turn.
        # Direct jump allowed if all evidence is present on the same quote.
        def easing(w):
            s=slopes[w]
            return s is not None and s[0]<0 and s[1]>=self.config.flatten_ratio*s[0]
        def positive(w):
            s=slopes[w]
            return s is not None and s[1]>max(noise,0.25)
        context=easing(30) or easing(10) or positive(30)
        self.focus=("ARMED" if context and positive(5) and positive(2)
                    else "PREPARE" if context and positive(5)
                    else "WATCH" if context else "30M")
        turn=max(1.,self.config.sensitivity*noise)
        if self.extreme is None:self.extreme=p
        peak_exit=False
        if self.direction==0:
            if abs(p-self.extreme)>=turn:
                self.direction=1 if p>self.extreme else -1
                self.extreme=p
        elif self.direction==1:
            if p>self.extreme:self.extreme=p
            elif self.extreme-p>=turn:
                self.highs.append(self.extreme)
                peak_exit=True
                self.direction=-1;self.extreme=p
        else:
            if p<self.extreme:self.extreme=p
            elif p-self.extreme>=turn:
                self.lows.append(self.extreme)
                if len(self.highs)>=2 and self.highs[-1]<self.highs[-2]:
                    self.level=self.highs[-1]
                else:self.level=None
                self.direction=1;self.extreme=p
        entry=False
        if self.level is not None and self.focus=="ARMED" and p>=self.level+self.config.breakout and self.level!=self.used:
            self.used=self.level;entry=True
        return self.trace(entry,peak_exit,slopes,turn)
    def trace(self,entry,exit,slopes,turn):
        return dict(focus=self.focus,entry=entry,exit=exit,
            level=None if self.level is None else self.sign*self.level,
            turn=turn,slopes=slopes,highs=tuple(self.sign*v for v in self.highs),
            lows=tuple(self.sign*v for v in self.lows))
