"""Hybrid routing: which pages go to GitHub and which stay on this computer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Router:
    """Local first. A page goes to the remote tier when it is big enough (its size against A4 is
    at least `min_size_factor`; 0 turns the rule off) or when the OCR phase it asks for is one
    of `phases` (`moderate`, `deep`; the quick phase is local unless listed)."""

    min_size_factor: float
    phases: tuple[str, ...] = ()

    def remote(self, size_factor: float, phase: str = "quick") -> bool:
        if phase in self.phases:
            return True
        return self.min_size_factor > 0 and size_factor >= self.min_size_factor
