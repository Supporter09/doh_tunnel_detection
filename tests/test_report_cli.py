"""Focused behavioral unit and integration tests for report-generation CLI.

Verifies:
1. Absent Phase 2 time-series: generates all 6 tables and Markdown report,
   with verified Phase 1 numbers and explicit 'unavailable' strings (no 0.0).
2. Multi-task Phase 2: populates both Layer 1 and Layer 2 time-series rows,
   window sweeps, split leakage comparisons, and marks improvements implemented.
3. Deterministic output: byte-identical outputs across repeated runs.
4. Overwrite guard: refuses to overwrite non-empty output directory unless --force.
5. Strict schema rejection: rejects corrupted or invalid metric payloads.
6. Subprocess CLI invocation: real command-line execution succeeds with standard exits.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Ensure scripts and src are discoverable
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"

for p in [SCRIPTS_DIR, SRC_DIR, REPO_ROOT]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import generate_report
from generate_report import build_parser, generate_report, main
from doh_reproduction.comparison import (
    IncompatibleMetricSchemaError,
    UNAVAILABLE_STR,
    load_latency_benchmarks,
    validate_latency_benchmarks_schema,
)


class TestReportCLIAbsentPhase2(unittest.TestCase):
    """Verify report generation when Phase 2 time-series metrics are absent."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "reports"
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_absent_phase2_generates_all_tables_with_unavailable_timeseries(self) -> None:
        """All 6 tables and 1 Markdown document must be generated; timeseries rows are unavailable."""
        self.assertTrue(self.l1_evidence.is_file(), f"Missing manifest: {self.l1_evidence}")
        self.assertTrue(self.l2_evidence.is_file(), f"Missing manifest: {self.l2_evidence}")

        written = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.out_dir,
            phase2_metrics_path=None,
        )

        # 1. Assert all 7 artifact paths are returned and exist
        expected_keys = {
            "markdown",
            "statistical_comparison",
            "timeseries_window_sweeps",
            "paper_vs_project",
            "corrected_vs_random_splits",
            "latency_tradeoffs",
            "improvements",
        }
        self.assertEqual(set(written.keys()), expected_keys)
        for k, p in written.items():
            self.assertTrue(p.is_file(), f"Artifact '{k}' at '{p}' does not exist.")
            self.assertGreater(p.stat().st_size, 0, f"Artifact '{k}' is empty.")

        # 2. Check statistical_comparison.csv contains real verified rows
        stat_csv = written["statistical_comparison"].read_text(encoding="utf-8")
        reader = list(csv.reader(io.StringIO(stat_csv)))
        self.assertGreater(len(reader), 10)
        headers = reader[0]
        self.assertIn("F1-Score / Macro-F1", headers)
        self.assertIn("Provenance", headers)

        # Find project Random Forest rows (canonical name is "Project Random Forest")
        rf_l1_rows = [
            r for r in reader
            if "Layer 1" in r[0] and r[1] == "Project Random Forest"
        ]
        self.assertEqual(len(rf_l1_rows), 1)
        # Macro F1 for L1 RF is ~0.9965, provenance is [Project-Observed]
        self.assertEqual(rf_l1_rows[0][2], "[Project-Observed]")
        self.assertEqual(rf_l1_rows[0][6], "0.9965")
        self.assertEqual(rf_l1_rows[0][7], "0.000939")

        rf_l2_rows = [
            r for r in reader
            if "Layer 2" in r[0] and r[1] == "Project Random Forest"
        ]
        self.assertEqual(len(rf_l2_rows), 1)
        # Macro F1 for L2 RF is ~0.9997, provenance is [Project-Observed]
        self.assertEqual(rf_l2_rows[0][2], "[Project-Observed]")
        self.assertEqual(rf_l2_rows[0][6], "0.9997")
        self.assertEqual(rf_l2_rows[0][7], "0.000523")
        # 3. Check timeseries_window_sweeps.csv renders unavailable (never 0.0)
        ts_csv = written["timeseries_window_sweeps"].read_text(encoding="utf-8")
        ts_reader = list(csv.reader(io.StringIO(ts_csv)))
        # Exactly 1 header + 20 paper rows + 20 project rows = 41 rows
        self.assertEqual(len(ts_reader), 41)

        project_ts_rows = [r for r in ts_reader if "Project" in r[2]]
        self.assertEqual(len(project_ts_rows), 20)
        for r in project_ts_rows:
            self.assertEqual(r[3], "[Unavailable]")
            self.assertEqual(r[5], UNAVAILABLE_STR)
            self.assertEqual(r[6], UNAVAILABLE_STR)
            self.assertEqual(r[7], UNAVAILABLE_STR)
            self.assertEqual(r[8], UNAVAILABLE_STR)
            self.assertEqual(r[9], UNAVAILABLE_STR)
            self.assertEqual(r[10], "unavailable")
            # Strict no-fabrication check
            self.assertNotIn("0.0", r[5:10])
            self.assertNotIn("0", r[5:10])

        # 4. Check paper_vs_project.csv
        pvp_csv = written["paper_vs_project"].read_text(encoding="utf-8")
        pvp_reader = list(csv.reader(io.StringIO(pvp_csv)))
        self.assertEqual(len(pvp_reader), 9)  # 1 header + 8 rows

        # Project timeseries rows at l=6 (L1) and l=3 (L2) must be unavailable
        l1_ts_proj = [r for r in pvp_reader if "Layer 1" in r[0] and "Time-Series" in r[1] and "Project" in r[2]][0]
        self.assertEqual(l1_ts_proj[3], "[Unavailable]")
        self.assertEqual(l1_ts_proj[8], UNAVAILABLE_STR)
        self.assertEqual(l1_ts_proj[11], "unavailable")

        l2_ts_proj = [r for r in pvp_reader if "Layer 2" in r[0] and "Time-Series" in r[1] and "Project" in r[2]][0]
        self.assertEqual(l2_ts_proj[3], "[Unavailable]")
        self.assertEqual(l2_ts_proj[8], UNAVAILABLE_STR)
        self.assertEqual(l2_ts_proj[11], "unavailable")

        # 5. Check improvements.csv: Neural Architecture row must be 'ready' (pending execution)
        imp_csv = written["improvements"].read_text(encoding="utf-8")
        imp_reader = list(csv.reader(io.StringIO(imp_csv)))
        arch_row = [r for r in imp_reader if "Mask-Aware BiGRU" in r[1]][0]
        self.assertEqual(arch_row[5], "ready")

        # 6. Check comparison_report.md
        md_text = written["markdown"].read_text(encoding="utf-8")
        self.assertIn("# Comprehensive Experimental Comparison: CIRA-CIC-DoHBrw-2020 Reproduction", md_text)
        self.assertIn("### Statistical Flow-Level Classification: Paper vs. Project Benchmark", md_text)
        self.assertIn("### Time-Series Packet-Clump Sequence Evaluation: Sliding Window Sweeps", md_text)
        self.assertIn("### Head-to-Head Comparison: Original Paper Claims vs Project Implementations", md_text)
        self.assertIn("### Protocol Leakage Audit: Flow-Level Random Split vs Session/Scenario Group-Disjoint Split", md_text)
        self.assertIn("### Early Detection Latency vs Accuracy Trade-Off: Full-Flow vs Clump Sequences", md_text)
        self.assertIn("### Project Modernization: Methodological, Algorithmic, and Operational Improvements", md_text)


class TestReportCLIMultiTaskPhase2(unittest.TestCase):
    """Verify report generation when a multi-task Phase 2 metrics.json is provided."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "reports_multitask"
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

        # Create valid multi-task Phase 2 metrics payload covering L1 and L2
        self.p2_metrics_file = Path(self.temp_dir.name) / "phase2_multitask_metrics.json"
        p2_data = {
            "manifest_version": "1.0.0",
            "task": "both",
            "execution_mode": "train",
            "status": "training_completed",
            "dataset_slug": "dhoogla/cicdohbrw2020",
            "dataset_version": "3",
            "runs": [
                # L1 Flow-Random optimal window l=6
                {
                    "task": "l1",
                    "model": "paper_v4",
                    "window_size": 6,
                    "split_protocol": "paper_flow_random",
                    "precision": 0.9935,
                    "recall": 0.9930,
                    "f1_score": 0.9932,
                    "fpr": 0.0008,
                    "latencies_seconds": {
                        "mean_duration": 0.570,
                        "median_duration": 0.045,
                    },
                },
                # L1 Group-Disjoint optimal window l=6
                {
                    "task": "l1",
                    "model": "paper_v4",
                    "window_size": 6,
                    "split_protocol": "session_scenario_disjoint",
                    "precision": 0.9450,
                    "recall": 0.9420,
                    "f1_score": 0.9435,
                    "fpr": 0.0050,
                    "latencies_seconds": {
                        "mean_duration": 0.572,
                        "median_duration": 0.046,
                    },
                },
                # L2 Flow-Random optimal window l=3
                {
                    "task": "l2",
                    "model": "paper_v4",
                    "window_size": 3,
                    "split_protocol": "paper_flow_random",
                    "precision": 0.9915,
                    "recall": 0.9910,
                    "f1_score": 0.9912,
                    "fpr": 0.0009,
                    "latencies_seconds": {
                        "mean_duration": 0.501,
                        "median_duration": 0.049,
                    },
                },
                # L2 Group-Disjoint optimal window l=3
                {
                    "task": "l2",
                    "model": "paper_v4",
                    "window_size": 3,
                    "split_protocol": "session_scenario_disjoint",
                    "precision": 0.9120,
                    "recall": 0.9080,
                    "f1_score": 0.9100,
                    "fpr": 0.0085,
                    "latencies_seconds": {
                        "mean_duration": 0.503,
                        "median_duration": 0.050,
                    },
                },
            ],
        }
        with open(self.p2_metrics_file, "w", encoding="utf-8") as f:
            json.dump(p2_data, f, indent=2)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_multitask_phase2_populates_both_layers(self) -> None:
        """Multi-task Phase 2 metrics must populate L1 and L2 rows with observed values."""
        written = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.out_dir,
            phase2_metrics_path=self.p2_metrics_file,
        )

        # 1. Check timeseries_window_sweeps.csv
        ts_csv = written["timeseries_window_sweeps"].read_text(encoding="utf-8")
        ts_reader = list(csv.reader(io.StringIO(ts_csv)))

        # Find L1 window 6 project row
        # Find L1 window 6 project row: must prefer flow-random over group-disjoint
        l1_w6 = [r for r in ts_reader if "Layer 1" in r[0] and r[1] == "6" and "Project" in r[2]][0]
        self.assertEqual(l1_w6[3], "[Project-Replication]")
        self.assertEqual(l1_w6[4], "paper_flow_random")
        self.assertEqual(l1_w6[5], "0.9935")  # flow-random precision, NOT group-disjoint 0.9450
        self.assertEqual(l1_w6[6], "0.9930")  # flow-random recall, NOT group-disjoint 0.9420
        self.assertEqual(l1_w6[7], "0.9932")  # flow-random f1, NOT group-disjoint 0.9435
        self.assertEqual(l1_w6[8], "0.570 s")
        self.assertEqual(l1_w6[10], "completed")

        # Find L2 window 3 project row: must prefer flow-random over group-disjoint
        l2_w3 = [r for r in ts_reader if "Layer 2" in r[0] and r[1] == "3" and "Project" in r[2]][0]
        self.assertEqual(l2_w3[3], "[Project-Replication]")
        self.assertEqual(l2_w3[4], "paper_flow_random")
        self.assertEqual(l2_w3[5], "0.9915")  # flow-random precision, NOT group-disjoint 0.9120
        self.assertEqual(l2_w3[6], "0.9910")  # flow-random recall, NOT group-disjoint 0.9080
        self.assertEqual(l2_w3[7], "0.9912")  # flow-random f1, NOT group-disjoint 0.9100
        self.assertEqual(l2_w3[8], "0.501 s")
        self.assertEqual(l2_w3[10], "completed")
        # Other windows remain unavailable
        l1_w1 = [r for r in ts_reader if "Layer 1" in r[0] and r[1] == "1" and "Project" in r[2]][0]
        self.assertEqual(l1_w1[10], "unavailable")
        self.assertEqual(l1_w1[7], UNAVAILABLE_STR)

        # 2. Check paper_vs_project.csv head-to-head table
        pvp_csv = written["paper_vs_project"].read_text(encoding="utf-8")
        pvp_reader = list(csv.reader(io.StringIO(pvp_csv)))

        l1_proj_row = [r for r in pvp_reader if "Layer 1" in r[0] and "Time-Series" in r[1] and "Project" in r[2]][0]
        self.assertEqual(l1_proj_row[8], "0.9932")
        self.assertEqual(l1_proj_row[11], "completed")

        l2_proj_row = [r for r in pvp_reader if "Layer 2" in r[0] and "Time-Series" in r[1] and "Project" in r[2]][0]
        self.assertEqual(l2_proj_row[8], "0.9912")
        self.assertEqual(l2_proj_row[11], "completed")

        # 3. Check corrected_vs_random_splits.csv
        split_csv = written["corrected_vs_random_splits"].read_text(encoding="utf-8")
        split_reader = list(csv.reader(io.StringIO(split_csv)))

        # L1 flow random vs group disjoint
        l1_fr = [r for r in split_reader if "Layer 1" in r[0] and "Stratified Random" in r[2]][0]
        l1_gd = [r for r in split_reader if "Layer 1" in r[0] and "Session/Scenario" in r[2]][0]
        self.assertEqual(l1_fr[6], "0.9932")
        self.assertEqual(l1_fr[7], "0.0008")
        self.assertEqual(l1_fr[9], "completed")
        self.assertEqual(l1_gd[6], "0.9435")
        self.assertEqual(l1_gd[7], "0.0050")
        self.assertEqual(l1_gd[9], "completed")

        # L2 flow random vs group disjoint
        l2_fr = [r for r in split_reader if "Layer 2" in r[0] and "Stratified Random" in r[2]][0]
        l2_gd = [r for r in split_reader if "Layer 2" in r[0] and "Session/Scenario" in r[2]][0]
        self.assertEqual(l2_fr[6], "0.9912")
        self.assertEqual(l2_fr[7], "0.0009")
        self.assertEqual(l2_fr[9], "completed")
        self.assertEqual(l2_gd[6], "0.9100")
        self.assertEqual(l2_gd[7], "0.0085")
        self.assertEqual(l2_gd[9], "completed")

        # 4. Check improvements.csv marks BiGRU architecture implemented
        imp_csv = written["improvements"].read_text(encoding="utf-8")
        imp_reader = list(csv.reader(io.StringIO(imp_csv)))
        arch_row = [r for r in imp_reader if "Mask-Aware BiGRU" in r[1]][0]
        self.assertEqual(arch_row[5], "implemented")

    def test_window_sweeps_falls_back_to_group_disjoint_when_flow_random_absent(self) -> None:
        """When flow-random is absent, window sweeps must fall back to group-disjoint with [Project-Corrected]."""
        gd_only_payload = {
            "manifest_version": "1.0.0",
            "task": "both",
            "execution_mode": "train",
            "status": "training_completed",
            "runs": [
                {
                    "task": "l1",
                    "model": "paper_v4",
                    "window_size": 6,
                    "split_protocol": "session_scenario_disjoint",
                    "precision": 0.9450,
                    "recall": 0.9420,
                    "f1_score": 0.9435,
                    "fpr": 0.0050,
                    "latencies_seconds": {"mean_duration": 0.572, "median_duration": 0.046},
                },
            ],
        }
        gd_file = Path(self.temp_dir.name) / "gd_only_metrics.json"
        with open(gd_file, "w", encoding="utf-8") as f:
            json.dump(gd_only_payload, f)

        out_gd = Path(self.temp_dir.name) / "reports_gd_fallback"
        written = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=out_gd,
            phase2_metrics_path=gd_file,
        )

        ts_csv = written["timeseries_window_sweeps"].read_text(encoding="utf-8")
        ts_reader = list(csv.reader(io.StringIO(ts_csv)))
        l1_w6 = [r for r in ts_reader if "Layer 1" in r[0] and r[1] == "6" and "Project" in r[2]][0]
        # Must fall back to group-disjoint and carry [Project-Corrected] badge
        self.assertEqual(l1_w6[3], "[Project-Corrected]")
        self.assertEqual(l1_w6[4], "session_scenario_disjoint")
        self.assertEqual(l1_w6[5], "0.9450")
        self.assertEqual(l1_w6[7], "0.9435")
        self.assertEqual(l1_w6[10], "completed")


class TestReportCLIDeterministicOutput(unittest.TestCase):
    """Verify that repeated invocations produce byte-identical artifacts."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_a = Path(self.temp_dir.name) / "run_a"
        self.dir_b = Path(self.temp_dir.name) / "run_b"
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repeated_runs_produce_byte_identical_artifacts(self) -> None:
        """Artifacts from run_a and run_b must be bitwise identical."""
        written_a = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.dir_a,
        )
        written_b = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.dir_b,
        )

        self.assertEqual(set(written_a.keys()), set(written_b.keys()))

        for key in written_a:
            bytes_a = written_a[key].read_bytes()
            bytes_b = written_b[key].read_bytes()
            self.assertEqual(
                bytes_a,
                bytes_b,
                f"Artifact '{key}' is not byte-identical across runs.",
            )


class TestReportCLIOverwriteGuard(unittest.TestCase):
    """Verify overwrite guard behavior on non-empty directories."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "protected_dir"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.sentinel = self.out_dir / "sentinel.txt"
        self.sentinel.write_text("critical pre-existing data", encoding="utf-8")
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_refuses_overwrite_without_force(self) -> None:
        """Calling generate_report without force on non-empty directory must raise FileExistsError."""
        with self.assertRaises(FileExistsError) as ctx:
            generate_report(
                phase1_l1_path=self.l1_evidence,
                phase1_l2_path=self.l2_evidence,
                output_dir=self.out_dir,
                force=False,
            )
        self.assertIn("not empty", str(ctx.exception))
        # Ensure sentinel file is intact and untouched
        self.assertTrue(self.sentinel.is_file())
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "critical pre-existing data")
        # Ensure no report CSVs were partially written
        self.assertFalse((self.out_dir / "statistical_comparison.csv").exists())

    def test_cli_main_exit_code_on_overwrite(self) -> None:
        """CLI main must return exit code 1 when attempting to overwrite without --force."""
        ret = main([
            "--phase1-l1", str(self.l1_evidence),
            "--phase1-l2", str(self.l2_evidence),
            "--output-dir", str(self.out_dir),
            "--quiet",
        ])
        self.assertEqual(ret, 1)
        self.assertTrue(self.sentinel.is_file())

    def test_overwrites_successfully_with_force(self) -> None:
        """Specifying force=True must allow overwriting and write all report files."""
        written = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.out_dir,
            force=True,
        )
        self.assertIn("markdown", written)
        self.assertTrue((self.out_dir / "comparison_report.md").is_file())
        self.assertTrue((self.out_dir / "statistical_comparison.csv").is_file())


class TestReportCLISchemaValidation(unittest.TestCase):
    """Verify strict schema rejection of invalid, corrupted, or mismatched inputs."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "schema_out"
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rejects_missing_input_file(self) -> None:
        """Non-existent evidence file must raise FileNotFoundError and CLI exit 1."""
        non_existent = Path(self.temp_dir.name) / "does_not_exist.json"
        with self.assertRaises(FileNotFoundError):
            generate_report(
                phase1_l1_path=non_existent,
                phase1_l2_path=self.l2_evidence,
                output_dir=self.out_dir,
            )

        ret = main([
            "--phase1-l1", str(non_existent),
            "--phase1-l2", str(self.l2_evidence),
            "--output-dir", str(self.out_dir),
            "--quiet",
        ])
        self.assertEqual(ret, 1)

    def test_rejects_incompatible_manifest_version(self) -> None:
        """Phase 1 payload with version 2.0.0 must raise IncompatibleMetricSchemaError and CLI exit 2."""
        corrupt_p1 = Path(self.temp_dir.name) / "corrupt_l1.json"
        with open(self.l1_evidence, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["manifest_version"] = "2.0.0"  # Incompatible version
        with open(corrupt_p1, "w", encoding="utf-8") as f:
            json.dump(data, f)

        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            generate_report(
                phase1_l1_path=corrupt_p1,
                phase1_l2_path=self.l2_evidence,
                output_dir=self.out_dir,
            )
        self.assertIn("manifest_version", str(ctx.exception))

        ret = main([
            "--phase1-l1", str(corrupt_p1),
            "--phase1-l2", str(self.l2_evidence),
            "--output-dir", str(self.out_dir),
            "--quiet",
        ])
        self.assertEqual(ret, 2)

    def test_rejects_task_mismatch(self) -> None:
        """Passing L2 evidence to --phase1-l1 must raise IncompatibleMetricSchemaError."""
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            generate_report(
                phase1_l1_path=self.l2_evidence,  # Mismatched task (l2 instead of l1)
                phase1_l2_path=self.l2_evidence,
                output_dir=self.out_dir,
            )
        self.assertIn("expected 'l1'", str(ctx.exception))

    def test_rejects_corrupted_timeseries_metrics(self) -> None:
        """Corrupted timeseries metrics (e.g., window_size > 10) must raise IncompatibleMetricSchemaError."""
        corrupt_p2 = Path(self.temp_dir.name) / "corrupt_p2.json"
        bad_ts_data = {
            "manifest_version": "1.0.0",
            "task": "l1",
            "window_sweep": [
                {"window_size": 25, "metrics": {"f1_score": 0.99}}  # Max is 10
            ],
        }
        with open(corrupt_p2, "w", encoding="utf-8") as f:
            json.dump(bad_ts_data, f)

        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            generate_report(
                phase1_l1_path=self.l1_evidence,
                phase1_l2_path=self.l2_evidence,
                output_dir=self.out_dir,
                phase2_metrics_path=corrupt_p2,
            )
        self.assertIn("window_size", str(ctx.exception))


class TestReportCLISubprocessInvocation(unittest.TestCase):
    """Verify that the CLI can be executed as a standalone shell process."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "cli_proc_out"
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"
        self.script_path = SCRIPTS_DIR / "generate_report.py"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_help_flag_displays_usage(self) -> None:
        """--help flag must return code 0 and describe required evidence paths."""
        proc = subprocess.run(
            [sys.executable, str(self.script_path), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--phase1-l1", proc.stdout)
        self.assertIn("--phase1-l2", proc.stdout)
        self.assertIn("--output-dir", proc.stdout)
        self.assertIn("--force", proc.stdout)

    def test_subprocess_execution_generates_artifacts(self) -> None:
        """Executing CLI via subprocess produces full report suite and prints summary."""
        proc = subprocess.run(
            [
                sys.executable,
                str(self.script_path),
                "--phase1-l1", str(self.l1_evidence),
                "--phase1-l2", str(self.l2_evidence),
                "--output-dir", str(self.out_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"CLI stderr: {proc.stderr}")
        self.assertIn("Report generation complete", proc.stdout)
        self.assertIn("comparison_report.md", proc.stdout)
        self.assertIn("statistical_comparison.csv", proc.stdout)

        # Check files on disk
        self.assertTrue((self.out_dir / "comparison_report.md").is_file())
        self.assertTrue((self.out_dir / "statistical_comparison.csv").is_file())
        self.assertTrue((self.out_dir / "timeseries_window_sweeps.csv").is_file())
        self.assertTrue((self.out_dir / "paper_vs_project.csv").is_file())
        self.assertTrue((self.out_dir / "corrected_vs_random_splits.csv").is_file())
        self.assertTrue((self.out_dir / "latency_tradeoffs.csv").is_file())
        self.assertTrue((self.out_dir / "improvements.csv").is_file())

def _make_cli_latency_benchmark(
    task: str = "l1",
    model: str = "paper_v4",
    window_size: int = 6,
    split_protocol: str = "session_scenario_disjoint",
    sample_count: int = 500,
    device: str = "cpu",
    device_name: str = "Apple M3 Max",
    col_mean: float = 0.523,
    prep_mean_ms: float = 0.042,
    infer_mean_ms: float = 1.120,
    e2e_mean: float = 0.524,
) -> dict[str, Any]:
    return {
        "task": task,
        "model": model,
        "window_size": window_size,
        "split_protocol": split_protocol,
        "device": device,
        "device_name": device_name,
        "sample_count": sample_count,
        "batch_size": 1,
        "warmup_iterations": 10,
        "claim_boundary": "Phase A operational latency microbenchmarks measured on first-window-per-test-flow samples with batch size 1.",
        "traffic_collection_delay": {
            "count": sample_count,
            "mean_seconds": col_mean,
            "median_seconds": col_mean * 0.1,
            "p50_seconds": col_mean * 0.1,
            "p95_seconds": col_mean * 0.9,
            "p99_seconds": col_mean * 1.0,
            "min_seconds": 0.001,
            "max_seconds": col_mean * 1.5,
            "std_seconds": 0.05,
            "mean_ms": col_mean * 1000.0,
            "median_ms": col_mean * 100.0,
            "p50_ms": col_mean * 100.0,
            "p95_ms": col_mean * 900.0,
            "p99_ms": col_mean * 1000.0,
            "min_ms": 1.0,
            "max_ms": col_mean * 1500.0,
            "std_ms": 50.0,
        },
        "preprocessing_latency": {
            "count": sample_count,
            "mean_seconds": prep_mean_ms / 1000.0,
            "median_seconds": (prep_mean_ms * 0.9) / 1000.0,
            "p50_seconds": (prep_mean_ms * 0.9) / 1000.0,
            "p95_seconds": (prep_mean_ms * 1.1) / 1000.0,
            "p99_seconds": (prep_mean_ms * 1.2) / 1000.0,
            "min_seconds": 0.00001,
            "max_seconds": 0.0001,
            "std_seconds": 0.00001,
            "mean_ms": prep_mean_ms,
            "median_ms": prep_mean_ms * 0.9,
            "p50_ms": prep_mean_ms * 0.9,
            "p95_ms": prep_mean_ms * 1.1,
            "p99_ms": prep_mean_ms * 1.2,
            "min_ms": 0.01,
            "max_ms": 0.1,
            "std_ms": 0.01,
        },
        "inference_latency": {
            "count": sample_count,
            "mean_seconds": infer_mean_ms / 1000.0,
            "median_seconds": (infer_mean_ms * 0.95) / 1000.0,
            "p50_seconds": (infer_mean_ms * 0.95) / 1000.0,
            "p95_seconds": (infer_mean_ms * 1.1) / 1000.0,
            "p99_seconds": (infer_mean_ms * 1.2) / 1000.0,
            "min_seconds": 0.0005,
            "max_seconds": 0.002,
            "std_seconds": 0.0001,
            "mean_ms": infer_mean_ms,
            "median_ms": infer_mean_ms * 0.95,
            "p50_ms": infer_mean_ms * 0.95,
            "p95_ms": infer_mean_ms * 1.1,
            "p99_ms": infer_mean_ms * 1.2,
            "min_ms": 0.5,
            "max_ms": 2.0,
            "std_ms": 0.1,
            "throughput_samples_per_second": 1000.0 / infer_mean_ms,
        },
        "end_to_end_latency": {
            "count": sample_count,
            "mean_seconds": e2e_mean,
            "median_seconds": e2e_mean * 0.1,
            "p50_seconds": e2e_mean * 0.1,
            "p95_seconds": e2e_mean * 0.9,
            "p99_seconds": e2e_mean * 1.0,
            "min_seconds": 0.002,
            "max_seconds": e2e_mean * 1.5,
            "std_seconds": 0.05,
            "mean_ms": e2e_mean * 1000.0,
            "median_ms": e2e_mean * 100.0,
            "p50_ms": e2e_mean * 100.0,
            "p95_ms": e2e_mean * 900.0,
            "p99_ms": e2e_mean * 1000.0,
            "min_ms": 2.0,
            "max_ms": e2e_mean * 1500.0,
            "std_ms": 50.0,
        },
    }


def _make_cli_latency_payload(benchmarks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "manifest_version": "1.0.0",
        "generated_at_utc": "2026-10-17T09:00:00Z",
        "claim_boundary": "Phase A operational latency microbenchmarks measured on first-window-per-test-flow samples.",
        "total_benchmarks": len(benchmarks),
        "benchmarks": benchmarks,
    }


class TestReportCLIWithPhase2Latency(unittest.TestCase):
    """Verify report generation with optional --phase2-latency artifact."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp_dir.name) / "reports"
        self.l1_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        self.l2_evidence = REPO_ROOT / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_omitted_phase2_latency_matches_baseline(self) -> None:
        """When phase2_latency_path is omitted, latency_tradeoffs.csv has exactly 8 lines (header + 7 paper rows)."""
        written = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.out_dir,
            phase2_latency_path=None,
        )
        csv_text = written["latency_tradeoffs"].read_text(encoding="utf-8")
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(len(reader), 8)
        self.assertEqual(reader[0][0], "Layer")
        self.assertIn("Paper RF", reader[1][1])
        for row in reader[1:]:
            self.assertNotIn("[Project-Observed]", row[1])

    def test_phase2_latency_appends_project_observed_rows(self) -> None:
        """Providing valid latency_benchmarks.json appends [Project-Observed] component rows."""
        lat_file = Path(self.temp_dir.name) / "latency_benchmarks.json"
        benchmarks = [
            _make_cli_latency_benchmark(
                task="l1",
                model="paper_v4",
                window_size=6,
                split_protocol="session_scenario_disjoint",
                sample_count=500,
                device="cpu",
                device_name="Apple M3 Max",
            ),
            _make_cli_latency_benchmark(
                task="l2",
                model="improved_bidi_gru",
                window_size=3,
                split_protocol="session_scenario_disjoint",
                sample_count=450,
                device="cuda:0",
                device_name="NVIDIA T4",
            ),
        ]
        payload = _make_cli_latency_payload(benchmarks)
        lat_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        written = generate_report(
            phase1_l1_path=self.l1_evidence,
            phase1_l2_path=self.l2_evidence,
            output_dir=self.out_dir,
            phase2_latency_path=lat_file,
        )

        csv_text = written["latency_tradeoffs"].read_text(encoding="utf-8")
        reader = list(csv.reader(io.StringIO(csv_text)))
        # 1 header + 7 paper + 4 L1 + 4 L2 = 16 rows
        self.assertEqual(len(reader), 16)

        # First 7 rows are paper
        for r in reader[1:8]:
            self.assertNotIn("[Project-Observed]", r[1])

        # Next 8 rows are project-observed
        project_rows = reader[8:]
        self.assertEqual(len(project_rows), 8)
        for r in project_rows:
            self.assertIn("[Project-Observed]", r[1])

        # Check explicit device / hardware
        l1_rows = project_rows[:4]
        for r in l1_rows:
            self.assertIn("Apple M3 Max", r[1])
            self.assertIn("First 6 clumps", r[2])
            self.assertIn("n=500", r[2])

        l2_rows = project_rows[4:]
        for r in l2_rows:
            self.assertIn("NVIDIA T4", r[1])
            self.assertIn("First 3 clumps", r[2])
            self.assertIn("n=450", r[2])

        # Check Markdown document contains the new rows
        md_text = written["markdown"].read_text(encoding="utf-8")
        self.assertIn("Traffic Collection Delay", md_text)
        self.assertIn("Apple M3 Max", md_text)
        self.assertIn("NVIDIA T4", md_text)

    def test_subprocess_cli_with_phase2_latency(self) -> None:
        """CLI invocation via subprocess with --phase2-latency succeeds with exit code 0."""
        lat_file = Path(self.temp_dir.name) / "latency_benchmarks.json"
        benchmarks = [
            _make_cli_latency_benchmark(task="l1", model="paper_v4", window_size=6),
        ]
        payload = _make_cli_latency_payload(benchmarks)
        lat_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "generate_report.py"),
            "--phase1-l1",
            str(self.l1_evidence),
            "--phase1-l2",
            str(self.l2_evidence),
            "--phase2-latency",
            str(lat_file),
            "--output-dir",
            str(self.out_dir),
            "--quiet",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, f"CLI stderr: {proc.stderr}")
        self.assertTrue((self.out_dir / "latency_tradeoffs.csv").is_file())

        csv_text = (self.out_dir / "latency_tradeoffs.csv").read_text(encoding="utf-8")
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertEqual(len(reader), 12)  # 1 header + 7 paper + 4 project

    def test_invalid_phase2_latency_schema_exits_code_2(self) -> None:
        """Malformed latency benchmarks payload causes CLI to exit with code 2."""
        bad_lat_file = Path(self.temp_dir.name) / "bad_latency.json"
        bad_payload = {
            "manifest_version": "1.0.0",
            "claim_boundary": "Test boundary",
            "total_benchmarks": 1,
            "benchmarks": [{"task": "invalid_task"}],
        }
        bad_lat_file.write_text(json.dumps(bad_payload, indent=2), encoding="utf-8")

        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "generate_report.py"),
            "--phase1-l1",
            str(self.l1_evidence),
            "--phase1-l2",
            str(self.l2_evidence),
            "--phase2-latency",
            str(bad_lat_file),
            "--output-dir",
            str(self.out_dir),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Schema Error", proc.stderr)

    def test_invalid_phase2_latency_raises_programmatic(self) -> None:
        """Programmatic generate_report raises IncompatibleMetricSchemaError on malformed latency input."""
        bad_lat_file = Path(self.temp_dir.name) / "bad_latency.json"
        bad_payload = {
            "manifest_version": "1.0.0",
            "claim_boundary": "Test boundary",
            "total_benchmarks": 99,
            "benchmarks": [],
        }
        bad_lat_file.write_text(json.dumps(bad_payload, indent=2), encoding="utf-8")

        with self.assertRaises(IncompatibleMetricSchemaError):
            generate_report(
                phase1_l1_path=self.l1_evidence,
                phase1_l2_path=self.l2_evidence,
                output_dir=self.out_dir,
                phase2_latency_path=bad_lat_file,
            )

if __name__ == "__main__":
    unittest.main()
