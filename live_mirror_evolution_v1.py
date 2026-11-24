"""Bounded, deterministic research evolution on independent chronological folds.

The engine shares precomputed signal features. No LIVE registry or Saxo
authority. The 1000-model experiment is unlocked only by an independently
validated simulator, including account P/L. This is not a profit guarantee.
"""
from dataclasses import dataclass, asdict
from math import isfinite
from random import Random
from statistics import median
from datetime import datetime


@dataclass(frozen=True)
class Genome:
    macd_weight: float
    entry: float
    exit: float
    build_delta: float
    max_tranches: int

    def __post_init__(self):
        if not (0.2<=self.macd_weight<=0.95 and 0.08<=self.entry<=0.8
                and 0.01<=self.exit<self.entry and 0<=self.build_delta<=0.3
                and 1<=self.max_tranches<=10):
            raise ValueError("invalid genome")


BASE=Genome(.7,.22,.10,.02,10)


@dataclass(frozen=True)
class Evaluation:
    genome: Genome
    net_returns: tuple[float,...]
    drawdowns: tuple[float,...]
    trades: tuple[int,...]

    @property
    def fitness(self):
        # Penalize the worst fold and drawdown rather than reward one lucky run.
        return median(self.net_returns)+.5*min(self.net_returns)-max(self.drawdowns)


def mutate(parent,rng):
    clamp=lambda x,a,b:min(b,max(a,x))
    entry=clamp(parent.entry+rng.gauss(0,.04),.08,.8)
    return Genome(round(clamp(parent.macd_weight+rng.gauss(0,.06),.2,.95),5),
        round(entry,5),round(clamp(parent.exit+rng.gauss(0,.025),.01,entry-.01),5),
        round(clamp(parent.build_delta+rng.gauss(0,.025),0,.3),5),
        int(clamp(parent.max_tranches+rng.choice((-1,0,1)),1,10)))


def evolve(*, folds, holdout, evaluate, validation, population=1000,
           generations=5, seed=42):
    """Evaluator is injected; each candidate uses same fixed broker assumptions.

    folds and holdout are (start,end,immutable shared features). A distinct
    chronological holdout is evaluated only once after selection. No genome
    is automatically promoted. A full-account validation gate must be
    supplied by the operator-facing validator, not just synthetic tests.
    """
    if not (validation.get("passed") is True and validation.get("pnl_validated") is True):
        raise ValueError("empirical execution AND account P/L validation required")
    if not 2<=population<=1000 or not 1<=generations<=50 or len(folds)<2:
        raise ValueError("bounded population and at least two training folds required")
    previous=None
    for start,end,_ in (*folds,holdout):
        if (not isinstance(start,datetime) or not isinstance(end,datetime)
            or start.tzinfo is None or end.tzinfo is None or start>=end
            or (previous is not None and start<previous)):
            raise ValueError("overlapping or unordered experiment windows")
        previous=end
    rng=Random(seed)
    pool=[BASE]
    while len(pool)<population:
        child=mutate(BASE,rng)
        if child not in pool:
            pool.append(child)
    archive=[]
    cache={}
    def score(g):
        if g in cache:
            return cache[g]
        results=tuple(evaluate(g,f[2]) for f in folds)
        if any(len(r)!=3 or not all(isfinite(x) for x in r)
               or r[1]<0 or r[2]<0 for r in results):
            raise ValueError("invalid evaluator output")
        e=Evaluation(g,tuple(r[0] for r in results),tuple(r[1] for r in results),
                      tuple(int(r[2]) for r in results))
        cache[g]=e
        return e
    for generation in range(generations):
        ranked=sorted(map(score,pool),key=lambda e:e.fitness,reverse=True)
        archive.append({"generation":generation+1,"population":len(ranked),
                        "median_fitness":median(e.fitness for e in ranked),
                        "best_fitness":ranked[0].fitness})
        elite=[e.genome for e in ranked[:max(1,population//10)]]
        if generation+1<generations:
            pool=list(elite)
            seen=set(pool)
            while len(pool)<population:
                child=mutate(rng.choice(elite),rng)
                if child not in seen:
                    pool.append(child);seen.add(child)
    champion=ranked[0]
    test=evaluate(champion.genome,holdout[2])
    baseline=cache.get(BASE) or score(BASE)
    baseline_test=test if champion.genome==BASE else evaluate(BASE,holdout[2])
    return {"seed":seed,"generations":archive,"unique_genomes":len(cache),
            "champion":asdict(champion.genome),"training_fitness":champion.fitness,
            "holdout":test,"baseline_holdout":baseline_test,
            "baseline_training_fitness":baseline.fitness,
            "status":"RESEARCH_ONLY_NO_PROMOTION"}


@dataclass(frozen=True)
class FeatureFrame:
    """Frozen features available at decision time; quotes are settlement only."""
    at: datetime
    macd_component: float
    stoch_component: float
    regime: str
    quotes: tuple

    def __post_init__(self):
        if self.at.tzinfo is None or not all(isfinite(x) and -1<=x<=1
                for x in (self.macd_component,self.stoch_component)):
            raise ValueError("invalid causal frame")


@dataclass(frozen=True)
class ReplayFold:
    frames: tuple[FeatureFrame,...]
    initial_cash: float
    terms: object
    allowed_regimes: tuple[str,...] = ("BULL","BEAR","SIDEWAYS")


def evaluate_genome(genome, fold):
    """V2.1-family parameter variants, shared features, identical virtual broker.

    Each frame's quotes must be recorded after its decision and before the
    next decision. No optimistic bar-open fills. Unfilled intents expire.
    Fold starts flat and ends at the last observable liquidation mark.
    This evaluator is research-only; funding and regime variants must be
    added before using multi-day folds with nonzero financing.
    """
    from datetime import timedelta
    from live_mirror_broker_v1 import MirrorAccount,execute_target
    if not fold.frames or fold.initial_cash<=0:
        raise ValueError("missing fold")
    a=MirrorAccount(fold.initial_cash)
    prior=None
    peak=fold.initial_cash
    dd=0.
    trades=0
    last_quote=None
    for i,f in enumerate(fold.frames):
        if i and f.at<=fold.frames[i-1].at:
            raise ValueError("unordered features")
        end=f.at+timedelta(seconds=fold.terms.max_quote_wait_seconds)
        if i+1<len(fold.frames):
            end=min(end,fold.frames[i+1].at-timedelta(microseconds=1))
        quotes=tuple(q for q in f.quotes if f.at<=q.received_at<=end
                     and q.at<=q.received_at and q.at>=f.at
                     and (q.received_at-q.at).total_seconds()<=5)
        score=genome.macd_weight*f.macd_component+(1-genome.macd_weight)*f.stoch_component
        current=a.inventory
        target=current
        if current*score<0 or abs(score)<=genome.exit:
            target=0.
        elif (abs(score)>=genome.entry and prior is not None and score*prior>0
              and abs(prior)>=genome.entry and (not current or
                   abs(score)-abs(prior)>genome.build_delta)
              and f.regime in fold.allowed_regimes):
            target=(1 if score>0 else -1)*min(genome.max_tranches*fold.terms.minimum_lots,
                        abs(current)+fold.terms.minimum_lots)
        prior=score
        result=execute_target(a,target,decided_at=f.at,quotes=quotes,
                              now=end,terms=fold.terms)
        a=result.account
        trades+=int(result.status=="FILLED")
        if quotes:
            last_quote=max(quotes,key=lambda q:q.received_at)
            value=a.equity(last_quote.bid,last_quote.ask,fold.terms)
            peak=max(peak,value)
            dd=max(dd,(peak-value)/fold.initial_cash)
    if last_quote is None:
        raise ValueError("no observable settlement quotes")
    # Refuse stale terminal marks; report no optimistic liquidation price.
    if last_quote.received_at<fold.frames[-1].at:
        raise ValueError("no terminal observable quote")
    value=a.equity(last_quote.bid,last_quote.ask,fold.terms)
    return (100*(value/fold.initial_cash-1),100*dd,trades)
