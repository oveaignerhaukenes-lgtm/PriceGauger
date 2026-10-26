"""Causal stochastic-model tournament for persisted Saxo 1m close prices.

Research-only. Fits every candidate with only observations and forward labels
already resolved at its as-of timestamp; selects on historical validation,
checks the selected candidate on a later held-out, non-overlapping block.
No broker reads or writes. Brownian/OU/jump models are discretized proxies
and may be invalid when the market is not stationary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import erf, exp, isfinite, log, sqrt
import random
from statistics import median
from typing import Sequence

from probability_lab_v1 import (
    LABELS, _index, _label, _segments, _sign, walk_forward_probability,
)

MODELS = {
    "baseline": "Rullerende frekvens (referanse)",
    "markov": "Markov, historisk fortegnsmønster",
    "skellam": "Poisson/Skellam, 1m-hendelsesproxy",
    "ewma": "Eksponentielt vektet Bernoulli/Dirichlet",
    "streak": "Strekavhengig Markov (løpelengde)",
    "regime": "Volatilitetsregime, empirisk fordeling",
    "brownian": "Geometrisk Brownsk bevegelse (normaldiffusjon)",
    "ou": "Ornstein–Uhlenbeck / AR(1) på avkastning",
    "jump": "Hoppdiffusjon, normalblanding",
}


@dataclass(frozen=True)
class ModelForecast:
    asof: str
    horizon: int
    actual: str
    return_pct: float
    probabilities: dict[str, tuple[float, float, float]]


@dataclass(frozen=True)
class Tournament:
    horizon: int
    candidates: tuple[str, ...]
    selected: str | None
    rows: tuple[ModelForecast, ...]
    validation: tuple[ModelForecast, ...]
    holdout: tuple[ModelForecast, ...]
    validation_scores: dict[str, dict]
    holdout_scores: dict[str, dict]
    gain_brier: float | None
    gain_ci95: tuple[float, float] | None
    evidence: bool
    gap_count: int
    notes: tuple[str, ...]


def _blend(counts: list[float], prior: tuple[float, float, float],
           strength: float = 12.) -> tuple[float, float, float]:
    total = sum(counts) + strength
    return tuple((counts[k] + strength * prior[k]) / total for k in range(3))


def _gaussian_probs(mean: float, sigma: float,
                    prior: tuple[float, float, float]) -> tuple[float, float, float]:
    if not isfinite(mean) or not isfinite(sigma):
        return prior
    sig = max(sigma, 1.e-9)
    p_up = .5 * (1. + erf(mean / (sqrt(2.) * sig)))
    p_up = min(1., max(0., p_up))
    # A small prior mixture maintains nonzero support for exact ties;
    # a continuous normal alone has P(exact equality)=0.
    return (.98 * p_up + .02 * prior[0],
            .98 * (1. - p_up) + .02 * prior[1],
            .02 * prior[2])


def _stats(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0., 1.e-6
    mu = sum(values) / len(values)
    var = sum((x - mu) ** 2 for x in values) / max(1, len(values) - 1)
    return mu, sqrt(max(1.e-14, var))


def _streaks(returns: list[float]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = [(0, 0)]
    prior = 0
    n = 0
    for x in returns[1:]:
        sign = _sign(x)
        n = min(4, n + 1) if sign and sign == prior else (1 if sign else 0)
        result.append((sign, n))
        prior = sign
    return result


def _volatility(returns: list[float], span: int = 20) -> list[float | None]:
    vols: list[float | None] = []
    for i in range(len(returns)):
        if i < span:
            vols.append(None)
        else:
            _, sd = _stats(returns[i - span + 1:i + 1])
            vols.append(sd)
    return vols


def _other_models(
    close: list[float], returns: list[float], streak: list[tuple[int, int]],
    vol: list[float | None], i: int, horizon: int, window: int,
    base: tuple[float, float, float],
) -> dict[str, tuple[float, float, float]]:
    start = max(3, i - window)
    end = i - horizon
    if end < start:
        raise ValueError("unresolved training targets")
    pairs = [(j, _index(_sign(close[j + horizon] - close[j])))
             for j in range(start, end + 1)]
    if len(pairs) < 24:
        raise ValueError("insufficient resolved labels")
    # Decayed evidence: exponentially weighted multinomial/Dirichlet posterior.
    half_life = max(12., window / 4)
    counts = [0., 0., 0.]
    for j, outcome in pairs:
        counts[outcome] += .5 ** ((end - j) / half_life)
    ewma = _blend(counts, base, 8.)
    # Semi-Markov-style sign run length (not a fitted duration distribution).
    counts = [0., 0., 0.]
    for j, outcome in pairs:
        if streak[j] == streak[i]:
            counts[outcome] += 1
    streak_model = _blend(counts, base, 16.)
    # Volatility regime label always uses information available at j.
    historical_vol = [vol[j] for j, _ in pairs if vol[j] is not None]
    counts = [0., 0., 0.]
    if len(historical_vol) >= 25 and vol[i] is not None:
        threshold = median(historical_vol)
        regime = vol[i] > threshold
        for j, outcome in pairs:
            if vol[j] is not None and (vol[j] > threshold) == regime:
                counts[outcome] += 1.
    regime_model = _blend(counts, base, 20.)
    # Minute log returns r_t are observed and causal by construction.
    recent = returns[max(1, i - window + 1):i + 1]
    mu, sigma = _stats(recent)
    brownian = _gaussian_probs(horizon * mu, sqrt(horizon) * sigma, base)
    # OU: discrete AR(1) on log returns, NOT mean reversion in price levels.
    lagged = recent[:-1]
    nexts = recent[1:]
    xbar, _ = _stats(lagged)
    ybar, _ = _stats(nexts)
    denominator = sum((x - xbar) ** 2 for x in lagged)
    rho = (sum((x - xbar) * (y - ybar) for x, y in zip(lagged, nexts))
           / denominator if denominator > 1.e-16 else 0.)
    rho = min(.90, max(-.90, rho))
    ar_mean = horizon * mu + (recent[-1] - mu) * sum(
        rho ** k for k in range(1, horizon + 1)
    )
    # Stationary AR(1) approximate innovation persistence variance scaling.
    multiplier = sqrt(max(.3, min(5., (1. + rho) / (1. - rho))))
    ou = _gaussian_probs(ar_mean, sqrt(horizon) * sigma * multiplier, base)
    # Static normal-mixture jump-diffusion proxy: recent large residuals
    # estimate rare-jump frequency, jumps have 3x diffusion variance.
    jumps = sum(abs(x - mu) > 2.5 * sigma for x in recent)
    pi = min(.35, max(.01, jumps / max(1, len(recent))))
    calm = _gaussian_probs(horizon * mu, sqrt(horizon) * sigma, base)
    stressed = _gaussian_probs(horizon * mu, sqrt(horizon) * sigma * 3., base)
    jump = tuple((1. - pi) * calm[k] + pi * stressed[k] for k in range(3))
    return {
        "ewma": ewma, "streak": streak_model,
        "regime": regime_model, "brownian": brownian, "ou": ou,
        "jump": jump,
    }


def _score(rows: Sequence[ModelForecast], model: str,
           threshold: float, roundtrip_bps: float) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "brier": None, "log_loss": None, "hit_rate": None,
                "up_calibration_mae": None, "signals": 0, "mean_net_signal_pct": None}
    brier = nll = hit = error_up = net = 0.
    signals = 0
    for row in rows:
        p = row.probabilities[model]
        truth = LABELS.index(row.actual)
        brier += sum((p[k] - (k == truth)) ** 2 for k in range(3))
        nll -= log(max(1.e-12, p[truth]))
        hit += int(p.index(max(p)) == truth)
        error_up += abs(p[0] - (truth == 0))
        direction = 1 if p[0] >= threshold and p[0] > p[1] else (
            -1 if p[1] >= threshold and p[1] > p[0] else 0
        )
        if direction:
            signals += 1
            net += direction * row.return_pct - roundtrip_bps / 100.
    return {
        "n": n, "brier": brier / n, "log_loss": nll / n,
        "hit_rate": hit / n, "up_calibration_mae": error_up / n,
        "signals": signals,
        "mean_net_signal_pct": net / signals if signals else None,
    }


def _paired_gain_ci(rows: Sequence[ModelForecast], winner: str, *, horizon: int,
                    replicates: int = 300) -> tuple[float, tuple[float, float]]:
    """Chronological moving-block bootstrap for Brier baseline-minus-winner."""
    differences = []
    for row in rows:
        target = LABELS.index(row.actual)
        loss_base = sum((p - (k == target)) ** 2
                        for k, p in enumerate(row.probabilities["baseline"]))
        loss_best = sum((p - (k == target)) ** 2
                        for k, p in enumerate(row.probabilities[winner]))
        differences.append(loss_base - loss_best)
    if not differences:
        return 0., (0., 0.)
    n = len(differences)
    # Held-out rows already non-overlapping per horizon. Blocks still
    # account approximately for residual serial correlation.
    block = min(n, max(8, horizon * 2))
    rng = random.Random(20261026)
    samples = []
    for _ in range(replicates):
        draws = []
        while len(draws) < n:
            begin = rng.randrange(max(1, n - block + 1))
            draws.extend(differences[begin:begin + block])
        samples.append(sum(draws[:n]) / n)
    samples.sort()
    return sum(differences) / n, (
        samples[int(.025 * (replicates - 1))],
        samples[int(.975 * (replicates - 1))]
    )


def run_model_tournament(
    bars: Sequence, *, horizon: int = 1, window: int = 180,
    threshold: float = .55, roundtrip_bps: float = 8.,
) -> Tournament:
    """Fit a fixed model roster, choose on validation, evaluate held-out once.

    Fixed roster and hyperparameters, no automatic per-market tuning.
    Predictions whose forward interval overlaps are subsampled at horizon
    cadence before validation/held-out statistics.
    """
    if not .35 <= threshold <= 1. or not 0 <= roundtrip_bps <= 1000:
        raise ValueError("invalid diagnostic parameters")
    base_rows, _, gaps = walk_forward_probability(
        bars, horizon=horizon, lag=2, window=window,
    )
    lookup = {r.asof: r for r in base_rows}
    full_rows: list[ModelForecast] = []
    for group in _segments(bars):
        if len(group) < 50:
            continue
        times = [at for at, _ in group]
        close = [price for _, price in group]
        returns = [0.] + [log(close[k] / close[k - 1])
                           for k in range(1, len(close))]
        streak = _streaks(returns)
        vols = _volatility(returns)
        for i, at in enumerate(times):
            b = lookup.get(at.isoformat())
            if b is None:
                continue
            extra = _other_models(close, returns, streak, vols, i, horizon,
                                  window, b.baseline)
            p = {"baseline": b.baseline, "markov": b.markov,
                 "skellam": b.skellam, **extra}
            full_rows.append(ModelForecast(
                asof=b.asof, horizon=horizon, actual=b.actual,
                return_pct=float(b.return_pct), probabilities=p,
            ))
    # UTC-aligned sampling prevents overlapping future labels in scoring,
    # including at market segment boundaries.
    scored = [r for r in full_rows if
              int(datetime.fromisoformat(r.asof).timestamp() // 60) % horizon == 0]
    n = len(scored)
    cutoff = int(.7 * n)
    validation = scored[:cutoff]
    holdout = scored[cutoff:]
    # Purge h minutes on both sides of split to avoid cross-split target
    # overlap / selecting with information that is part of held-out labels.
    if validation and holdout:
        holdout_start = datetime.fromisoformat(holdout[0].asof)
        validation = [
            r for r in validation
            if (holdout_start - datetime.fromisoformat(r.asof)).total_seconds()
            >= 2 * horizon * 60
        ]
    validation_scores = {
        key: _score(validation, key, threshold, roundtrip_bps) for key in MODELS
    }
    holdout_scores = {
        key: _score(holdout, key, threshold, roundtrip_bps) for key in MODELS
    }
    selected = None
    gain = ci = None
    credible = False
    notes: list[str] = [
        "Modellvalg på første 70 %, siste 30 % er tidsmessig holdout.",
        "Felles 1m OHLC per eksakt instrument. Ingen fremtidsbar eller gap brukes til trening.",
        "Holdout evalueres på ikke-overlappende prognoseintervaller.",
        "Signalavkastning er hypotetisk close-til-close minus brukerdefinert kost; ingen Saxo-fill.",
    ]
    if len(validation) >= 40 and len(holdout) >= 30:
        selected = min(MODELS, key=lambda key: (
            validation_scores[key]["brier"],
            validation_scores[key]["log_loss"],
            key,
        ))
        gain, ci = _paired_gain_ci(holdout, selected, horizon=horizon)
        credible = (selected != "baseline" and len(holdout) >= 100
                    and gain > 0 and ci[0] > 0
                    and validation_scores[selected]["brier"]
                    < validation_scores["baseline"]["brier"])
    else:
        notes.append(
            "For få ikke-overlappende observasjoner til kontrollert modellvalg "
            "(minimum 40 validering og 30 holdout)."
        )
    if len(holdout) < 100:
        notes.append(
            "Holdout <100; ingen modell får status som robust bedre enn baseline."
        )
    return Tournament(
        horizon=horizon, candidates=tuple(MODELS),
        selected=selected, rows=tuple(scored),
        validation=tuple(validation), holdout=tuple(holdout),
        validation_scores=validation_scores,
        holdout_scores=holdout_scores,
        gain_brier=gain, gain_ci95=ci,
        evidence=credible, gap_count=gaps,
        notes=tuple(notes),
    )


def explain_tournament(t: Tournament, *, market: str, roundtrip_bps: float) -> dict[str, str]:
    """Deterministic Norwegian interpretation based ONLY on actual measured scores."""
    if t.selected is None:
        return {
            "summary": (f"{market}: For lite sammenhengende historikk til å rangere "
                        "stokastiske prosesser på uavhengig kontrollperiode."),
            "interpretation": "Ingen modellvinner kan kåres forsvarlig fra disse dataene.",
            "recommendation": "Utvid analyseperioden. Ikke aktiver handel på grunnlaget.",
        }
    chosen = t.selected
    name = MODELS[chosen]
    val = t.validation_scores[chosen]
    test = t.holdout_scores[chosen]
    ref = t.holdout_scores["baseline"]
    delta = (ref["brier"] - test["brier"])
    summary = (
        f"{market}: {len(t.validation)} valideringsprognoser, "
        f"{len(t.holdout)} ikke-overlappende holdout-prognoser, "
        f"{t.gap_count} tidsbrudd. Beste modell på valideringen: {name} "
        f"(Brier {val['brier']:.4f})."
    )
    interpretation = (
        f"På siste holdout: Brier {test['brier']:.4f} mot "
        f"{ref['brier']:.4f} for frekvensbaseline "
        f"(forbedring {delta:+.4f}; lavere Brier er bedre). "
        f"Treffprosent {100 * test['hit_rate']:.1f} %. "
    )
    if t.gain_ci95 is not None:
        interpretation += (
            f"Blokk-bootstrap 95 % intervall for Brier-forbedring "
            f"[{t.gain_ci95[0]:+.4f}, {t.gain_ci95[1]:+.4f}]. "
        )
    avg = test["mean_net_signal_pct"]
    interpretation += (
        f"Ved valgt signalgrense ble {test['signals']} hypotetiske signaler "
        f"generert, med gjennomsnittlig close-til-close-utfall "
        f"{avg:+.4f} % etter {roundtrip_bps:g} bps antatt kost. "
        if avg is not None else "Ingen hypotetiske signaler over valgt terskel. "
    )
    if chosen == "baseline":
        recommendation = (
            "Frekvensbaseline vant modellvalget. Det finnes ikke støtte her "
            "for at mer komplekse modeller forbedrer prediksjonene. "
            "Fortsett PAPER-forskning, ingen LIVE-bruk."
        )
    elif not t.evidence:
        recommendation = (
            "Ingen robust holdout-forbedring er dokumentert. "
            "Unngå å kåre en fungerende modell eller knytte den til LIVE. "
            "Test flere uavhengige markedsdager og regimer."
        )
    elif test["signals"] < 30 or avg is None or avg <= 0:
        recommendation = (
            "Sannsynlighetene viser målbar holdout-forbedring, men "
            "det er ikke tilstrekkelig signalgrunnlag eller positiv "
            "kostjustert hypotetisk avkastning. Ikke klar for handelsbruk."
        )
    else:
        recommendation = (
            "Forsiktig kandidat for PROSPEKTIV PAPER-test, ikke LIVE. "
            "Kalibrer mot nye dager og faktisk historisk BBO/spread, "
            "mål gjennomførbare fills, drawdown og netto kontoresultat "
            "før en ny vurdering. Modellvalg må ikke optimaliseres på holdout."
        )
    return {"summary": summary, "interpretation": interpretation,
            "recommendation": recommendation}
