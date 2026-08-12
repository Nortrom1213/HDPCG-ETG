"""Scale profiles for ETG-bank and benchmark experiments."""

from __future__ import annotations

import copy
from typing import Any

from .paper_config import load_paper_config


def _scale_profiles() -> dict[str, dict[str, Any]]:
    return dict(load_paper_config()["benchmark"]["scale_profiles"])


def list_scale_names() -> list[str]:
    return list(_scale_profiles().keys())


def scale_profile(scale: str) -> dict[str, Any]:
    key = str(scale).strip().lower()
    profiles = _scale_profiles()
    if key not in profiles:
        raise ValueError(f"unknown scale: {scale}")
    base = copy.deepcopy(profiles[key])
    base["cpSatNumWorkers"] = int(base.get("cpSatNumWorkers") or 1)
    return base


def build_scale_config(scale: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = scale_profile(scale)
    if overrides:
        for key, value in overrides.items():
            cfg[key] = value
    return cfg
