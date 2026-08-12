"""Deterministic random utilities shared by the Python and browser implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


UINT32_MASK = 0xFFFFFFFF


def _imul32(a: int, b: int) -> int:
    """Signed 32-bit integer multiplication with JS-like overflow semantics."""
    a &= UINT32_MASK
    b &= UINT32_MASK
    a_signed = a if a < 0x80000000 else a - 0x100000000
    b_signed = b if b < 0x80000000 else b - 0x100000000
    out = (a_signed * b_signed) & UINT32_MASK
    return out


def hash_string(value: str) -> int:
    """FNV-1a style hash mirrored from src/random.js."""
    h = 2166136261
    for ch in value:
        h ^= ord(ch)
        h = _imul32(h, 16777619)
    return h & UINT32_MASK


@dataclass
class Mulberry32:
    """Stateful Mulberry32 PRNG."""

    seed: int

    def __post_init__(self) -> None:
        self._t = int(self.seed) & UINT32_MASK

    def random(self) -> float:
        self._t = (self._t + 0x6D2B79F5) & UINT32_MASK
        r = _imul32(self._t ^ (self._t >> 15), 1 | self._t)
        r ^= (r + _imul32(r ^ (r >> 7), 61 | r)) & UINT32_MASK
        out = (r ^ (r >> 14)) & UINT32_MASK
        return out / 4294967296.0

    def __call__(self) -> float:
        return self.random()



def rng_from_seed(seed: int | str) -> Mulberry32:
    n = hash_string(seed) if isinstance(seed, str) else int(seed)
    return Mulberry32(n & UINT32_MASK)


def rand_range(rng: Mulberry32, min_value: float, max_value: float) -> float:
    return min_value + (max_value - min_value) * rng.random()


def rand_int(rng: Mulberry32, min_value: int, max_value: int) -> int:
    return int(rand_range(rng, min_value, max_value + 1))


def pick(rng: Mulberry32, values: Sequence[T]) -> T:
    if not values:
        raise ValueError("values must be non-empty")
    return values[rand_int(rng, 0, len(values) - 1)]


def shuffled(rng: Mulberry32, values: Iterable[T]) -> list[T]:
    out = list(values)
    for i in range(len(out) - 1, 0, -1):
        j = rand_int(rng, 0, i)
        out[i], out[j] = out[j], out[i]
    return out
