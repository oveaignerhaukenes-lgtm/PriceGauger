"""Configurable IC v1.4: one causal tick model for LIVE and signal preview.
No broker calls. Optional indicators operate on observed midquotes, not
invented candle data. Normal hold/exit filters never veto urgent/gap exits.
"""
from dataclasses import dataclass, field, asdict
from datetime import timedelta
from math import isfinite
from statistics import median
from collections import deque
import json
from autotrader_impulse_catcher_v1 import ImpulseCatcher, ImpulseCatcherConfig, ImpulseCatcherDecision

KEYS=frozenset("impulse-catcher-"+s+"-v1-4" for s in ("long","short"))
INDICATORS=("velocity","acceleration","efficiency","macd","stochastic","rsi","structure")
# Bounds and steps also define the UI. Units are seconds, points or ratios.
SLIDERS={
 "fast_window":(3,15,1,5),"slow_window":(6,30,1,12),
 "min_impulse_points":(1.,40.,.5,9.),"entry_gain_points":(-20.,20.,.5,0.),"relative_impulse_multiple":(1.,8.,.25,3.),
 "minimum_directional_efficiency":(.1,1.,.05,.78),
 "maximum_spread_points":(.5,15.,.5,5.),"spread_impulse_multiple":(1.,10.,.5,4.),
 "entry_confirmation_seconds":(0,15,1,3),"minimum_hold_seconds":(0,90,1,15),
 "exhaustion_seconds":(0,45,1,8),"minimum_retrace_points":(1.,30.,.5,5.),
 "retrace_fraction":(.05,.8,.05,.3),"exit_noise_multiple":(0.,10.,.5,4.),
 "exit_confirmation_seconds":(0,20,1,5),"urgent_retrace_points":(5.,40.,.5,12.),
 "cooldown_seconds":(0,180,1,5),"dynamic_hold_pct":(0,100,5,0),"dynamic_hold_seconds":(30,600,15,120),"atr_period":(3,24,1,14),
 "atr_entry_multiple":(0.,5.,.25,0.),"atr_exit_multiple":(0.,5.,.25,0.),
 "velocity_period":(3,60,1,10),"acceleration_period":(3,60,1,10),
 "efficiency_period":(3,60,1,14),"stochastic_period":(3,60,1,14),
 "rsi_period":(3,60,1,14),"structure_period":(3,60,1,14),
 "macd_fast":(3,30,1,12),"macd_slow":(8,60,1,26),"macd_signal":(2,30,1,9),
 "velocity_threshold":(0.,5.,.05,0.),"acceleration_threshold":(0.,20.,.5,0.),
 "efficiency_threshold":(0.,1.,.05,0.),"macd_threshold":(0.,10.,.1,0.),
 "stochastic_threshold":(0.,.9,.05,0.),"rsi_threshold":(0.,.9,.05,0.),
}
DEFAULTS={k:v[3] for k,v in SLIDERS.items()}
DEFAULTS.update(entry_indicators=[],hold_indicators=[],exit_indicators=[])
def normalize_settings(raw):
    if not isinstance(raw,dict) or set(raw)-set(DEFAULTS):
        raise ValueError("unknown IC v1.4 settings")
    out={}
    for k,(lo,hi,step,default) in SLIDERS.items():
        v=raw.get(k,default)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) or not lo<=v<=hi:
            raise ValueError("invalid "+k)
        if isinstance(default,int) and int(v)!=v:
            raise ValueError("integer required "+k)
        out[k]=int(v) if isinstance(default,int) else float(v)
    for k in ("entry_indicators","hold_indicators","exit_indicators"):
        v=raw.get(k,[])
        if not isinstance(v,(list,tuple)) or any(x not in INDICATORS for x in v):
            raise ValueError("unknown indicator "+k)
        out[k]=[x for x in INDICATORS if x in v]
    if out["fast_window"]>=out["slow_window"]:
        raise ValueError("fast window must be smaller than slow")
    if out["macd_fast"]>=out["macd_slow"]:
        raise ValueError("MACD fast must be smaller than slow")
    if out["urgent_retrace_points"]<out["minimum_retrace_points"]:
        raise ValueError("urgent threshold must not be below normal")
    return out

def config_v14(side,raw=None):
    d=normalize_settings(raw or {})
    return ConfigV14(side=side,windows_seconds=(d.pop("fast_window"),d.pop("slow_window")),
                     history_seconds=150,quote_gap_seconds=8.,**d)

@dataclass(frozen=True,slots=True)
class ConfigV14(ImpulseCatcherConfig):
    entry_gain_points:float=0.
    # Never accepted by normalize_settings or durable LIVE settings.
    research_unclamped_entry:bool=False
    entry_confirmation_seconds:int=3
    minimum_hold_seconds:int=15
    dynamic_hold_pct:int=0
    dynamic_hold_seconds:int=120
    atr_period:int=14
    atr_entry_multiple:float=0.
    atr_exit_multiple:float=0.
    velocity_period:int=10
    acceleration_period:int=10
    efficiency_period:int=14
    stochastic_period:int=14
    rsi_period:int=14
    structure_period:int=14
    macd_fast:int=12
    macd_slow:int=26
    macd_signal:int=9
    velocity_threshold:float=0.
    acceleration_threshold:float=0.
    efficiency_threshold:float=0.
    macd_threshold:float=0.
    stochastic_threshold:float=0.
    rsi_threshold:float=0.
    entry_indicators:tuple=()
    hold_indicators:tuple=()
    exit_indicators:tuple=()

def _ema(values,n):
    v=values[0]
    a=2/(n+1)
    for x in values[1:]:
        v+=a*(x-v)
    return v

def indicator_values(samples,at,cfg):
    # Periods are observed ticks. ATR alone uses completed 5s buckets.
    p=[v for _,v in samples]
    out={k:None for k in INDICATORS}
    out["atr"]=None
    for k in ("velocity","efficiency","stochastic"):
        n=getattr(cfg,k+"_period")
        if len(p)<n+1:continue
        recent=p[-n-1:]
        delta=recent[-1]-recent[0]
        path=sum(abs(b-a) for a,b in zip(recent,recent[1:]))
        if k=="velocity":out[k]=delta/n
        elif k=="efficiency":out[k]=delta/path if path else 0.
        else:out[k]=2*(recent[-1]-min(recent))/(max(recent)-min(recent))-1 if max(recent)>min(recent) else 0.
    n=cfg.rsi_period
    if len(p)>=n+1:
        moves=[b-a for a,b in zip(p,p[1:])]
        gain=sum(max(0.,v) for v in moves[:n])/n
        loss=sum(max(0.,-v) for v in moves[:n])/n
        for v in moves[n:]:
            gain=(gain*(n-1)+max(0.,v))/n;loss=(loss*(n-1)+max(0.,-v))/n
        out["rsi"]=(gain-loss)/(gain+loss) if gain+loss else 0.
    n=cfg.acceleration_period
    if len(p)>=2*n+1:
        out["acceleration"]=(p[-1]-p[-n-1])-(p[-n-1]-p[-2*n-1])
    n=cfg.structure_period
    if len(p)>=2*n:
        old=p[-2*n:-n];new=p[-n:]
        out["structure"]=1. if max(new)>max(old) and min(new)>min(old) else -1. if max(new)<max(old) and min(new)<min(old) else 0.
    if len(p)>=cfg.macd_slow+cfg.macd_signal:
        fast=slow=p[0];hist=[]
        for v in p:
            fast+=(2/(cfg.macd_fast+1))*(v-fast);slow+=(2/(cfg.macd_slow+1))*(v-slow);hist.append(fast-slow)
        out["macd"]=hist[-1]-_ema(hist,cfg.macd_signal)
    atr_period=cfg.atr_period
    # True range on genuine completed 5-second midpoint OHLC buckets.
    # Reject missing buckets; never bridge a feed outage or interpolate.
    buckets={}
    boundary=int(at.timestamp())//5
    for t,v in samples:
        k=int(t.timestamp())//5
        if k<boundary:
            buckets.setdefault(k,[]).append(v)
    keys=range(boundary-atr_period-1,boundary)
    if all(k in buckets and len(buckets[k])>=3 for k in keys):
        tr=[]
        prev=buckets[boundary-atr_period-1][-1]
        for k in range(boundary-atr_period,boundary):
            vals=buckets[k]
            tr.append(max(max(vals)-min(vals),abs(max(vals)-prev),abs(min(vals)-prev)))
            prev=vals[-1]
        out["atr"]=sum(tr)/len(tr)
    return out

@dataclass(slots=True)
class ImpulseCatcherV14(ImpulseCatcher):
    entered_at:object=None
    candidate_at:object=None
    retrace_at:object=None
    settings_key:str=""
    trace:dict=field(default_factory=dict)

    def on_quote(self,at,bid,ask,*,allow_entry=True):
        cfg=self.config
        bid,ask=float(bid),float(ask)
        if at.tzinfo is None or not(isfinite(bid) and isfinite(ask) and 0<bid<=ask):
            raise ValueError("invalid BBO")
        if self.samples and at<=self.samples[-1][0]:
            return None
        mid=(bid+ask)/2;spread=ask-bid;sign=1 if cfg.side=="LONG" else -1
        elapsed=(at-self.samples[-1][0]).total_seconds() if self.samples else 0.
        gap=elapsed>cfg.quote_gap_seconds
        previous_candidate=self.candidate_at
        previous_confirm=(at-previous_candidate).total_seconds()-elapsed if previous_candidate is not None else None
        if elapsed>2.:
            # Confirmation requires observed persistence, not elapsed silence.
            self.candidate_at=self.retrace_at=None
        self.trace={"mid":mid,"target":self.target,"entry_ratio":None,"retrace":None,"exit_threshold":None,"urgent":None,"normal_price":None,"urgent_price":None,"entry_price":None,"entry_base_price":None,"entry_base_threshold":None,"entry_base_source":None,"entry_gain_applied":None,"entry_fast_price":None,"entry_slow_price":None,"entry_threshold":None,"entry_window":None,"entry_confirm_elapsed":None,"hold_remaining":None,"exit_confirm_elapsed":None,"gate_detail":"","gate":"WARMUP","entry_confirm_required":cfg.entry_confirmation_seconds,"entry_rejected":False,"entry_reject_elapsed":None,"entry_reject_reason":None,"threshold_source":None,"entry_efficiency":None,"entry_efficiency_required":cfg.minimum_directional_efficiency}
        def rejected(reason):
            if previous_candidate is not None:
                self.trace.update(entry_rejected=True,entry_reject_elapsed=max(0.,previous_confirm),entry_reject_reason=reason)
        if elapsed>2.:
            rejected("Datagap: bekreftelsen avbrutt")
        if gap:
            self.samples.clear()
            self.candidate_at=self.retrace_at=None
        self.samples.append((at,mid))
        while self.samples and (at-self.samples[0][0]).total_seconds()>cfg.history_seconds:
            self.samples.popleft()
        def flat(reason):
            self.target="FLAT";self.last_exit_at=at
            self.entry_mid=self.extreme=self.last_extreme_at=self.entered_at=self.candidate_at=self.retrace_at=None
            self.trace.update(target="FLAT",gate=reason)
            return ImpulseCatcherDecision("FLAT",reason,mid,at)
        if gap:
            if self.target!="FLAT":return flat("QUOTE_GAP_FLAT")
            self.last_exit_at=at;return None
        vals=indicator_values(self.samples,at,cfg)
        self.trace.update(vals)
        def favorable(k):return vals[k] is not None and sign*vals[k]>getattr(cfg,k+'_threshold',0.)
        def adverse(k):return vals[k] is None or sign*vals[k]<-getattr(cfg,k+'_threshold',0.)
        atr=vals["atr"]
        if self.target!="FLAT":
            if self.entered_at is None:self.entered_at=at
            if self.extreme is None or sign*(mid-self.extreme)>0:
                self.extreme=mid;self.last_extreme_at=at;self.retrace_at=None
            if self.last_extreme_at is None:self.last_extreme_at=at
            travelled=max(0.,sign*(self.extreme-(self.entry_mid if self.entry_mid is not None else mid)))
            retrace=sign*(self.extreme-mid)
            recent=[(t,p) for t,p in self.samples if t>=at-timedelta(seconds=20)]
            steps=[abs(b[1]-a[1]) for a,b in zip(recent,recent[1:]) if 0<(b[0]-a[0]).total_seconds()<=2]
            threshold=max(cfg.minimum_retrace_points,cfg.retrace_fraction*travelled,2*spread,
                          cfg.exit_noise_multiple*median(steps) if steps else 0.,
                          cfg.atr_exit_multiple*atr if atr is not None else 0.)
            urgent=max(cfg.urgent_retrace_points,.35*travelled,3*spread)
            # Earn tolerance through favorable extension, not mere time in position.
            # A stalled or losing entry cannot accumulate maturity by waiting.
            extension_age=max(0.,(self.last_extreme_at-self.entered_at).total_seconds())
            maturity=min(1.,extension_age/cfg.dynamic_hold_seconds)*min(1.,travelled/max(1.,4*spread,2*cfg.minimum_retrace_points))
            dynamic=cfg.dynamic_hold_pct/100.*maturity
            base_threshold=threshold
            release=cfg.exit_confirmation_seconds
            if dynamic>0:
                threshold=max(base_threshold,min(urgent,base_threshold*(1.+dynamic)))
                release+=20.*dynamic
            self.trace.update(retrace=retrace,exit_threshold=threshold,urgent=urgent,extreme=self.extreme,normal_price=self.extreme-sign*threshold,urgent_price=self.extreme-sign*urgent,gate="HOLD",dynamic_hold_strength=dynamic,dynamic_hold_maturity=maturity,dynamic_hold_base_threshold=base_threshold,dynamic_hold_release=release)
            if retrace>=urgent:return flat("URGENT_REVERSAL")
            if retrace>=threshold:
                self.retrace_at=self.retrace_at or at
            else:self.retrace_at=None
            normal=(self.retrace_at is not None and
                    (at-self.retrace_at).total_seconds()>=release and
                    (at-self.entered_at).total_seconds()>=cfg.minimum_hold_seconds and
                    (at-self.last_extreme_at).total_seconds()>=cfg.exhaustion_seconds)
            # Diagnostic only: expose the exact normal-exit gates without changing the decision.
            self.trace["hold_remaining"]=max(0.,cfg.minimum_hold_seconds-(at-self.entered_at).total_seconds())
            self.trace["exit_confirm_elapsed"]=(at-self.retrace_at).total_seconds() if self.retrace_at is not None else 0.
            reasons=[]
            if retrace<threshold:reasons.append("Retrace under terskel")
            if self.trace["hold_remaining"]>0:reasons.append("Minimum hold")
            if (at-self.last_extreme_at).total_seconds()<cfg.exhaustion_seconds:reasons.append("Nytt ekstrempunkt nylig")
            if self.trace["exit_confirm_elapsed"]<release:reasons.append("Exit-bekreftelse")
            if any(favorable(k) for k in cfg.hold_indicators):reasons.append("Hold-indikator i medgang")
            if not all(adverse(k) for k in cfg.exit_indicators):reasons.append("Exit-indikator ikke bekreftet")
            self.trace["gate_detail"]=" · ".join(reasons)
            if normal and not any(favorable(k) for k in cfg.hold_indicators) and all(adverse(k) for k in cfg.exit_indicators):
                return flat("CONFIRMED_EXIT")
            return None
        if not allow_entry:
            rejected("Venter på bekreftet FLAT")
            self.candidate_at=None;self.trace['gate']='WAIT_BROKER_FLAT';return None
        if spread>cfg.maximum_spread_points or (self.last_exit_at and (at-self.last_exit_at).total_seconds()<cfg.cooldown_seconds):
            reason="Spread over maks" if spread>cfg.maximum_spread_points else "Cooldown etter exit"
            rejected(reason)
            self.trace["gate_detail"]=reason
            self.candidate_at=None;self.trace["gate"]="SPREAD_OR_COOLDOWN";return None
        best=None;best_ratio=0.
        boundaries=[]
        for w in cfg.windows_seconds:
            start=at-timedelta(seconds=w)
            recent=[(t,p) for t,p in self.samples if t>=start]
            if len(recent)<3 or (at-recent[0][0]).total_seconds()<w-1 or any((b[0]-a[0]).total_seconds()>4 for a,b in zip(recent,recent[1:])):continue
            delta=sign*(mid-recent[0][1]);travel=sum(abs(b[1]-a[1]) for a,b in zip(recent,recent[1:]))
            eff=delta/travel if travel else 0.
            old=[(t,p) for t,p in self.samples if t<start]
            hist=[]
            for i in range(1,len(old),max(1,w//2)):
                t,p=old[i]
                anchor=next((v for t0,v in reversed(old[:i]) if w-1<=(t-t0).total_seconds()<=w+1),None)
                if anchor is not None:hist.append(abs(p-anchor))
            if len(hist)<5:continue
            baseline=median(hist)
            components=(("Threshold",cfg.min_impulse_points),("Spread",cfg.spread_impulse_multiple*spread),
                        ("Normalstøy",cfg.relative_impulse_multiple*baseline),("ATR",cfg.atr_entry_multiple*atr if atr is not None else 0.))
            source,base_threshold=max(components,key=lambda v:v[1])
            # Positive trim lowers the completed adaptive distance on BOTH sides.
            # Preserve one-spread/one-point floor, maximum-spread gate and all
            # directional, data-quality, timing and broker guards. Zero is identity.
            floor=max(1.,spread)
            adjusted=base_threshold-cfg.entry_gain_points
            threshold=adjusted if cfg.research_unclamped_entry else max(floor,adjusted)
            effective_source="Fri research" if cfg.research_unclamped_entry else "Minimumsgulv" if adjusted<floor else source
            # Exact observed price-distance threshold for this arm. Efficiency,
            # ATR availability, indicators and confirmation remain separate gates.
            boundary=recent[0][1]+sign*threshold
            self.trace["entry_fast_price" if w==cfg.windows_seconds[0] else "entry_slow_price"]=boundary
            boundaries.append((sign*(boundary-mid),boundary,threshold,w,eff,effective_source,base_threshold,source))
            if threshold>0:
                ratio=max(0.,delta/threshold)
                if best_ratio is not None:best_ratio=max(best_ratio,ratio)
            elif cfg.research_unclamped_entry:
                # A ratio against a nonpositive threshold has no meaning.
                best_ratio=None
            if delta>=threshold and eff>=cfg.minimum_directional_efficiency:
                best=(delta,baseline,w)
        self.trace["entry_ratio"]=best_ratio
        if boundaries:
            _,boundary,threshold,w,eff,source,base_threshold,base_source=min(boundaries,key=lambda x:x[0])
            self.trace.update(entry_price=boundary,entry_threshold=threshold,entry_window=w,entry_efficiency=eff,threshold_source=source,
                              entry_base_price=boundary+sign*(base_threshold-threshold),entry_base_threshold=base_threshold,entry_base_source=base_source,
                              entry_gain_applied=base_threshold-threshold)
        blocked_indicators=[k for k in cfg.entry_indicators if not favorable(k)]
        if cfg.atr_entry_multiple and atr is None:
            detail="Manglende ATR"
        elif blocked_indicators:
            detail="Entry-filter: "+", ".join(blocked_indicators)
        elif not boundaries:
            detail="Oppvarming / manglende impulsvindu"
        elif best is None:
            detail="Retningseffektivitet under krav" if any(b[0]<=0 for b in boundaries) else "Impuls under prisgrense"
        else:
            detail="Bekreftelse pågår"
        self.trace["gate_detail"]=detail
        if best is None or (cfg.atr_entry_multiple and atr is None) or not all(favorable(k) for k in cfg.entry_indicators):
            if not self.trace["entry_rejected"]:
                rejected(detail)
            self.candidate_at=None;self.trace["gate"]="ENTRY_BLOCKED";return None
        self.candidate_at=self.candidate_at or at
        self.trace["gate"]="ENTRY_CONFIRM"
        self.trace["entry_confirm_elapsed"]=(at-self.candidate_at).total_seconds()
        if (at-self.candidate_at).total_seconds()<cfg.entry_confirmation_seconds:return None
        delta,baseline,w=best
        self.target=cfg.side;self.entry_mid=self.extreme=mid;self.entered_at=self.last_extreme_at=at
        self.candidate_at=self.retrace_at=None
        self.trace.update(target=self.target,gate="ENTRY",gate_detail="Attack fullført")
        return ImpulseCatcherDecision(cfg.side,"QUALIFIED_IMPULSE_V14",mid,at,delta,baseline,w)

def load_settings(db,trader_id,key):
    if key not in KEYS:raise ValueError("not IC v1.4")
    db.execute("""CREATE TABLE IF NOT EXISTS pg_ic_v14_settings(
       trader_id TEXT NOT NULL,strategy_key TEXT NOT NULL,settings_json TEXT NOT NULL,
       PRIMARY KEY(trader_id,strategy_key))""")
    row=db.execute("SELECT settings_json FROM pg_ic_v14_settings WHERE trader_id=? AND strategy_key=?",(str(trader_id),key)).fetchone()
    return normalize_settings(json.loads(row["settings_json"]) if row else {})

def save_settings(db,trader_id,key,raw):
    if key not in KEYS:raise ValueError("not IC v1.4")
    settings=normalize_settings(raw)
    load_settings(db,trader_id,key)
    db.execute("""INSERT INTO pg_ic_v14_settings(trader_id,strategy_key,settings_json) VALUES(?,?,?)
        ON CONFLICT(trader_id,strategy_key) DO UPDATE SET settings_json=excluded.settings_json""",
        (str(trader_id),key,json.dumps(settings,sort_keys=True)))
    return settings

def preview(quotes,config):
    model=ImpulseCatcherV14(config=config)
    result=[]
    for q in quotes:
        decision=model.on_quote(q.at,q.bid,q.ask)
        result.append(dict(at=q.at,**model.trace,decision=decision.reason if decision else None))
    return result
