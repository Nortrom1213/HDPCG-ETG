"""Quality metrics used by the paper experiments."""

from __future__ import annotations

import itertools
import math
import statistics
from typing import Any

from .etg_core import NODE_TYPES, compute_canonical_route
from .paper_config import load_paper_config
from .topology import validate_global_topology


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _std(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def _band_score(value: float, target: float, width: float) -> float:
    return _clamp01(1.0 - abs(float(value) - float(target)) / max(1e-9, float(width)))


def _entropy(counts: dict[str, int]) -> float:
    total = sum(max(0, int(value)) for value in counts.values())
    if total <= 0:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values() if count > 0)


def _node_types(item: dict[str, Any]) -> list[str]:
    if isinstance(item.get("types"), list) and item["types"]:
        return [str(value) for value in item["types"]]
    return [str(item.get("type") or "None")]


def _anchor_position(anchor: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(anchor, dict):
        return None
    value = anchor.get("entry") or anchor.get("exit") or anchor
    if not isinstance(value, dict):
        return None
    return {axis: float(value.get(axis, 0.0)) for axis in ("x", "y", "z")}


def _path_geometry(level: dict[str, Any], sequence: list[str]) -> tuple[float, list[float], list[float], list[float]]:
    positions = [_anchor_position((level.get("anchors") or {}).get(node_id)) for node_id in sequence]
    positions = [position for position in positions if position is not None]
    lengths: list[float] = []
    turns: list[float] = []
    vectors: list[tuple[float, float]] = []
    for first, second in zip(positions, positions[1:]):
        dx = second["x"] - first["x"]
        dz = second["z"] - first["z"]
        lengths.append(math.hypot(dx, dz))
        vectors.append((dx, dz))
    for first, second in zip(vectors, vectors[1:]):
        first_length = math.hypot(*first)
        second_length = math.hypot(*second)
        if first_length > 1e-9 and second_length > 1e-9:
            cosine = _clamp01((first[0] * second[0] + first[1] * second[1]) / (first_length * second_length) * 0.5 + 0.5)
            turns.append(math.acos(2.0 * cosine - 1.0) / math.pi)
    return sum(lengths), lengths, turns, [position["y"] for position in positions]


def _progression_balance(
    level: dict[str, Any],
    etg: dict[str, Any],
    sequence: list[str],
    path_length: float,
    key_lock_order_ok: bool,
) -> tuple[float, dict[str, Any]]:
    node_mapping = ((level.get("mapping") or {}).get("node") or {})
    node_by_id = {str(node.get("id")): node for node in (etg.get("nodes") or []) if node.get("id")}
    platform_by_id = {str(platform.get("id")): platform for platform in (level.get("platforms") or []) if platform.get("id")}
    route_positions = {str(node_id): index for index, node_id in enumerate(sequence)}
    bin_count = max(1, min(8, len(sequence) // 2))
    bins = [0 for _ in range(bin_count)]
    total_events = 0

    for node_id, index in route_positions.items():
        record = node_mapping.get(node_id) or {}
        events = len(record.get("enemies") or []) + len(record.get("keys") or []) + len(record.get("locks") or [])
        events += sum(
            1
            for platform_id in (record.get("platforms") or [])
            if (platform_by_id.get(str(platform_id)) or {}).get("kind") == "moving"
        )
        node_types = _node_types(node_by_id.get(node_id) or {})
        if NODE_TYPES["JUMP"] in node_types or NODE_TYPES["DROP"] in node_types:
            events += 1
        if events <= 0:
            continue
        bin_index = min(bin_count - 1, int((index / max(1, len(sequence))) * bin_count))
        bins[bin_index] += events
        total_events += events

    event_density = total_events / max(1.0, path_length if path_length > 0.0 else float(len(sequence)))
    path_signal = max(float(len(sequence)), float(path_length or 0.0))
    density_target = max(0.06, min(0.10, 0.095 - max(0.0, path_signal - 5.0) * 0.0022))
    density_width = max(0.06, min(0.11, 0.065 + path_signal * 0.0018))
    density_score = _band_score(event_density, density_target, density_width)

    if total_events <= 0:
        spread_score = 0.25
    else:
        occupied = sum(1 for value in bins if value > 0)
        coverage = occupied / bin_count
        concentration = max(bins) / total_events
        spread_score = _clamp01(0.55 * coverage + 0.45 * (1.0 - concentration))

    key_lock_scores: list[float] = []
    for node in etg.get("nodes") or []:
        if NODE_TYPES["LOCK"] not in _node_types(node):
            continue
        required_key = node.get("requires_key_id")
        if not required_key:
            continue
        key_node = next(
            (
                candidate
                for candidate in (etg.get("nodes") or [])
                if NODE_TYPES["KEY"] in _node_types(candidate) and candidate.get("key_id") == required_key
            ),
            None,
        )
        key_position = route_positions.get(str((key_node or {}).get("id")))
        lock_position = route_positions.get(str(node.get("id")))
        if key_position is None or lock_position is None or key_position >= lock_position:
            key_lock_scores.append(0.0)
            continue
        gap_ratio = (lock_position - key_position) / max(1, len(sequence))
        key_lock_scores.append(_band_score(gap_ratio, 0.22, 0.22))

    key_lock_pacing = _mean(key_lock_scores) if key_lock_scores else (1.0 if key_lock_order_ok else 0.3)
    score = _clamp01(0.42 * density_score + 0.33 * spread_score + 0.25 * key_lock_pacing)
    return score, {
        "event_density": event_density,
        "density_score": density_score,
        "spread_score": spread_score,
        "key_lock_pacing": key_lock_pacing,
        "bins": bins,
    }


def compute_paper_composites(
    *,
    node_coverage: float,
    route_length_agreement: float,
    topology_validity: float,
    etg_fidelity: float,
    content_variation: float,
    event_balance: float,
    route_rhythm: float,
    playability: float,
    key_lock_consistency: float,
) -> dict[str, float]:
    weights = load_paper_config()["metrics"]
    controllability = (
        weights["controllability"]["node_coverage"] * node_coverage
        + weights["controllability"]["route_length_agreement"] * route_length_agreement
    )
    topological_consistency = (
        weights["topological_consistency"]["topology_validity"] * topology_validity
        + weights["topological_consistency"]["etg_fidelity"] * etg_fidelity
    )
    pacing_variation = (
        weights["pacing_variation"]["content_variation"] * content_variation
        + weights["pacing_variation"]["event_balance"] * event_balance
        + weights["pacing_variation"]["route_rhythm"] * route_rhythm
    )
    overall_weights = weights["overall"]
    overall = (
        overall_weights["playability"] * playability
        + overall_weights["key_lock_consistency"] * key_lock_consistency
        + overall_weights["controllability"] * controllability
        + overall_weights["topological_consistency"] * topological_consistency
        + overall_weights["pacing_variation"] * pacing_variation
    )
    return {
        "controllability": _clamp01(controllability),
        "topological_consistency": _clamp01(topological_consistency),
        "pacing_variation": _clamp01(pacing_variation),
        "overall": _clamp01(overall),
    }


def evaluate_level_quality(
    level: dict[str, Any],
    expected_etg: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    etg = expected_etg or level.get("etg") or {"nodes": [], "edges": []}
    topology = validate_global_topology(level, etg, options.get("topology") or {})
    nodes = list(etg.get("nodes") or [])
    edges = list(etg.get("edges") or [])
    observed_sequence = list(topology.get("observed_node_sequence_path") or topology.get("observed_node_sequence") or [])
    expected_node_ids = {str(item.get("id")) for item in nodes if item.get("id")}
    node_coverage = len(set(observed_sequence) & expected_node_ids) / max(1, len(expected_node_ids))

    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    expected_length = float(canonical.get("totalLength", 0.0)) if canonical.get("ok") else 0.0
    observed_length, segment_lengths, turns, route_heights = _path_geometry(level, observed_sequence)
    relative_length_error = abs(observed_length - expected_length) / max(1.0, expected_length)
    route_length_agreement = _clamp01(1.0 - relative_length_error)

    goal_reachable = bool(topology.get("goal_reachable", topology.get("ok", False)))
    key_lock_order_ok = bool((topology.get("key_lock_order") or {}).get("ok", True))
    playability = 1.0 if goal_reachable else 0.0
    key_lock_consistency = 1.0 if key_lock_order_ok else 0.0
    topology_validity = 1.0 if goal_reachable and key_lock_order_ok else 0.0
    etg_fidelity = _clamp01(float(topology.get("fidelity_score", 0.0)))

    component_meta = (level.get("meta") or {}).get("component_generation") or {}
    family_usage = component_meta.get("family_usage") if isinstance(component_meta.get("family_usage"), dict) else {}
    family_entropy = _entropy({str(key): int(value) for key, value in family_usage.items()})
    family_count = len([value for value in family_usage.values() if int(value) > 0])
    family_entropy_norm = _clamp01(family_entropy / math.log2(max(2, family_count))) if family_count else 0.0

    platforms = list(level.get("platforms") or [])
    heights = [float((item.get("pos") or {}).get("y", 0.0)) for item in platforms]
    widths = [float((item.get("size") or {}).get("x", 0.0)) for item in platforms]
    geometry_variation = _clamp01((_std(heights) / 3.0 + _std(widths) / 6.0) * 0.5)
    content_variation = _clamp01(0.7 * family_entropy_norm + 0.3 * geometry_variation)

    event_balance, balance_components = _progression_balance(
        level,
        etg,
        observed_sequence,
        observed_length,
        key_lock_order_ok,
    )
    length_rhythm = _clamp01((_std(segment_lengths) / max(1e-6, _mean(segment_lengths))) / 0.55) if segment_lengths else 0.0
    turn_rhythm = _mean([_band_score(turn, 0.22, 0.22) for turn in turns]) if turns else 0.0
    elevation_rhythm = _clamp01(_std(route_heights) / 2.0) if len(route_heights) > 1 else 0.0
    route_rhythm = _clamp01(0.40 * length_rhythm + 0.35 * turn_rhythm + 0.25 * elevation_rhythm)

    composites = compute_paper_composites(
        node_coverage=node_coverage,
        route_length_agreement=route_length_agreement,
        topology_validity=topology_validity,
        etg_fidelity=etg_fidelity,
        content_variation=content_variation,
        event_balance=event_balance,
        route_rhythm=route_rhythm,
        playability=playability,
        key_lock_consistency=key_lock_consistency,
    )

    type_stream = [node_type for item in nodes for node_type in _node_types(item)]
    type_counts = {node_type: type_stream.count(node_type) for node_type in set(type_stream)}
    challenge_types = {
        NODE_TYPES["JUMP"],
        NODE_TYPES["DROP"],
        NODE_TYPES["ENEMY"],
        NODE_TYPES["KEY"],
        NODE_TYPES["LOCK"],
    }
    terminal_types = {NODE_TYPES["START"], NODE_TYPES["GOAL"]}
    non_terminal_nodes = [item for item in nodes if not any(node_type in terminal_types for node_type in _node_types(item))]
    challenge_ratio = sum(
        any(node_type in challenge_types for node_type in _node_types(item)) for item in non_terminal_nodes
    ) / max(1, len(non_terminal_nodes))
    comparison = topology.get("comparison") or {}
    metrics = {
        "metric_profile": "paper",
        "playability": {
            "goal_reachable": goal_reachable,
            "key_lock_order_ok": key_lock_order_ok,
            "score": playability,
        },
        "key_lock_consistency": {
            "order_ok": key_lock_order_ok,
            "score": key_lock_consistency,
        },
        "controllability": {
            "canonical_expected_length": expected_length,
            "observed_length": observed_length,
            "relative_length_error": relative_length_error,
            "node_coverage": node_coverage,
            "route_length_agreement": route_length_agreement,
            "score": composites["controllability"],
        },
        "topological_consistency": {
            "topology_validity": topology_validity,
            "etg_fidelity": etg_fidelity,
            "score": composites["topological_consistency"],
        },
        "etg_fidelity": {
            "score": etg_fidelity,
            "node_f1": float(((comparison.get("node") or {}).get("f1", 0.0))),
            "edge_f1": float(((comparison.get("edge") or {}).get("f1", 0.0))),
            "sequence_similarity": float(((comparison.get("sequence") or {}).get("similarity", 0.0))),
            "comparison": comparison,
        },
        "fun_proxy": {
            "score": composites["pacing_variation"],
            "components": {
                "content_variation": content_variation,
                "event_balance": event_balance,
                "route_rhythm": route_rhythm,
                "length_variation": length_rhythm,
                "turning": turn_rhythm,
                "elevation": elevation_rhythm,
            },
        },
        "component_diversity": {
            "strategy": component_meta.get("strategy"),
            "score": content_variation,
            "family_entropy": family_entropy,
            "family_count": family_count,
            "family_usage_total": sum(int(value) for value in family_usage.values()),
        },
        "diversity": {
            "score": 0.0,
            "scope": "batch",
        },
        "balance": {
            "score": event_balance,
            "components": balance_components,
        },
        "structure": {"node_count": len(nodes), "edge_count": len(edges), "challenge_ratio": challenge_ratio},
        "overall_score": composites["overall"],
    }
    return {
        "ok": True,
        "metric_profile": "paper",
        "metrics": metrics,
        "topology": topology,
        "signature": {
            "node_types": sorted(type_stream),
            "type_entropy": _entropy(type_counts),
            "component_families": sorted(str(key) for key in family_usage),
            "component_family_entropy": family_entropy,
            "shape_vector": [geometry_variation, content_variation, event_balance, route_rhythm],
        },
    }


def _jaccard_distance(first: set[str], second: set[str]) -> float:
    return 0.0 if not first and not second else 1.0 - len(first & second) / max(1, len(first | second))


def _vector_distance(first: list[float], second: list[float]) -> float:
    length = max(len(first), len(second))
    return math.sqrt(sum(((first[index] if index < len(first) else 0.0) - (second[index] if index < len(second) else 0.0)) ** 2 for index in range(length)))


def compute_signature_diversity(signatures: list[dict[str, Any]]) -> dict[str, float]:
    type_sets = [set(str(value) for value in signature.get("node_types") or []) for signature in signatures]
    family_sets = [set(str(value) for value in signature.get("component_families") or []) for signature in signatures]
    vectors = [[_clamp01(float(value)) for value in (signature.get("shape_vector") or [])] for signature in signatures]

    type_distances = [_jaccard_distance(type_sets[i], type_sets[j]) for i, j in itertools.combinations(range(len(signatures)), 2)]
    family_distances = [_jaccard_distance(family_sets[i], family_sets[j]) for i, j in itertools.combinations(range(len(signatures)), 2)]
    shape_distances = []
    for i, j in itertools.combinations(range(len(signatures)), 2):
        dimensions = max(len(vectors[i]), len(vectors[j]))
        shape_distances.append(_clamp01(_vector_distance(vectors[i], vectors[j]) / math.sqrt(max(1, dimensions))))

    type_profiles = [tuple(sorted(str(value) for value in signature.get("node_types") or [])) for signature in signatures]
    family_profiles = [tuple(sorted(str(value) for value in signature.get("component_families") or [])) for signature in signatures]
    shape_profiles = [tuple(round(value, 1) for value in vector) for vector in vectors]

    def normalized_entropy(values: list[tuple[Any, ...]]) -> float:
        counts = {value: values.count(value) for value in set(values)}
        return _clamp01(_entropy(counts) / math.log2(len(values))) if len(values) > 1 else 0.0

    type_distance = _mean(type_distances)
    family_distance = _mean(family_distances)
    shape_distance = _mean(shape_distances)
    type_entropy = normalized_entropy(type_profiles)
    family_entropy = normalized_entropy(family_profiles)
    shape_entropy = normalized_entropy(shape_profiles)
    if len(signatures) < 2:
        score = 0.0
    else:
        distributional_distance = _mean([type_distance, family_distance, shape_distance])
        entropy_score = _mean([type_entropy, family_entropy, shape_entropy])
        score = _clamp01(0.5 * distributional_distance + 0.5 * entropy_score)
    return {
        "score": score,
        "type_jaccard_distance_mean": type_distance,
        "component_family_jaccard_distance_mean": family_distance,
        "shape_vector_distance_mean": shape_distance,
        "type_entropy": type_entropy,
        "component_family_entropy": family_entropy,
        "shape_entropy": shape_entropy,
    }


def evaluate_batch_quality(
    levels: list[dict[str, Any]],
    etgs: list[dict[str, Any] | None] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    etgs = etgs or [None] * len(levels)
    reports = [evaluate_level_quality(level, etg, options) for level, etg in zip(levels, etgs)]
    scores = [float(report["metrics"]["overall_score"]) for report in reports]
    diversity = compute_signature_diversity([report["signature"] for report in reports])
    return {
        "ok": True,
        "count": len(reports),
        "overall_score": {"mean": _mean(scores), "std": _std(scores), "min": min(scores, default=0.0), "max": max(scores, default=0.0)},
        "diversity": diversity,
        "reports": reports,
    }


def summarize_report_scalars(report: dict[str, Any]) -> dict[str, float]:
    metrics = report.get("metrics") or {}
    return {
        "overall_score": float(metrics.get("overall_score", 0.0)),
        "playability_score": float((metrics.get("playability") or {}).get("score", 0.0)),
        "key_lock_ok": float((metrics.get("key_lock_consistency") or {}).get("score", 0.0)),
        "controllability_score": float((metrics.get("controllability") or {}).get("score", 0.0)),
        "length_error": float((metrics.get("controllability") or {}).get("relative_length_error", 1.0)),
        "node_coverage": float((metrics.get("controllability") or {}).get("node_coverage", 0.0)),
        "etg_fidelity_score": float((metrics.get("etg_fidelity") or {}).get("score", 0.0)),
        "pacing_variation_score": float((metrics.get("fun_proxy") or {}).get("score", 0.0)),
        "component_diversity_score": float((metrics.get("component_diversity") or {}).get("score", 0.0)),
        "diversity_score": float((metrics.get("diversity") or {}).get("score", 0.0)),
        "balance_score": float((metrics.get("balance") or {}).get("score", 0.0)),
    }
