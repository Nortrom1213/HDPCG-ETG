"""Candidate scoring and stochastic selection for DI-HDPCG."""

from __future__ import annotations

import math
from typing import Any

from .random_utils import Mulberry32


def _safe_number(value: Any, fallback: float = 0.0) -> float:
    try:
        n = float(value)
    except Exception:
        n = fallback
    if math.isfinite(n):
        return n
    return fallback


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _novelty_from_usage(family_usage: dict[str, int], family: str) -> float:
    used = _safe_number((family_usage or {}).get(family), 0.0)
    return 1.0 / (1.0 + used)


def score_candidate(
    candidate: dict[str, Any],
    *,
    edge_length: float,
    family_usage: dict[str, int],
    weights: dict[str, float],
) -> dict[str, Any]:
    wa = _safe_number(weights.get("alignmentWeight"), 0.35)
    wp = _safe_number(weights.get("playabilityWeight"), 0.30)
    wn = _safe_number(weights.get("noveltyWeight"), 0.20)
    ws = _safe_number(weights.get("shapeWeight"), 0.15)
    wr = _safe_number(weights.get("riskWeight"), 0.20)

    complexity = _clamp(_safe_number(candidate.get("complexity"), 0.5), 0.0, 1.0)
    alignment = 1.0 - abs(complexity - _clamp(_safe_number(edge_length) / 48.0, 0.0, 1.0))
    playability = 1.0 - max(0.0, complexity - 0.75)
    novelty = 0.5 * _novelty_from_usage(family_usage, candidate.get("connectorFamily", "")) + 0.5 * _novelty_from_usage(
        family_usage, candidate.get("nodeFamily", "")
    )
    connector = candidate.get("connector") or {}
    node = candidate.get("node") or {}
    shape = _clamp(
        abs(_safe_number(connector.get("lateralAmplitude"), 0.0) - _safe_number(node.get("scaleZ"), 0.0)) * 0.35
        + abs(_safe_number(connector.get("verticalAmplitude"), 0.0) - _safe_number(node.get("verticalBias"), 0.0)) * 0.2,
        0.0,
        1.0,
    )
    risk = _clamp(complexity * 0.85, 0.0, 1.0)
    score = wa * alignment + wp * playability + wn * novelty + ws * shape - wr * risk
    out = dict(candidate)
    out["score"] = score
    out["scoreDetail"] = {
        "alignment": alignment,
        "playability": playability,
        "novelty": novelty,
        "shape": shape,
        "risk": risk,
    }
    return out


def _softmax(values: list[float], temperature: float) -> list[float]:
    t = _clamp(_safe_number(temperature, 0.80), 0.05, 4.0)
    m = max(values) if values else 0.0
    exps = [math.exp((v - m) / t) for v in values]
    s = sum(exps) or 1.0
    return [x / s for x in exps]


def _sample_index(probs: list[float], rng: Mulberry32) -> int:
    r = rng.random()
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if r <= acc:
            return i
    return max(0, len(probs) - 1)


def select_candidate_order(
    scored_candidates: list[dict[str, Any]],
    *,
    selection_top_p: float,
    selection_temperature: float,
    rng: Mulberry32,
) -> list[dict[str, Any]]:
    if not scored_candidates:
        return []
    sorted_list = sorted(scored_candidates, key=lambda x: float(x.get("score", 0.0)), reverse=True)
    keep = max(1, int(math.ceil(len(sorted_list) * _clamp(_safe_number(selection_top_p, 0.70), 0.05, 1.0))))
    pool = list(sorted_list[:keep])
    out: list[dict[str, Any]] = []
    while pool:
        probs = _softmax([float(x.get("score", 0.0)) for x in pool], selection_temperature)
        idx = _sample_index(probs, rng)
        out.append(pool[idx])
        pool.pop(idx)
    return out
