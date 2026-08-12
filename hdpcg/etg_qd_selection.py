"""QD ETG-bank generation and selection utilities."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .etg_core import NODE_TYPES, compute_canonical_route, validate_etg
from .etg_generator import create_etg
from .experiment_scale_profiles import build_scale_config, list_scale_names
from .io_utils import write_json
from .random_utils import rng_from_seed

DESCRIPTOR_KEYS = [
    "node_count",
    "edge_count",
    "canonical_length",
    "branch_factor",
    "loop_count",
    "type_entropy",
    "key_count",
    "lock_count",
    "challenge_ratio",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(value: Any) -> float:
    try:
        n = float(value)
    except Exception:
        n = 0.0
    return max(0.0, min(1.0, n))


def _entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    n = len(values)
    out = 0.0
    for c in counts.values():
        p = c / n
        out -= p * math.log2(max(1e-12, p))
    return out


def _node_types(node: dict[str, Any]) -> list[str]:
    if isinstance(node.get("types"), list) and node.get("types"):
        return list(node.get("types"))
    if node.get("type"):
        return [node.get("type")]
    return [NODE_TYPES["NONE"]]


def compute_etg_descriptor(etg: dict[str, Any]) -> dict[str, float]:
    nodes = etg.get("nodes") or []
    edges = etg.get("edges") or []
    degree: dict[str, int] = {str(n["id"]): 0 for n in nodes if n.get("id")}
    for edge in edges:
        a = edge.get("from")
        b = edge.get("to")
        if a in degree:
            degree[a] += 1
        if b in degree:
            degree[b] += 1
    branch_factor = sum(degree.values()) / max(1, len(degree))

    type_stream: list[str] = []
    challenge_nodes = 0
    non_terminal_nodes = 0
    key_count = 0
    lock_count = 0
    challenge_types = {
        NODE_TYPES["JUMP"],
        NODE_TYPES["DROP"],
        NODE_TYPES["ENEMY"],
        NODE_TYPES["KEY"],
        NODE_TYPES["LOCK"],
    }
    terminal_types = {NODE_TYPES["START"], NODE_TYPES["GOAL"]}
    for node in nodes:
        types = _node_types(node)
        type_stream.extend(types)
        if NODE_TYPES["KEY"] in types:
            key_count += 1
        if NODE_TYPES["LOCK"] in types:
            lock_count += 1
        if any(node_type in terminal_types for node_type in types):
            continue
        non_terminal_nodes += 1
        if any(node_type in challenge_types for node_type in types):
            challenge_nodes += 1

    canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
    canonical_len = float(canonical.get("totalLength", 0.0)) if canonical.get("ok") else 0.0
    challenge_ratio = challenge_nodes / max(1, non_terminal_nodes)
    loop_count = max(0, len(edges) - len(nodes) + 1)
    return {
        "node_count": float(len(nodes)),
        "edge_count": float(len(edges)),
        "canonical_length": canonical_len,
        "branch_factor": branch_factor,
        "loop_count": float(loop_count),
        "type_entropy": _entropy(type_stream),
        "key_count": float(key_count),
        "lock_count": float(lock_count),
        "challenge_ratio": challenge_ratio,
    }


def _build_bounds(candidates: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    bounds: dict[str, tuple[float, float]] = {}
    for key in DESCRIPTOR_KEYS:
        values = [float((cand.get("descriptor") or {}).get(key, 0.0)) for cand in candidates]
        if not values:
            bounds[key] = (0.0, 1.0)
            continue
        bounds[key] = (min(values), max(values))
    return bounds


def _normalize(value: float, lo: float, hi: float) -> float:
    if hi <= lo + 1e-9:
        return 0.5
    return (value - lo) / (hi - lo)


def _descriptor_vector(descriptor: dict[str, float], bounds: dict[str, tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for key in DESCRIPTOR_KEYS:
        lo, hi = bounds.get(key, (0.0, 1.0))
        out.append(_normalize(float(descriptor.get(key, 0.0)), lo, hi))
    return out


def _vector_distance(a: list[float], b: list[float]) -> float:
    n = max(len(a), len(b))
    total = 0.0
    for i in range(n):
        av = float(a[i]) if i < len(a) else 0.0
        bv = float(b[i]) if i < len(b) else 0.0
        d = av - bv
        total += d * d
    return math.sqrt(total)


def _quality_score(vector: list[float], descriptor: dict[str, float]) -> float:
    idx = {name: i for i, name in enumerate(DESCRIPTOR_KEYS)}
    type_entropy_norm = vector[idx["type_entropy"]]
    branch_factor_norm = vector[idx["branch_factor"]]
    canonical_length_norm = vector[idx["canonical_length"]]
    challenge_ratio = _clamp01(descriptor.get("challenge_ratio", 0.0))
    return (
        0.35 * type_entropy_norm
        + 0.25 * branch_factor_norm
        + 0.20 * challenge_ratio
        + 0.20 * canonical_length_norm
    )


def select_qd_candidates(candidates: list[dict[str, Any]], select_count: int = 3) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    valid = [cand for cand in candidates if cand.get("valid")]
    if len(valid) < select_count:
        return [], {"reason": "insufficient_valid", "valid_count": len(valid), "pairwise_distances": []}

    bounds = _build_bounds(valid)
    for cand in valid:
        descriptor = cand.get("descriptor") or {}
        vec = _descriptor_vector(descriptor, bounds)
        cand["descriptor_norm"] = {k: v for k, v in zip(DESCRIPTOR_KEYS, vec)}
        cand["quality"] = _quality_score(vec, descriptor)

    valid_sorted = sorted(valid, key=lambda item: float(item.get("quality", 0.0)), reverse=True)
    top_count = max(select_count, int(math.ceil(len(valid_sorted) * 0.5)))
    pool = valid_sorted[:top_count]
    if len(pool) < select_count:
        return [], {"reason": "insufficient_pool", "valid_count": len(valid), "pairwise_distances": []}

    selected: list[dict[str, Any]] = [pool[0]]
    selected_vecs = [_descriptor_vector(selected[0].get("descriptor") or {}, bounds)]
    pool_set = {cand["id"] for cand in pool}

    while len(selected) < select_count:
        best = None
        best_score = -1.0
        best_quality = -1.0
        for cand in pool:
            if cand["id"] not in pool_set:
                continue
            if cand["id"] in {item["id"] for item in selected}:
                continue
            vec = _descriptor_vector(cand.get("descriptor") or {}, bounds)
            min_dist = min(_vector_distance(vec, s_vec) for s_vec in selected_vecs) if selected_vecs else 0.0
            quality = float(cand.get("quality", 0.0))
            if min_dist > best_score + 1e-9 or (abs(min_dist - best_score) <= 1e-9 and quality > best_quality):
                best = cand
                best_score = min_dist
                best_quality = quality
        if best is None:
            break
        selected.append(best)
        selected_vecs.append(_descriptor_vector(best.get("descriptor") or {}, bounds))

    if len(selected) < select_count:
        return selected, {"reason": "selection_shortfall", "valid_count": len(valid), "pairwise_distances": []}

    pairwise = []
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            a = selected[i]
            b = selected[j]
            dist = _vector_distance(
                _descriptor_vector(a.get("descriptor") or {}, bounds),
                _descriptor_vector(b.get("descriptor") or {}, bounds),
            )
            pairwise.append({"a": a["id"], "b": b["id"], "distance": dist})
    return selected, {"reason": None, "valid_count": len(valid), "pairwise_distances": pairwise}


def make_etg_bank(
    out_dir: str | Path,
    *,
    pool_size: int = 120,
    select_count: int = 3,
    seed_prefix: str = "paper_etg",
    scales: list[str] | None = None,
    extra_batch_size: int = 40,
    max_extra_batches: int = 5,
) -> dict[str, Any]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    scales_use = [s.lower() for s in (scales or list_scale_names())]

    manifest: dict[str, Any] = {
        "version": "etg_bank_v1",
        "created_at": _iso_now(),
        "config": {
            "pool_size": int(pool_size),
            "select_count": int(select_count),
            "seed_prefix": seed_prefix,
            "extra_batch_size": int(extra_batch_size),
            "max_extra_batches": int(max_extra_batches),
            "scales": scales_use,
        },
        "scales": {},
        "selected_global": [],
        "dataset_incomplete": False,
    }

    for scale in scales_use:
        scale_dir = root / scale
        pool_dir = scale_dir / "pool"
        selected_dir = scale_dir / "selected"
        pool_dir.mkdir(parents=True, exist_ok=True)
        selected_dir.mkdir(parents=True, exist_ok=True)

        candidates: list[dict[str, Any]] = []
        next_index = 0
        batches_done = 0
        selected: list[dict[str, Any]] = []
        selection_meta: dict[str, Any] = {"reason": "not_run", "valid_count": 0, "pairwise_distances": []}

        while True:
            target_batch = int(pool_size) if batches_done == 0 else int(extra_batch_size)
            if target_batch <= 0:
                break
            cfg = build_scale_config(scale)
            for _ in range(target_batch):
                seed = f"{seed_prefix}_{scale}_{next_index:04d}"
                next_index += 1
                run_cfg = dict(cfg)
                run_cfg["seed"] = seed
                etg = create_etg(run_cfg, rng_from_seed(f"{seed}-etg"))
                validation = validate_etg(etg)
                canonical = compute_canonical_route(etg, {"defaultSpeed": (etg.get("meta") or {}).get("defaultSpeed")})
                descriptor = compute_etg_descriptor(etg)
                valid = bool(validation.ok and canonical.get("ok"))
                entry_id = f"{scale}_{next_index - 1:04d}"
                pool_path = pool_dir / f"{entry_id}.json"
                write_json(pool_path, etg)
                candidates.append(
                    {
                        "id": entry_id,
                        "scale": scale,
                        "seed": seed,
                        "path": str(pool_path.relative_to(root)).replace("\\", "/"),
                        "valid": valid,
                        "issues": list(validation.issues),
                        "warnings": list(validation.warnings),
                        "descriptor": descriptor,
                        "canonical_ok": bool(canonical.get("ok")),
                    }
                )

            batches_done += 1
            selected, selection_meta = select_qd_candidates(candidates, select_count=select_count)
            if len(selected) >= select_count:
                break
            if batches_done > int(max_extra_batches):
                break

        selected_index = {item["id"]: item for item in selected}
        selected_exports: list[dict[str, Any]] = []
        for cand in candidates:
            if cand["id"] not in selected_index:
                continue
            etg_payload = None
            try:
                etg_payload = Path(root / cand["path"]).read_text(encoding="utf-8")
            except Exception:
                etg_payload = None
            if etg_payload is not None:
                # Write selected ETGs as standalone benchmark inputs.
                (selected_dir / f"{cand['id']}.json").write_text(etg_payload, encoding="utf-8")
            selected_entry = {
                "id": cand["id"],
                "scale": scale,
                "seed": cand["seed"],
                "path": str((selected_dir / f"{cand['id']}.json").relative_to(root)).replace("\\", "/"),
                "descriptor": cand["descriptor"],
                "quality": float(selected_index[cand["id"]].get("quality", 0.0)),
            }
            selected_exports.append(selected_entry)
            manifest["selected_global"].append(selected_entry)

        scale_summary = {
            "scale": scale,
            "profile": build_scale_config(scale),
            "pool_count": len(candidates),
            "valid_count": int(selection_meta.get("valid_count", 0)),
            "selected_count": len(selected_exports),
            "batches_done": batches_done,
            "selection_reason": selection_meta.get("reason"),
            "pairwise_distances": selection_meta.get("pairwise_distances") or [],
            "pool": [
                {
                    "id": c["id"],
                    "seed": c["seed"],
                    "path": c["path"],
                    "valid": bool(c["valid"]),
                    "descriptor": c["descriptor"],
                    "quality": float(c.get("quality", 0.0)),
                }
                for c in candidates
            ],
            "selected": selected_exports,
        }
        manifest["scales"][scale] = scale_summary
        if len(selected_exports) < int(select_count):
            manifest["dataset_incomplete"] = True

    write_json(root / "dataset_manifest.json", manifest)
    return manifest
