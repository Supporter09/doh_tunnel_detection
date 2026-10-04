"""Defensive offline reproduction framework for DoH tunnel detection."""

from .clumping import (
    CLUMP_TIMEOUT_SECONDS,
    Clump,
    Packet,
    clumping,
    segment_clumps,
)

__all__ = [
    "CLUMP_TIMEOUT_SECONDS",
    "Packet",
    "Clump",
    "clumping",
    "segment_clumps",
]
