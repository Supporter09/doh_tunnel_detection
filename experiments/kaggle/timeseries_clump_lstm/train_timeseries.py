#!/usr/bin/env python3
"""Audit-first standalone Kaggle runner for CIRA-CIC-DoHBrw-2020 raw-PCAP packet-clump sequence classification.

Scope:
    Replicates and evaluates packet-clump time-series sequence models (Paper v4 LSTM and
    Improved Masked BiGRU) on raw PCAP network captures from CIRA-CIC-DoHBrw-2020.
    Enforces a strict scientific distinction between:
      1. Paper-text reconstruction (MontazeriShatoori et al. 2020: 1ms clumping, flow-random 80/20 split
         with prominent data leakage caveat).
      2. DoHLyzer reference-code facts (v4.py architecture, reference feature order, normalization).
      3. Project improvements (Session/scenario-disjoint 70/15/15 grouping, mask-aware BiGRU with attention
         pooling, class-weighted BCE, validation-only Platt calibration and threshold selection under target FPR).

Artifacts emitted to --output-dir:
    - pcap_audit.json
    - metrics.json
    - experiment_manifest.json
    - training_history.csv
    - confusion_matrix_<task>_<model>_w<window>_<split>.csv

Security & Boundaries:
    - Never emits binary model weights (.pt, .pth, .pkl, .h5, .joblib) or raw PCAP files.
    - Operates strictly in passive defensive mode; never launches live tunnels or replays traffic.
    - Streams nested ZIP archives member-by-member without full extraction to disk or loading full PCAPs into RAM.
    - Enforces bounded memory and execution via max_capture_members, max_flows_per_class, and max_cache_bytes.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import logging
import os
import platform
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

# ---------------------------------------------------------------------------
# Path setup: ensure doh_reproduction package is discoverable
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent  # doh_tunnel_detection root
_SRC_DIR = _PROJECT_ROOT / "src"

for _candidate in [_SCRIPT_DIR, _SRC_DIR, _PROJECT_ROOT]:
    _cand_str = str(_candidate)
    if _cand_str not in sys.path and _candidate.exists():
        sys.path.insert(0, _cand_str)

# ---------------------------------------------------------------------------
# Provenance Constants (Injected by Kaggle Push Wrappers or Environment)
# ---------------------------------------------------------------------------
EMBEDDED_CONFIG_JSON: Optional[str | Dict[str, Any]] = None
KAGGLE_GIT_SHA: str = os.environ.get("KAGGLE_GIT_SHA", "unknown")
KAGGLE_SOURCE_SNAPSHOT_SHA256: str = os.environ.get("KAGGLE_SOURCE_SNAPSHOT_SHA256", "unknown")

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("kaggle_timeseries_runner")

# ---------------------------------------------------------------------------
# Optional & Dynamic Imports with Version Discovery
# ---------------------------------------------------------------------------
try:
    import numpy as np
    NUMPY_VERSION: str = getattr(np, "__version__", "unknown")
except ImportError:
    np = None  # type: ignore[assignment]
    NUMPY_VERSION = "not_installed"

try:
    import scipy
    SCIPY_VERSION: str = getattr(scipy, "__version__", "unknown")
except ImportError:
    scipy = None  # type: ignore[assignment]
    SCIPY_VERSION = "not_installed"

try:
    import sklearn
    SKLEARN_VERSION: str = getattr(sklearn, "__version__", "unknown")
except ImportError:
    sklearn = None  # type: ignore[assignment]
    SKLEARN_VERSION = "not_installed"

try:
    import dpkt
    DPKT_VERSION: str = getattr(dpkt, "__version__", "unknown")
except ImportError:
    dpkt = None  # type: ignore[assignment]
    DPKT_VERSION = "not_installed"

try:
    import torch
    TORCH_VERSION: str = getattr(torch, "__version__", "unknown")
    TORCH_CUDA_AVAILABLE: bool = torch.cuda.is_available()
except ImportError:
    torch = None  # type: ignore[assignment]
    TORCH_VERSION = "not_installed"
    TORCH_CUDA_AVAILABLE = False

# Import staged doh_reproduction modules lazily / with safe fallbacks
try:
    from doh_reproduction.clumping import Clump, Packet, clumping, segment_clumps
except ImportError:
    Clump = None  # type: ignore[assignment,misc]
    Packet = None  # type: ignore[assignment,misc]
    clumping = None  # type: ignore[assignment]
    segment_clumps = None  # type: ignore[assignment]

try:
    from doh_reproduction.pcap import FlowKey, FlowRecord, iter_pcap_flows
except ImportError:
    FlowKey = None  # type: ignore[assignment,misc]
    FlowRecord = None  # type: ignore[assignment,misc]
    iter_pcap_flows = None  # type: ignore[assignment]

try:
    from doh_reproduction.raw_dataset import (
        CaptureSource,
        audit_capture_sources,
        derive_capture_metadata,
        discover_capture_sources,
        labels_for_flow,
    )
except ImportError:
    CaptureSource = None  # type: ignore[assignment,misc]
    audit_capture_sources = None  # type: ignore[assignment]
    derive_capture_metadata = None  # type: ignore[assignment]
    discover_capture_sources = None  # type: ignore[assignment]
    labels_for_flow = None  # type: ignore[assignment]

try:
    from doh_reproduction.timeseries_data import (
        LAYER1_LABEL_DOH,
        LAYER1_LABEL_NON_DOH,
        LAYER1_WINDOW_SIZE,
        LAYER2_LABEL_BENIGN,
        LAYER2_LABEL_MALICIOUS,
        LAYER2_WINDOW_SIZE,
        PADDING_VECTOR,
        PAPER_REFERENCE_FEATURE_ORDER,
        ImpossibleSplitError,
        SequenceMetadata,
        SequenceSample,
        SplitLeakageReport,
        SplitManifest,
        SplitResult,
        build_split_manifest,
        clumps_to_reference_vectors,
        compute_class_weights,
        compute_pos_weight,
        create_segments,
        create_sequence_samples,
        samples_to_arrays,
        split_samples,
    )
except ImportError:
    PADDING_VECTOR = [-1.0, -1.0, -1.0, -1.0, 0.0]  # type: ignore[assignment]
    PAPER_REFERENCE_FEATURE_ORDER = ("interarrival", "duration", "size", "packet_count", "direction")  # type: ignore[assignment]
    LAYER1_WINDOW_SIZE = 6
    LAYER2_WINDOW_SIZE = 3
    LAYER1_LABEL_NON_DOH = 0
    LAYER1_LABEL_DOH = 1
    LAYER2_LABEL_BENIGN = 0
    LAYER2_LABEL_MALICIOUS = 1
    SequenceMetadata = None  # type: ignore[assignment,misc]
    SequenceSample = None  # type: ignore[assignment,misc]
    SplitResult = None  # type: ignore[assignment,misc]
    SplitManifest = None  # type: ignore[assignment,misc]
    SplitLeakageReport = None  # type: ignore[assignment,misc]
    ImpossibleSplitError = ValueError  # type: ignore[assignment,misc]
    clumps_to_reference_vectors = None  # type: ignore[assignment]
    create_segments = None  # type: ignore[assignment]
    create_sequence_samples = None  # type: ignore[assignment]
    split_samples = None  # type: ignore[assignment]
    build_split_manifest = None  # type: ignore[assignment]
    compute_class_weights = None  # type: ignore[assignment]
    compute_pos_weight = None  # type: ignore[assignment]
    samples_to_arrays = None  # type: ignore[assignment]

try:
    from doh_reproduction.timeseries_models import (
        binary_metrics,
        configure_bce_loss,
        confusion_matrix_counts,
        create_improved_model,
        create_paper_model,
        fit_model,
        platt_calibrate,
        predict_probabilities,
        select_threshold_at_fpr,
        set_deterministic_seed,
    )
except ImportError:
    create_paper_model = None  # type: ignore[assignment]
    create_improved_model = None  # type: ignore[assignment]
    set_deterministic_seed = None  # type: ignore[assignment]
    configure_bce_loss = None  # type: ignore[assignment]
    fit_model = None  # type: ignore[assignment]
    predict_probabilities = None  # type: ignore[assignment]
    platt_calibrate = None  # type: ignore[assignment]
    select_threshold_at_fpr = None  # type: ignore[assignment]
    confusion_matrix_counts = None  # type: ignore[assignment]
    binary_metrics = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Pure Configuration Validation Helpers
# ---------------------------------------------------------------------------
VALID_MODES: Set[str] = {"audit", "train"}
VALID_TASKS: Set[str] = {"l1", "l2", "both"}
VALID_SPLIT_PROTOCOLS: Set[str] = {
    "paper_flow_random",
    "session_scenario_disjoint",
    "both",
}
VALID_MODELS: Set[str] = {"paper_v4", "improved_bidi_gru", "all"}

RESOURCE_CAP_KEYS: Tuple[str, ...] = (
    "max_capture_members",
    "max_flows_per_class",
    "max_flows_per_capture",
    "max_raw_packets",
    "max_raw_bytes",
    "max_capture_packets",
    "max_capture_bytes",
    "max_flow_packets",
    "max_flow_bytes",
    "max_windows_per_flow",
    "max_windows_per_class",
    "max_standalone_capture_bytes",
    "max_member_bytes",
    "max_nested_archive_bytes",
    "max_total_uncompressed_bytes",
    "max_compression_ratio",
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "audit",
    "dataset_dir": "/kaggle/input/cicdohbrw2020-raw-pcaps",
    "dataset_slug": "nhtminhmai/cicdohbrw2020-raw-pcaps",
    "dataset_version": "1",
    "task": "both",
    "split_protocol": "session_scenario_disjoint",
    "window_sizes": [3, 6],
    "models": ["paper_v4", "improved_bidi_gru"],
    "seed": 42,
    "max_capture_members": 20_000,
    "max_flows_per_class": 500,
    "max_flows_per_capture": 25,
    "max_raw_packets": 1_000_000,
    "max_raw_bytes": 1_073_741_824,                      # 1 GB raw packet bytes per capture
    "max_capture_packets": 200_000,
    "max_capture_bytes": 536_870_912,                     # 512 MB accepted TLS bytes per capture
    "max_flow_packets": 10_000,
    "max_flow_bytes": 52_428_800,                         # 50 MB accepted TLS bytes per flow
    "max_windows_per_flow": 1_000,
    "max_windows_per_class": 10_000,
    "max_standalone_capture_bytes": 21_474_836_480,       # 20 GB
    "max_member_bytes": 10_737_418_240,                   # 10 GB
    "max_nested_archive_bytes": 26_843_545_600,           # 25 GB
    "max_total_uncompressed_bytes": 214_748_364_800,      # 200 GB
    "max_compression_ratio": 100.0,
    "target_false_positive_rate": 0.001,
    "epochs": 15,
    "batch_size": 64,
    "learning_rate": 0.001,
    "patience": 5,
    "enable_score_calibration": True,
    "description": "Safe default audit configuration for raw-PCAP packet-clump sequence classification.",
}


def validate_run_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Pure helper that strictly validates and normalizes the experiment configuration dictionary.

    Raises:
        ValueError: If any key contains an invalid type, out-of-range value, or unsupported option.
    """
    if not isinstance(config, dict):
        raise ValueError(f"Configuration must be a dictionary, got {type(config).__name__}")

    cfg: Dict[str, Any] = copy.deepcopy(config)

    # 1. Mode validation
    raw_mode = cfg.get("mode", DEFAULT_CONFIG["mode"])
    if not isinstance(raw_mode, str) or raw_mode.strip().lower() not in VALID_MODES:
        raise ValueError(
            f"Invalid 'mode': {raw_mode!r}. Must be one of {sorted(VALID_MODES)}"
        )
    cfg["mode"] = raw_mode.strip().lower()

    # 2. Dataset dir
    dataset_dir = cfg.get("dataset_dir", DEFAULT_CONFIG["dataset_dir"])
    if not isinstance(dataset_dir, (str, Path)) or not str(dataset_dir).strip():
        raise ValueError(f"Invalid 'dataset_dir': {dataset_dir!r}. Must be a non-empty string or Path.")
    cfg["dataset_dir"] = str(dataset_dir).strip()

    # 3. Dataset slug and version
    dataset_slug = cfg.get("dataset_slug", DEFAULT_CONFIG["dataset_slug"])
    if not isinstance(dataset_slug, str) or not dataset_slug.strip():
        raise ValueError(f"Invalid 'dataset_slug': {dataset_slug!r}. Must be a non-empty string.")
    cfg["dataset_slug"] = dataset_slug.strip()

    dataset_version = cfg.get("dataset_version", DEFAULT_CONFIG["dataset_version"])
    cfg["dataset_version"] = str(dataset_version).strip() if dataset_version is not None else "1"

    # 4. Task validation
    task = cfg.get("task", DEFAULT_CONFIG["task"])
    if not isinstance(task, str) or task.strip().lower() not in VALID_TASKS:
        raise ValueError(f"Invalid 'task': {task!r}. Must be one of {sorted(VALID_TASKS)}")
    cfg["task"] = task.strip().lower()

    # 5. Split protocol validation
    split_protocol = cfg.get("split_protocol", DEFAULT_CONFIG["split_protocol"])
    if not isinstance(split_protocol, str) or split_protocol.strip().lower() not in VALID_SPLIT_PROTOCOLS:
        raise ValueError(
            f"Invalid 'split_protocol': {split_protocol!r}. Must be one of {sorted(VALID_SPLIT_PROTOCOLS)}"
        )
    cfg["split_protocol"] = split_protocol.strip().lower()

    # 6. Window sizes validation
    window_sizes = cfg.get("window_sizes", DEFAULT_CONFIG["window_sizes"])
    if isinstance(window_sizes, int):
        window_sizes = [window_sizes]
    if not isinstance(window_sizes, (list, tuple)) or len(window_sizes) == 0:
        raise ValueError(f"Invalid 'window_sizes': {window_sizes!r}. Must be a non-empty sequence of positive integers.")
    normalized_windows: List[int] = []
    for w in window_sizes:
        if not isinstance(w, int) or w <= 0:
            raise ValueError(f"Window size {w!r} is invalid. Each window size must be an integer >= 1.")
        normalized_windows.append(w)
    cfg["window_sizes"] = sorted(list(set(normalized_windows)))

    # 7. Models validation
    models = cfg.get("models", DEFAULT_CONFIG["models"])
    if isinstance(models, str):
        if models.strip().lower() == "all":
            models = ["paper_v4", "improved_bidi_gru"]
        else:
            models = [models.strip().lower()]
    if not isinstance(models, (list, tuple)) or len(models) == 0:
        raise ValueError(f"Invalid 'models': {models!r}. Must be a non-empty list of model identifiers.")
    normalized_models: List[str] = []
    for m in models:
        m_str = str(m).strip().lower()
        if m_str == "all":
            for exp_m in ["paper_v4", "improved_bidi_gru"]:
                if exp_m not in normalized_models:
                    normalized_models.append(exp_m)
        elif m_str in {"paper_v4", "improved_bidi_gru"}:
            if m_str not in normalized_models:
                normalized_models.append(m_str)
        else:
            raise ValueError(
                f"Unknown model identifier: {m!r}. Supported models: ['paper_v4', 'improved_bidi_gru', 'all']"
            )
    cfg["models"] = normalized_models

    # 8. Seed validation
    seed = cfg.get("seed", DEFAULT_CONFIG["seed"])
    if not isinstance(seed, int) or seed < 0:
        raise ValueError(f"Invalid 'seed': {seed!r}. Must be a non-negative integer.")
    cfg["seed"] = seed

    # 9. Bounded capture members
    max_capture_members = cfg.get("max_capture_members", DEFAULT_CONFIG["max_capture_members"])
    if max_capture_members is not None:
        if not isinstance(max_capture_members, int) or max_capture_members <= 0:
            raise ValueError(
                f"Invalid 'max_capture_members': {max_capture_members!r}. Must be None or an integer >= 1."
            )
    cfg["max_capture_members"] = max_capture_members

    # 10. Bounded flows per class
    max_flows_per_class = cfg.get("max_flows_per_class", DEFAULT_CONFIG["max_flows_per_class"])
    if max_flows_per_class is not None:
        if not isinstance(max_flows_per_class, int) or max_flows_per_class <= 0:
            raise ValueError(
                f"Invalid 'max_flows_per_class': {max_flows_per_class!r}. Must be None or an integer >= 1."
            )
    cfg["max_flows_per_class"] = max_flows_per_class

    # 11. Resource Bounds (Centralized validation for all cap keys)
    for cap_key in RESOURCE_CAP_KEYS:
        if cap_key == "max_compression_ratio":
            comp_ratio = cfg.get(cap_key, DEFAULT_CONFIG[cap_key])
            if comp_ratio is not None:
                if not isinstance(comp_ratio, (int, float)) or float(comp_ratio) < 1.0:
                    raise ValueError(f"Invalid '{cap_key}': {comp_ratio!r}. Must be None or a float >= 1.0.")
                cfg[cap_key] = float(comp_ratio)
            else:
                cfg[cap_key] = None
        else:
            val = cfg.get(cap_key, DEFAULT_CONFIG[cap_key])
            if val is not None:
                if not isinstance(val, int) or val < 1:
                    raise ValueError(f"Invalid '{cap_key}': {val!r}. Must be None or an integer >= 1.")
            cfg[cap_key] = val

    # Clean legacy cache keys if provided in older configs
    cfg.pop("cache_dir", None)
    cfg.pop("max_cache_bytes", None)
    # 12. Target FPR
    target_fpr = cfg.get("target_false_positive_rate", DEFAULT_CONFIG["target_false_positive_rate"])
    if not isinstance(target_fpr, (int, float)) or not (0.0 < float(target_fpr) < 1.0):
        raise ValueError(
            f"Invalid 'target_false_positive_rate': {target_fpr!r}. Must be a float strictly between 0 and 1."
        )
    cfg["target_false_positive_rate"] = float(target_fpr)

    # 13. Training hyper-parameters
    epochs = cfg.get("epochs", DEFAULT_CONFIG["epochs"])
    if not isinstance(epochs, int) or epochs <= 0:
        raise ValueError(f"Invalid 'epochs': {epochs!r}. Must be an integer >= 1.")
    cfg["epochs"] = epochs

    batch_size = cfg.get("batch_size", DEFAULT_CONFIG["batch_size"])
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError(f"Invalid 'batch_size': {batch_size!r}. Must be an integer >= 1.")
    cfg["batch_size"] = batch_size

    lr = cfg.get("learning_rate", DEFAULT_CONFIG["learning_rate"])
    if not isinstance(lr, (int, float)) or float(lr) <= 0.0:
        raise ValueError(f"Invalid 'learning_rate': {lr!r}. Must be a positive float.")
    cfg["learning_rate"] = float(lr)

    patience = cfg.get("patience", DEFAULT_CONFIG["patience"])
    if not isinstance(patience, int) or patience <= 0:
        raise ValueError(f"Invalid 'patience': {patience!r}. Must be an integer >= 1.")
    cfg["patience"] = patience

    cfg["enable_score_calibration"] = bool(cfg.get("enable_score_calibration", True))
    cfg["description"] = str(cfg.get("description", DEFAULT_CONFIG["description"]))

    return cfg


def resolve_config(config_file_arg: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Resolves experiment configuration following a strict precedence hierarchy:
    1. EMBEDDED_CONFIG_JSON constant (injected by push wrapper into script)
    2. Explicit CLI config file (--config path)
    3. run_config.json located in the same directory as this script
    4. Safe DEFAULT_CONFIG
    """
    global EMBEDDED_CONFIG_JSON

    # 1. Embedded configuration check
    if EMBEDDED_CONFIG_JSON is not None:
        logger.info("Found EMBEDDED_CONFIG_JSON constant in script.")
        if isinstance(EMBEDDED_CONFIG_JSON, str):
            parsed = json.loads(EMBEDDED_CONFIG_JSON)
        elif isinstance(EMBEDDED_CONFIG_JSON, dict):
            parsed = EMBEDDED_CONFIG_JSON
        else:
            raise ValueError(f"EMBEDDED_CONFIG_JSON has unsupported type: {type(EMBEDDED_CONFIG_JSON)}")
        validated = validate_run_config(parsed)
        return validated, "embedded"

    # 2. CLI config file check
    if config_file_arg:
        p = Path(config_file_arg)
        if not p.is_file():
            raise FileNotFoundError(f"Specified configuration file does not exist: {p}")
        logger.info("Loading configuration from CLI path: %s", p)
        with open(p, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        validated = validate_run_config(parsed)
        return validated, f"cli_file:{p.name}"

    # 3. Local run_config.json next to script
    local_cfg_path = _SCRIPT_DIR / "run_config.json"
    if local_cfg_path.is_file():
        logger.info("Loading configuration from adjacent run_config.json: %s", local_cfg_path)
        with open(local_cfg_path, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        validated = validate_run_config(parsed)
        return validated, "local_file:run_config.json"

    # 4. Safe default configuration fallback
    logger.info("No external configuration provided. Falling back to safe DEFAULT_CONFIG in 'audit' mode.")
    validated = validate_run_config(DEFAULT_CONFIG)
    return validated, "defaults"


# ---------------------------------------------------------------------------
# Lightweight Standalone Discovery & Audit Fallbacks
# ---------------------------------------------------------------------------
def compute_sha256_stream(stream: Any, block_size: int = 1048576) -> str:
    """Computes SHA-256 hash incrementally over a stream."""
    hasher = hashlib.sha256()
    while True:
        chunk = stream.read(block_size)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()


def compute_file_sha256(path: Path) -> str:
    """Computes SHA-256 hash of a local file."""
    with open(path, "rb") as f:
        return compute_sha256_stream(f)


def fallback_derive_capture_metadata(filename: str, parent_path: str = "") -> Dict[str, Any]:
    """Pure fallback rule to infer scenario, session, and maliciousness from filename/path."""
    fn_lower = filename.lower()
    parent_lower = parent_path.lower()
    combined = f"{parent_lower}/{fn_lower}"

    # 1. Determine maliciousness and scenario
    if any(m in combined for m in ["dns2tcp", "dnscat2", "iodine", "malicious"]):
        category = "malicious_doh"
        is_malicious = True
        if "dns2tcp" in combined:
            scenario_id = "malicious_doh_dns2tcp"
        elif "dnscat2" in combined:
            scenario_id = "malicious_doh_dnscat2"
        else:
            scenario_id = "malicious_doh_iodine"
    # 2. Check NonDoH patterns BEFORE generic browser names
    elif any(nd in combined for nd in ["nondoh", "non_doh", "non-doh", "non doh"]) or "ndoh" in combined:
        category = "non_doh"
        is_malicious = False
        if "firefox" in combined:
            scenario_id = "non_doh_firefox"
        elif "chrome" in combined:
            scenario_id = "non_doh_chrome"
        elif "video" in combined:
            scenario_id = "non_doh_video"
        elif "download" in combined:
            scenario_id = "non_doh_download"
        else:
            scenario_id = "non_doh_browsing"
    # 3. Check Benign DoH
    elif "benign" in combined or "doh" in combined:
        category = "benign_doh"
        is_malicious = False
        if "firefox" in combined:
            scenario_id = "benign_doh_firefox"
        elif "chrome" in combined:
            scenario_id = "benign_doh_chrome"
        else:
            scenario_id = "benign_doh_general"
    else:
        category = "non_doh"
        is_malicious = False
        scenario_id = "non_doh_browsing"

    # Extract session identifier from filename
    session_id = Path(filename).stem
    return {
        "scenario_id": scenario_id,
        "session_id": session_id,
        "category": category,
        "is_malicious": is_malicious,
    }


def perform_pcap_audit(
    dataset_dir: Path,
    max_members: Optional[int] = None,
    max_standalone_capture_bytes: int = 21474836480,
    max_member_bytes: int = 10737418240,
    max_nested_archive_bytes: int = 26843545600,
    max_total_uncompressed_bytes: int = 214748364800,
    max_compression_ratio: float = 100.0,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Discovers all capture sources using hardened raw_dataset and produces structured audit records.
    Fails closed if hardened discovery is unavailable or if discovery checks fail.
    """
    logger.info("Scanning dataset directory for PCAP captures and archives: %s", dataset_dir)
    if discover_capture_sources is None or audit_capture_sources is None:
        raise RuntimeError(
            "Hardened doh_reproduction.raw_dataset module must be available; fallback scanning is prohibited."
        )

    sources = discover_capture_sources(
        dataset_dir,
        max_capture_members=max_members,
        max_standalone_capture_bytes=max_standalone_capture_bytes,
        max_member_bytes=max_member_bytes,
        max_nested_archive_bytes=max_nested_archive_bytes,
        max_total_uncompressed_bytes=max_total_uncompressed_bytes,
        max_compression_ratio=max_compression_ratio,
    )
    audit_dict = audit_capture_sources(
        dataset_dir,
        max_sources=max_members,
        max_standalone_capture_bytes=max_standalone_capture_bytes,
        max_member_bytes=max_member_bytes,
        max_nested_archive_bytes=max_nested_archive_bytes,
        max_total_uncompressed_bytes=max_total_uncompressed_bytes,
        max_compression_ratio=max_compression_ratio,
        sources=sources,
    )
    cat_counts = audit_dict.get("category_counts", {})
    audit_dict.setdefault("summary_by_category", cat_counts)
    audit_dict.setdefault("category_counts", cat_counts)
    audit_dict.setdefault("total_capture_sources", len(sources))
    audit_dict.setdefault("total_sources", len(sources))
    audit_dict.setdefault("total_uncompressed_bytes", audit_dict.get("total_bytes", 0))
    audit_dict.setdefault("capture_sources", audit_dict.get("sources", []))
    audit_dict.setdefault("sources", audit_dict.get("capture_sources", []))
    return sources, audit_dict


# ---------------------------------------------------------------------------
# Capture Streaming Context Manager (Zero Disk Extraction)
# ---------------------------------------------------------------------------
class CaptureStreamOpener:
    """Safely opens a raw PCAP or nested ZIP member using hardened CaptureSource."""

    def __init__(self, capture: Any) -> None:
        self.capture = capture
        self._cm: Optional[Any] = None
        self.stream: Optional[Any] = None

    def __enter__(self) -> Any:
        if hasattr(self.capture, "open_stream") and callable(self.capture.open_stream):
            self._cm = self.capture.open_stream()
            self.stream = self._cm.__enter__()
            return self.stream
        raise TypeError(
            f"CaptureStreamOpener requires a hardened CaptureSource with open_stream(), "
            f"got {type(self.capture).__name__}"
        )

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._cm is not None:
            try:
                self._cm.__exit__(exc_type, exc_val, exc_tb)
            finally:
                self._cm = None
                self.stream = None
# ---------------------------------------------------------------------------
# Streaming Ingestion & Bounded Flow Records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BoundedFlowRecord:
    """Bounded in-memory representation of an ingested flow with its clumps and canonical labels."""

    flow_id: str
    session_id: str
    scenario_id: str
    source_id: str
    clumps: tuple[Any, ...]
    l1_label: int  # 0: non_doh, 1: doh
    l2_label: Optional[int] = None  # 0: benign_doh, 1: malicious_doh, None: non-doh
    start_time: float = 0.0
    end_time: float = 0.0
    truncated: bool = False

def stream_and_collect_flows(
    capture_sources: List[Any],
    max_flows_per_class: Optional[int] = 500,
    max_flows_per_capture: Optional[int] = 25,
    task: str = "both",
    max_raw_packets: Optional[int] = None,
    max_raw_bytes: Optional[int] = None,
    max_capture_packets: Optional[int] = None,
    max_capture_bytes: Optional[int] = None,
    max_flow_packets: Optional[int] = None,
    max_flow_bytes: Optional[int] = None,
    counters: Optional[Dict[str, Any]] = None,
) -> List[BoundedFlowRecord]:
    """Streams PCAP flows iteratively, applies 1ms clumping, determines canonical L1/L2 labels,
    and enforces quotas strictly by actual flow label (not capture category).
    """
    logger.info("Beginning streaming flow ingestion over %d capture sources...", len(capture_sources))
    if iter_pcap_flows is None:
        raise RuntimeError(
            "doh_reproduction.pcap.iter_pcap_flows is not available. Please verify module staging."
        )

    # Track retained flow counts strictly by actual flow classification label
    class_flow_counts: Dict[str, int] = {"non_doh": 0, "benign_doh": 0, "malicious_doh": 0}
    retained_flows: List[BoundedFlowRecord] = []
    total_flows_processed = 0
    flows_truncated_count = 0
    captures_truncated_count = 0
    total_raw_packets = 0
    total_raw_bytes = 0
    total_accepted_packets = 0
    total_accepted_bytes = 0
    any_raw_packets_capped = False
    any_raw_bytes_capped = False
    def quotas_satisfied() -> bool:
        if max_flows_per_class is None:
            return False
        if task == "l1":
            return (
                class_flow_counts.get("non_doh", 0) >= max_flows_per_class
                and (class_flow_counts.get("benign_doh", 0) + class_flow_counts.get("malicious_doh", 0)) >= max_flows_per_class
            )
        elif task == "l2":
            return (
                class_flow_counts.get("benign_doh", 0) >= max_flows_per_class
                and class_flow_counts.get("malicious_doh", 0) >= max_flows_per_class
            )
        else:  # "both"
            return (
                class_flow_counts.get("non_doh", 0) >= max_flows_per_class
                and class_flow_counts.get("benign_doh", 0) >= max_flows_per_class
                and class_flow_counts.get("malicious_doh", 0) >= max_flows_per_class
            )

    for idx, capture in enumerate(capture_sources):
        if quotas_satisfied():
            break

        if isinstance(capture, dict):
            source_id = capture.get("source_id") or capture.get("filename") or os.path.basename(capture.get("path", f"source_{idx}"))
            scenario_id = capture.get("scenario_id", "unknown")
            session_id = capture.get("session_id", f"sess_{idx}")
            capture_cat = capture.get("category", "non_doh")
        else:
            source_id = getattr(capture, "source_id", None) or getattr(capture, "filename", None) or os.path.basename(getattr(capture, "path", f"source_{idx}"))
            scenario_id = getattr(capture, "scenario_id", "unknown")
            session_id = getattr(capture, "session_id", f"sess_{idx}")
            capture_cat = getattr(capture, "category", "non_doh")

        retained_from_capture = 0
        pcap_stats: Dict[str, Any] = {}
        try:
            with CaptureStreamOpener(capture) as stream:
                for flow in iter_pcap_flows(
                    stream,
                    source_id=source_id,
                    session_id=session_id,
                    scenario_id=scenario_id,
                    max_raw_packets=max_raw_packets,
                    max_raw_bytes=max_raw_bytes,
                    max_capture_packets=max_capture_packets,
                    max_capture_bytes=max_capture_bytes,
                    max_flow_packets=max_flow_packets,
                    max_flow_bytes=max_flow_bytes,
                    stats=pcap_stats,
                ):
                    if (
                        max_flows_per_capture is not None
                        and retained_from_capture >= max_flows_per_capture
                    ):
                        break
                    total_flows_processed += 1
                    if getattr(flow, "truncated", False):
                        flows_truncated_count += 1

                    # Extract ground-truth labels using canonical raw_dataset.labels_for_flow
                    l1_label: int = 0
                    l2_label: Optional[int] = None

                    if labels_for_flow is not None:
                        lbl_dict = labels_for_flow(flow, capture)
                        l1_label = int(lbl_dict.get("l1_label", 0))
                        raw_l2 = lbl_dict.get("l2_label")
                        l2_label = int(raw_l2) if raw_l2 is not None else None
                    else:
                        is_doh = getattr(flow, "is_doh", False)
                        if not is_doh and capture_cat == "non_doh":
                            l1_label = 0
                            l2_label = None
                        elif capture_cat == "benign_doh":
                            l1_label = 1
                            l2_label = 0
                        elif capture_cat == "malicious_doh":
                            l1_label = 1
                            l2_label = 1
                        else:
                            l1_label = 1 if is_doh else 0
                            l2_label = None if l1_label == 0 else (1 if getattr(flow, "is_malicious", False) else 0)

                    # Determine actual flow class for quota enforcement
                    if l1_label == 0:
                        flow_class = "non_doh"
                    elif l2_label == 1:
                        flow_class = "malicious_doh"
                    elif l2_label == 0:
                        flow_class = "benign_doh"
                    else:
                        flow_class = "benign_doh"

                    # Enforce quotas strictly by actual flow label and configured task
                    if max_flows_per_class is not None:
                        if task == "l1":
                            if flow_class == "non_doh" and class_flow_counts.get("non_doh", 0) >= max_flows_per_class:
                                if quotas_satisfied():
                                    break
                                continue
                            elif flow_class in {"benign_doh", "malicious_doh"}:
                                current_doh = class_flow_counts.get("benign_doh", 0) + class_flow_counts.get("malicious_doh", 0)
                                if current_doh >= max_flows_per_class:
                                    if quotas_satisfied():
                                        break
                                    continue
                        elif task == "l2":
                            if flow_class == "non_doh":
                                continue
                            elif class_flow_counts.get(flow_class, 0) >= max_flows_per_class:
                                if quotas_satisfied():
                                    break
                                continue
                        else:  # "both"
                            if class_flow_counts.get(flow_class, 0) >= max_flows_per_class:
                                if quotas_satisfied():
                                    break
                                continue
                    # Extract clumps from flow
                    clumps = getattr(flow, "clumps", None)
                    if clumps is None and clumping is not None:
                        packets = getattr(flow, "packets", [])
                        if packets:
                            clumps = clumping(packets)
                    if not clumps or len(clumps) == 0:
                        continue

                    class_flow_counts[flow_class] = class_flow_counts.get(flow_class, 0) + 1

                    flow_id = getattr(flow, "flow_id", f"{source_id}_{total_flows_processed}")
                    start_time = getattr(flow, "start_time", 0.0)
                    end_time = getattr(flow, "end_time", 0.0)

                    record = BoundedFlowRecord(
                        flow_id=str(flow_id),
                        session_id=str(session_id),
                        scenario_id=str(scenario_id),
                        source_id=str(source_id),
                        clumps=tuple(clumps),
                        l1_label=l1_label,
                        l2_label=l2_label,
                        start_time=float(start_time),
                        end_time=float(end_time),
                        truncated=getattr(flow, "truncated", False),
                    )
                    retained_flows.append(record)
                    retained_from_capture += 1

                    if quotas_satisfied():
                        break

        except Exception as err:
            logger.warning("Failed streaming capture %s: %s", source_id, err)

        total_raw_packets += pcap_stats.get("raw_packets_read", 0)
        total_raw_bytes += pcap_stats.get("raw_bytes_read", 0)
        total_accepted_packets += pcap_stats.get("accepted_packets", 0)
        total_accepted_bytes += pcap_stats.get("accepted_bytes", 0)
        if pcap_stats.get("raw_packets_capped"):
            any_raw_packets_capped = True
        if pcap_stats.get("raw_bytes_capped"):
            any_raw_bytes_capped = True
        if pcap_stats.get("capture_truncated"):
            captures_truncated_count += 1

        if quotas_satisfied():
            logger.info("All flow class quotas reached (%d per class) for task %s. Stopping ingestion early.", max_flows_per_class, task)
            break

    logger.info(
        "Flow ingestion completed. Processed %d flows, retained %d bounded flows. Breakdown by actual flow label: %s",
        total_flows_processed,
        len(retained_flows),
        class_flow_counts,
    )
    if counters is not None:
        counters["total_flows_processed"] = total_flows_processed
        counters["flows_retained"] = len(retained_flows)
        counters["class_flow_counts"] = dict(class_flow_counts)
        counters["max_flows_per_capture"] = max_flows_per_capture
        counters["quotas_satisfied"] = quotas_satisfied()
        counters["flows_truncated"] = flows_truncated_count
        counters["captures_truncated"] = captures_truncated_count
        counters["raw_packets_read"] = total_raw_packets
        counters["raw_bytes_read"] = total_raw_bytes
        counters["raw_packets_capped"] = any_raw_packets_capped
        counters["raw_bytes_capped"] = any_raw_bytes_capped
        counters["accepted_packets"] = total_accepted_packets
        counters["accepted_bytes"] = total_accepted_bytes
    return retained_flows


def build_samples_for_task_and_window(
    flows: Sequence[BoundedFlowRecord],
    task: str,
    window_size: int,
    stride: int = 1,
    pad: bool = True,
    max_windows_per_flow: Optional[int] = None,
    max_windows_per_class: Optional[int] = None,
    counters: Optional[Dict[str, int]] = None,
) -> List[SequenceSample]:
    """Generate exact window-specific SequenceSample records for a specific task and window size.

    - For L1 ('l1'): uses l1_label (0=non_doh, 1=doh), layer=1.
    - For L2 ('l2'): filters to DoH flows with l2_label in {0, 1} (0=benign_doh, 1=malicious_doh), layer=2.
    """
    samples: List[SequenceSample] = []
    layer_num = 1 if task == "l1" else 2
    class_sample_counts: Dict[int, int] = {}
    truncated_by_flow = 0
    truncated_by_class = 0

    for flow in flows:
        if task == "l1":
            if flow.l1_label not in {0, 1}:
                continue
            lbl = flow.l1_label
        elif task == "l2":
            if flow.l2_label not in {0, 1}:
                continue
            lbl = flow.l2_label
        else:
            raise ValueError(f"Unknown task: {task!r}. Expected 'l1' or 'l2'.")

        # Check class window quota
        if max_windows_per_class is not None and class_sample_counts.get(lbl, 0) >= max_windows_per_class:
            continue

        if create_sequence_samples is not None:
            flow_samples = create_sequence_samples(
                flow_id=flow.flow_id,
                session_id=flow.session_id,
                scenario_id=flow.scenario_id,
                label=lbl,
                clumps=list(flow.clumps),
                window_size=window_size,
                stride=stride,
                pad=pad,
                layer=layer_num,
                source_file=flow.source_id,
                start_time=flow.start_time,
                end_time=flow.end_time,
                max_windows=max_windows_per_flow,
            )
        elif SequenceSample is not None and clumps_to_reference_vectors is not None:
            ref_vectors = clumps_to_reference_vectors(flow.clumps, normalize=True)
            flow_samples = []
            if len(ref_vectors) < window_size and pad:
                padded = list(ref_vectors) + [PADDING_VECTOR] * (window_size - len(ref_vectors))
                s_features = tuple(tuple(float(v) for v in row) for row in padded)
                meta = SequenceMetadata(
                    sample_id=f"{flow.flow_id}_seg0",
                    flow_id=flow.flow_id,
                    session_id=flow.session_id,
                    scenario_id=flow.scenario_id,
                    label=lbl,
                    layer=layer_num,
                    window_index=0,
                    window_size=window_size,
                    is_padded=True,
                    pad_count=window_size - len(ref_vectors),
                    source_file=flow.source_id,
                )
                flow_samples.append(SequenceSample(features=s_features, metadata=meta))
            elif len(ref_vectors) >= window_size:
                for seg_i, start_i in enumerate(range(0, len(ref_vectors) - window_size + 1, stride)):
                    if max_windows_per_flow is not None and len(flow_samples) >= max_windows_per_flow:
                        truncated_by_flow += 1
                        break
                    sub = ref_vectors[start_i : start_i + window_size]
                    s_features = tuple(tuple(float(v) for v in row) for row in sub)
                    meta = SequenceMetadata(
                        sample_id=f"{flow.flow_id}_seg{seg_i}",
                        flow_id=flow.flow_id,
                        session_id=flow.session_id,
                        scenario_id=flow.scenario_id,
                        label=lbl,
                        layer=layer_num,
                        window_index=seg_i,
                        window_size=window_size,
                        is_padded=False,
                        pad_count=0,
                        source_file=flow.source_id,
                    )
                    flow_samples.append(SequenceSample(features=s_features, metadata=meta))
        else:
            flow_samples = []

        # Enforce class window limits
        if max_windows_per_class is not None:
            remaining = max_windows_per_class - class_sample_counts.get(lbl, 0)
            if len(flow_samples) > remaining:
                truncated_by_class += len(flow_samples) - remaining
                flow_samples = flow_samples[:remaining]

        samples.extend(flow_samples)
        class_sample_counts[lbl] = class_sample_counts.get(lbl, 0) + len(flow_samples)

    if counters is not None:
        counters["total_windows"] = len(samples)
        counters["truncated_by_flow"] = truncated_by_flow
        counters["truncated_by_class"] = truncated_by_class

    return samples


def stream_and_build_sequences(
    capture_sources: List[Any],
    max_flows_per_class: Optional[int] = 500,
    window_sizes: Sequence[int] = (3, 6),
    task: str = "l1",
) -> List[SequenceSample]:
    """Streams PCAP flows and generates sequence samples for backward compatibility."""
    flows = stream_and_collect_flows(capture_sources, max_flows_per_class=max_flows_per_class, task=task)
    w = max(window_sizes) if window_sizes else 6
    return build_samples_for_task_and_window(flows, task=task, window_size=w)


def make_data_loader(
    samples: Sequence[SequenceSample],
    batch_size: int = 64,
    shuffle: bool = False,
) -> Any:
    """Build a PyTorch DataLoader yielding (x, y, mask) batches from SequenceSamples."""
    if not samples:
        return None
    if torch is None or not hasattr(torch, "utils") or not hasattr(torch.utils, "data"):
        raise RuntimeError("PyTorch is required to build DataLoaders.")

    X, y, masks = samples_to_arrays(samples)
    x_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(y, dtype=torch.float32)
    mask_tensor = torch.tensor(masks, dtype=torch.float32)
    dataset = torch.utils.data.TensorDataset(x_tensor, y_tensor, mask_tensor)
    return torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=shuffle)


# ---------------------------------------------------------------------------
# Metric & Manifest Output Serializers
# ---------------------------------------------------------------------------
def write_json_artifact(path: Path, payload: Dict[str, Any]) -> None:
    """Atomically serializes dictionary to JSON with formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Artifact written: %s (%d bytes)", path.name, path.stat().st_size)


def write_csv_artifact(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, Any]]) -> None:
    """Serializes rows to CSV format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    logger.info("CSV artifact written: %s (%d rows)", path.name, len(rows))


def emit_audit_mode_artifacts(
    output_dir: Path,
    config: Dict[str, Any],
    config_source: str,
    audit_payload: Dict[str, Any],
) -> None:
    """Emits minimal lightweight artifacts when running in audit-only mode without training."""
    # 1. pcap_audit.json
    write_json_artifact(output_dir / "pcap_audit.json", audit_payload)

    # 2. metrics.json (audit status, zero fabricated numbers) compliant with validate_timeseries_metrics_schema
    metrics_payload: Dict[str, Any] = {
        "manifest_version": "1.0.0",
        "task": config.get("task", "both"),
        "execution_mode": "audit",
        "status": "not_trained",
        "dataset_slug": config["dataset_slug"],
        "dataset_version": config["dataset_version"],
        "pcap_audit_file": "pcap_audit.json",
        "total_capture_sources": audit_payload.get("total_capture_sources", 0),
        "message": "Audit completed successfully. Mode is 'audit'; no models were trained or evaluated.",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": KAGGLE_GIT_SHA,
        "source_snapshot_sha256": KAGGLE_SOURCE_SNAPSHOT_SHA256,
        "runs": [],
    }
    write_json_artifact(output_dir / "metrics.json", metrics_payload)

    # 3. experiment_manifest.json (audit_only)
    is_capped = any(config.get(k) is not None for k in RESOURCE_CAP_KEYS)
    manifest_payload: Dict[str, Any] = {
        "manifest_version": "1.0.0",
        "execution_mode": "audit",
        "status": "audit_only",
        "dataset_slug": config["dataset_slug"],
        "dataset_version": config["dataset_version"],
        "config_source": config_source,
        "resolved_config": config,
        "resource_bounds": {
            "is_capped_run": is_capped,
            "active_caps": {k: config.get(k) for k in RESOURCE_CAP_KEYS},
            "truncation_counters": {
                "sources_discovered": audit_payload.get("total_sources", 0),
                "sources_truncated_by_max_members": audit_payload.get("audit_counters", {}).get(
                    "truncated_due_to_max_sources", False
                ),
                "raw_packets_read": 0,
                "raw_bytes_read": 0,
                "raw_packets_capped": False,
                "raw_bytes_capped": False,
                "accepted_packets": 0,
                "accepted_bytes": 0,
                "capture_truncated": False,
                "flows_processed": 0,
                "flows_retained": 0,
                "flows_truncated_by_flow_caps": 0,
                "class_quotas_satisfied": False,
                "windows_generated": 0,
                "windows_truncated_by_flow_cap": 0,
                "windows_truncated_by_class_cap": 0,
            },
        },
        "provenance": {
            "git_sha": KAGGLE_GIT_SHA,
            "source_snapshot_sha256": KAGGLE_SOURCE_SNAPSHOT_SHA256,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "embedded_config_present": EMBEDDED_CONFIG_JSON is not None,
        },
        "software_versions": {
            "python": sys.version.split()[0],
            "numpy": NUMPY_VERSION,
            "torch": TORCH_VERSION,
            "torch_cuda_available": TORCH_CUDA_AVAILABLE,
            "dpkt": DPKT_VERSION,
            "scikit_learn": SKLEARN_VERSION,
            "scipy": SCIPY_VERSION,
        },
        "hardware_info": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "claim_boundaries": {
            "paper_replication": (
                "Reconstructs MontazeriShatoori et al. (2020) packet-clumping LSTM (DoHLyzer v4.py) with 1ms clumping timeout, "
                "reference feature order [interarrival, duration, size, packet_count, direction], and flow-random 80/20 split. "
                "Marked with explicit data leakage caveat due to cross-partition session overlap."
            ),
            "reference_facts": (
                "DoHLyzer v4.py reference implementation architecture: Dense(10, ReLU) -> LSTM(8*l, ReLU) -> Dense(6*l, ReLU) -> "
                "Dropout(0.2) -> Dense(2*l, ReLU) -> Dense(1, Sigmoid). Normalization formulas verified from DoHLyzer analyzer/dataset.py. "
                "Training hyperparameters (Adam, learning rate, batch size, epochs, patience) were omitted in the published paper and represent project decisions."
            ),
            "project_improvements": (
                "Corrected evaluation protocol: Session/scenario-disjoint 70/15/15 group split proving zero session overlap across partitions; "
                "mask-aware Bidirectional GRU model with attention pooling; class-weighted BCE loss; validation-only Platt probability calibration "
                "and decision threshold selection under strict target FPR constraint (FPR <= 0.001). Never tunes threshold on test data."
            ),
        },
        "capture_sources_summary": {
            "total_capture_sources": audit_payload.get("total_capture_sources", 0),
            "total_uncompressed_bytes": audit_payload.get("total_uncompressed_bytes", 0),
            "summary_by_category": audit_payload.get("summary_by_category", {}),
        },
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json_artifact(output_dir / "experiment_manifest.json", manifest_payload)


# ---------------------------------------------------------------------------
# Main Training & Sweeps Runner
# ---------------------------------------------------------------------------
def run_timeseries_pipeline(
    config: Dict[str, Any],
    output_dir: Path,
    config_source: str = "defaults",
) -> int:
    """Executes the full audit-first time-series runner pipeline."""
    # Strictly validate and normalize configuration against DEFAULT_CONFIG at pipeline entry boundary
    config = validate_run_config(config)
    start_time = time.time()
    logger.info("Initializing Kaggle Time-Series Runner. Mode: %s", config["mode"])

    dataset_dir = Path(config["dataset_dir"])
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. PCAP Dataset Discovery and Audit (Always performed first)
    capture_sources, audit_payload = perform_pcap_audit(
        dataset_dir,
        max_members=config.get("max_capture_members"),
        max_standalone_capture_bytes=config.get("max_standalone_capture_bytes", 21474836480),
        max_member_bytes=config.get("max_member_bytes", 10737418240),
        max_nested_archive_bytes=config.get("max_nested_archive_bytes", 26843545600),
        max_total_uncompressed_bytes=config.get("max_total_uncompressed_bytes", 214748364800),
        max_compression_ratio=config.get("max_compression_ratio", 100.0),
    )

    # In audit mode, emit audit artifacts and exit 0 cleanly without training
    if config["mode"] == "audit":
        logger.info("Operating in audit mode. Emitting pcap_audit.json and lightweight manifests...")
        emit_audit_mode_artifacts(output_dir, config, config_source, audit_payload)
        logger.info("Audit mode execution complete. Exiting cleanly.")
        return 0

    # 2. Strict Pre-Training Dataset Validation
    if len(capture_sources) == 0:
        raise ValueError(
            f"Dataset directory '{dataset_dir}' contains no valid PCAP or ZIP capture sources. "
            "Refusing to train on unaudited empty dataset."
        )

    # Verify that requested classification tasks have candidate ground-truth categories
    cat_summary = (
        audit_payload.get("summary_by_category")
        or audit_payload.get("category_counts")
        or {}
    )
    if not cat_summary:
        sources_list = audit_payload.get("capture_sources") or audit_payload.get("sources") or capture_sources
        for s in sources_list:
            c = s.get("category") if isinstance(s, dict) else getattr(s, "category", "non_doh")
            cat_summary[c] = cat_summary.get(c, 0) + 1

    task_mode = config["task"]

    # Layer 1 ground truth is assigned per decoded flow from resolver IPs. A
    # combined BenignDoH-NonDoH capture legitimately contains both L1 classes,
    # so capture-level categories cannot prove either class is missing. The
    # stratified flow split below remains the fail-closed class-presence check.

    if task_mode in {"l2", "both"}:
        benign_candidates = cat_summary.get("benign_doh", 0)
        malicious_candidates = cat_summary.get("malicious_doh", 0)
        if benign_candidates == 0 or malicious_candidates == 0:
            raise ValueError(
                f"Cannot execute Layer 2 training: missing classes. "
                f"Discovered Benign DoH candidates: {benign_candidates}, Malicious DoH candidates: {malicious_candidates}."
            )

    # Always write pcap_audit.json before starting sequence extraction
    write_json_artifact(output_dir / "pcap_audit.json", audit_payload)

    # 3. Stream & Collect Bounded Flows
    ingestion_counters: Dict[str, Any] = {}
    flows = stream_and_collect_flows(
        capture_sources,
        max_flows_per_class=config.get("max_flows_per_class"),
        task=task_mode,
        max_flows_per_capture=config.get("max_flows_per_capture"),
        max_raw_packets=config.get("max_raw_packets"),
        max_raw_bytes=config.get("max_raw_bytes"),
        max_capture_packets=config.get("max_capture_packets"),
        max_capture_bytes=config.get("max_capture_bytes"),
        max_flow_packets=config.get("max_flow_packets"),
        max_flow_bytes=config.get("max_flow_bytes"),
        counters=ingestion_counters,
    )

    if len(flows) == 0:
        raise ValueError(
            "Insufficient flows collected (0 flows). "
            "Verify that PCAPs contain valid IP/TCP/UDP flows and packet clumps."
        )

    # 4. Determine Sweeps
    tasks_to_run: List[str] = ["l1", "l2"] if task_mode == "both" else [task_mode]
    protocols_to_run: List[str] = (
        ["session_scenario_disjoint", "paper_flow_random"]
        if config["split_protocol"] == "both"
        else [config["split_protocol"]]
    )
    window_sizes_to_run: List[int] = config["window_sizes"]
    models_to_run: List[str] = config["models"]

    all_metric_rows: List[Dict[str, Any]] = []
    all_training_history_rows: List[Dict[str, Any]] = []

    device = "cuda" if (torch is not None and torch.cuda.is_available()) else "cpu"

    total_window_counters: Dict[str, int] = {
        "total_windows": 0,
        "truncated_by_flow": 0,
        "truncated_by_class": 0,
    }

    # 5. Execute Task / Window / Protocol / Model Sweeps
    for task_name in tasks_to_run:
        logger.info("=== Running Sweep for Task: %s ===", task_name.upper())

        # Filter candidate flows for this task
        if task_name == "l1":
            candidate_flows = [f for f in flows if f.l1_label in {0, 1}]
            classes_present = {f.l1_label for f in candidate_flows}
        else:
            candidate_flows = [f for f in flows if f.l2_label in {0, 1}]
            classes_present = {f.l2_label for f in candidate_flows}

        if len(classes_present) < 2:
            logger.warning(
                "Insufficient class diversity for task %s (classes found: %s). Skipping task.",
                task_name,
                classes_present,
            )
            continue

        for w_size in window_sizes_to_run:
            logger.info("... Generating exact window samples for task %s, window size %d ...", task_name, w_size)
            step_window_counters: Dict[str, int] = {}
            task_window_samples = build_samples_for_task_and_window(
                candidate_flows,
                task=task_name,
                window_size=w_size,
                stride=1,
                pad=True,
                max_windows_per_flow=config.get("max_windows_per_flow"),
                max_windows_per_class=config.get("max_windows_per_class"),
                counters=step_window_counters,
            )
            for k_w in ("total_windows", "truncated_by_flow", "truncated_by_class"):
                total_window_counters[k_w] += step_window_counters.get(k_w, 0)

            if len(task_window_samples) < 2:
                logger.warning(
                    "Insufficient sequence samples generated for task %s, window %d (%d samples). Skipping.",
                    task_name,
                    w_size,
                    len(task_window_samples),
                )
                continue

            for split_proto in protocols_to_run:
                logger.info(
                    "--- Splitting dataset under protocol: %s (Task: %s, Window: %d) ---",
                    split_proto,
                    task_name,
                    w_size,
                )
                if split_samples is None:
                    raise RuntimeError("doh_reproduction.timeseries_data.split_samples is not available.")

                try:
                    split_res = split_samples(task_window_samples, protocol=split_proto, seed=config["seed"])
                except Exception as split_err:
                    logger.warning(
                        "Split failed for task %s, window %d under protocol %s: %s. Skipping.",
                        task_name,
                        w_size,
                        split_proto,
                        split_err,
                    )
                    continue

                # Verify split invariants
                if split_proto == "session_scenario_disjoint":
                    train_sessions = {s.session_id for s in split_res.train}
                    val_sessions = {s.session_id for s in split_res.val}
                    test_sessions = {s.session_id for s in split_res.test}
                    if (train_sessions & test_sessions) or (train_sessions & val_sessions) or (val_sessions & test_sessions):
                        raise RuntimeError(
                            f"Data leakage detected in session_scenario_disjoint split! "
                            f"Train & Test session overlap: {train_sessions & test_sessions}, "
                            f"Train & Val session overlap: {train_sessions & val_sessions}, "
                            f"Val & Test session overlap: {val_sessions & test_sessions}"
                        )
                    leakage_caveat_text = None
                else:
                    leakage_caveat_text = (
                        "WARNING: Evaluated under paper_flow_random 80/20 split. Flows from the same capture session "
                        "appear in both train and test partitions, causing session-level data leakage and optimistic metrics."
                    )

                # Build real PyTorch DataLoaders before fit_model
                train_loader = make_data_loader(split_res.train, batch_size=config["batch_size"], shuffle=True)
                val_loader = (
                    make_data_loader(split_res.val, batch_size=config["batch_size"], shuffle=False)
                    if len(split_res.val) > 0
                    else None
                )
                test_loader = make_data_loader(split_res.test, batch_size=config["batch_size"], shuffle=False)

                for model_name in models_to_run:
                    logger.info(
                        "... Training model: %s (Window: %d, Task: %s, Split: %s) ...",
                        model_name,
                        w_size,
                        task_name,
                        split_proto,
                    )

                    # Determine evidence status
                    if model_name == "paper_v4" and split_proto == "paper_flow_random":
                        evidence_status = "paper_replication_leaky_split"
                    elif model_name == "paper_v4" and split_proto == "session_scenario_disjoint":
                        evidence_status = "paper_model_corrected_split"
                    elif model_name == "improved_bidi_gru" and split_proto == "session_scenario_disjoint":
                        evidence_status = "improved_candidate_corrected_split"
                    else:
                        evidence_status = "improved_candidate_leaky_split"

                    # Seeding for reproducibility
                    if set_deterministic_seed is not None:
                        set_deterministic_seed(config["seed"])

                    # Build model instance matching exact window size
                    model = None
                    if model_name == "paper_v4":
                        if create_paper_model is not None:
                            model = create_paper_model(window_size=w_size)
                    elif model_name == "improved_bidi_gru":
                        if create_improved_model is not None:
                            model = create_improved_model(window_size=w_size)

                    if model is None:
                        raise RuntimeError(f"Failed to instantiate model '{model_name}'. Check timeseries_models module.")

                    # Pass pos_weight only for the improved model
                    pos_weight: Optional[float] = None
                    if model_name == "improved_bidi_gru":
                        train_labels = [s.label for s in split_res.train]
                        if compute_pos_weight is not None and len(train_labels) > 0:
                            pos_weight = compute_pos_weight(train_labels)

                    # Train model using fit_model with DataLoaders
                    training_history: Dict[str, Any] = {}
                    if fit_model is not None:
                        try:
                            training_history = fit_model(
                                model,
                                train_loader=train_loader,
                                val_loader=val_loader,
                                epochs=config["epochs"],
                                lr=config["learning_rate"],
                                pos_weight=pos_weight,
                                patience=config["patience"],
                                device=device,
                                target_fpr=config["target_false_positive_rate"],
                            )
                        except Exception as e:
                            logger.error("Error during fit_model: %s", e)
                            raise

                    # Record per-epoch training history
                    epoch_losses = training_history.get("train_loss", training_history.get("train_losses", []))
                    val_losses = training_history.get("val_loss", training_history.get("val_losses", []))
                    for ep_i, t_loss in enumerate(epoch_losses):
                        if t_loss is not None:
                            all_training_history_rows.append({
                                "task": task_name,
                                "model": model_name,
                                "window_size": int(w_size),
                                "split_protocol": split_proto,
                                "epoch": ep_i + 1,
                                "train_loss": float(t_loss),
                                "val_loss": (
                                    float(val_losses[ep_i])
                                    if ep_i < len(val_losses) and val_losses[ep_i] is not None
                                    else None
                                ),
                            })

                    # Predict on test split using DataLoader
                    y_test = [s.label for s in split_res.test]
                    if predict_probabilities is not None and test_loader is not None:
                        raw_test_probs = predict_probabilities(model, test_loader, device=device)
                        raw_test_probs = [float(p) for p in raw_test_probs]
                    else:
                        raw_test_probs = [0.5] * len(y_test)

                    # Platt Calibration & Validation-only Threshold Selection
                    threshold = 0.5
                    is_calibrated = False
                    eval_test_probs = list(raw_test_probs)
                    val_samples = split_res.val

                    if (
                        config.get("enable_score_calibration", True)
                        and len(val_samples) > 0
                        and platt_calibrate is not None
                        and select_threshold_at_fpr is not None
                        and predict_probabilities is not None
                    ):
                        try:
                            val_loader_eval = make_data_loader(
                                val_samples,
                                batch_size=config["batch_size"],
                                shuffle=False,
                            )
                            y_val = [s.label for s in val_samples]
                            raw_val_probs = predict_probabilities(model, val_loader_eval, device=device)
                            raw_val_probs = [float(p) for p in raw_val_probs]

                            # Platt scaling strictly on validation scores/labels, applied to test scores
                            _, val_cal_probs, test_cal_probs = platt_calibrate(
                                val_scores=raw_val_probs,
                                y_val=y_val,
                                test_scores=raw_test_probs,
                            )
                            val_scores_for_thresh = [float(p) for p in val_cal_probs]
                            if test_cal_probs is not None:
                                eval_test_probs = [float(p) for p in test_cal_probs]
                            is_calibrated = True

                            # Select operating threshold strictly on validation data with correct (y_val, scores) order
                            sel_thresh, achieved_fpr, _ = select_threshold_at_fpr(
                                y_val,
                                val_scores_for_thresh,
                                target_fpr=config["target_false_positive_rate"],
                            )
                            threshold = float(sel_thresh)
                        except Exception as cal_err:
                            logger.warning("Calibration fallback: %s", cal_err)
                    elif (
                        len(val_samples) > 0
                        and select_threshold_at_fpr is not None
                        and predict_probabilities is not None
                    ):
                        try:
                            val_loader_eval = make_data_loader(
                                val_samples,
                                batch_size=config["batch_size"],
                                shuffle=False,
                            )
                            y_val = [s.label for s in val_samples]
                            raw_val_probs = predict_probabilities(model, val_loader_eval, device=device)
                            raw_val_probs = [float(p) for p in raw_val_probs]
                            sel_thresh, achieved_fpr, _ = select_threshold_at_fpr(
                                y_val,
                                raw_val_probs,
                                target_fpr=config["target_false_positive_rate"],
                            )
                            threshold = float(sel_thresh)
                        except Exception as thresh_err:
                            logger.warning("Threshold fallback: %s", thresh_err)

                    # Predictions and Metrics
                    y_test_pred = [1 if p >= threshold else 0 for p in eval_test_probs]

                    if binary_metrics is not None and confusion_matrix_counts is not None:
                        metrics_dict = binary_metrics(y_test, y_test_pred, eval_test_probs)
                        tn, fp, fn, tp = confusion_matrix_counts(y_test, y_test_pred)
                    else:
                        tn, fp, fn, tp = 0, 0, 0, 0
                        metrics_dict = {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0, "fpr": 0.0}

                    # Write confusion matrix CSV
                    cm_filename = f"confusion_matrix_{task_name}_{model_name}_w{w_size}_{split_proto}.csv"
                    cm_rows = [
                        {"actual": "negative", "predicted_negative": int(tn), "predicted_positive": int(fp)},
                        {"actual": "positive", "predicted_negative": int(fn), "predicted_positive": int(tp)},
                    ]
                    write_csv_artifact(
                        output_dir / cm_filename,
                        fieldnames=["actual", "predicted_negative", "predicted_positive"],
                        rows=cm_rows,
                    )

                    metric_row = {
                        "task": task_name,
                        "model": model_name,
                        "window_size": int(w_size),
                        "split_protocol": split_proto,
                        "evidence_status": evidence_status,
                        "train_samples": len(split_res.train),
                        "val_samples": len(split_res.val),
                        "test_samples": len(split_res.test),
                        "accuracy": metrics_dict.get("accuracy"),
                        "precision": metrics_dict.get("precision"),
                        "recall": metrics_dict.get("recall"),
                        "f1_score": metrics_dict.get("f1"),
                        "f1": metrics_dict.get("f1"),
                        "fpr": metrics_dict.get("fpr"),
                        "roc_auc": metrics_dict.get("roc_auc"),
                        "pr_auc": metrics_dict.get("pr_auc"),
                        "tn": int(tn),
                        "fp": int(fp),
                        "fn": int(fn),
                        "tp": int(tp),
                        "threshold_used": float(threshold),
                        "is_calibrated": bool(is_calibrated),
                        "target_fpr": float(config["target_false_positive_rate"]),
                        "leakage_caveat": leakage_caveat_text,
                    }
                    all_metric_rows.append(metric_row)

    # 6. Emit Metrics Artifact (metrics.json) compliant with validate_timeseries_metrics_schema
    metrics_payload: Dict[str, Any] = {
        "manifest_version": "1.0.0",
        "task": config.get("task", "both"),
        "execution_mode": "train",
        "status": "training_completed",
        "dataset_slug": config["dataset_slug"],
        "dataset_version": config["dataset_version"],
        "total_evaluations": len(all_metric_rows),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_sha": KAGGLE_GIT_SHA,
        "source_snapshot_sha256": KAGGLE_SOURCE_SNAPSHOT_SHA256,
        "runs": all_metric_rows,
    }
    write_json_artifact(output_dir / "metrics.json", metrics_payload)

    # 7. Emit Training History CSV (training_history.csv)
    if len(all_training_history_rows) > 0:
        write_csv_artifact(
            output_dir / "training_history.csv",
            fieldnames=["task", "model", "window_size", "split_protocol", "epoch", "train_loss", "val_loss"],
            rows=all_training_history_rows,
        )

    # 8. Emit Experiment Manifest (experiment_manifest.json)
    duration_sec = time.time() - start_time
    is_capped = any(config.get(k) is not None for k in RESOURCE_CAP_KEYS)
    manifest_payload: Dict[str, Any] = {
        "manifest_version": "1.0.0",
        "execution_mode": "train",
        "status": "training_completed",
        "dataset_slug": config["dataset_slug"],
        "dataset_version": config["dataset_version"],
        "config_source": config_source,
        "resolved_config": config,
        "resource_bounds": {
            "is_capped_run": is_capped,
            "active_caps": {k: config.get(k) for k in RESOURCE_CAP_KEYS},
            "truncation_counters": {
                "sources_discovered": audit_payload.get("total_sources", len(capture_sources)),
                "sources_truncated_by_max_members": audit_payload.get("audit_counters", {}).get(
                    "truncated_due_to_max_sources", False
                ),
                "raw_packets_read": ingestion_counters.get("raw_packets_read", 0),
                "raw_bytes_read": ingestion_counters.get("raw_bytes_read", 0),
                "raw_packets_capped": ingestion_counters.get("raw_packets_capped", False),
                "raw_bytes_capped": ingestion_counters.get("raw_bytes_capped", False),
                "accepted_packets": ingestion_counters.get("accepted_packets", 0),
                "accepted_bytes": ingestion_counters.get("accepted_bytes", 0),
                "capture_truncated": ingestion_counters.get("captures_truncated", 0) > 0,
                "flows_processed": ingestion_counters.get("total_flows_processed", 0),
                "flows_retained": len(flows),
                "flows_truncated_by_flow_caps": ingestion_counters.get("flows_truncated", 0),
                "class_quotas_satisfied": ingestion_counters.get("quotas_satisfied", False),
                "windows_generated": total_window_counters.get("total_windows", 0),
                "windows_truncated_by_flow_cap": total_window_counters.get("truncated_by_flow", 0),
                "windows_truncated_by_class_cap": total_window_counters.get("truncated_by_class", 0),
            },
        },
        "provenance": {
            "git_sha": KAGGLE_GIT_SHA,
            "source_snapshot_sha256": KAGGLE_SOURCE_SNAPSHOT_SHA256,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "embedded_config_present": EMBEDDED_CONFIG_JSON is not None,
        },
        "software_versions": {
            "python": sys.version.split()[0],
            "numpy": NUMPY_VERSION,
            "torch": TORCH_VERSION,
            "torch_cuda_available": TORCH_CUDA_AVAILABLE,
            "dpkt": DPKT_VERSION,
            "scikit_learn": SKLEARN_VERSION,
            "scipy": SCIPY_VERSION,
        },
        "hardware_info": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "claim_boundaries": {
            "paper_replication": (
                "Reconstructs MontazeriShatoori et al. (2020) packet-clumping LSTM (DoHLyzer v4.py) with 1ms clumping timeout, "
                "reference feature order [interarrival, duration, size, packet_count, direction], and flow-random 80/20 split. "
                "Marked with explicit data leakage caveat due to cross-partition session overlap."
            ),
            "reference_facts": (
                "DoHLyzer v4.py reference implementation architecture: Dense(10, ReLU) -> LSTM(8*l, ReLU) -> Dense(6*l, ReLU) -> "
                "Dropout(0.2) -> Dense(2*l, ReLU) -> Dense(1, Sigmoid). Normalization formulas verified from DoHLyzer analyzer/dataset.py. "
                "Training hyperparameters (Adam, learning rate, batch size, epochs, patience) were omitted in the published paper and represent project decisions."
            ),
            "project_improvements": (
                "Corrected evaluation protocol: Session/scenario-disjoint 70/15/15 group split proving zero session overlap across partitions; "
                "mask-aware Bidirectional GRU model with attention pooling; class-weighted BCE loss; validation-only Platt probability calibration "
                "and decision threshold selection under strict target FPR constraint (FPR <= 0.001). Never tunes threshold on test data."
            ),
        },
        "execution_summary": {
            "tasks_evaluated": sorted({str(row["task"]) for row in all_metric_rows}),
            "models_evaluated": sorted({str(row["model"]) for row in all_metric_rows}),
            "window_sizes_evaluated": sorted({int(row["window_size"]) for row in all_metric_rows}),
            "split_protocols_evaluated": sorted({str(row["split_protocol"]) for row in all_metric_rows}),
            "total_metric_rows": len(all_metric_rows),
            "duration_seconds": round(duration_sec, 2),
        },
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json_artifact(output_dir / "experiment_manifest.json", manifest_payload)

    # 9. Safety Invariant: Ensure zero raw PCAP bytes or binary weights (.pt, .pkl) exist in output_dir
    for out_f in output_dir.rglob("*"):
        if out_f.is_file():
            if out_f.suffix.lower() in {".pt", ".pth", ".pkl", ".h5", ".joblib", ".pcap", ".pcapng", ".cap"}:
                logger.warning("Safety guard: Removing prohibited binary/capture artifact: %s", out_f)
                out_f.unlink()

    logger.info("Pipeline execution successfully completed in %.2f seconds.", duration_sec)
    return 0


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parses command-line arguments for local execution or testing."""
    parser = argparse.ArgumentParser(
        description="Audit-first standalone Kaggle runner for CIRA-CIC-DoHBrw-2020 raw-PCAP packet-clump sequence classification."
    )
    parser.add_argument(
        "--config",
        dest="config_file",
        type=str,
        default=None,
        help="Path to external run_config.json file.",
    )
    parser.add_argument(
        "--mode",
        choices=["audit", "train"],
        default=None,
        help="Override execution mode ('audit' or 'train').",
    )
    parser.add_argument(
        "--task",
        choices=["l1", "l2", "both"],
        default=None,
        help="Override evaluation task ('l1', 'l2', or 'both').",
    )
    parser.add_argument(
        "--split-protocol",
        choices=["paper_flow_random", "session_scenario_disjoint", "both"],
        default=None,
        help="Override split protocol.",
    )
    parser.add_argument(
        "--dataset-dir",
        type=str,
        default=None,
        help="Override dataset directory containing raw PCAPs or ZIP archives.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write output artifacts (defaults to /kaggle/working if present, else current directory).",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Force execution in audit mode without training.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override pseudo-random seed.",
    )
    parser.add_argument(
        "--max-captures",
        type=int,
        default=None,
        help="Override maximum capture files/members to parse.",
    )
    parser.add_argument(
        "--max-flows",
        type=int,
        default=None,
        help="Override maximum flows to extract per class.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Callable entry point for Kaggle script or CLI execution."""
    args = parse_args(argv)

    # Resolve base configuration
    resolved_cfg, cfg_source = resolve_config(args.config_file)

    # Apply CLI overrides if explicitly passed
    if args.mode:
        resolved_cfg["mode"] = args.mode
    if args.audit_only:
        resolved_cfg["mode"] = "audit"
    if args.task:
        resolved_cfg["task"] = args.task
    if args.split_protocol:
        resolved_cfg["split_protocol"] = args.split_protocol
    if args.dataset_dir:
        resolved_cfg["dataset_dir"] = args.dataset_dir
    if args.seed is not None:
        resolved_cfg["seed"] = args.seed
    if args.max_captures is not None:
        resolved_cfg["max_capture_members"] = args.max_captures
    if args.max_flows is not None:
        resolved_cfg["max_flows_per_class"] = args.max_flows

    # Re-validate after overrides
    final_cfg = validate_run_config(resolved_cfg)

    # Determine output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        kaggle_working = Path("/kaggle/working")
        out_dir = kaggle_working if kaggle_working.exists() and os.access(kaggle_working, os.W_OK) else Path(".")

    return run_timeseries_pipeline(final_cfg, output_dir=out_dir, config_source=cfg_source)


if __name__ == "__main__":
    sys.exit(main())
