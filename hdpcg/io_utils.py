"""JSON IO helpers for ETG/Level/Package interoperability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_payload_kind(data: dict[str, Any]) -> str:
    if isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list):
        return "etg"
    if isinstance(data, dict) and isinstance((data.get("level") or {}).get("platforms"), list):
        return "package"
    if isinstance(data, dict) and isinstance(data.get("platforms"), list) and data.get("start"):
        return "level"
    raise ValueError("Unsupported JSON payload. Expected ETG, level, or level package")


def normalize_level(level: dict[str, Any]) -> dict[str, Any]:
    return {
        **level,
        "platforms": list(level.get("platforms") or []),
        "enemies": list(level.get("enemies") or []),
        "sweepers": list(level.get("sweepers") or []),
        "timed_gates": list(level.get("timed_gates") or []),
        "bumpers": list(level.get("bumpers") or []),
        "showcase_characters": list(level.get("showcase_characters") or []),
        "keys": list(level.get("keys") or []),
        "locks": list(level.get("locks") or []),
        "checkpoints": list(level.get("checkpoints") or []),
        "start": level.get("start") or {"x": 0, "y": 0, "z": 0},
        "goal": level.get("goal"),
        "mapping": level.get("mapping") or {"node": {}, "edge": {}},
        "anchors": level.get("anchors") or {},
    }


def extract_level_and_etg(data: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    kind = detect_payload_kind(data)
    if kind == "etg":
        return None, data, "etg"
    if kind == "level":
        return normalize_level(data), data.get("etg"), "level"
    package_raw = dict(data.get("level") or {})
    if not package_raw.get("anchors") and isinstance(data.get("anchors"), dict):
        package_raw["anchors"] = data.get("anchors")
    if not package_raw.get("mapping") and isinstance(data.get("mapping"), dict):
        package_raw["mapping"] = data.get("mapping")
    if not package_raw.get("etg") and isinstance(data.get("etg"), dict):
        package_raw["etg"] = data.get("etg")
    package_level = normalize_level(package_raw)
    return package_level, data.get("etg") or package_level.get("etg"), "package"
