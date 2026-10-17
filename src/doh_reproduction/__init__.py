"""Defensive offline reproduction framework for DoH tunnel detection."""

from .clumping import (
    CLUMP_TIMEOUT_SECONDS,
    Clump,
    Packet,
    clumping,
    segment_clumps,
)
from .operational_latency import (
    OperationalLatencyBenchmarkResult,
    benchmark_operational_latency,
    compute_distribution_summary,
    compute_percentile,
    compute_window_collection_delay,
    emit_latency_benchmark_artifacts,
)

__all__ = [
    "CLUMP_TIMEOUT_SECONDS",
    "Packet",
    "Clump",
    "clumping",
    "segment_clumps",
    "OperationalLatencyBenchmarkResult",
    "benchmark_operational_latency",
    "compute_distribution_summary",
    "compute_percentile",
    "compute_window_collection_delay",
    "emit_latency_benchmark_artifacts",
]
