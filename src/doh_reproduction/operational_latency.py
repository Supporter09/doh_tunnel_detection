"""Operational latency benchmarking for DoH packet-clump sequence classification (Phase A).

Evaluates operational latency distributions on first-window-per-test-flow samples:
1. Traffic Collection Delay: Physical network time required to collect the clumps in
   the window: sum(duration + interarrival) across clumps in the window.
2. Sequence Preprocessing Latency: Time to extract reference vectors, apply DoHLyzer
   logarithmic normalizations, apply deterministic post-padding, and assemble tensors.
3. Model Inference Latency: Time for PyTorch forward pass (batch size = 1) with warm-up
   and CUDA device synchronization.
4. End-to-End Latency: Aligned sum of collection delay, preprocessing latency, and
   inference latency for each evaluated sample.

Explicit Claim Boundary:
Phase A operational latency microbenchmarks measure first-window-per-test-flow samples with
batch size 1, warm-up iterations, and CUDA synchronization. Evaluates traffic collection delay
(physical clump network observation time), sequence preprocessing, and PyTorch model forward pass.
Traffic collection delay is derived from clump timestamps/durations; preprocessing and inference are
timed in-memory without disk I/O. Does not claim OS socket capture or full network stack overhead.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import platform
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger("doh_reproduction.operational_latency")

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False

try:
    from .clumping import Clump
    from .timeseries_data import (
        PADDING_VECTOR,
        SequenceMetadata,
        SequenceSample,
        clump_to_reference_vector,
    )
except ImportError:
    try:
        from doh_reproduction.clumping import Clump
        from doh_reproduction.timeseries_data import (
            PADDING_VECTOR,
            SequenceMetadata,
            SequenceSample,
            clump_to_reference_vector,
        )
    except ImportError:
        Clump = None  # type: ignore[assignment,misc]
        PADDING_VECTOR = [-1.0, -1.0, -1.0, -1.0, 0.0]  # type: ignore[assignment]
        SequenceMetadata = None  # type: ignore[assignment,misc]
        SequenceSample = None  # type: ignore[assignment,misc]
        clump_to_reference_vector = None  # type: ignore[assignment]

PHASE_A_LATENCY_CLAIM_BOUNDARY: str = (
    "Phase A operational latency microbenchmarks measured on first-window-per-test-flow samples with "
    "batch size 1, warm-up iterations, and CUDA synchronization. Evaluates traffic collection delay "
    "(physical clump network observation time), sequence preprocessing, and PyTorch model forward pass. "
    "Traffic collection delay is derived from clump timestamps/durations; preprocessing and inference are "
    "timed in-memory without disk I/O. End-to-end latency represents the sum of aligned per-sample components."
)

LATENCY_CSV_FIELDNAMES: Tuple[str, ...] = (
    "task",
    "model",
    "window_size",
    "split_protocol",
    "device",
    "device_name",
    "sample_count",
    "batch_size",
    "warmup_iterations",
    # Collection Delay (seconds)
    "collection_mean_seconds",
    "collection_median_seconds",
    "collection_p50_seconds",
    "collection_p95_seconds",
    "collection_p99_seconds",
    "collection_min_seconds",
    "collection_max_seconds",
    "collection_std_seconds",
    # Preprocessing Latency (ms)
    "prep_mean_ms",
    "prep_median_ms",
    "prep_p50_ms",
    "prep_p95_ms",
    "prep_p99_ms",
    "prep_min_ms",
    "prep_max_ms",
    "prep_std_ms",
    # Inference Latency (ms)
    "infer_mean_ms",
    "infer_median_ms",
    "infer_p50_ms",
    "infer_p95_ms",
    "infer_p99_ms",
    "infer_min_ms",
    "infer_max_ms",
    "infer_std_ms",
    "infer_throughput_samples_per_second",
    # End-to-End Latency (seconds)
    "e2e_mean_seconds",
    "e2e_median_seconds",
    "e2e_p50_seconds",
    "e2e_p95_seconds",
    "e2e_p99_seconds",
    "e2e_min_seconds",
    "e2e_max_seconds",
    "e2e_std_seconds",
    "claim_boundary",
)


def compute_percentile(sorted_values: Sequence[float], q: float) -> float:
    """Compute q-th percentile (q in [0, 100]) using linear interpolation.

    Assumes sorted_values is already sorted in non-decreasing order.
    Guarantees that for q1 <= q2, compute_percentile(q1) <= compute_percentile(q2).
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    if q <= 0.0:
        return float(sorted_values[0])
    if q >= 100.0:
        return float(sorted_values[-1])

    rank = (float(q) / 100.0) * (n - 1)
    low_idx = int(math.floor(rank))
    high_idx = int(math.ceil(rank))
    if low_idx == high_idx:
        return float(sorted_values[low_idx])
    weight = rank - low_idx
    return float(sorted_values[low_idx] * (1.0 - weight) + sorted_values[high_idx] * weight)


def compute_distribution_summary(values: Sequence[float]) -> Dict[str, Any]:
    """Computes distribution statistics (p50, p95, p99, mean, std, min, max, count).

    Returns metrics both in original units (seconds) and milliseconds.
    Guarantees p50 <= p95 <= p99 for any distribution.
    """
    if not values:
        return {
            "count": 0,
            "mean_seconds": 0.0,
            "median_seconds": 0.0,
            "p50_seconds": 0.0,
            "p95_seconds": 0.0,
            "p99_seconds": 0.0,
            "min_seconds": 0.0,
            "max_seconds": 0.0,
            "std_seconds": 0.0,
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "std_ms": 0.0,
        }

    sorted_vals = sorted(float(v) for v in values)
    n = len(sorted_vals)
    mean_val = float(sum(sorted_vals) / n)
    variance = float(sum((x - mean_val) ** 2 for x in sorted_vals) / n) if n > 1 else 0.0
    std_val = math.sqrt(max(0.0, variance))

    min_val = float(sorted_vals[0])
    max_val = float(sorted_vals[-1])
    p50_val = compute_percentile(sorted_vals, 50.0)
    p95_val = compute_percentile(sorted_vals, 95.0)
    p99_val = compute_percentile(sorted_vals, 99.0)

    # Invariant guard: ensure numerical ordering p50 <= p95 <= p99
    p95_val = max(p50_val, p95_val)
    p99_val = max(p95_val, p99_val)

    return {
        "count": n,
        "mean_seconds": mean_val,
        "median_seconds": p50_val,
        "p50_seconds": p50_val,
        "p95_seconds": p95_val,
        "p99_seconds": p99_val,
        "min_seconds": min_val,
        "max_seconds": max_val,
        "std_seconds": std_val,
        "mean_ms": mean_val * 1000.0,
        "median_ms": p50_val * 1000.0,
        "p50_ms": p50_val * 1000.0,
        "p95_ms": p95_val * 1000.0,
        "p99_ms": p99_val * 1000.0,
        "min_ms": min_val * 1000.0,
        "max_ms": max_val * 1000.0,
        "std_ms": std_val * 1000.0,
    }


def compute_window_collection_delay(clumps: Sequence[Any], window_size: int) -> float:
    """Compute physical network observation duration for the window in seconds.

    Formula per contract:
    T_collection = sum(c.duration + c.interarrival for c in clumps[:window_size])
    """
    if not clumps or window_size <= 0:
        return 0.0
    window_clumps = clumps[:window_size]
    total_delay = 0.0
    for c in window_clumps:
        if hasattr(c, "duration") and hasattr(c, "interarrival"):
            dur = float(getattr(c, "duration", 0.0))
            ia = float(getattr(c, "interarrival", 0.0))
        elif isinstance(c, Mapping):
            dur = float(c.get("duration", 0.0))
            ia = float(c.get("interarrival", 0.0))
        else:
            dur = 0.0
            ia = 0.0
        total_delay += (dur + ia)
    return float(total_delay)


def sync_cuda_device(device: Union[str, Any] = "cpu") -> None:
    """Synchronize CUDA device if CUDA is active and device is CUDA."""
    if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
        dev_str = str(device).lower() if device is not None else ""
        if "cuda" in dev_str:
            try:
                torch.cuda.synchronize(device)
            except Exception:
                try:
                    torch.cuda.synchronize()
                except Exception:
                    pass


def preprocess_window_sample(
    clumps: Sequence[Any],
    window_size: int,
    device: Union[str, Any] = "cpu",
    is_bigru: bool = False,
) -> Tuple[Any, Optional[Any], float]:
    """Reconstruct exact sequence preprocessing from raw clumps.

    Measures:
    1. Converting clumps to reference vectors [interarrival, duration, size, packet_count, direction].
    2. Applying DoHLyzer logarithmic normalizations.
    3. Applying deterministic post-padding with PADDING_VECTOR.
    4. Tensor conversion and host-to-device transfer.
    5. Constructing boolean padding mask if model is BiGRU.

    Returns:
        (x_tensor, mask_tensor, preprocessing_seconds)
    """
    if not TORCH_AVAILABLE or torch is None:
        raise RuntimeError("PyTorch is required for preprocessing window samples.")

    dev = torch.device(device)
    window_clumps = list(clumps[:window_size]) if clumps else []
    pad_vec = list(PADDING_VECTOR)

    sync_cuda_device(dev)
    t0 = time.perf_counter_ns()

    vectors: List[List[float]] = []
    for c in window_clumps:
        if Clump is not None and isinstance(c, Clump):
            if clump_to_reference_vector is not None:
                vectors.append(clump_to_reference_vector(c, normalize=True))
            else:
                vectors.append([float(c.interarrival), float(c.duration), float(c.size), float(c.pkt_count), float(c.direction)])
        elif isinstance(c, (list, tuple)):
            vectors.append([float(x) for x in c])
        elif isinstance(c, Mapping):
            if Clump is not None and clump_to_reference_vector is not None:
                clump_obj = Clump(
                    size=int(c.get("size", 0)),
                    pkt_count=int(c.get("pkt_count", 1)),
                    direction=int(c.get("direction", 0)),
                    duration=float(c.get("duration", 0.0)),
                    interarrival=float(c.get("interarrival", 0.0)),
                )
                vectors.append(clump_to_reference_vector(clump_obj, normalize=True))
            else:
                vectors.append([
                    float(c.get("interarrival", 0.0)),
                    float(c.get("duration", 0.0)),
                    float(c.get("size", 0.0)),
                    float(c.get("pkt_count", 1.0)),
                    float(c.get("direction", 0.0)),
                ])
        else:
            vectors.append(list(pad_vec))

    # Post-padding to exact window_size
    n_vecs = len(vectors)
    if n_vecs < window_size:
        pad_needed = window_size - n_vecs
        for _ in range(pad_needed):
            vectors.append(list(pad_vec))
    elif n_vecs > window_size:
        vectors = vectors[:window_size]

    x_tensor = torch.tensor(vectors, dtype=torch.float32, device=dev).unsqueeze(0)

    mask_tensor = None
    if is_bigru:
        # Step-level boolean mask: True for valid clump, False for padding
        mask_list = [v != pad_vec for v in vectors]
        if not any(mask_list):
            mask_list = [True] * len(mask_list)
        mask_tensor = torch.tensor([mask_list], dtype=torch.bool, device=dev)

    sync_cuda_device(dev)
    t1 = time.perf_counter_ns()

    elapsed_s = max(0.0, (t1 - t0) / 1e9)
    return x_tensor, mask_tensor, elapsed_s


@dataclass
class OperationalLatencyBenchmarkResult:
    """Benchmark result for a single model/window/split configuration."""

    task: str
    model: str
    window_size: int
    split_protocol: str
    device: str
    sample_count: int
    batch_size: int = 1
    warmup_iterations: int = 10
    device_name: str = ""
    traffic_collection_delay: Dict[str, Any] = field(default_factory=dict)
    preprocessing_latency: Dict[str, Any] = field(default_factory=dict)
    inference_latency: Dict[str, Any] = field(default_factory=dict)
    end_to_end_latency: Dict[str, Any] = field(default_factory=dict)
    claim_boundary: str = PHASE_A_LATENCY_CLAIM_BOUNDARY

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to serializable dictionary."""
        return asdict(self)

    def to_csv_row(self) -> Dict[str, Any]:
        """Convert result to flat row format matching LATENCY_CSV_FIELDNAMES."""
        col = self.traffic_collection_delay
        prep = self.preprocessing_latency
        inf = self.inference_latency
        e2e = self.end_to_end_latency

        return {
            "task": self.task,
            "model": self.model,
            "window_size": int(self.window_size),
            "split_protocol": self.split_protocol,
            "device": self.device,
            "device_name": self.device_name,
            "sample_count": int(self.sample_count),
            "batch_size": int(self.batch_size),
            "warmup_iterations": int(self.warmup_iterations),
            # Collection Delay (seconds)
            "collection_mean_seconds": float(col.get("mean_seconds", 0.0)),
            "collection_median_seconds": float(col.get("median_seconds", 0.0)),
            "collection_p50_seconds": float(col.get("p50_seconds", 0.0)),
            "collection_p95_seconds": float(col.get("p95_seconds", 0.0)),
            "collection_p99_seconds": float(col.get("p99_seconds", 0.0)),
            "collection_min_seconds": float(col.get("min_seconds", 0.0)),
            "collection_max_seconds": float(col.get("max_seconds", 0.0)),
            "collection_std_seconds": float(col.get("std_seconds", 0.0)),
            # Preprocessing Latency (ms)
            "prep_mean_ms": float(prep.get("mean_ms", 0.0)),
            "prep_median_ms": float(prep.get("median_ms", 0.0)),
            "prep_p50_ms": float(prep.get("p50_ms", 0.0)),
            "prep_p95_ms": float(prep.get("p95_ms", 0.0)),
            "prep_p99_ms": float(prep.get("p99_ms", 0.0)),
            "prep_min_ms": float(prep.get("min_ms", 0.0)),
            "prep_max_ms": float(prep.get("max_ms", 0.0)),
            "prep_std_ms": float(prep.get("std_ms", 0.0)),
            # Inference Latency (ms)
            "infer_mean_ms": float(inf.get("mean_ms", 0.0)),
            "infer_median_ms": float(inf.get("median_ms", 0.0)),
            "infer_p50_ms": float(inf.get("p50_ms", 0.0)),
            "infer_p95_ms": float(inf.get("p95_ms", 0.0)),
            "infer_p99_ms": float(inf.get("p99_ms", 0.0)),
            "infer_min_ms": float(inf.get("min_ms", 0.0)),
            "infer_max_ms": float(inf.get("max_ms", 0.0)),
            "infer_std_ms": float(inf.get("std_ms", 0.0)),
            "infer_throughput_samples_per_second": float(inf.get("throughput_samples_per_second", 0.0)),
            # End-to-End Latency (seconds)
            "e2e_mean_seconds": float(e2e.get("mean_seconds", 0.0)),
            "e2e_median_seconds": float(e2e.get("median_seconds", 0.0)),
            "e2e_p50_seconds": float(e2e.get("p50_seconds", 0.0)),
            "e2e_p95_seconds": float(e2e.get("p95_seconds", 0.0)),
            "e2e_p99_seconds": float(e2e.get("p99_seconds", 0.0)),
            "e2e_min_seconds": float(e2e.get("min_seconds", 0.0)),
            "e2e_max_seconds": float(e2e.get("max_seconds", 0.0)),
            "e2e_std_seconds": float(e2e.get("std_seconds", 0.0)),
            "claim_boundary": self.claim_boundary,
        }


def benchmark_operational_latency(
    model: Any,
    test_samples: Sequence[SequenceSample],
    flows: Optional[Union[Sequence[Any], Mapping[str, Any]]] = None,
    task: str = "l1",
    model_name: str = "paper_v4",
    window_size: int = 6,
    split_protocol: str = "session_scenario_disjoint",
    device: Union[str, Any] = "cpu",
    warmup_iterations: int = 10,
    max_samples: Optional[int] = 500,
) -> OperationalLatencyBenchmarkResult:
    """Benchmark operational latency on first-window-per-test-flow samples.

    Contract requirements satisfied:
    - Selects one first-window sample per test flow deterministically.
    - Caps sample count via max_samples (from config).
    - Reconstructs exact sequence preprocessing from raw clumps.
    - Measures batch size 1 trained model forward pass.
    - Runs warm-up iterations before timing.
    - Synchronizes CUDA timing when device is CUDA.
    - Computes p50/p95/p99/mean/throughput.
    - Collection delay = sum(clump.interarrival + clump.duration) through the window.
    - End-to-end adds aligned per-sample components.
    """
    if not TORCH_AVAILABLE or torch is None:
        raise RuntimeError("PyTorch is required for operational latency benchmarking.")

    dev = torch.device(device)
    model.eval()
    model.to(dev)

    is_bigru = (
        model_name == "improved_bidi_gru"
        or getattr(model, "model_type", "") == "improved_masked_bigru"
    )

    # 1. Warm-up passes (batch size 1)
    if warmup_iterations > 0:
        dummy_x = torch.zeros((1, window_size, 5), dtype=torch.float32, device=dev)
        dummy_mask = torch.ones((1, window_size), dtype=torch.bool, device=dev) if is_bigru else None
        with torch.no_grad():
            for _ in range(warmup_iterations):
                if is_bigru:
                    _ = model(dummy_x, mask=dummy_mask, return_probs=False)
                else:
                    _ = model(dummy_x, return_probs=False)
        sync_cuda_device(dev)

    # 2. Select one first-window sample per test flow deterministically
    test_flow_first_samples: Dict[str, SequenceSample] = {}
    for s in test_samples:
        fid = s.metadata.flow_id
        if fid not in test_flow_first_samples or s.metadata.window_index < test_flow_first_samples[fid].metadata.window_index:
            test_flow_first_samples[fid] = s

    # Sort flow IDs alphabetically for strict determinism
    sorted_flow_ids = sorted(test_flow_first_samples.keys())
    if max_samples is not None and max_samples > 0:
        selected_flow_ids = sorted_flow_ids[:max_samples]
    else:
        selected_flow_ids = sorted_flow_ids

    # 3. Index flows for clump lookup
    flows_by_id: Dict[str, Any] = {}
    if flows is not None:
        if isinstance(flows, Mapping):
            flows_by_id = dict(flows)
        else:
            for f in flows:
                fid = getattr(f, "flow_id", None)
                if fid is not None:
                    flows_by_id[fid] = f

    # Determine device name
    if torch.cuda.is_available() and "cuda" in str(dev).lower():
        try:
            device_name = torch.cuda.get_device_name(dev)
        except Exception:
            device_name = "CUDA Device"
    else:
        device_name = platform.processor() or "CPU"

    collection_times: List[float] = []
    preprocessing_times: List[float] = []
    inference_times: List[float] = []
    end_to_end_times: List[float] = []

    # 4. Profile each test flow sample
    for fid in selected_flow_ids:
        sample = test_flow_first_samples[fid]
        flow = flows_by_id.get(fid)

        if flow is not None and hasattr(flow, "clumps"):
            clumps = list(flow.clumps)
        else:
            clumps = []

        # Component 1: Traffic collection delay (seconds)
        t_collect = compute_window_collection_delay(clumps, window_size)

        # Component 2: Sequence preprocessing latency (seconds)
        if clumps:
            x_tensor, mask_tensor, t_prep = preprocess_window_sample(
                clumps=clumps,
                window_size=window_size,
                device=dev,
                is_bigru=is_bigru,
            )
        else:
            # Fallback timing using existing sample features
            sync_cuda_device(dev)
            t0_p = time.perf_counter_ns()
            x_tensor = torch.tensor(sample.to_list(), dtype=torch.float32, device=dev).unsqueeze(0)
            mask_tensor = (
                torch.tensor([sample.get_mask()], dtype=torch.bool, device=dev)
                if is_bigru
                else None
            )
            sync_cuda_device(dev)
            t_prep = max(0.0, (time.perf_counter_ns() - t0_p) / 1e9)

        # Component 3: Model inference latency (seconds, batch size 1)
        sync_cuda_device(dev)
        t0_i = time.perf_counter_ns()
        with torch.no_grad():
            if is_bigru:
                _ = model(x_tensor, mask=mask_tensor, return_probs=False)
            else:
                _ = model(x_tensor, return_probs=False)
        sync_cuda_device(dev)
        t_infer = max(0.0, (time.perf_counter_ns() - t0_i) / 1e9)

        # Component 4: End-to-end latency (seconds, aligned per sample)
        t_e2e = t_collect + t_prep + t_infer

        collection_times.append(t_collect)
        preprocessing_times.append(t_prep)
        inference_times.append(t_infer)
        end_to_end_times.append(t_e2e)

    # 5. Compute summary distributions
    col_summary = compute_distribution_summary(collection_times)
    prep_summary = compute_distribution_summary(preprocessing_times)
    infer_summary = compute_distribution_summary(inference_times)
    e2e_summary = compute_distribution_summary(end_to_end_times)

    # Calculate throughput (samples / second)
    total_infer_time_s = sum(inference_times)
    if total_infer_time_s > 0.0 and len(inference_times) > 0:
        throughput = round(len(inference_times) / total_infer_time_s, 2)
    else:
        throughput = 0.0
    infer_summary["throughput_samples_per_second"] = throughput

    return OperationalLatencyBenchmarkResult(
        task=task,
        model=model_name,
        window_size=int(window_size),
        split_protocol=split_protocol,
        device=str(dev),
        sample_count=len(selected_flow_ids),
        batch_size=1,
        warmup_iterations=warmup_iterations,
        device_name=device_name,
        traffic_collection_delay=col_summary,
        preprocessing_latency=prep_summary,
        inference_latency=infer_summary,
        end_to_end_latency=e2e_summary,
        claim_boundary=PHASE_A_LATENCY_CLAIM_BOUNDARY,
    )


def emit_latency_benchmark_artifacts(
    output_dir: Path,
    results: Sequence[OperationalLatencyBenchmarkResult],
    claim_boundary: Optional[str] = None,
) -> Tuple[Path, Path]:
    """Emit dedicated latency_benchmarks.json and latency_benchmarks.csv artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latency_benchmarks.json"
    csv_path = output_dir / "latency_benchmarks.csv"

    # 1. JSON Artifact
    payload: Dict[str, Any] = {
        "manifest_version": "1.0.0",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "claim_boundary": claim_boundary or PHASE_A_LATENCY_CLAIM_BOUNDARY,
        "total_benchmarks": len(results),
        "benchmarks": [
            r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in results
        ],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    # 2. CSV Artifact
    csv_rows = [
        r.to_csv_row() if hasattr(r, "to_csv_row") else dict(r) for r in results
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(LATENCY_CSV_FIELDNAMES))
        writer.writeheader()
        for row in csv_rows:
            writer.writerow({k: row.get(k, "") for k in LATENCY_CSV_FIELDNAMES})

    logger.info("Emitted latency benchmark artifacts: %s and %s", json_path, csv_path)
    return json_path, csv_path
