"""Deterministic pseudo-random numbers for statistical tests (no `random` module)."""

from __future__ import annotations

import math
from collections.abc import Iterator


class Noise:
    """Deterministic N(0, 1) stream (LCG + Box-Muller): reproducible, no `random` module."""

    def __init__(self, seed: int) -> None:
        self._state = seed + 1
        self._spare: Iterator[float] = iter(())

    def _uniform(self) -> float:
        self._state = (6364136223846793005 * self._state + 1442695040888963407) % 2**64
        return ((self._state >> 11) + 1) / (2**53 + 1)

    def gauss(self, mu: float, sigma: float) -> float:
        z = next(self._spare, None)
        if z is None:
            u1, u2 = self._uniform(), self._uniform()
            radius = math.sqrt(-2 * math.log(u1))
            z = radius * math.cos(2 * math.pi * u2)
            self._spare = iter((radius * math.sin(2 * math.pi * u2),))
        return mu + sigma * z
