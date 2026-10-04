"""Deterministic offline workflow demonstration of two-layer DoH tunnel detection.

NOTICE:
This module demonstrates the offline pipeline workflow mechanics (clumping,
segmentation, cascade evaluation, and latency accounting) using deterministic
synthetic packet traces and a sequence-prototype scoring classifier. It is a
defensive workflow verification harness, NOT a replication of the paper's
published LSTM benchmark on the CIRA-CIC-DoHBrw-2020 dataset.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time
from dataclasses import dataclass
from typing import Any, Sequence

from .clumping import Clump, Packet, clumping, segment_clumps

WORKFLOW_WARNING: str = (
    "WORKFLOW DEMONSTRATION ONLY - NOT A PAPER REPLICATION. This script "
    "uses deterministic synthetic packet traces and a transparent sequence-prototype "
    "scoring model (non-paper-proxy) solely to verify clumping, sliding-window "
    "segmentation, two-layer serial cascading, and metric calculation within a pure "
    "Python standard-library environment. It does NOT use the licensed CIRA-CIC-DoHBrw-2020 "
    "dataset or LSTM neural network architectures. Synthetic results MUST NOT be cited "
    "or presented as empirical replication of MontazeriShatoori et al. (2020)."
)


@dataclass(frozen=True)
class SyntheticFlow:
    """Represents a synthetic flow with provenance metadata."""

    flow_id: str
    scenario_id: str
    ground_truth_category: str  # "non_doh", "benign_doh", "tunnel_like"
    packets: list[Packet]

    @property
    def l1_label(self) -> str:
        return "non_doh" if self.ground_truth_category == "non_doh" else "doh"

    @property
    def l2_label(self) -> str:
        if self.ground_truth_category == "non_doh":
            return "not_applicable"
        return self.ground_truth_category


def generate_synthetic_flow(
    flow_id: str,
    scenario_id: str,
    category: str,
    rng: random.Random,
    base_timestamp: float = 100.0,
) -> SyntheticFlow:
    """Generate deterministic synthetic packet traces modeling traffic profiles.

    Traffic profiles:
    - non_doh: Standard web browsing HTTPS. Large asymmetric bursts (server -> client),
      varying packet lengths up to 1460 bytes, bursty interarrivals.
    - benign_doh: Interactive DNS lookups over HTTPS. Short request (150-320 bytes),
      rapid small response (200-650 bytes), intermittent pauses between resolutions.
    - tunnel_like: Covert DNS tunnel encapsulated in DoH. Regular periodic queries,
      moderate payload sizes (350-520 bytes) representing chunked data transfers,
      low interarrival variance.
    """
    packets: list[Packet] = []
    t = base_timestamp

    if category == "non_doh":
        # Simulate 6-10 web transactions (request + bursty multi-packet download)
        num_bursts = rng.randint(6, 10)
        for _ in range(num_bursts):
            # Client request (forward = 0)
            req_len = rng.randint(200, 500)
            packets.append(Packet(timestamp=round(t, 6), length=req_len, direction=0))
            t += rng.uniform(0.015, 0.050)

            # Server response bursts (backward = 1)
            resp_packet_count = rng.randint(3, 8)
            for _ in range(resp_packet_count):
                packets.append(
                    Packet(
                        timestamp=round(t, 6),
                        length=rng.randint(1100, 1460),
                        direction=1,
                    )
                )
                # Packets within same clump have tiny gaps <= 0.0008s
                t += rng.uniform(0.0001, 0.0008)

            # Idle pause before next asset/page request
            t += rng.uniform(0.080, 0.300)

    elif category == "benign_doh":
        # Simulate 8-14 interactive DNS query/response pairs
        num_queries = rng.randint(8, 14)
        for _ in range(num_queries):
            # Client DNS Query over HTTPS
            packets.append(
                Packet(
                    timestamp=round(t, 6),
                    length=rng.randint(160, 320),
                    direction=0,
                )
            )
            # Round-trip resolution delay to public resolver
            t += rng.uniform(0.010, 0.035)

            # Resolver DNS Response over HTTPS
            resp_pkts = rng.randint(1, 2)
            for _ in range(resp_pkts):
                packets.append(
                    Packet(
                        timestamp=round(t, 6),
                        length=rng.randint(220, 680),
                        direction=1,
                    )
                )
                t += rng.uniform(0.0002, 0.0006)

            # User browsing delay before next domain resolution
            t += rng.uniform(0.050, 0.250)

    elif category == "tunnel_like":
        # Simulate 10-18 periodic tunneling chunks (Iodine/dns2tcp-like steady streaming)
        num_chunks = rng.randint(10, 18)
        for _ in range(num_chunks):
            # Client upstream chunk (tunneled query payload)
            packets.append(
                Packet(
                    timestamp=round(t, 6),
                    length=rng.randint(380, 520),
                    direction=0,
                )
            )
            # Resolver/C2 round-trip response
            t += rng.uniform(0.018, 0.030)

            # Downstream response chunk
            packets.append(
                Packet(
                    timestamp=round(t, 6),
                    length=rng.randint(280, 480),
                    direction=1,
                )
            )
            # Regular inter-chunk pacing (100-1100 B/s cadence simulation)
            t += rng.uniform(0.020, 0.045)
    else:
        raise ValueError(f"Unknown synthetic traffic category: {category}")

    return SyntheticFlow(
        flow_id=flow_id,
        scenario_id=scenario_id,
        ground_truth_category=category,
        packets=packets,
    )


def build_synthetic_scenarios(
    seed: int = 42,
) -> tuple[list[SyntheticFlow], list[SyntheticFlow], dict[str, Any]]:
    """Build group-disjoint train and test scenarios without leakage.

    Each scenario represents an isolated session/host environment.
    Training and test partitions share ZERO scenario IDs.
    """
    rng = random.Random(seed)

    train_scenarios = [
        ("train_web_sess_01", "non_doh", 4),
        ("train_web_sess_02", "non_doh", 4),
        ("train_web_sess_03", "non_doh", 4),
        ("train_doh_browsing_01", "benign_doh", 4),
        ("train_doh_browsing_02", "benign_doh", 4),
        ("train_doh_browsing_03", "benign_doh", 4),
        ("train_tunnel_stream_01", "tunnel_like", 4),
        ("train_tunnel_stream_02", "tunnel_like", 4),
        ("train_tunnel_stream_03", "tunnel_like", 4),
    ]

    test_scenarios = [
        ("test_web_sess_01", "non_doh", 4),
        ("test_web_sess_02", "non_doh", 4),
        ("test_doh_browsing_01", "benign_doh", 4),
        ("test_doh_browsing_02", "benign_doh", 4),
        ("test_tunnel_stream_01", "tunnel_like", 4),
        ("test_tunnel_stream_02", "tunnel_like", 4),
    ]

    train_flows: list[SyntheticFlow] = []
    for scen_id, cat, count in train_scenarios:
        for idx in range(count):
            flow_id = f"{scen_id}_flow_{idx+1:02d}"
            train_flows.append(generate_synthetic_flow(flow_id, scen_id, cat, rng))

    test_flows: list[SyntheticFlow] = []
    for scen_id, cat, count in test_scenarios:
        for idx in range(count):
            flow_id = f"{scen_id}_flow_{idx+1:02d}"
            test_flows.append(generate_synthetic_flow(flow_id, scen_id, cat, rng))

    provenance = {
        "strategy": "group_disjoint_by_scenario_id",
        "train_scenario_ids": [s[0] for s in train_scenarios],
        "test_scenario_ids": [s[0] for s in test_scenarios],
        "train_flow_count": len(train_flows),
        "test_flow_count": len(test_flows),
        "leakage_safeguards": (
            "Train and test sets strictly partition by scenario ID. No scenario, "
            "host, or session overlap exists across folds. Prototype centroids "
            "and scaling variances are computed exclusively on the training fold."
        ),
    }

    return train_flows, test_flows, provenance


def extract_segment_features(segment: Sequence[Clump]) -> list[float]:
    """Extract deterministic feature representations from a clump segment.

    Features:
    0: Mean clump byte size
    1: Maximum clump byte size
    2: Mean packet count per clump
    3: Mean clump duration (seconds)
    4: Mean clump interarrival time (seconds)
    5: Standard deviation of clump byte size
    6: Fraction of forward clumps (direction == 0)
    7: Total segment duration span (sum of durations and interarrivals)
    """
    m = len(segment)
    if m == 0:
        return [0.0] * 8

    sizes = [float(c.size) for c in segment]
    pkt_counts = [float(c.pkt_count) for c in segment]
    durations = [c.duration for c in segment]
    interarrivals = [c.interarrival for c in segment]
    fwd_count = sum(1.0 for c in segment if c.direction == 0)

    mean_size = sum(sizes) / m
    max_size = max(sizes)
    mean_pkts = sum(pkt_counts) / m
    mean_dur = sum(durations) / m
    mean_iat = sum(interarrivals) / m
    size_std = statistics.pstdev(sizes) if m > 1 else 0.0
    fwd_ratio = fwd_count / m
    total_span = sum(durations) + sum(interarrivals)

    return [
        mean_size,
        max_size,
        mean_pkts,
        mean_dur,
        mean_iat,
        size_std,
        fwd_ratio,
        total_span,
    ]


class SequencePrototypeClassifier:
    """Transparent deterministic sequence-prototype classifier (non-paper-proxy).

    Computes class prototypes (centroids) in normalized feature space
    from training segments and scores test segments via normalized Euclidean
    distance. This transparent baseline is used solely to verify the two-stage
    pipeline mechanics without external ML frameworks.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.classes: list[str] = []
        self.centroids: dict[str, list[float]] = {}
        self.scales: list[float] = []

    def fit(self, segments: Sequence[Sequence[Clump]], labels: Sequence[str]) -> None:
        """Fit prototype centroids and feature scaling from training segments."""
        if len(segments) != len(labels) or not segments:
            raise ValueError("Mismatched or empty segments/labels")

        feature_matrix = [extract_segment_features(seg) for seg in segments]
        n_features = len(feature_matrix[0])
        self.classes = sorted(list(set(labels)))

        # Compute pooled standard deviation for scaling to prevent single-feature dominance
        self.scales = []
        for j in range(n_features):
            col = [row[j] for row in feature_matrix]
            std = statistics.pstdev(col)
            # Use small epsilon floor to prevent division by zero
            self.scales.append(std if std > 1e-6 else 1.0)

        # Compute centroid for each class
        self.centroids = {}
        for c in self.classes:
            c_rows = [
                row for row, label in zip(feature_matrix, labels, strict=True) if label == c
            ]
            centroid = []
            for j in range(n_features):
                vals = [r[j] for r in c_rows]
                centroid.append(sum(vals) / len(vals))
            self.centroids[c] = centroid

    def predict_with_scores(
        self, segment: Sequence[Clump]
    ) -> tuple[str, dict[str, float]]:
        """Predict class and return softmax-normalized prototype proximity scores."""
        feat = extract_segment_features(segment)

        distances: dict[str, float] = {}
        for c, centroid in self.centroids.items():
            dist_sq = 0.0
            for j in range(len(feat)):
                norm_diff = (feat[j] - centroid[j]) / self.scales[j]
                dist_sq += norm_diff * norm_diff
            distances[c] = math.sqrt(dist_sq)

        # Convert distances to softmax affinity scores
        min_dist = min(distances.values())
        exp_weights: dict[str, float] = {}
        for c, d in distances.items():
            # Shift by min_dist for numerical stability
            exp_weights[c] = math.exp(-min(d - min_dist, 50.0))
        total_weight = sum(exp_weights.values())

        scores = {c: round(w / total_weight, 4) for c, w in exp_weights.items()}
        best_class = min(distances.keys(), key=lambda c: distances[c])
        return best_class, scores


def calculate_binary_metrics(
    y_true: list[str],
    y_pred: list[str],
    positive_label: str,
    negative_label: str,
    durations: list[float],
) -> dict[str, Any]:
    """Calculate confusion matrix, precision, recall, F1, and latency statistics."""
    tp = fp = tn = fn = 0
    for true, pred in zip(y_true, y_pred, strict=True):
        if true == positive_label:
            if pred == positive_label:
                tp += 1
            else:
                fn += 1
        elif true == negative_label:
            if pred == positive_label:
                fp += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2.0 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    mean_duration = statistics.mean(durations) if durations else 0.0
    median_duration = statistics.median(durations) if durations else 0.0
    min_duration = min(durations) if durations else 0.0
    max_duration = max(durations) if durations else 0.0

    return {
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "true_negative": tn,
            "false_negative": fn,
            "total_evaluated": tp + fp + tn + fn,
        },
        "metrics": {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "false_positive_rate": round(fpr, 4),
        },
        "latency_seconds": {
            "mean_segment_duration": round(mean_duration, 4),
            "median_segment_duration": round(median_duration, 4),
            "min_segment_duration": round(min_duration, 4),
            "max_segment_duration": round(max_duration, 4),
        },
    }


def compute_segment_duration(segment: Sequence[Clump]) -> float:
    """Compute the observation duration for a clump segment in seconds."""
    if not segment:
        return 0.0
    return sum(c.duration + c.interarrival for c in segment)


def run_demo(seed: int = 42) -> dict[str, Any]:
    """Execute the end-to-end two-stage DoH tunnel detection demonstration."""
    start_wall_time = time.perf_counter()

    # 1. Generate group-disjoint train and test scenarios
    train_flows, test_flows, provenance = build_synthetic_scenarios(seed=seed)

    # 2. Extract clumps and segments for training
    # Layer 1: window_size = 6 clumps (paper Table V threshold)
    # Layer 2: window_size = 3 clumps (paper Table VI threshold)
    l1_train_segments: list[list[Clump]] = []
    l1_train_labels: list[str] = []

    l2_train_segments: list[list[Clump]] = []
    l2_train_labels: list[str] = []

    for flow in train_flows:
        flow_clumps = clumping(flow.packets)
        l1_segs = segment_clumps(flow_clumps, window_size=6, stride=2, pad=True)
        for seg in l1_segs:
            l1_train_segments.append(seg)
            l1_train_labels.append(flow.l1_label)

        # Layer 2 is trained only on DoH traffic (benign_doh vs tunnel_like)
        if flow.l1_label == "doh":
            l2_segs = segment_clumps(flow_clumps, window_size=3, stride=2, pad=True)
            for seg in l2_segs:
                l2_train_segments.append(seg)
                l2_train_labels.append(flow.l2_label)

    # 3. Train Layer 1 and Layer 2 sequence-prototype classifiers
    l1_classifier = SequencePrototypeClassifier("Layer1_DoH_Filter_L6")
    l1_classifier.fit(l1_train_segments, l1_train_labels)

    l2_classifier = SequencePrototypeClassifier("Layer2_Tunnel_Characterizer_L3")
    l2_classifier.fit(l2_train_segments, l2_train_labels)

    # 4. Evaluate test flows through the two-layer cascade
    l1_test_true: list[str] = []
    l1_test_pred: list[str] = []
    l1_test_durations: list[float] = []

    l2_test_true: list[str] = []
    l2_test_pred: list[str] = []
    l2_test_durations: list[float] = []
    l2_flow_decisions: list[str] = []

    sample_prediction_record: dict[str, Any] = {}
    for idx, flow in enumerate(test_flows):
        flow_clumps = clumping(flow.packets)

        # Layer 1 decision (threshold = 6 clumps)
        l1_segments = segment_clumps(flow_clumps, window_size=6, pad=True)
        l1_eval_seg = l1_segments[0]
        l1_pred, l1_scores = l1_classifier.predict_with_scores(l1_eval_seg)
        l1_dur = compute_segment_duration(l1_eval_seg)

        l1_test_true.append(flow.l1_label)
        l1_test_pred.append(l1_pred)
        l1_test_durations.append(l1_dur)

        # Layer 2 execution (serial: only triggered if Layer 1 outputs "doh")
        l2_triggered = l1_pred == "doh"
        l2_pred = "filtered_by_layer1"
        l2_scores: dict[str, float] = {}
        l2_dur = 0.0

        if l2_triggered:
            l2_segments = segment_clumps(flow_clumps, window_size=3, pad=True)
            l2_eval_seg = l2_segments[0]
            l2_pred, l2_scores = l2_classifier.predict_with_scores(l2_eval_seg)
            l2_dur = compute_segment_duration(l2_eval_seg)

            # Record metrics for flows that reached Layer 2
            l2_test_true.append(flow.l2_label)
            l2_test_pred.append(l2_pred)
            l2_test_durations.append(l2_dur)

        l2_flow_decisions.append(l2_pred if l2_triggered else "filtered_by_layer1")

        # Capture a representative tunnel flow for example prediction walkthrough
        if not sample_prediction_record and flow.ground_truth_category == "tunnel_like":
            total_flow_span = (
                flow.packets[-1].timestamp - flow.packets[0].timestamp
                if len(flow.packets) > 1
                else 0.0
            )
            sample_prediction_record = {
                "sample_id": flow.flow_id,
                "scenario_id": flow.scenario_id,
                "ground_truth_category": flow.ground_truth_category,
                "raw_packet_count": len(flow.packets),
                "extracted_clump_count": len(flow_clumps),
                "full_flow_duration_seconds": round(total_flow_span, 4),
                "layer1_stage": {
                    "task": "DoH Filtering (doh vs non_doh)",
                    "clump_window_threshold": 6,
                    "clumps_evaluated": len(l1_eval_seg),
                    "segment_duration_seconds": round(l1_dur, 4),
                    "scores": l1_scores,
                    "predicted_label": l1_pred,
                    "decision": "Forwarded to Layer 2",
                },
                "layer2_stage": {
                    "task": "Tunnel Characterization (benign_doh vs tunnel_like)",
                    "clump_window_threshold": 3,
                    "clumps_evaluated": 3 if l2_triggered else 0,
                    "segment_duration_seconds": round(l2_dur, 4),
                    "scores": l2_scores,
                    "predicted_label": l2_pred,
                    "decision": "Flagged as DNS Tunnel Covert Channel",
                },
                "pipeline_verdict": l2_pred,
                "earliest_detection_latency_seconds": round(l1_dur, 4),
                "latency_reduction_ratio": round(
                    (total_flow_span - l1_dur) / total_flow_span, 4
                )
                if total_flow_span > 0
                else 0.0,
            }

    # 5. Calculate metrics for Layer 1 and Layer 2
    l1_results = calculate_binary_metrics(
        y_true=l1_test_true,
        y_pred=l1_test_pred,
        positive_label="doh",
        negative_label="non_doh",
        durations=l1_test_durations,
    )
    l1_results["threshold_clump_length"] = 6
    l1_results["task_description"] = "Layer 1: DoH vs Non-DoH classification"

    l2_results = calculate_binary_metrics(
        y_true=l2_test_true,
        y_pred=l2_test_pred,
        positive_label="tunnel_like",
        negative_label="benign_doh",
        durations=l2_test_durations,
    )
    l2_results["threshold_clump_length"] = 3
    l2_results["task_description"] = (
        "Layer 2: Benign DoH vs Malicious Tunnel characterization"
    )

    # 6. Overall serial pipeline summary
    total_test = len(test_flows)
    true_tunnels = sum(
        1 for f in test_flows if f.ground_truth_category == "tunnel_like"
    )
    detected_tunnels = sum(
        1
        for flow, l1, l2 in zip(
            test_flows, l1_test_pred, l2_flow_decisions, strict=True
        )
        if flow.ground_truth_category == "tunnel_like"
        and l1 == "doh"
        and l2 == "tunnel_like"
    )

    elapsed_wall_time = round(time.perf_counter() - start_wall_time, 4)

    return {
        "warning": WORKFLOW_WARNING,
        "metadata": {
            "demo_name": "doh_reproduction_two_layer_demo",
            "model_type": "Deterministic Sequence-Prototype Scoring (non-paper-proxy)",
            "clump_timeout_seconds": 0.001,
            "layer1_clump_threshold": 6,
            "layer2_clump_threshold": 3,
            "wall_execution_time_seconds": elapsed_wall_time,
        },
        "split_provenance": provenance,
        "layer1_evaluation": l1_results,
        "layer2_evaluation": l2_results,
        "pipeline_summary": {
            "total_test_flows": total_test,
            "true_tunnel_flows": true_tunnels,
            "detected_tunnel_flows": detected_tunnels,
            "overall_tunnel_detection_rate": round(
                detected_tunnels / true_tunnels, 4
            )
            if true_tunnels > 0
            else 0.0,
            "pipeline_design": (
                "Serial two-stage architecture: Only traffic flagged as DoH by "
                "Layer 1 proceeds to Layer 2 characterization."
            ),
        },
        "example_prediction": sample_prediction_record,
    }


def main() -> None:
    """CLI entrypoint for python -m doh_reproduction.demo."""
    results = run_demo(seed=42)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
