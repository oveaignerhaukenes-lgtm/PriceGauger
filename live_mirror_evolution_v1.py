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
