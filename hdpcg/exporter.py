"""Build level package JSON compatible with JS exporter format."""

from __future__ import annotations

import math
from typing import Any


def _sample_motion(platform: dict[str, Any], t: float) -> dict[str, Any]:
    motion = platform.get("motion") or {}
    axis = motion.get("axis", "x")
    amplitude = float(motion.get("amplitude", 0.0))
    period = float(motion.get("period", 1.0))
    phase = float(motion.get("phase", 0.0))
    omega = (2.0 * math.pi) / max(1e-6, period)
    offset = math.sin(omega * t + phase) * amplitude
    pos = dict(platform.get("pos") or {})
    pos[axis] = float(pos.get(axis, 0.0)) + offset
    return pos


def _sample_enemy(enemy: dict[str, Any], t: float) -> dict[str, Any]:
    patrol = enemy.get("patrol")
    if not patrol:
        return dict(enemy.get("pos") or {})

    from_pos = patrol.get("from") or {}
    to_pos = patrol.get("to") or {}
    span = float(to_pos.get("x", 0.0)) - float(from_pos.get("x", 0.0))
    speed = float(enemy.get("speed", 1.0) or 1.0)
    cycle = 2.0 * abs(span)
    if cycle <= 1e-6:
        return {
            "x": float(from_pos.get("x", 0.0)),
            "y": float(from_pos.get("y", 0.0)),
            "z": float(from_pos.get("z", 0.0)),
        }
    phase = (t * speed) % cycle
    offset = phase
    if offset > abs(span):
        offset = cycle - offset
    direction = 1.0 if span >= 0 else -1.0
    return {
        "x": float(from_pos.get("x", 0.0)) + direction * offset,
        "y": float(from_pos.get("y", 0.0)),
        "z": float(from_pos.get("z", 0.0)),
    }


def _sample_sweeper_angle(sweeper: dict[str, Any], t: float) -> float:
    period = max(1e-6, float(sweeper.get("period", 4.0) or 4.0))
    direction = 1.0 if float(sweeper.get("direction", 1.0) or 1.0) >= 0 else -1.0
    phase = float(sweeper.get("phase", 0.0) or 0.0)
    return direction * ((2.0 * math.pi * t) / period) + phase


def _sample_timed_gate_open(gate: dict[str, Any], t: float) -> bool:
    period = max(1e-6, float(gate.get("period", 5.0) or 5.0))
    open_duration = max(0.0, min(period, float(gate.get("openDuration", period * 0.45) or period * 0.45)))
    phase = float(gate.get("phase", 0.0) or 0.0)
    local = (t + phase) % period
    return local < open_duration


def _build_flag_map(items: list[dict[str, Any]], value: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        key = item.get("key_id") or item.get("lock_id") or item.get("id")
        if key:
            out[str(key)] = value
    return out


def _build_timing_windows(etg: dict[str, Any] | None) -> dict[str, Any]:
    if not etg:
        return {}
    windows: dict[str, Any] = {}
    for node in etg.get("nodes") or []:
        window = ((node.get("data") or {}).get("timing_window")) if isinstance(node, dict) else None
        if window:
            windows[node.get("id")] = window
    for edge in etg.get("edges") or []:
        window = ((edge.get("data") or {}).get("window")) if isinstance(edge, dict) else None
        if window:
            windows[edge.get("id")] = window
    return windows


def _build_phase_flags(etg: dict[str, Any] | None) -> dict[str, list[str]]:
    if not etg:
        return {}
    flags: dict[str, list[str]] = {}
    version = etg.get("version")
    if version == 2:
        for node in etg.get("nodes") or []:
            types = node.get("types") if isinstance(node.get("types"), list) and node.get("types") else ([node.get("type")] if node.get("type") else [])
            if "Key" in types:
                key_id = node.get("key_id") or "K1"
                flags[node.get("id")] = [f"has_key[{key_id}]=1"]
            if "Lock" in types:
                key_id = node.get("requires_key_id") or "K1"
                flags[f"{node.get('id')}:pre"] = [f"has_key[{key_id}]==1"]
        for edge in etg.get("edges") or []:
            length = edge.get("length")
            if isinstance(length, (int, float)):
                flags[edge.get("id")] = [f"edge_length={round(float(length), 2)}"]
        return flags

    for node in etg.get("nodes") or []:
        effects = node.get("effects") if isinstance(node.get("effects"), list) else None
        pre = node.get("preconditions") if isinstance(node.get("preconditions"), list) else None
        if effects:
            flags[node.get("id")] = list(effects)
        if pre:
            flags[f"{node.get('id')}:pre"] = list(pre)

    for edge in etg.get("edges") or []:
        effects = edge.get("effects") if isinstance(edge.get("effects"), list) else None
        pre = edge.get("preconditions") if isinstance(edge.get("preconditions"), list) else None
        if effects:
            flags[edge.get("id")] = list(effects)
        if pre:
            flags[f"{edge.get('id')}:pre"] = list(pre)

    return flags


def build_export_package(level: dict[str, Any], report: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    sample_duration = float(options.get("sampleDuration", 10))
    sample_step = float(options.get("sampleStep", 1.0))

    etg = level.get("etg")
    meta = level.get("meta") or {}
    component_generation = (meta.get("component_generation") if isinstance(meta, dict) else None) or None
    timing_windows = _build_timing_windows(etg)
    phase_flags = _build_phase_flags(etg)

    timeline: list[dict[str, Any]] = []
    t = 0.0
    while t <= sample_duration + 1e-6:
        timeline.append(
            {
                "t": round(t, 2),
                "moving_platforms": [
                    {"id": platform.get("id"), "pos": _sample_motion(platform, t)}
                    for platform in level.get("platforms") or []
                    if platform.get("kind") == "moving" and platform.get("motion")
                ],
                "sweepers": [
                    {"id": sweeper.get("id"), "angle": _sample_sweeper_angle(sweeper, t)}
                    for sweeper in level.get("sweepers") or []
                ],
                "timed_gates": [
                    {"id": gate.get("id"), "open": _sample_timed_gate_open(gate, t)}
                    for gate in level.get("timed_gates") or []
                ],
                "bumpers": level.get("bumpers") or [],
                "showcase_characters": level.get("showcase_characters") or [],
                "enemies": [
                    {"id": enemy.get("id"), "pos": _sample_enemy(enemy, t)} for enemy in level.get("enemies") or []
                ],
                "flags": {
                    "has_key": _build_flag_map(level.get("keys") or [], 0),
                    "lock_open": _build_flag_map(level.get("locks") or [], 0),
                },
                "phase": 0,
            }
        )
        t += sample_step

    return {
        "meta": {
            **meta,
            "component_generation": component_generation,
        },
        "etg": etg,
        "constraints": {
            "timing_windows": timing_windows,
            "phase_flags": phase_flags,
            "component_generation": component_generation,
        },
        "level": {
            "platforms": level.get("platforms") or [],
            "enemies": level.get("enemies") or [],
            "sweepers": level.get("sweepers") or [],
            "timed_gates": level.get("timed_gates") or [],
            "bumpers": level.get("bumpers") or [],
            "showcase_characters": level.get("showcase_characters") or [],
            "keys": level.get("keys") or [],
            "locks": level.get("locks") or [],
            "checkpoints": level.get("checkpoints") or [],
            "start": level.get("start"),
            "goal": level.get("goal"),
        },
        "mapping": level.get("mapping") or {"node": {}, "edge": {}},
        "anchors": level.get("anchors") or {},
        "time_expanded": {
            "duration": sample_duration,
            "step": sample_step,
            "timeline": timeline,
        },
        "validation": report,
    }
