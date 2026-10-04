"""Packet and clump data structures and pure clumping transformation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Clump inactivity timeout in seconds (1 millisecond) per DoHlyzer reference
CLUMP_TIMEOUT_SECONDS: float = 0.001


@dataclass(frozen=True)
class Packet:
    """Represents a single directional packet observation within a flow.

    Attributes:
        timestamp: Packet arrival time in seconds (must be non-negative and monotonic).
        length: Application payload size or frame length in bytes (must be non-negative).
        direction: Flow direction (0 for forward/client-to-server, 1 for backward/server-to-client).
    """

    timestamp: float
    length: int
    direction: int

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, (int, float)):
            raise TypeError(
                f"Packet timestamp must be numeric, got {type(self.timestamp).__name__}"
            )
        if not isinstance(self.length, int):
            raise TypeError(
                f"Packet length must be integer, got {type(self.length).__name__}"
            )
        if not isinstance(self.direction, int):
            raise TypeError(
                f"Packet direction must be integer, got {type(self.direction).__name__}"
            )
        if self.length < 0:
            raise ValueError(f"Packet length cannot be negative: {self.length}")


@dataclass(frozen=True)
class Clump:
    """Represents an aggregated clump of consecutive packets in the same direction.

    Characterized by the 5-tuple:
        size: Total bytes of all packets aggregated into this clump.
        pkt_count: Total number of physical packets in this clump.
        direction: Direction of transmission (0: forward, 1: backward).
        duration: Elapsed time from first to last packet in the clump (t_last - t_first).
        interarrival: Time elapsed from conclusion of previous clump to start of this clump.
    """

    size: int
    pkt_count: int
    direction: int
    duration: float
    interarrival: float

    @classmethod
    def empty(cls) -> Clump:
        """Deterministic zero-padded clump for short flows."""
        return cls(size=0, pkt_count=0, direction=0, duration=0.0, interarrival=0.0)

    def to_vector(self) -> list[float]:
        """Convert clump to 5-element numerical vector: [size, pkt_count, direction, duration, interarrival]."""
        return [
            float(self.size),
            float(self.pkt_count),
            float(self.direction),
            float(self.duration),
            float(self.interarrival),
        ]


def clumping(
    packets: Sequence[Packet],
    timeout: float = CLUMP_TIMEOUT_SECONDS,
    first_interarrival: float = 0.0,
) -> list[Clump]:
    """Pure clumping function grouping packets into directional bursts.

    Rules:
    - Starts a new clump when transmission direction changes.
    - Starts a new clump when the inter-packet gap (current - previous) > timeout (0.001s).
    - Rejects negative payload lengths.
    - Rejects non-monotonic packet timestamps (t[i] < t[i-1]).
    - Defines the first clump's interarrival deterministically (default 0.0).
    - For subsequent clumps, interarrival is (current_clump_start - previous_clump_end).

    Args:
        packets: Sequence of Packet records.
        timeout: Maximum idle time between packets in same clump (seconds).
        first_interarrival: Deterministic interarrival time for the initial clump.

    Returns:
        List of Clump records.
    """
    if not packets:
        return []

    # Validate inputs: negative length and non-monotonic timestamps
    for i, pkt in enumerate(packets):
        if pkt.length < 0:
            raise ValueError(f"Negative packet length at index {i}: {pkt.length}")
        if i > 0 and pkt.timestamp < packets[i - 1].timestamp:
            raise ValueError(
                f"Non-monotonic timestamp detected at index {i}: "
                f"{pkt.timestamp} < {packets[i - 1].timestamp}"
            )

    clumps: list[Clump] = []
    current_pkts: list[Packet] = [packets[0]]
    prev_clump_end_time: float = packets[0].timestamp
    is_first_clump: bool = True

    for i in range(1, len(packets)):
        pkt = packets[i]
        last_pkt = current_pkts[-1]
        gap = pkt.timestamp - last_pkt.timestamp

        # Split clump if direction changed OR idle gap exceeds timeout
        if pkt.direction != current_pkts[0].direction or gap > timeout:
            clump_duration = current_pkts[-1].timestamp - current_pkts[0].timestamp
            interarrival = (
                first_interarrival
                if is_first_clump
                else (current_pkts[0].timestamp - prev_clump_end_time)
            )
            clump_size = sum(p.length for p in current_pkts)

            clumps.append(
                Clump(
                    size=clump_size,
                    pkt_count=len(current_pkts),
                    direction=current_pkts[0].direction,
                    duration=clump_duration,
                    interarrival=interarrival,
                )
            )
            prev_clump_end_time = current_pkts[-1].timestamp
            is_first_clump = False
            current_pkts = [pkt]
        else:
            current_pkts.append(pkt)

    # Finalize the terminal clump
    clump_duration = current_pkts[-1].timestamp - current_pkts[0].timestamp
    interarrival = (
        first_interarrival
        if is_first_clump
        else (current_pkts[0].timestamp - prev_clump_end_time)
    )
    clump_size = sum(p.length for p in current_pkts)
    clumps.append(
        Clump(
            size=clump_size,
            pkt_count=len(current_pkts),
            direction=current_pkts[0].direction,
            duration=clump_duration,
            interarrival=interarrival,
        )
    )

    return clumps


def segment_clumps(
    clumps: Sequence[Clump],
    window_size: int,
    stride: int = 1,
    pad: bool = True,
) -> list[list[Clump]]:
    """Segment a sequence of clumps using a fixed sliding window.

    Args:
        clumps: Sequence of Clump records.
        window_size: Number of clumps per segment (e.g. 6 for L1, 3 for L2).
        stride: Step size between consecutive segments (default 1).
        pad: If True, short flows (|clumps| < window_size) are zero-padded to window_size.

    Returns:
        List of segments, where each segment has exactly `window_size` Clump records.
    """
    if window_size <= 0:
        raise ValueError(f"window_size must be positive, got {window_size}")
    if stride <= 0:
        raise ValueError(f"stride must be positive, got {stride}")

    if not clumps:
        return []

    n = len(clumps)
    if n < window_size:
        if pad:
            padded = list(clumps) + [Clump.empty() for _ in range(window_size - n)]
            return [padded]
        return []

    segments: list[list[Clump]] = []
    for start in range(0, n - window_size + 1, stride):
        segments.append(list(clumps[start : start + window_size]))
    return segments
