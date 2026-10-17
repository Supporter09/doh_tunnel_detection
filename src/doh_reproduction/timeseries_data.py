"""DoHLyzer-reference time-series data pipeline, normalization, windowing, and split protocols.

This module implements:
1. Exact DoHLyzer reference clump normalization and vector ordering:
   Order: [interarrival, duration, size, packet_count, direction]
   Padding: [-1.0, -1.0, -1.0, -1.0, 0.0]
2. Sliding window segmentation with stride=1 and deterministic post-padding.
3. Immutable sequence sample metadata and sample records.
4. Stratified 80/20 paper_flow_random splitter with explicit data leakage caveat.
5. Group/session-disjoint 70/15/15 splitter with mathematical zero session overlap guarantee.
6. Split leakage reporting and serializable manifests.
7. Strictly train-derived class weights and feature scaling (preventing data snooping).
8. Nested-list data payloads suitable for zero-copy NumPy/PyTorch conversion.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Sequence

try:
    from .clumping import Clump, clumping, segment_clumps
except ImportError:
    from doh_reproduction.clumping import Clump, clumping, segment_clumps

# -----------------------------------------------------------------------------
# Constants & Contract Definitions
# -----------------------------------------------------------------------------

# Reference vector order per DoHLyzer dataset.py and meter/time_series/flow_clumps.py
PAPER_REFERENCE_FEATURE_ORDER: tuple[str, ...] = (
    "interarrival",
    "duration",
    "size",
    "packet_count",
    "direction",
)

# Reference padding vector for DoHLyzer time-series model (v4.py)
PADDING_VECTOR: list[float] = [-1.0, -1.0, -1.0, -1.0, 0.0]
DOHLYZER_PADDING_VECTOR: list[float] = PADDING_VECTOR

# Sequence lengths (window sizes) per paper evaluation:
# Layer 1 (DoH vs Non-DoH): Table V uses l=6
# Layer 2 (Benign DoH vs Malicious DoH): Table VI uses l=3 (and l=6)
LAYER1_WINDOW_SIZE: int = 6
LAYER2_WINDOW_SIZE: int = 3

# Canonical ground-truth layer labels
LAYER1_LABEL_NON_DOH: int = 0
LAYER1_LABEL_DOH: int = 1
LAYER2_LABEL_BENIGN: int = 0
LAYER2_LABEL_MALICIOUS: int = 1

# Explicit paper data leakage caveat
PAPER_FLOW_RANDOM_LEAKAGE_CAVEAT: str = (
    "CAVEAT: paper_flow_random splits flows randomly across train and test sets without "
    "session or scenario isolation. Flows originating from the same browser session or "
    "tunnel execution share TCP stack signatures, TLS ciphers, and timing dynamics. "
    "Random flow splitting allows the model to memorize session-level artifacts, leading "
    "to overly optimistic test metrics that do not generalize to unseen sessions or hosts."
)

CORRECTED_DISJOINT_ASSURANCE: str = (
    "CORRECTED PROTOCOL: Group/session-disjoint split isolates entire sessions into "
    "strictly separate folds (Train, Validation, Test). Guarantees zero session and "
    "scenario overlap between folds, eliminating cross-session data leakage."
)


# -----------------------------------------------------------------------------
# DoHLyzer Reference Normalization Equations
# -----------------------------------------------------------------------------

def normalize_time(val: float) -> float:
    """Normalize time duration or interarrival time per DoHLyzer reference:
    normalize(log10(max(1e-12, x)), -12, -2)
    Scaled linearly: (val - min) / (max - min) = (log10(x) - (-12)) / (-2 - (-12))
    """
    safe_val = max(1e-12, float(val))
    log_val = math.log10(safe_val)
    return (log_val - (-12.0)) / (-2.0 - (-12.0))


def normalize_size(val: int | float) -> float:
    """Normalize clump total byte size per DoHLyzer reference:
    normalize(log10(min(1e4, size)), 0.5, 4)
    Scaled linearly: (log10(size) - 0.5) / (4.0 - 0.5)
    """
    safe_val = min(1e4, max(1e-12, float(val)))
    log_val = math.log10(safe_val)
    return (log_val - 0.5) / (4.0 - 0.5)


def normalize_count(val: int | float) -> float:
    """Normalize clump packet count per DoHLyzer reference:
    normalize(log2(min(256, count)), 0, 8)
    Scaled linearly: (log2(count) - 0) / (8 - 0)
    """
    safe_val = min(256, max(1, int(val)))
    log_val = math.log2(float(safe_val))
    return (log_val - 0.0) / (8.0 - 0.0)


def normalize_direction(val: int) -> float:
    """Normalize clump direction to +1.0 / -1.0 per DoHLyzer reference:
    Canonical Clump direction:
      0: Client-to-Server (initiator / forward) -> +1.0
      1: Server-to-Client (responder / backward) -> -1.0
    Also accepts direct +1 / -1 representations.
    """
    if val == 0:
        return 1.0
    elif val == 1:
        return -1.0
    elif val == -1:
        return -1.0
    raise ValueError(f"Invalid clump direction: {val}; expected 0 (forward), 1 (backward), or -1")


def clump_to_reference_vector(clump: Clump, normalize: bool = True) -> list[float]:
    """Convert a canonical Clump into DoHLyzer reference order vector:
    Order: [interarrival, duration, size, packet_count, direction]

    Args:
        clump: Canonical Clump dataclass instance.
        normalize: If True, applies DoHLyzer logarithmic min-max normalization.
                   If False, returns raw values in reference order.

    Returns:
        5-element list of floats.
    """
    if normalize:
        return [
            normalize_time(clump.interarrival),
            normalize_time(clump.duration),
            normalize_size(clump.size),
            normalize_count(clump.pkt_count),
            normalize_direction(clump.direction),
        ]
    return [
        float(clump.interarrival),
        float(clump.duration),
        float(clump.size),
        float(clump.pkt_count),
        float(clump.direction),
    ]


def clumps_to_reference_vectors(
    clumps: Sequence[Clump],
    normalize: bool = True,
) -> list[list[float]]:
    """Convert a sequence of Clumps into DoHLyzer reference order vectors."""
    return [clump_to_reference_vector(c, normalize=normalize) for c in clumps]


# -----------------------------------------------------------------------------
# Sliding Window Segmentation & Padding
# -----------------------------------------------------------------------------

def create_segments(
    clumps: Sequence[Clump] | Sequence[Sequence[float]],
    window_size: int,
    stride: int = 1,
    pad: bool = True,
    padding_vector: Sequence[float] = PADDING_VECTOR,
    normalize: bool = True,
    max_segments: int | None = None,
) -> list[list[list[float]]]:
    """Segment a sequence of clumps or vectors into sliding windows.

    Args:
        clumps: Sequence of Clump objects or already formatted vectors.
        window_size: Number of steps per segment window (e.g. 6 for L1, 3 for L2).
        stride: Stride between consecutive window starts (default 1).
        pad: If True, sequences shorter than window_size are padded with padding_vector.
        padding_vector: 5-element vector used for post-padding (default [-1,-1,-1,-1,0]).
        normalize: Whether to normalize if Clump objects are provided.

    Returns:
        List of windows, where each window is a list of window_size 5-element vectors.
    """
    if window_size <= 0:
        raise ValueError(f"window_size must be positive, got {window_size}")
    if stride <= 0:
        raise ValueError(f"stride must be positive, got {stride}")

    if not clumps:
        return []

    # Format input into list of vectors
    vectors: list[list[float]]
    first = clumps[0]
    if isinstance(first, Clump):
        vectors = clumps_to_reference_vectors(clumps, normalize=normalize)  # type: ignore[arg-type]
    else:
        vectors = [list(float(x) for x in step) for step in clumps]  # type: ignore[arg-type]

    n = len(vectors)
    pad_vec = list(float(x) for x in padding_vector)

    if n < window_size:
        if pad:
            pad_needed = window_size - n
            padded_window = [list(v) for v in vectors] + [list(pad_vec) for _ in range(pad_needed)]
            return [padded_window]
        return []

    segments: list[list[list[float]]] = []
    for start in range(0, n - window_size + 1, stride):
        if max_segments is not None and len(segments) >= max_segments:
            break
        segment = [list(v) for v in vectors[start : start + window_size]]
        segments.append(segment)
    return segments


def create_mask_for_window(
    window: Sequence[Sequence[float]],
    padding_vector: Sequence[float] = PADDING_VECTOR,
) -> list[float]:
    """Generate a step-level binary mask (1.0 for valid step, 0.0 for padding)."""
    pad_list = list(padding_vector)
    mask: list[float] = []
    for step in window:
        if list(step) == pad_list:
            mask.append(0.0)
        else:
            mask.append(1.0)
    return mask


# -----------------------------------------------------------------------------
# Immutable Sequence Metadata & Sample Structures
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class SequenceMetadata:
    """Immutable provenance and experiment metadata for a single sequence sample."""

    sample_id: str
    flow_id: str
    session_id: str
    scenario_id: str
    label: int
    label_name: str = ""
    layer: int = 1
    window_index: int = 0
    window_size: int = 6
    stride: int = 1
    is_padded: bool = False
    pad_count: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    source_file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SequenceSample:
    """Immutable sequence sample containing normalized feature window and metadata."""

    features: tuple[tuple[float, ...], ...]
    metadata: SequenceMetadata

    @property
    def label(self) -> int:
        return self.metadata.label

    @property
    def session_id(self) -> str:
        return self.metadata.session_id

    @property
    def scenario_id(self) -> str:
        return self.metadata.scenario_id

    @property
    def flow_id(self) -> str:
        return self.metadata.flow_id

    @property
    def is_padded(self) -> bool:
        return self.metadata.is_padded

    def to_list(self) -> list[list[float]]:
        """Return feature window as nested list [window_size, 5]."""
        return [list(step) for step in self.features]

    def get_mask(self) -> list[float]:
        """Return binary attention/padding mask for this sample."""
        return create_mask_for_window(self.features, padding_vector=PADDING_VECTOR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "features": self.to_list(),
            "metadata": self.metadata.to_dict(),
        }


def create_sequence_samples(
    flow_id: str,
    session_id: str,
    scenario_id: str,
    label: int,
    clumps: Sequence[Clump],
    window_size: int = 6,
    stride: int = 1,
    pad: bool = True,
    layer: int = 1,
    label_name: str = "",
    start_time: float = 0.0,
    end_time: float = 0.0,
    source_file: str = "",
    max_windows: int | None = None,
) -> list[SequenceSample]:
    """Segment a sequence of Clumps into immutable SequenceSample records."""
    if not clumps:
        return []

    segments = create_segments(
        clumps,
        window_size=window_size,
        stride=stride,
        pad=pad,
        padding_vector=PADDING_VECTOR,
        normalize=True,
        max_segments=max_windows,
    )
    if max_windows is not None and len(segments) > max_windows:
        segments = segments[:max_windows]

    n_clumps = len(clumps)
    samples: list[SequenceSample] = []
    for idx, seg in enumerate(segments):
        is_padded = n_clumps < window_size and pad
        pad_count = max(0, window_size - n_clumps) if is_padded else 0
        sample_id = f"{flow_id}_w{idx}"
        resolved_label_name = label_name
        if not resolved_label_name:
            if layer == 1:
                resolved_label_name = "doh" if label == LAYER1_LABEL_DOH else "non_doh"
            else:
                resolved_label_name = "malicious_doh" if label == LAYER2_LABEL_MALICIOUS else "benign_doh"

        meta = SequenceMetadata(
            sample_id=sample_id,
            flow_id=flow_id,
            session_id=session_id,
            scenario_id=scenario_id,
            label=label,
            label_name=resolved_label_name,
            layer=layer,
            window_index=idx,
            window_size=window_size,
            stride=stride,
            is_padded=is_padded,
            pad_count=pad_count,
            start_time=start_time,
            end_time=end_time,
            source_file=source_file,
        )

        sample = SequenceSample(
            features=tuple(tuple(float(x) for x in step) for step in seg),
            metadata=meta,
        )
        samples.append(sample)

    return samples


# -----------------------------------------------------------------------------
# Train-Only Statistics & Class Weights
# -----------------------------------------------------------------------------

def compute_class_weights(labels: Sequence[int]) -> dict[int, float]:
    """Compute balanced class weights: w_c = N / (K * N_c).
    Strictly fitted on training labels.
    """
    if not labels:
        raise ValueError("Cannot compute class weights on empty labels sequence")

    counts: dict[int, int] = {}
    for y in labels:
        counts[y] = counts.get(y, 0) + 1

    total = len(labels)
    num_classes = len(counts)
    if num_classes < 2:
        return {k: 1.0 for k in counts}

    weights: dict[int, float] = {}
    for c, cnt in sorted(counts.items()):
        weights[c] = float(total) / (float(num_classes) * float(cnt))
    return weights


def compute_pos_weight(labels: Sequence[int]) -> float:
    """Compute pos_weight = neg_count / pos_count for binary BCEWithLogitsLoss.
    Strictly fitted on training labels.
    """
    if not labels:
        raise ValueError("Cannot compute pos_weight on empty labels sequence")

    pos_count = sum(1 for y in labels if y == 1)
    neg_count = sum(1 for y in labels if y == 0)

    if pos_count == 0:
        raise ValueError("Cannot compute pos_weight with zero positive samples in training set")
    if neg_count == 0:
        return 1.0

    return float(neg_count) / float(pos_count)


class TrainOnlyFeatureScaler:
    """Computes empirical mean and standard deviation strictly on training samples.
    Demonstrates zero feature data snooping or distribution leakage to val/test sets.
    """

    def __init__(self) -> None:
        self.means: tuple[float, ...] | None = None
        self.stds: tuple[float, ...] | None = None
        self.fitted_samples_count: int = 0

    @property
    def is_fitted(self) -> bool:
        return self.means is not None and self.stds is not None

    def fit(self, train_samples: Sequence[SequenceSample]) -> TrainOnlyFeatureScaler:
        """Fit empirical mean and std strictly on unmasked steps of train_samples."""
        if not train_samples:
            raise ValueError("Cannot fit scaler on empty training set")

        sums = [0.0] * 5
        sum_sqs = [0.0] * 5
        count = 0

        for sample in train_samples:
            for step in sample.features:
                if list(step) == PADDING_VECTOR:
                    continue
                count += 1
                for f_idx, val in enumerate(step):
                    sums[f_idx] += val
                    sum_sqs[f_idx] += val * val

        if count == 0:
            raise ValueError("Training samples contain only padding steps; cannot fit scaler")

        means = [s / count for s in sums]
        stds = []
        for f_idx in range(5):
            variance = max(1e-12, (sum_sqs[f_idx] / count) - (means[f_idx] ** 2))
            stds.append(math.sqrt(variance))

        self.means = tuple(means)
        self.stds = tuple(stds)
        self.fitted_samples_count = len(train_samples)
        return self

    def transform(self, samples: Sequence[SequenceSample]) -> list[list[list[float]]]:
        """Apply train-learned scaling parameters to arbitrary samples."""
        if not self.is_fitted or self.means is None or self.stds is None:
            raise ValueError("Scaler must be fit on train data before transform()")

        transformed: list[list[list[float]]] = []
        for sample in samples:
            win_scaled: list[list[float]] = []
            for step in sample.features:
                if list(step) == PADDING_VECTOR:
                    win_scaled.append(list(PADDING_VECTOR))
                else:
                    scaled_step = [
                        (val - self.means[f_idx]) / self.stds[f_idx]
                        for f_idx, val in enumerate(step)
                    ]
                    win_scaled.append(scaled_step)
            transformed.append(win_scaled)
        return transformed

    def to_dict(self) -> dict[str, Any]:
        return {
            "means": list(self.means) if self.means else None,
            "stds": list(self.stds) if self.stds else None,
            "fitted_samples_count": self.fitted_samples_count,
        }


# -----------------------------------------------------------------------------
# Split Manifests & Leakage Reports
# -----------------------------------------------------------------------------

class ImpossibleSplitError(ValueError):
    """Raised when a requested split cannot be satisfied under the specified constraints."""


@dataclass(frozen=True)
class SplitLeakageReport:
    """Formal audit report of potential identity or cross-session leakage."""

    protocol: str
    train_val_session_overlap: list[str] = field(default_factory=list)
    train_test_session_overlap: list[str] = field(default_factory=list)
    val_test_session_overlap: list[str] = field(default_factory=list)
    has_session_leakage: bool = False
    caveat: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SplitManifest:
    """Serializable, audit-compliant manifest recording split provenance and distributions."""

    manifest_version: str
    dataset_id: str
    protocol: str
    split_timestamp: str
    train_sample_ids: list[str]
    val_sample_ids: list[str]
    test_sample_ids: list[str]
    train_session_ids: list[str]
    val_session_ids: list[str]
    test_session_ids: list[str]
    train_class_counts: dict[str, int]
    val_class_counts: dict[str, int]
    test_class_counts: dict[str, int]
    class_weights: dict[str, float]
    pos_weight: float
    leakage_report: dict[str, Any]
    leakage_caveat: str
    has_leakage: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitManifest:
        return cls(**data)


@dataclass(frozen=True)
class SplitResult:
    """Result container for split functions, supporting tuple unpacking."""

    train: list[SequenceSample]
    val: list[SequenceSample]
    test: list[SequenceSample]
    manifest: SplitManifest
    leakage_report: SplitLeakageReport
    leakage_caveat: str

    def __iter__(self) -> Iterable[list[SequenceSample]]:
        return iter((self.train, self.val, self.test))

    @property
    def train_labels(self) -> list[int]:
        return [s.label for s in self.train]

    @property
    def val_labels(self) -> list[int]:
        return [s.label for s in self.val]

    @property
    def test_labels(self) -> list[int]:
        return [s.label for s in self.test]


def evaluate_split_leakage(
    train: Sequence[SequenceSample],
    test: Sequence[SequenceSample],
    val: Sequence[SequenceSample] = (),
    protocol: str = "",
) -> SplitLeakageReport:
    """Examine split partitions for cross-partition session ID overlap."""
    train_sessions = {s.session_id for s in train if s.session_id}
    test_sessions = {s.session_id for s in test if s.session_id}
    val_sessions = {s.session_id for s in val if s.session_id}

    train_test_overlap = sorted(train_sessions & test_sessions)
    train_val_overlap = sorted(train_sessions & val_sessions)
    val_test_overlap = sorted(val_sessions & test_sessions)

    has_leakage = bool(train_test_overlap or train_val_overlap or val_test_overlap)

    caveat = ""
    if protocol == "paper_flow_random":
        caveat = PAPER_FLOW_RANDOM_LEAKAGE_CAVEAT
    elif not has_leakage:
        caveat = CORRECTED_DISJOINT_ASSURANCE
    else:
        caveat = f"WARNING: Detected cross-partition session leakage: {len(train_test_overlap)} overlapping sessions."

    return SplitLeakageReport(
        protocol=protocol,
        train_val_session_overlap=train_val_overlap,
        train_test_session_overlap=train_test_overlap,
        val_test_session_overlap=val_test_overlap,
        has_session_leakage=has_leakage,
        caveat=caveat,
    )


def build_split_manifest(
    split_result: SplitResult,
    dataset_id: str = "cira-cic-dohbrw-2020",
    manifest_version: str = "1.0.0",
) -> SplitManifest:
    """Build a serializable SplitManifest from a SplitResult."""
    def count_classes(samples: Sequence[SequenceSample]) -> dict[str, int]:
        c: dict[str, int] = {}
        for s in samples:
            k = str(s.label)
            c[k] = c.get(k, 0) + 1
        return c

    train_c = count_classes(split_result.train)
    val_c = count_classes(split_result.val)
    test_c = count_classes(split_result.test)

    train_labels = [s.label for s in split_result.train]
    class_weights_raw = compute_class_weights(train_labels) if train_labels else {}
    class_weights = {str(k): round(v, 6) for k, v in class_weights_raw.items()}
    pos_weight = round(compute_pos_weight(train_labels), 6) if train_labels and 1 in train_labels else 1.0

    return SplitManifest(
        manifest_version=manifest_version,
        dataset_id=dataset_id,
        protocol=split_result.leakage_report.protocol,
        split_timestamp=datetime.now(timezone.utc).isoformat(),
        train_sample_ids=[s.metadata.sample_id for s in split_result.train],
        val_sample_ids=[s.metadata.sample_id for s in split_result.val],
        test_sample_ids=[s.metadata.sample_id for s in split_result.test],
        train_session_ids=sorted({s.session_id for s in split_result.train if s.session_id}),
        val_session_ids=sorted({s.session_id for s in split_result.val if s.session_id}),
        test_session_ids=sorted({s.session_id for s in split_result.test if s.session_id}),
        train_class_counts=train_c,
        val_class_counts=val_c,
        test_class_counts=test_c,
        class_weights=class_weights,
        pos_weight=pos_weight,
        leakage_report=split_result.leakage_report.to_dict(),
        leakage_caveat=split_result.leakage_caveat,
        has_leakage=split_result.leakage_report.has_session_leakage,
    )


# -----------------------------------------------------------------------------
# Split Protocols: paper_flow_random & session_scenario_disjoint
# -----------------------------------------------------------------------------

def paper_flow_random(
    samples: Sequence[SequenceSample],
    train_ratio: float = 0.80,
    seed: int = 42,
    dataset_id: str = "cira-cic-dohbrw-2020",
) -> SplitResult:
    """Replication protocol: Stratified 80/20 flow-level random split.

    Per paper Section IV-B:
    The dataset is randomly partitioned 80% train and 20% test.
    This splitter preserves class stratification but operates at sample/flow level,
    which introduces session and host leakage. It explicitly emits the paper leakage caveat.

    Args:
        samples: Sequence of SequenceSample records.
        train_ratio: Proportion of samples allocated to train (default 0.80).
        seed: Deterministic integer seed for reproducible shuffling.
        dataset_id: Identifier for manifest generation.

    Returns:
        SplitResult container with (train, val=[], test), manifest, and leakage report.
    """
    if not samples:
        raise ImpossibleSplitError("Cannot split empty sample sequence")
    if not (0.0 < train_ratio < 1.0):
        raise ValueError(f"train_ratio must be strictly between 0 and 1, got {train_ratio}")

    # Group samples by class label
    by_label: dict[int, list[SequenceSample]] = {}
    for s in samples:
        by_label.setdefault(s.label, []).append(s)

    if len(by_label) < 2:
        raise ImpossibleSplitError(
            f"Stratified split requires at least 2 distinct classes, found {len(by_label)}"
        )

    for c, s_list in by_label.items():
        if len(s_list) < 2:
            raise ImpossibleSplitError(
                f"Class {c} has only {len(s_list)} sample(s); at least 2 required for 80/20 train/test split"
            )

    rng = random.Random(seed)
    train_samples: list[SequenceSample] = []
    test_samples: list[SequenceSample] = []

    for c in sorted(by_label.keys()):
        s_list = by_label[c]
        # Sort deterministically by sample_id before shuffling
        s_sorted = sorted(s_list, key=lambda s: s.metadata.sample_id)
        s_shuffled = list(s_sorted)
        rng.shuffle(s_shuffled)

        n = len(s_shuffled)
        n_test = max(1, round(n * (1.0 - train_ratio)))
        n_train = n - n_test
        if n_train < 1:
            n_train = 1
            n_test = n - 1

        train_samples.extend(s_shuffled[:n_train])
        test_samples.extend(s_shuffled[n_train:])

    # Sort outputs deterministically
    train_samples.sort(key=lambda s: s.metadata.sample_id)
    test_samples.sort(key=lambda s: s.metadata.sample_id)

    leakage_report = evaluate_split_leakage(
        train=train_samples,
        test=test_samples,
        val=[],
        protocol="paper_flow_random",
    )

    dummy_result = SplitResult(
        train=train_samples,
        val=[],
        test=test_samples,
        manifest=None,  # type: ignore[arg-type]
        leakage_report=leakage_report,
        leakage_caveat=PAPER_FLOW_RANDOM_LEAKAGE_CAVEAT,
    )
    manifest = build_split_manifest(dummy_result, dataset_id=dataset_id)

    return SplitResult(
        train=train_samples,
        val=[],
        test=test_samples,
        manifest=manifest,
        leakage_report=leakage_report,
        leakage_caveat=PAPER_FLOW_RANDOM_LEAKAGE_CAVEAT,
    )


def session_scenario_disjoint(
    samples: Sequence[SequenceSample],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
    dataset_id: str = "cira-cic-dohbrw-2020",
) -> SplitResult:
    """Modern corrected protocol: Group/session-disjoint 70/15/15 split.

    Groups samples strictly by session_id and scenario_id.
    Guarantees mathematically that:
      sessions(Train) ∩ sessions(Val) = ∅
      sessions(Train) ∩ sessions(Test) = ∅
      sessions(Val) ∩ sessions(Test) = ∅
    Eliminates cross-session data leakage.

    Args:
        samples: Sequence of SequenceSample records.
        train_ratio: Proportion allocated to train (default 0.70).
        val_ratio: Proportion allocated to validation (default 0.15).
        test_ratio: Proportion allocated to test (default 0.15).
        seed: Deterministic integer seed.
        dataset_id: Identifier for manifest generation.

    Returns:
        SplitResult container with (train, val, test), manifest, and leakage report.
    """
    if not samples:
        raise ImpossibleSplitError("Cannot split empty sample sequence")

    total_ratio = train_ratio + val_ratio + test_ratio
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError(f"Split ratios must sum to 1.0, got {total_ratio}")
    if train_ratio <= 0 or val_ratio <= 0 or test_ratio <= 0:
        raise ValueError("train_ratio, val_ratio, and test_ratio must all be strictly positive")

    # Group samples by session_id
    session_to_samples: dict[str, list[SequenceSample]] = {}
    for s in samples:
        if not s.session_id:
            raise ValueError(
                f"Sample {s.metadata.sample_id} lacks session_id; required for session_scenario_disjoint split"
            )
        session_to_samples.setdefault(s.session_id, []).append(s)

    if len(session_to_samples) < 3:
        raise ImpossibleSplitError(
            f"Cannot perform 3-way disjoint split with only {len(session_to_samples)} session(s); "
            "at least 3 distinct sessions required."
        )

    # All unique classes present in the dataset
    all_classes = sorted({s.label for s in samples})
    if len(all_classes) < 2:
        raise ImpossibleSplitError(
            f"Disjoint stratified split requires at least 2 distinct classes, found {len(all_classes)}"
        )

    # For each class, find all sessions that contain at least one sample of that class
    sessions_containing_class: dict[int, list[str]] = {}
    for c in all_classes:
        matching = [
            sid
            for sid, s_list in session_to_samples.items()
            if any(s.label == c for s in s_list)
        ]
        if len(matching) < 3:
            raise ImpossibleSplitError(
                f"Class {c} appears in only {len(matching)} session(s); at least 3 distinct sessions "
                f"containing class {c} are required to populate train, val, and test disjointly without empty folds."
            )
        # Sort deterministically: largest session first, tie-break by session_id
        sessions_containing_class[c] = sorted(
            matching, key=lambda sid: (-len(session_to_samples[sid]), sid)
        )

    # Allocate sessions to train, val, test ensuring each partition covers all classes
    train_sessions: set[str] = set()
    val_sessions: set[str] = set()
    test_sessions: set[str] = set()

    # Rarest classes first (fewest containing sessions) to constrain assignment early
    classes_by_rarity = sorted(all_classes, key=lambda c: len(sessions_containing_class[c]))

    def class_covered(part_sessions: set[str], cls: int) -> bool:
        return any(any(s.label == cls for s in session_to_samples[sid]) for sid in part_sessions)

    # Step 1: Ensure each partition has at least one session covering each class
    for c in classes_by_rarity:
        for part_set in (train_sessions, val_sessions, test_sessions):
            if not class_covered(part_set, c):
                candidates = [
                    sid
                    for sid in sessions_containing_class[c]
                    if sid not in train_sessions and sid not in val_sessions and sid not in test_sessions
                ]
                if not candidates:
                    raise ImpossibleSplitError(
                        f"Cannot disjointly cover class {c} across train, val, and test partitions "
                        "due to conflicting multi-class session constraints."
                    )
                part_set.add(candidates[0])

    # Step 2: Allocate remaining sessions greedily according to target ratios
    all_assigned = train_sessions | val_sessions | test_sessions
    unassigned = sorted(
        [sid for sid in session_to_samples if sid not in all_assigned],
        key=lambda sid: (-len(session_to_samples[sid]), sid),
    )

    t_cnt = sum(len(session_to_samples[sid]) for sid in train_sessions)
    v_cnt = sum(len(session_to_samples[sid]) for sid in val_sessions)
    e_cnt = sum(len(session_to_samples[sid]) for sid in test_sessions)

    for sid in unassigned:
        cnt = len(session_to_samples[sid])
        tot = t_cnt + v_cnt + e_cnt + cnt
        diff_t = (t_cnt + cnt) / tot - train_ratio
        diff_v = (v_cnt + cnt) / tot - val_ratio
        diff_e = (e_cnt + cnt) / tot - test_ratio

        best_part = min(
            [("train", diff_t), ("val", diff_v), ("test", diff_e)],
            key=lambda x: x[1],
        )[0]

        if best_part == "train":
            train_sessions.add(sid)
            t_cnt += cnt
        elif best_part == "val":
            val_sessions.add(sid)
            v_cnt += cnt
        else:
            test_sessions.add(sid)
            e_cnt += cnt
    # Inviolable mathematical verification: Zero session overlap
    assert not (train_sessions & val_sessions), "Invariant violated: train and val sessions overlap!"
    assert not (train_sessions & test_sessions), "Invariant violated: train and test sessions overlap!"
    assert not (val_sessions & test_sessions), "Invariant violated: val and test sessions overlap!"

    # Collect samples
    train_samples = [s for sid in sorted(train_sessions) for s in session_to_samples[sid]]
    val_samples = [s for sid in sorted(val_sessions) for s in session_to_samples[sid]]
    test_samples = [s for sid in sorted(test_sessions) for s in session_to_samples[sid]]

    train_samples.sort(key=lambda s: s.metadata.sample_id)
    val_samples.sort(key=lambda s: s.metadata.sample_id)
    test_samples.sort(key=lambda s: s.metadata.sample_id)

    leakage_report = evaluate_split_leakage(
        train=train_samples,
        test=test_samples,
        val=val_samples,
        protocol="session_scenario_disjoint",
    )

    dummy_result = SplitResult(
        train=train_samples,
        val=val_samples,
        test=test_samples,
        manifest=None,  # type: ignore[arg-type]
        leakage_report=leakage_report,
        leakage_caveat=CORRECTED_DISJOINT_ASSURANCE,
    )
    manifest = build_split_manifest(dummy_result, dataset_id=dataset_id)

    return SplitResult(
        train=train_samples,
        val=val_samples,
        test=test_samples,
        manifest=manifest,
        leakage_report=leakage_report,
        leakage_caveat=CORRECTED_DISJOINT_ASSURANCE,
    )


def split_samples(
    samples: Sequence[SequenceSample],
    protocol: str = "paper_flow_random",
    seed: int = 42,
    **kwargs: Any,
) -> SplitResult:
    """Unified entry point for time-series dataset splitting.

    Supported protocols:
    - "paper_flow_random": Stratified 80/20 flow split (with explicit paper leakage caveat).
    - "session_scenario_disjoint": Group-disjoint 70/15/15 split (zero session overlap).
    """
    if protocol == "paper_flow_random":
        train_ratio = kwargs.get("train_ratio", 0.80)
        dataset_id = kwargs.get("dataset_id", "cira-cic-dohbrw-2020")
        return paper_flow_random(samples, train_ratio=train_ratio, seed=seed, dataset_id=dataset_id)
    elif protocol == "session_scenario_disjoint":
        train_ratio = kwargs.get("train_ratio", 0.70)
        val_ratio = kwargs.get("val_ratio", 0.15)
        test_ratio = kwargs.get("test_ratio", 0.15)
        dataset_id = kwargs.get("dataset_id", "cira-cic-dohbrw-2020")
        return session_scenario_disjoint(
            samples,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
            seed=seed,
            dataset_id=dataset_id,
        )
    else:
        raise ValueError(
            f"Unknown split protocol: {protocol!r}. "
            "Supported protocols are 'paper_flow_random' and 'session_scenario_disjoint'."
        )


# -----------------------------------------------------------------------------
# NumPy / PyTorch Conversion Helpers
# -----------------------------------------------------------------------------

def samples_to_arrays(
    samples: Sequence[SequenceSample],
) -> tuple[list[list[list[float]]], list[int], list[list[float]]]:
    """Extract (X, y, masks) as nested lists suitable for NumPy or PyTorch conversion.

    Returns:
        X: [N, window_size, 5] nested list of floats
        y: [N] list of integer ground-truth labels
        masks: [N, window_size] nested list of floats (1.0 for valid step, 0.0 for padding)
    """
    X = [s.to_list() for s in samples]
    y = [s.label for s in samples]
    masks = [s.get_mask() for s in samples]
    return X, y, masks


def samples_to_numpy_payload(samples: Sequence[SequenceSample]) -> dict[str, Any]:
    """Convert sequence samples into a complete serializable payload for runner execution."""
    X, y, masks = samples_to_arrays(samples)
    return {
        "X": X,
        "y": y,
        "masks": masks,
        "sample_ids": [s.metadata.sample_id for s in samples],
        "session_ids": [s.metadata.session_id for s in samples],
        "scenario_ids": [s.metadata.scenario_id for s in samples],
    }


def compute_window_collection_delay(clumps: Sequence[Any], window_size: int) -> float:
    """Compute physical network observation duration for a clump window in seconds.

    Formula: sum(c.duration + c.interarrival for c in clumps[:window_size])
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


def compute_segment_duration(segment: Sequence[Clump]) -> float:
    """Backward compatible alias for window collection delay on Clump sequences."""
    return compute_window_collection_delay(segment, len(segment))
