"""Candidate component sampler for DI-HDPCG."""

from __future__ import annotations

from typing import Any

from .components import family_base_complexity, list_connector_families, list_node_families
from .random_utils import Mulberry32, pick, rand_range


def _connector_params(family: str, rng: Mulberry32) -> dict[str, Any]:
    return {
        "family": family,
        "lateralAmplitude": rand_range(rng, 0.2, 2.8),
        "verticalAmplitude": rand_range(rng, 0.15, 2.4),
        "zigzagPeriod": rand_range(rng, 2.5, 7.5),
        "stairStep": rand_range(rng, 0.4, 1.25),
        "movingRate": rand_range(rng, 0.2, 0.7),
        "hazardDensity": rand_range(rng, 0.1, 0.65),
    }


def _node_params(family: str, rng: Mulberry32) -> dict[str, Any]:
    return {
        "family": family,
        "scaleX": rand_range(rng, 0.8, 1.8),
        "scaleZ": rand_range(rng, 0.8, 1.8),
        "verticalBias": rand_range(rng, -0.6, 1.4),
        "enemyBias": rand_range(rng, 0.0, 1.0),
        "movingBias": rand_range(rng, 0.0, 1.0),
        "branchBias": rand_range(rng, 0.0, 1.0),
    }


def build_candidate_pool(
    *,
    edge: dict[str, Any],
    to_node: dict[str, Any],
    rng: Mulberry32,
    pool_size: int,
) -> list[dict[str, Any]]:
    size = max(1, min(48, int(pool_size)))
    connector_families = list_connector_families(float(edge.get("length", 0)))
    node_families = list_node_families(to_node)
    out: list[dict[str, Any]] = []
    for i in range(size):
        connector_family = pick(rng, connector_families)
        node_family = pick(rng, node_families)
        out.append(
            {
                "id": f"cand_{i}",
                "connectorFamily": connector_family,
                "nodeFamily": node_family,
                "connector": _connector_params(connector_family, rng),
                "node": _node_params(node_family, rng),
                "complexity": 0.5
                * (
                    family_base_complexity(connector_family)
                    + family_base_complexity(node_family)
                ),
            }
        )
    return out
