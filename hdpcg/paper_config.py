from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_paper_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "configs" / "paper.json"
    return json.loads(path.read_text(encoding="utf-8"))


def method_profiles() -> list[dict[str, Any]]:
    return list(load_paper_config()["benchmark"]["methods"])
