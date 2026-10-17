"""Unit and behavioral tests for Phase A operational latency benchmarking.

Verifies:
1. compute_percentile: monotonicity and linear interpolation.
2. compute_distribution_summary: non-negative statistics, unit conversions, p50 <= p95 <= p99.
3. compute_window_collection_delay: exact analytical network observation durations for known clumps.
4. Deterministic first-window-per-test-flow selection and max-samples capping.
5. Paper LSTM model (PaperReferenceLSTMModel) microbenchmarking with batch size 1.
6. Improved candidate model (ImprovedMaskedBiGRUModel) mask-aware microbenchmarking.
7. CUDA device synchronization wiring when running on CUDA.
8. Aligned per-sample end-to-end component summation (T_e2e = T_collect + T_prep + T_infer).
9. Artifact emission: latency_benchmarks.json and latency_benchmarks.csv formats and schemas.
10. Backward compatible config validation and conservative defaults.
11. Audit mode skips model benchmarking even when enable_latency_benchmark is True.
12. End-to-end pipeline integration on tiny synthetic run emitting both latency artifacts.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
SRC_DIR = REPO_ROOT / "src"
RUNNER_DIR = REPO_ROOT / "experiments" / "kaggle" / "timeseries_clump_lstm"

for p in [str(RUNNER_DIR), str(SRC_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import train_timeseries as runner
from doh_reproduction.clumping import Clump
from doh_reproduction.comparison import validate_timeseries_metrics_schema
from doh_reproduction.operational_latency import (
    LATENCY_CSV_FIELDNAMES,
    PHASE_A_LATENCY_CLAIM_BOUNDARY,
    OperationalLatencyBenchmarkResult,
    benchmark_operational_latency,
    compute_distribution_summary,
    compute_percentile,
    compute_window_collection_delay,
    emit_latency_benchmark_artifacts,
    preprocess_window_sample,
    sync_cuda_device,
)
from doh_reproduction.timeseries_data import (
    PADDING_VECTOR,
    SequenceMetadata,
    SequenceSample,
    create_sequence_samples,
)
from doh_reproduction.timeseries_models import (
    create_improved_model,
    create_paper_model,
    is_torch_available,
)

try:
    import torch
except ImportError:
    torch = None


def make_test_clump(
    direction: int = 0,
    size: int = 150,
    duration: float = 0.005,
    interarrival: float = 0.002,
) -> Clump:
    """Helper to create a deterministic Clump."""
    return Clump(
        size=size,
        pkt_count=2,
        direction=direction,
        duration=duration,
        interarrival=interarrival,
    )


def make_synthetic_flow(
    flow_id: str,
    session_id: str = "sess_0",
    scenario_id: str = "scen_0",
    l1_label: int = 1,
    l2_label: Optional[int] = 0,
    num_clumps: int = 6,
    base_duration: float = 0.005,
    base_interarrival: float = 0.002,
) -> runner.BoundedFlowRecord:
    """Helper to create a BoundedFlowRecord with deterministic clumps."""
    clumps = tuple(
        make_test_clump(
            direction=i % 2,
            size=100 + i * 20,
            duration=base_duration * (i + 1),
            interarrival=base_interarrival * (i + 1),
        )
        for i in range(num_clumps)
    )
    return runner.BoundedFlowRecord(
        flow_id=flow_id,
        session_id=session_id,
        scenario_id=scenario_id,
        source_id="test.pcap",
        clumps=clumps,
        l1_label=l1_label,
        l2_label=l2_label,
        start_time=0.0,
        end_time=1.0,
    )


class TestOperationalLatencyStatistics(unittest.TestCase):
    """Unit tests for pure latency statistical routines."""

    def test_compute_percentile_empty_and_single(self) -> None:
        self.assertEqual(compute_percentile([], 50.0), 0.0)
        self.assertEqual(compute_percentile([42.5], 50.0), 42.5)
        self.assertEqual(compute_percentile([42.5], 0.0), 42.5)
        self.assertEqual(compute_percentile([42.5], 100.0), 42.5)

    def test_compute_percentile_linear_interpolation(self) -> None:
        vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        # rank for q=50: (50/100)*4 = 2.0 -> vals[2] = 30.0
        self.assertAlmostEqual(compute_percentile(vals, 50.0), 30.0)
        # rank for q=25: (25/100)*4 = 1.0 -> vals[1] = 20.0
        self.assertAlmostEqual(compute_percentile(vals, 25.0), 20.0)
        # rank for q=75: (75/100)*4 = 3.0 -> vals[3] = 40.0
        self.assertAlmostEqual(compute_percentile(vals, 75.0), 40.0)
        # rank for q=90: (90/100)*4 = 3.6 -> 40.0*0.4 + 50.0*0.6 = 46.0
        self.assertAlmostEqual(compute_percentile(vals, 90.0), 46.0)

    def test_p50_p95_p99_ordering_guarantee(self) -> None:
        test_distributions = [
            [0.1] * 20,
            [0.001, 0.002, 0.005, 0.010, 0.050, 0.100, 1.000],
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
            [0.005] * 10 + [0.1] * 5 + [2.0],
            [10.0, 1.0, 5.0, 2.0, 8.0],
        ]
        for dist in test_distributions:
            summary = compute_distribution_summary(dist)
            self.assertGreaterEqual(summary["p50_seconds"], summary["min_seconds"])
            self.assertGreaterEqual(summary["p95_seconds"], summary["p50_seconds"], f"Failed on dist {dist}")
            self.assertGreaterEqual(summary["p99_seconds"], summary["p95_seconds"], f"Failed on dist {dist}")
            self.assertGreaterEqual(summary["max_seconds"], summary["p99_seconds"])
            self.assertEqual(summary["p50_seconds"], summary["median_seconds"])
            self.assertAlmostEqual(summary["p50_ms"], summary["p50_seconds"] * 1000.0)
            self.assertAlmostEqual(summary["p95_ms"], summary["p95_seconds"] * 1000.0)
            self.assertAlmostEqual(summary["p99_ms"], summary["p99_seconds"] * 1000.0)

    def test_empty_distribution_summary(self) -> None:
        summary = compute_distribution_summary([])
        self.assertEqual(summary["count"], 0)
        self.assertEqual(summary["mean_seconds"], 0.0)
        self.assertEqual(summary["p50_seconds"], 0.0)
        self.assertEqual(summary["p95_seconds"], 0.0)
        self.assertEqual(summary["p99_seconds"], 0.0)
        self.assertEqual(summary["mean_ms"], 0.0)


class TestWindowCollectionDelay(unittest.TestCase):
    """Behavioral tests for traffic collection delay calculation."""

    def test_exact_collection_delay_known_clumps(self) -> None:
        clumps = [
            make_test_clump(duration=0.005, interarrival=0.002),  # sum = 0.007
            make_test_clump(duration=0.010, interarrival=0.004),  # sum = 0.014
            make_test_clump(duration=0.015, interarrival=0.006),  # sum = 0.021
            make_test_clump(duration=0.020, interarrival=0.008),  # sum = 0.028
        ]

        # For w=1: first clump only = 0.007
        delay_w1 = compute_window_collection_delay(clumps, window_size=1)
        self.assertAlmostEqual(delay_w1, 0.007, places=6)

        # For w=2: first 2 clumps = 0.007 + 0.014 = 0.021
        delay_w2 = compute_window_collection_delay(clumps, window_size=2)
        self.assertAlmostEqual(delay_w2, 0.021, places=6)

        # For w=3: first 3 clumps = 0.007 + 0.014 + 0.021 = 0.042
        delay_w3 = compute_window_collection_delay(clumps, window_size=3)
        self.assertAlmostEqual(delay_w3, 0.042, places=6)

        # For w=6 (only 4 clumps available): sums all 4 clumps = 0.042 + 0.028 = 0.070
        delay_w6 = compute_window_collection_delay(clumps, window_size=6)
        self.assertAlmostEqual(delay_w6, 0.070, places=6)

    def test_empty_clumps_returns_zero(self) -> None:
        self.assertEqual(compute_window_collection_delay([], window_size=6), 0.0)
        self.assertEqual(compute_window_collection_delay([make_test_clump()], window_size=0), 0.0)

    def test_mapping_clump_format(self) -> None:
        clump_dicts = [
            {"duration": 0.012, "interarrival": 0.003},
            {"duration": 0.008, "interarrival": 0.002},
        ]
        delay = compute_window_collection_delay(clump_dicts, window_size=2)
        self.assertAlmostEqual(delay, 0.025, places=6)


class TestLatencyConfigValidation(unittest.TestCase):
    """Behavioral tests verifying config validation, defaults, and error boundaries."""

    def test_default_config_includes_conservative_defaults(self) -> None:
        cfg = runner.validate_run_config({})
        self.assertIn("enable_latency_benchmark", cfg)
        self.assertFalse(cfg["enable_latency_benchmark"])
        self.assertEqual(cfg["latency_warmup_iterations"], 10)
        self.assertEqual(cfg["latency_max_samples"], 500)

    def test_explicit_valid_latency_config(self) -> None:
        user_cfg = {
            "enable_latency_benchmark": True,
            "latency_warmup_iterations": 25,
            "latency_max_samples": 200,
        }
        validated = runner.validate_run_config(user_cfg)
        self.assertTrue(validated["enable_latency_benchmark"])
        self.assertEqual(validated["latency_warmup_iterations"], 25)
        self.assertEqual(validated["latency_max_samples"], 200)

    def test_string_boolean_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            runner.validate_run_config({"enable_latency_benchmark": "true"})
        with self.assertRaises(ValueError):
            runner.validate_run_config({"enable_latency_benchmark": "false"})

    def test_invalid_config_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            runner.validate_run_config({"enable_latency_benchmark": 12345})

        with self.assertRaises(ValueError):
            runner.validate_run_config({"latency_warmup_iterations": -5})

        with self.assertRaises(ValueError):
            runner.validate_run_config({"latency_max_samples": 0})

        with self.assertRaises(ValueError):
            runner.validate_run_config({"latency_max_samples": "not_an_int"})


@unittest.skipUnless(is_torch_available(), "PyTorch required for model latency microbenchmarks")
class TestModelLatencyBenchmarking(unittest.TestCase):
    """Behavioral tests for model microbenchmarking routines and device handling."""

    def setUp(self) -> None:
        # Create 4 test flows across 2 sessions
        self.flows = [
            make_synthetic_flow("flow_0", session_id="s0", l1_label=0, num_clumps=5),
            make_synthetic_flow("flow_1", session_id="s0", l1_label=1, num_clumps=5),
            make_synthetic_flow("flow_2", session_id="s1", l1_label=0, num_clumps=5),
            make_synthetic_flow("flow_3", session_id="s1", l1_label=1, num_clumps=5),
        ]
        # Build samples for w=3 (stride 1)
        self.samples = runner.build_samples_for_task_and_window(
            self.flows, task="l1", window_size=3
        )
        # Ensure we have test samples
        self.assertGreater(len(self.samples), 0)

    def test_paper_lstm_microbenchmark_cpu(self) -> None:
        model = create_paper_model(window_size=3)
        res = benchmark_operational_latency(
            model=model,
            test_samples=self.samples,
            flows=self.flows,
            task="l1",
            model_name="paper_v4",
            window_size=3,
            split_protocol="session_scenario_disjoint",
            device="cpu",
            warmup_iterations=5,
            max_samples=2,
        )

        self.assertEqual(res.sample_count, 2)
        self.assertEqual(res.window_size, 3)
        self.assertEqual(res.task, "l1")
        self.assertEqual(res.model, "paper_v4")
        self.assertEqual(res.batch_size, 1)

        # Non-negative component statistics
        self.assertGreaterEqual(res.traffic_collection_delay["mean_seconds"], 0.0)
        self.assertGreaterEqual(res.preprocessing_latency["mean_seconds"], 0.0)
        self.assertGreaterEqual(res.inference_latency["mean_seconds"], 0.0)
        self.assertGreaterEqual(res.end_to_end_latency["mean_seconds"], 0.0)

        # Ordering holds
        self.assertLessEqual(
            res.inference_latency["p50_seconds"],
            res.inference_latency["p95_seconds"] + 1e-9,
        )
        self.assertLessEqual(
            res.inference_latency["p95_seconds"],
            res.inference_latency["p99_seconds"] + 1e-9,
        )

        # Throughput is positive
        self.assertGreater(res.inference_latency["throughput_samples_per_second"], 0.0)

        # Claim boundary is populated
        self.assertIn("Phase A operational latency microbenchmarks", res.claim_boundary)

    def test_improved_bigru_microbenchmark_cpu(self) -> None:
        model = create_improved_model(window_size=3)
        res = benchmark_operational_latency(
            model=model,
            test_samples=self.samples,
            flows=self.flows,
            task="l1",
            model_name="improved_bidi_gru",
            window_size=3,
            split_protocol="session_scenario_disjoint",
            device="cpu",
            warmup_iterations=5,
            max_samples=3,
        )

        self.assertEqual(res.sample_count, 3)
        self.assertEqual(res.model, "improved_bidi_gru")
        self.assertGreaterEqual(res.inference_latency["mean_ms"], 0.0)
        self.assertGreaterEqual(res.end_to_end_latency["mean_seconds"], 0.0)

    def test_cuda_synchronization_wiring(self) -> None:
        mock_sync = MagicMock()
        with patch("doh_reproduction.operational_latency.torch.cuda.is_available", return_value=True), \
             patch("doh_reproduction.operational_latency.torch.cuda.synchronize", mock_sync):
            sync_cuda_device("cuda")

        mock_sync.assert_called_once_with("cuda")

    def test_first_window_per_flow_deterministic_selection(self) -> None:
        # Create flows with multiple windows
        flow_b = make_synthetic_flow("flow_b", num_clumps=8)
        flow_a = make_synthetic_flow("flow_a", num_clumps=8)
        samples = runner.build_samples_for_task_and_window(
            [flow_b, flow_a], task="l1", window_size=3
        )
        # Multiple windows exist per flow
        self.assertGreater(len(samples), 2)

        model = create_paper_model(window_size=3)
        res = benchmark_operational_latency(
            model=model,
            test_samples=samples,
            flows=[flow_b, flow_a],
            task="l1",
            model_name="paper_v4",
            window_size=3,
            max_samples=1,  # Cap at 1 flow
        )

        # Only 1 sample should be evaluated, from flow_a (alphabetical tie-break)
        self.assertEqual(res.sample_count, 1)

    def test_aligned_per_sample_end_to_end_summation(self) -> None:
        model = create_paper_model(window_size=3)
        res = benchmark_operational_latency(
            model=model,
            test_samples=self.samples,
            flows=self.flows,
            task="l1",
            model_name="paper_v4",
            window_size=3,
            device="cpu",
            warmup_iterations=2,
            max_samples=4,
        )

        # Mean end-to-end must equal the sum of mean components
        expected_mean_e2e = (
            res.traffic_collection_delay["mean_seconds"]
            + res.preprocessing_latency["mean_seconds"]
            + res.inference_latency["mean_seconds"]
        )
        self.assertAlmostEqual(res.end_to_end_latency["mean_seconds"], expected_mean_e2e, places=6)


class TestArtifactEmission(unittest.TestCase):
    """Behavioral tests verifying emission of dedicated latency benchmark artifacts."""

    def test_emit_latency_artifacts_schema_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "benchmarks"

            dummy_col = compute_distribution_summary([0.05, 0.08, 0.12])
            dummy_prep = compute_distribution_summary([0.0001, 0.0002, 0.0003])
            dummy_infer = compute_distribution_summary([0.001, 0.0015, 0.002])
            dummy_infer["throughput_samples_per_second"] = 666.67
            dummy_e2e = compute_distribution_summary([0.0511, 0.0817, 0.1223])

            res = OperationalLatencyBenchmarkResult(
                task="l1",
                model="paper_v4",
                window_size=6,
                split_protocol="session_scenario_disjoint",
                device="cpu",
                sample_count=3,
                batch_size=1,
                warmup_iterations=10,
                device_name="TestCPU",
                traffic_collection_delay=dummy_col,
                preprocessing_latency=dummy_prep,
                inference_latency=dummy_infer,
                end_to_end_latency=dummy_e2e,
                claim_boundary=PHASE_A_LATENCY_CLAIM_BOUNDARY,
            )

            json_path, csv_path = emit_latency_benchmark_artifacts(out_dir, [res])
            self.assertTrue(json_path.is_file())
            self.assertTrue(csv_path.is_file())

            # Verify JSON payload
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["manifest_version"], "1.0.0")
            self.assertEqual(data["total_benchmarks"], 1)
            self.assertEqual(data["claim_boundary"], PHASE_A_LATENCY_CLAIM_BOUNDARY)
            entry = data["benchmarks"][0]
            self.assertEqual(entry["task"], "l1")
            self.assertEqual(entry["window_size"], 6)
            self.assertAlmostEqual(entry["traffic_collection_delay"]["mean_seconds"], dummy_col["mean_seconds"])

            # Verify CSV content
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["task"], "l1")
            self.assertEqual(row["model"], "paper_v4")
            self.assertEqual(int(row["window_size"]), 6)
            self.assertEqual(int(row["sample_count"]), 3)
            self.assertAlmostEqual(float(row["collection_mean_seconds"]), dummy_col["mean_seconds"])
            self.assertAlmostEqual(float(row["infer_throughput_samples_per_second"]), 666.67)
            self.assertEqual(row["claim_boundary"], PHASE_A_LATENCY_CLAIM_BOUNDARY)

            # Ensure all fieldnames exist in CSV
            for fname in LATENCY_CSV_FIELDNAMES:
                self.assertIn(fname, row)


@unittest.skipUnless(is_torch_available(), "PyTorch required for runner execution tests")
class TestPipelineLatencyIntegration(unittest.TestCase):
    """End-to-end integration tests in runner pipeline."""

    def test_audit_mode_never_benchmarks_latency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "output"
            cfg = {
                "mode": "audit",
                "dataset_dir": tmp_dir,
                "enable_latency_benchmark": True,
            }
            with patch("train_timeseries.perform_pcap_audit", return_value=([], {"total_sources": 0})):
                code = runner.run_timeseries_pipeline(cfg, output_dir=out_dir)
                self.assertEqual(code, 0)

            # Audit mode must NOT emit latency artifacts
            self.assertFalse((out_dir / "latency_benchmarks.json").exists())
            self.assertFalse((out_dir / "latency_benchmarks.csv").exists())

    def test_tiny_synthetic_pipeline_run_emits_latency_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"

            # Create synthetic flows across 3 distinct sessions to satisfy session-disjoint split
            synthetic_flows = [
                # Session 0: non-DoH, benign DoH, malicious DoH
                make_synthetic_flow("f_s0_nd", "sess_0", "non_doh", l1_label=0, l2_label=None, num_clumps=7),
                make_synthetic_flow("f_s0_b", "sess_0", "benign_doh", l1_label=1, l2_label=0, num_clumps=7),
                make_synthetic_flow("f_s0_m", "sess_0", "malicious_doh", l1_label=1, l2_label=1, num_clumps=7),
                # Session 1: non-DoH, benign DoH, malicious DoH
                make_synthetic_flow("f_s1_nd", "sess_1", "non_doh", l1_label=0, l2_label=None, num_clumps=7),
                make_synthetic_flow("f_s1_b", "sess_1", "benign_doh", l1_label=1, l2_label=0, num_clumps=7),
                make_synthetic_flow("f_s1_m", "sess_1", "malicious_doh", l1_label=1, l2_label=1, num_clumps=7),
                # Session 2: non-DoH, benign DoH, malicious DoH
                make_synthetic_flow("f_s2_nd", "sess_2", "non_doh", l1_label=0, l2_label=None, num_clumps=7),
                make_synthetic_flow("f_s2_b", "sess_2", "benign_doh", l1_label=1, l2_label=0, num_clumps=7),
                make_synthetic_flow("f_s2_m", "sess_2", "malicious_doh", l1_label=1, l2_label=1, num_clumps=7),
            ]

            mock_audit = {
                "total_capture_sources": 3,
                "summary_by_category": {"benign_doh": 2, "malicious_doh": 1},
                "category_counts": {"benign_doh": 2, "malicious_doh": 1},
                "capture_sources": [
                    {"category": "benign_doh", "filename": "combined_a.pcap"},
                    {"category": "benign_doh", "filename": "combined_b.pcap"},
                    {"category": "malicious_doh", "filename": "m.pcap"},
                ],
            }

            cfg = {
                "mode": "train",
                "dataset_dir": tmp_dir,
                "dataset_slug": "test/tiny-pcaps",
                "dataset_version": "1",
                "task": "l1",
                "split_protocol": "paper_flow_random",
                "window_sizes": [3],
                "models": ["paper_v4", "improved_bidi_gru"],
                "epochs": 1,
                "batch_size": 4,
                "learning_rate": 0.001,
                "patience": 2,
                "enable_score_calibration": False,
                "seed": 42,
                "enable_latency_benchmark": True,
                "latency_warmup_iterations": 2,
                "latency_max_samples": 10,
            }

            with patch("train_timeseries.perform_pcap_audit", return_value=([mock_audit["capture_sources"]], mock_audit)), \
                 patch("train_timeseries.stream_and_collect_flows", return_value=synthetic_flows):
                exit_code = runner.run_timeseries_pipeline(cfg, output_dir=output_dir)
                self.assertEqual(exit_code, 0)

            # 1. Verify latency JSON artifact
            latency_json_path = output_dir / "latency_benchmarks.json"
            self.assertTrue(latency_json_path.is_file(), "latency_benchmarks.json must exist")
            with open(latency_json_path, "r", encoding="utf-8") as f:
                lat_json = json.load(f)

            self.assertEqual(lat_json["manifest_version"], "1.0.0")
            self.assertGreater(lat_json["total_benchmarks"], 0)
            self.assertIn("Phase A operational latency microbenchmarks", lat_json["claim_boundary"])

            for b_entry in lat_json["benchmarks"]:
                self.assertIn("traffic_collection_delay", b_entry)
                self.assertIn("preprocessing_latency", b_entry)
                self.assertIn("inference_latency", b_entry)
                self.assertIn("end_to_end_latency", b_entry)
                self.assertGreater(b_entry["sample_count"], 0)
                # p50 <= p95 <= p99 ordering
                self.assertLessEqual(
                    b_entry["end_to_end_latency"]["p50_seconds"],
                    b_entry["end_to_end_latency"]["p95_seconds"] + 1e-9,
                )
                self.assertLessEqual(
                    b_entry["end_to_end_latency"]["p95_seconds"],
                    b_entry["end_to_end_latency"]["p99_seconds"] + 1e-9,
                )

            # 2. Verify latency CSV artifact
            latency_csv_path = output_dir / "latency_benchmarks.csv"
            self.assertTrue(latency_csv_path.is_file(), "latency_benchmarks.csv must exist")
            with open(latency_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            self.assertEqual(len(rows), lat_json["total_benchmarks"])
            for row in rows:
                self.assertGreater(int(row["sample_count"]), 0)
                self.assertGreaterEqual(float(row["collection_mean_seconds"]), 0.0)
                self.assertGreaterEqual(float(row["prep_mean_ms"]), 0.0)
                self.assertGreaterEqual(float(row["infer_mean_ms"]), 0.0)
                self.assertGreaterEqual(float(row["e2e_mean_seconds"]), 0.0)
                self.assertIn("Phase A operational latency microbenchmarks", row["claim_boundary"])

            # 3. Verify metrics.json remains valid under existing schema
            metrics_path = output_dir / "metrics.json"
            self.assertTrue(metrics_path.is_file())
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics_data = json.load(f)

            validate_timeseries_metrics_schema(metrics_data)

            # 4. Verify experiment_manifest.json contains operational_latency boundary
            manifest_path = output_dir / "experiment_manifest.json"
            self.assertTrue(manifest_path.is_file())
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            self.assertIn("operational_latency", manifest_data["claim_boundaries"])
            self.assertTrue(manifest_data["execution_summary"]["latency_benchmarks_enabled"])
            self.assertEqual(
                manifest_data["execution_summary"]["latency_benchmarks_evaluated"],
                lat_json["total_benchmarks"],
            )


if __name__ == "__main__":
    unittest.main()
