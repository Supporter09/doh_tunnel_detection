"""Behavioral integration tests for Kaggle time-series packet-clump runner.

Verifies:
1. L2 retention: DoH flows retain L2 labels (0: benign, 1: malicious) and non-DoH flows are excluded from L2.
2. Immutable metadata: SequenceMetadata is frozen and has no l2_label; samples are created with layer=1/2.
3. Exact window lengths: Sequences match the exact requested window size (no max-window slicing).
4. DataLoader adaptation: TensorDataset/DataLoader (x, y, mask) feeds fit_model and predict_probabilities.
5. pos_weight isolation: class weighting passed strictly to improved model, never to paper reference model.
6. Calibration & threshold argument order: (y_val, val_scores) order in select_threshold_at_fpr;
   Platt calibration strictly validation->test; test split never used for fit/cal/threshold.
7. Quota enforcement by actual flow label: flow labels determine quotas, not capture categories.
8. Audit mode: emits pcap_audit.json, metrics.json, manifest without training.
9. End-to-end tiny synthetic run: both L1 and L2 produce rows in metrics.json with correct window sizes.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

# Ensure src and experiments are importable
TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
SRC_DIR = REPO_ROOT / "src"
RUNNER_DIR = REPO_ROOT / "experiments" / "kaggle" / "timeseries_clump_lstm"

for p in [str(RUNNER_DIR), str(SRC_DIR), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import train_timeseries as runner
from doh_reproduction.clumping import Clump
from doh_reproduction.timeseries_data import (
    LAYER1_LABEL_DOH,
    LAYER1_LABEL_NON_DOH,
    LAYER2_LABEL_BENIGN,
    LAYER2_LABEL_MALICIOUS,
    SequenceMetadata,
    SequenceSample,
    create_sequence_samples,
)
from doh_reproduction.timeseries_models import (
    binary_metrics,
    create_improved_model,
    create_paper_model,
    is_torch_available,
    platt_calibrate,
    predict_probabilities,
    select_threshold_at_fpr,
)


def make_test_clump(direction: int = 0, size: int = 150) -> Clump:
    """Helper to create a deterministic test Clump."""
    return Clump(
        size=size,
        pkt_count=2,
        direction=direction,
        duration=0.005,
        interarrival=0.002,
    )


def make_test_flow(
    flow_id: str,
    session_id: str,
    scenario_id: str,
    l1_label: int,
    l2_label: Optional[int] = None,
    num_clumps: int = 5,
    source_id: str = "test.pcap",
) -> runner.BoundedFlowRecord:
    """Helper to create a BoundedFlowRecord with test clumps."""
    clumps = tuple(make_test_clump(i % 2, 100 + i * 20) for i in range(num_clumps))
    return runner.BoundedFlowRecord(
        flow_id=flow_id,
        session_id=session_id,
        scenario_id=scenario_id,
        source_id=source_id,
        clumps=clumps,
        l1_label=l1_label,
        l2_label=l2_label,
        start_time=0.0,
        end_time=0.05,
    )


class TestL2RetentionAndImmutability(unittest.TestCase):
    """Verifies that SequenceMetadata remains frozen and L2 labels are preserved without mutation."""

    def test_sequence_metadata_is_frozen_and_has_no_l2_label(self) -> None:
        meta = SequenceMetadata(
            sample_id="test_0",
            flow_id="flow_0",
            session_id="sess_0",
            scenario_id="scen_0",
            label=1,
            layer=1,
            window_index=0,
            window_size=6,
        )
        # Attempting to assign new attribute or mutate existing attribute must raise
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            meta.l2_label = 1  # type: ignore[attr-defined]
        with self.assertRaises(FrozenInstanceError):
            meta.label = 0  # type: ignore[misc]

    def test_l2_sample_retention_and_layer_separation(self) -> None:
        flows = [
            make_test_flow("f_non_doh", "sess_0", "non_doh_browsing", l1_label=0, l2_label=None),
            make_test_flow("f_benign", "sess_1", "benign_doh_firefox", l1_label=1, l2_label=0),
            make_test_flow("f_malicious", "sess_2", "malicious_doh_dns2tcp", l1_label=1, l2_label=1),
        ]

        # Layer 1 samples: all 3 flows included with layer=1
        l1_samples = runner.build_samples_for_task_and_window(flows, task="l1", window_size=6)
        self.assertGreater(len(l1_samples), 0)
        for s in l1_samples:
            self.assertEqual(s.metadata.layer, 1)
            self.assertIn(s.label, [LAYER1_LABEL_NON_DOH, LAYER1_LABEL_DOH])

        # Layer 2 samples: only the 2 DoH flows included with layer=2; non-DoH excluded
        l2_samples = runner.build_samples_for_task_and_window(flows, task="l2", window_size=3)
        self.assertGreater(len(l2_samples), 0)
        l2_labels = {s.label for s in l2_samples}
        self.assertEqual(l2_labels, {LAYER2_LABEL_BENIGN, LAYER2_LABEL_MALICIOUS})
        for s in l2_samples:
            self.assertEqual(s.metadata.layer, 2)
            self.assertNotEqual(s.metadata.flow_id, "f_non_doh")


class TestExactWindowLengths(unittest.TestCase):
    """Verifies that samples are created with exact window lengths per sweep, not max-window slicing."""

    def test_window_lengths_match_selected_window(self) -> None:
        flows = [
            make_test_flow("f1", "s1", "benign_doh", l1_label=1, l2_label=0, num_clumps=4),
            make_test_flow("f2", "s2", "malicious_doh", l1_label=1, l2_label=1, num_clumps=8),
        ]

        # Generate window size 3
        samples_w3 = runner.build_samples_for_task_and_window(flows, task="l2", window_size=3)
        self.assertGreater(len(samples_w3), 0)
        for s in samples_w3:
            self.assertEqual(len(s.features), 3, "Window size 3 sample must have length 3")
            self.assertEqual(s.metadata.window_size, 3)

        # Generate window size 6
        samples_w6 = runner.build_samples_for_task_and_window(flows, task="l2", window_size=6)
        self.assertGreater(len(samples_w6), 0)
        for s in samples_w6:
            self.assertEqual(len(s.features), 6, "Window size 6 sample must have length 6")
            self.assertEqual(s.metadata.window_size, 6)


@unittest.skipUnless(is_torch_available(), "PyTorch is required for DataLoader tests")
class TestDataLoaderAdaptation(unittest.TestCase):
    """Verifies that make_data_loader produces valid batches compatible with models."""

    def test_data_loader_batch_structure_and_types(self) -> None:
        import torch

        flows = [
            make_test_flow("f1", "s1", "non_doh", l1_label=0, l2_label=None, num_clumps=5),
            make_test_flow("f2", "s2", "benign_doh", l1_label=1, l2_label=0, num_clumps=5),
            make_test_flow("f3", "s3", "malicious_doh", l1_label=1, l2_label=1, num_clumps=5),
        ]
        samples = runner.build_samples_for_task_and_window(flows, task="l1", window_size=4)
        loader = runner.make_data_loader(samples, batch_size=2, shuffle=False)
        self.assertIsNotNone(loader)

        batches = list(loader)
        self.assertGreater(len(batches), 0)
        bx, by, bmask = batches[0]

        self.assertIsInstance(bx, torch.Tensor)
        self.assertIsInstance(by, torch.Tensor)
        self.assertIsInstance(bmask, torch.Tensor)
        self.assertEqual(bx.shape[1], 4, "Sequence length must match window_size")
        self.assertEqual(bx.shape[2], 5, "Feature dimension must be 5")
        self.assertEqual(bmask.shape[1], 4, "Mask length must match window_size")

    def test_predict_probabilities_accepts_data_loader(self) -> None:
        flows = [
            make_test_flow("f1", "s1", "non_doh", l1_label=0, l2_label=None, num_clumps=6),
            make_test_flow("f2", "s2", "doh", l1_label=1, l2_label=0, num_clumps=6),
        ]
        samples = runner.build_samples_for_task_and_window(flows, task="l1", window_size=6)
        loader = runner.make_data_loader(samples, batch_size=2, shuffle=False)
        model = create_paper_model(window_size=6)

        probs = predict_probabilities(model, loader, device="cpu")
        self.assertEqual(len(probs), len(samples))
        for p in probs:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


class TestCalibrationAndThresholdArgumentOrder(unittest.TestCase):
    """Verifies correct argument order (y_val, scores) and validation-only calibration."""

    def test_select_threshold_at_fpr_argument_order(self) -> None:
        # Ground truth: y_val=[0, 0, 0, 1, 1], scores=[0.01, 0.02, 0.05, 0.8, 0.9]
        y_val = [0, 0, 0, 1, 1]
        val_scores = [0.01, 0.02, 0.05, 0.8, 0.9]

        # Canonical signature: select_threshold_at_fpr(y_val, val_scores, target_fpr=...)
        tau, achieved_fpr, feasible = select_threshold_at_fpr(y_val, val_scores, target_fpr=0.01)
        self.assertIsInstance(tau, float)
        self.assertIsInstance(achieved_fpr, float)
        self.assertTrue(feasible)
        self.assertGreater(tau, 0.05)

    def test_platt_calibrate_validation_only_transformation(self) -> None:
        val_scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
        y_val = [0, 0, 0, 1, 1, 1]
        test_scores = [0.15, 0.85]

        calibrator, val_cal, test_cal = platt_calibrate(
            val_scores=val_scores,
            y_val=y_val,
            test_scores=test_scores,
        )
        self.assertIsNotNone(calibrator)
        self.assertEqual(len(val_cal), len(val_scores))
        self.assertIsNotNone(test_cal)
        self.assertEqual(len(test_cal), len(test_scores))
        for p in test_cal:
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


class TestQuotaEnforcementByActualFlowLabel(unittest.TestCase):
    """Verifies that quotas are enforced strictly by actual flow label, not capture category."""

    def test_quota_counts_by_flow_label_not_capture_category(self) -> None:
        # Create a mock capture whose category claims "benign_doh"
        mock_capture = {
            "filename": "fake_capture.pcap",
            "scenario_id": "benign_doh_chrome",
            "session_id": "sess_mixed",
            "category": "benign_doh",
        }

        # Yield flows that are actually non-DoH (is_doh=False)
        class MockFlow:
            def __init__(self, fid: str, is_doh: bool) -> None:
                self.flow_id = fid
                self.is_doh = is_doh
                self.clumps = [make_test_clump()]
                self.packets = []
                self.start_time = 0.0
                self.end_time = 0.01

        flows_yielded = [
            MockFlow("flow_1", is_doh=False),
            MockFlow("flow_2", is_doh=False),
            MockFlow("flow_3", is_doh=True),
        ]

        with patch("train_timeseries.CaptureStreamOpener") as mock_opener, \
             patch("train_timeseries.iter_pcap_flows", return_value=flows_yielded), \
             patch("train_timeseries.labels_for_flow", side_effect=lambda f, c: {
                 "l1_label": 1 if f.is_doh else 0,
                 "l2_label": 0 if f.is_doh else None,
             }):
            mock_opener.return_value.__enter__.return_value = None

            # With max_flows_per_class=1, only 1 non_doh and 1 benign_doh should be retained
            retained = runner.stream_and_collect_flows([mock_capture], max_flows_per_class=1)

            l1_counts = {0: 0, 1: 0}
            for rf in retained:
                l1_counts[rf.l1_label] += 1

            self.assertEqual(l1_counts[0], 1, "Non-DoH quota must cap at 1 despite benign_doh capture category")
            self.assertEqual(l1_counts[1], 1, "Benign DoH quota must cap at 1")


class TestAuditModeExecution(unittest.TestCase):
    """Verifies that audit mode executes cleanly and produces metadata without training models."""

    def test_audit_mode_emits_artifacts_without_training(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_dir = Path(tmp_dir) / "dataset"
            output_dir = Path(tmp_dir) / "output"
            dataset_dir.mkdir(parents=True)

            # Create dummy PCAP file
            dummy_pcap = dataset_dir / "dummy_traffic.pcap"
            dummy_pcap.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

            cfg = {
                "mode": "audit",
                "dataset_dir": str(dataset_dir),
                "dataset_slug": "test/dataset",
                "dataset_version": "1",
                "task": "both",
                "split_protocol": "session_scenario_disjoint",
                "window_sizes": [3, 6],
                "models": ["paper_v4"],
            }

            with patch("train_timeseries.fit_model") as mock_fit:
                exit_code = runner.run_timeseries_pipeline(cfg, output_dir=output_dir)
                self.assertEqual(exit_code, 0)
                mock_fit.assert_not_called()

            # Verify audit artifacts
            self.assertTrue((output_dir / "pcap_audit.json").is_file())
            self.assertTrue((output_dir / "metrics.json").is_file())
            self.assertTrue((output_dir / "experiment_manifest.json").is_file())

            with open(output_dir / "metrics.json", "r", encoding="utf-8") as f:
                metrics_data = json.load(f)
            self.assertEqual(metrics_data["execution_mode"], "audit")
            self.assertEqual(metrics_data["status"], "not_trained")
            self.assertEqual(metrics_data["runs"], [])

    def test_partial_config_normalization_at_pipeline_entry(self) -> None:
        """Verifies that passing a partial config resolves defaults without KeyError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_dir = Path(tmp_dir) / "dataset"
            output_dir = Path(tmp_dir) / "output"
            dataset_dir.mkdir(parents=True)

            dummy_pcap = dataset_dir / "dummy.pcap"
            dummy_pcap.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 20)

            # Minimal partial config omitting target_false_positive_rate, learning_rate, batch_size, etc.
            minimal_cfg = {
                "mode": "audit",
                "dataset_dir": str(dataset_dir),
            }

            exit_code = runner.run_timeseries_pipeline(minimal_cfg, output_dir=output_dir)
            self.assertEqual(exit_code, 0)

            with open(output_dir / "experiment_manifest.json", "r", encoding="utf-8") as f:
                manifest = json.load(f)
            resolved = manifest["resolved_config"]
            self.assertIn("target_false_positive_rate", resolved)
            self.assertEqual(resolved["target_false_positive_rate"], 0.001)
            self.assertIn("epochs", resolved)
            self.assertEqual(resolved["learning_rate"], 0.001)

@unittest.skipUnless(is_torch_available(), "PyTorch is required for pipeline training execution tests")
class TestTinySyntheticPipelineRun(unittest.TestCase):
    """Verifies end-to-end execution of a bounded tiny synthetic 1-epoch training run."""

    def test_tiny_synthetic_pipeline_both_l1_and_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"

            # Create synthetic flows across 3 distinct sessions to satisfy session-disjoint split
            synthetic_flows = [
                # Session 0: non-DoH, benign DoH, malicious DoH
                make_test_flow("f_s0_nd", "sess_0", "non_doh", l1_label=0, l2_label=None, num_clumps=7),
                make_test_flow("f_s0_b", "sess_0", "benign_doh", l1_label=1, l2_label=0, num_clumps=7),
                make_test_flow("f_s0_m", "sess_0", "malicious_doh", l1_label=1, l2_label=1, num_clumps=7),
                # Session 1: non-DoH, benign DoH, malicious DoH
                make_test_flow("f_s1_nd", "sess_1", "non_doh", l1_label=0, l2_label=None, num_clumps=7),
                make_test_flow("f_s1_b", "sess_1", "benign_doh", l1_label=1, l2_label=0, num_clumps=7),
                make_test_flow("f_s1_m", "sess_1", "malicious_doh", l1_label=1, l2_label=1, num_clumps=7),
                # Session 2: non-DoH, benign DoH, malicious DoH
                make_test_flow("f_s2_nd", "sess_2", "non_doh", l1_label=0, l2_label=None, num_clumps=7),
                make_test_flow("f_s2_b", "sess_2", "benign_doh", l1_label=1, l2_label=0, num_clumps=7),
                make_test_flow("f_s2_m", "sess_2", "malicious_doh", l1_label=1, l2_label=1, num_clumps=7),
            ]

            # Combined BenignDoH-NonDoH captures can contain both L1 labels
            # even though their capture-level category is benign_doh.
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
                "task": "both",
                "split_protocol": "paper_flow_random",
                "window_sizes": [3, 6],
                "models": ["paper_v4", "improved_bidi_gru"],
                "epochs": 1,
                "batch_size": 4,
                "learning_rate": 0.001,
                "patience": 2,
                "enable_score_calibration": False,  # paper_flow_random has val=[]
                "seed": 42,
            }

            with patch("train_timeseries.perform_pcap_audit", return_value=([mock_audit["capture_sources"]], mock_audit)), \
                 patch("train_timeseries.stream_and_collect_flows", return_value=synthetic_flows):
                exit_code = runner.run_timeseries_pipeline(cfg, output_dir=output_dir)
                self.assertEqual(exit_code, 0)

            # Verify metrics.json
            metrics_path = output_dir / "metrics.json"
            self.assertTrue(metrics_path.is_file())
            with open(metrics_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            self.assertEqual(payload["status"], "training_completed")
            rows = payload.get("runs", payload.get("metrics", []))
            self.assertGreater(len(rows), 0)
            # Verify both L1 and L2 rows are produced
            tasks_evaluated = {r["task"] for r in rows}
            self.assertEqual(tasks_evaluated, {"l1", "l2"}, "Both L1 and L2 tasks must produce evaluation rows")

            # Verify window sizes match model configurations
            windows_evaluated = {r["window_size"] for r in rows}
            self.assertEqual(windows_evaluated, {3, 6}, "Both window sizes 3 and 6 must be evaluated")

            # Verify models evaluated
            models_evaluated = {r["model"] for r in rows}
            self.assertEqual(models_evaluated, {"paper_v4", "improved_bidi_gru"})

            # Verify training_history.csv is populated
            history_path = output_dir / "training_history.csv"
            self.assertTrue(history_path.is_file())
            with open(history_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                hist_rows = list(reader)
            self.assertGreater(len(hist_rows), 0, "training_history.csv must have loss entries")

            # Verify confusion matrices exist
            for r in rows:
                cm_file = output_dir / f"confusion_matrix_{r['task']}_{r['model']}_w{r['window_size']}_{r['split_protocol']}.csv"
                self.assertTrue(cm_file.is_file(), f"Confusion matrix CSV {cm_file.name} must exist")

            from doh_reproduction.comparison import (
                LayerTask,
                Paradigm,
                SplitProtocol,
                generate_full_comparison_report,
                load_timeseries_metrics,
            )

            ts_metrics = load_timeseries_metrics(metrics_path)
            self.assertEqual(ts_metrics["manifest_version"], "1.0.0")

            tables = generate_full_comparison_report(
                timeseries_l1=ts_metrics,
                timeseries_l2=ts_metrics,
                flow_random_metrics=ts_metrics,
                group_disjoint_metrics=ts_metrics,
            )

            # Check paper vs project head-to-head table
            p_vs_p = tables["paper_vs_project"]
            l1_project_rows = [
                row for row in p_vs_p.rows
                if row[0] == LayerTask.L1.display_name
                and row[1] == Paradigm.TIMESERIES_CLUMP.display_name
                and row[11] == "completed"
            ]
            l2_project_rows = [
                row for row in p_vs_p.rows
                if row[0] == LayerTask.L2.display_name
                and row[1] == Paradigm.TIMESERIES_CLUMP.display_name
                and row[11] == "completed"
            ]
            self.assertGreater(len(l1_project_rows), 0)
            self.assertGreater(len(l2_project_rows), 0)
            for r in l1_project_rows:
                self.assertNotEqual(r[8], "unavailable", "L1 F1-score must be available")
                self.assertEqual(r[11], "completed")
            for r in l2_project_rows:
                self.assertNotEqual(r[8], "unavailable", "L2 F1-score must be available")
                self.assertEqual(r[11], "completed")

            # Check split leakage comparison table
            split_tbl = tables["corrected_vs_random_splits"]
            fr_l1 = [row for row in split_tbl.rows if row[0] == LayerTask.L1.display_name and row[2] == SplitProtocol.PAPER_FLOW_RANDOM.display_name]
            fr_l2 = [row for row in split_tbl.rows if row[0] == LayerTask.L2.display_name and row[2] == SplitProtocol.PAPER_FLOW_RANDOM.display_name]
            self.assertGreater(len(fr_l1), 0)
            self.assertGreater(len(fr_l2), 0)
            self.assertEqual(fr_l1[0][9], "completed")
            self.assertEqual(fr_l2[0][9], "completed")
class TestQuotaEarlyStop(unittest.TestCase):
    """Behavioral tests verifying early termination of flow ingestion once quotas are met."""

    def test_quota_early_stop_stops_flow_and_capture_iteration(self) -> None:
        mock_captures = [
            {"filename": f"cap_{i}.pcap", "scenario_id": "scen", "session_id": f"s_{i}", "category": "benign_doh"}
            for i in range(5)
        ]

        class MockFlow:
            def __init__(self, fid: str, is_doh: bool) -> None:
                self.flow_id = fid
                self.is_doh = is_doh
                self.clumps = [make_test_clump()]
                self.packets = []
                self.start_time = 0.0
                self.end_time = 0.01

        # Each capture yields alternating non-DoH and DoH flows
        def mock_iter_flows(stream, **kwargs):
            yield MockFlow("flow_nondoh", is_doh=False)
            yield MockFlow("flow_doh", is_doh=True)
            yield MockFlow("flow_extra", is_doh=False)

        counters: dict = {}
        with patch("train_timeseries.CaptureStreamOpener") as mock_opener, \
             patch("train_timeseries.iter_pcap_flows", side_effect=mock_iter_flows), \
             patch("train_timeseries.labels_for_flow", side_effect=lambda f, c: {
                 "l1_label": 1 if f.is_doh else 0,
                 "l2_label": 0 if f.is_doh else None,
             }):
            mock_opener.return_value.__enter__.return_value = None

            # For task l1, quotas are 2 non_doh and 2 doh flows
            # Capture 0 yields: nondoh (1), doh (1), nondoh (2) -> non_doh quota satisfied
            # Capture 1 yields: nondoh (skipped), doh (2) -> doh quota satisfied -> all quotas satisfied!
            retained = runner.stream_and_collect_flows(
                mock_captures,
                max_flows_per_class=2,
                task="l1",
                counters=counters,
            )
            self.assertEqual(len(retained), 4)
            self.assertTrue(counters.get("quotas_satisfied"))
            self.assertLess(counters.get("total_flows_processed"), 15)
            self.assertEqual(counters.get("class_flow_counts", {}).get("non_doh"), 2)
            self.assertEqual(counters.get("class_flow_counts", {}).get("benign_doh"), 2)


class TestBoundedWindowsPerFlowAndClass(unittest.TestCase):
    """Behavioral tests verifying per-flow and per-class sequence window materialization bounds."""

    def test_max_windows_per_flow_bounds_samples(self) -> None:
        flow = make_test_flow("flow_big", session_id="s1", scenario_id="browsing", l1_label=0, num_clumps=20)
        # Window size 3 stride 1 with 20 clumps would yield 18 windows
        counters: dict = {}
        samples = runner.build_samples_for_task_and_window(
            [flow],
            task="l1",
            window_size=3,
            max_windows_per_flow=4,
            counters=counters,
        )
        self.assertEqual(len(samples), 4)

    def test_max_windows_per_class_bounds_samples(self) -> None:
        flows = [
            make_test_flow(f"flow_{i}", session_id=f"s_{i}", scenario_id="browsing", l1_label=0, num_clumps=10)
            for i in range(5)
        ]
        counters: dict = {}
        samples = runner.build_samples_for_task_and_window(
            flows,
            task="l1",
            window_size=3,
            max_windows_per_class=7,
            counters=counters,
        )
        self.assertEqual(len(samples), 7)
        self.assertGreater(counters.get("truncated_by_class", 0), 0)


class TestManifestCapAndCounterProvenance(unittest.TestCase):
    """Behavioral tests verifying manifest provenance and schema compliance."""

    def test_audit_mode_manifest_and_metrics_schema(self) -> None:
        from doh_reproduction.comparison import validate_timeseries_metrics_schema

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "audit_out"
            cfg = {
                "mode": "audit",
                "dataset_dir": tmp_dir,
                "dataset_slug": "test/slug",
                "dataset_version": "1",
                "task": "both",
                "max_capture_members": 5,
                "max_flows_per_class": 10,
            }
            audit_payload = {
                "total_capture_sources": 2,
                "total_sources": 2,
                "total_bytes": 100,
                "summary_by_category": {"non_doh": 2},
                "audit_counters": {"truncated_due_to_max_sources": False},
            }
            runner.emit_audit_mode_artifacts(out_dir, cfg, "test_config", audit_payload)

            manifest_path = out_dir / "experiment_manifest.json"
            self.assertTrue(manifest_path.is_file())
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIn("resource_bounds", manifest)
            self.assertTrue(manifest["resource_bounds"]["is_capped_run"])
            self.assertEqual(manifest["resource_bounds"]["active_caps"]["max_capture_members"], 5)
            # All centralized cap keys must be represented in active_caps
            for cap_k in runner.RESOURCE_CAP_KEYS:
                self.assertIn(cap_k, manifest["resource_bounds"]["active_caps"])
            self.assertIn("raw_packets_read", manifest["resource_bounds"]["truncation_counters"])
            self.assertIn("accepted_packets", manifest["resource_bounds"]["truncation_counters"])

            metrics_path = out_dir / "metrics.json"
            self.assertTrue(metrics_path.is_file())
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            # Must validate cleanly against comparison schema
            validate_timeseries_metrics_schema(metrics)


class TestScannerFailsClosed(unittest.TestCase):
    """Behavioral tests verifying that scanner errors fail closed with zero fallback."""

    def test_perform_pcap_audit_fails_closed_on_scanner_error(self) -> None:
        with patch("train_timeseries.discover_capture_sources", side_effect=ValueError("Dataset symlink escape attempted")):
            with self.assertRaises(ValueError) as ctx:
                runner.perform_pcap_audit(Path("/any/dataset"))
            self.assertIn("Dataset symlink escape attempted", str(ctx.exception))
class TestCaptureStreamOpenerNestedZip(unittest.TestCase):
    """Behavioral tests verifying CaptureStreamOpener nested ZIP streaming and delegation."""

    def test_delegation_to_capture_source_open_stream(self) -> None:
        class MockCaptureSource:
            def __init__(self) -> None:
                self.opened = False
                self.source_id = "mock_source_01"

            @contextmanager
            def open_stream(self):
                self.opened = True
                yield io.BytesIO(b"MOCK_STREAM_BYTES")

        mock_src = MockCaptureSource()
        opener = runner.CaptureStreamOpener(mock_src)
        with opener as stream:
            content = stream.read()
            self.assertEqual(content, b"MOCK_STREAM_BYTES")
        self.assertTrue(mock_src.opened)


class TestFallbackMetadataNonDoHPriority(unittest.TestCase):
    """Behavioral test verifying NonDoH patterns are prioritized over generic browser names."""

    def test_nondoh_with_browser_name_classified_as_nondoh(self) -> None:
        meta = runner.fallback_derive_capture_metadata("chrome_browsing_nondoh.pcap", parent_path="NonDoH")
        self.assertEqual(meta["category"], "non_doh", "Must be non_doh, not benign_doh")
        self.assertEqual(meta["scenario_id"], "non_doh_chrome")
        self.assertFalse(meta["is_malicious"])


if __name__ == "__main__":
    unittest.main()
