from __future__ import annotations

import math
from typing import Any


def node(node_id: str, types: list[str], label: str, experience: str, domain_type: str, intensity: float, gx: float, gy: float) -> dict[str, Any]:
    return {"id": node_id, "type": types[0], "types": types, "label": label, "experience_type": experience, "domain_type": domain_type, "intensity": intensity, "data": {"layout": {"x": gx, "y": gy}, "fall_guys_node": domain_type}}


def edge(edge_id: str, source: str, target: str, length: float, role: str) -> dict[str, Any]:
    return {"id": edge_id, "from": source, "to": target, "length": length, "data": {"experience_transition": role}}


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def band_score(value: float, target: float, width: float) -> float:
    return clamp01(1.0 - abs(float(value) - target) / max(1e-6, width))


def distance(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(float(b["x"]) - float(a["x"]), float(b["z"]) - float(a["z"]))
