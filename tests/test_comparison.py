"""Comprehensive unit tests for comparison.py.

Verifies:
1. Exact paper-reported values for Tables III, IV, V, and VI.
2. Immutability of paper tables.
3. Provenance labels and badges on every generated row.
4. Deterministic stable ordering across multiple runs.
5. Unavailable-result behavior (never 0.0 or fabricated numbers).
6. Strict rejection of incompatible metric schemas.
7. End-to-end integration with repository manifests.
"""

from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path
from typing import Any

from doh_reproduction.comparison import (
    PAPER_TABLE_III,
    PAPER_TABLE_IV,
    PAPER_TABLE_V,
    PAPER_TABLE_VI,
    UNAVAILABLE_STR,
    ComparisonTable,
    IncompatibleMetricSchemaError,
    LayerTask,
    Paradigm,
    PaperStatisticalRow,
    PaperTimeSeriesRow,
    ProvenanceStatus,
    SplitProtocol,
    export_all_tables_to_csv,
    export_all_tables_to_markdown,
    format_latency,
    format_metric,
    generate_full_comparison_report,
    generate_improvements_table,
    generate_latency_tradeoff_table,
    generate_paper_vs_project_table,
    generate_split_leakage_comparison_table,
    generate_statistical_table,
    generate_timeseries_window_sweep_table,
    get_paper_table_iii,
    get_paper_table_iv,
    get_paper_table_v,
    get_paper_table_vi,
    load_evidence_json,
    load_latency_benchmarks,
    load_timeseries_metrics,
    validate_latency_benchmarks_schema,
    validate_phase1_evidence_schema,
    validate_timeseries_metrics_schema,
)


class TestPaperReportedTablesExactValues(unittest.TestCase):
    """Verify exact values published in MontazeriShatoori et al. (2020) for Tables III–VI."""

    def test_table_iii_exact_values(self) -> None:
        """Table III: Layer 1 Statistical (28 features, 80/20 flow split)."""
        table = get_paper_table_iii()
        self.assertEqual(len(table), 6)

        expected = [
            ("Random Forest (RF)", 0.993, 0.993, 0.993, 1.397, 20.393),
            ("C4.5 Decision Tree", 0.993, 0.993, 0.993, 1.397, 20.393),
            ("2D CNN", 0.980, 0.980, 0.980, 1.397, 20.393),
            ("DNN", 0.970, 0.970, 0.970, 1.397, 20.393),
            ("SVM", 0.877, 0.877, 0.877, 1.397, 20.393),
            ("Naive Bayes (NB)", 0.840, 0.834, 0.833, 1.397, 20.393),
        ]

        for row, (exp_model, exp_p, exp_r, exp_f1, exp_med, exp_mean) in zip(table, expected):
            self.assertEqual(row.model_name, exp_model)
            self.assertEqual(row.layer, LayerTask.L1)
            self.assertAlmostEqual(row.precision, exp_p, places=3)
            self.assertAlmostEqual(row.recall, exp_r, places=3)
            self.assertAlmostEqual(row.f1_score, exp_f1, places=3)
            self.assertAlmostEqual(row.median_latency_seconds, exp_med, places=3)
            self.assertAlmostEqual(row.mean_latency_seconds, exp_mean, places=3)
            self.assertEqual(row.provenance, ProvenanceStatus.PAPER_REPORTED)
            self.assertEqual(row.split_protocol, SplitProtocol.PAPER_FLOW_RANDOM)

    def test_table_iv_exact_values(self) -> None:
        """Table IV: Layer 2 Statistical (28 features, 80/20 flow split)."""
        table = get_paper_table_iv()
        self.assertEqual(len(table), 6)

        expected = [
            ("Random Forest (RF)", 0.999, 0.999, 0.999, 34.064, 53.924),
            ("C4.5 Decision Tree", 0.999, 0.999, 0.999, 34.064, 53.924),
            ("2D CNN", 0.990, 0.990, 0.990, 34.064, 53.924),
            ("DNN", 0.980, 0.980, 0.980, 34.064, 53.924),
            ("SVM", 0.890, 0.885, 0.884, 34.064, 53.924),
            ("Naive Bayes (NB)", 0.836, 0.833, 0.832, 34.064, 53.924),
        ]

        for row, (exp_model, exp_p, exp_r, exp_f1, exp_med, exp_mean) in zip(table, expected):
            self.assertEqual(row.model_name, exp_model)
            self.assertEqual(row.layer, LayerTask.L2)
            self.assertAlmostEqual(row.precision, exp_p, places=3)
            self.assertAlmostEqual(row.recall, exp_r, places=3)
            self.assertAlmostEqual(row.f1_score, exp_f1, places=3)
            self.assertAlmostEqual(row.median_latency_seconds, exp_med, places=3)
            self.assertAlmostEqual(row.mean_latency_seconds, exp_mean, places=3)
            self.assertEqual(row.provenance, ProvenanceStatus.PAPER_REPORTED)

    def test_table_v_exact_values_and_optimal_threshold(self) -> None:
        """Table V: Layer 1 Time-Series LSTM (l in 1..10). Optimal is l=6."""
        table = get_paper_table_v()
        self.assertEqual(len(table), 10)

        expected_rows = [
            (1, 0.877, 0.876, 0.876, 0.081, 0.000, False),
            (2, 0.950, 0.949, 0.949, 0.167, 0.002, False),
            (3, 0.953, 0.951, 0.951, 0.262, 0.010, False),
            (4, 0.983, 0.983, 0.983, 0.366, 0.020, False),
            (5, 0.987, 0.987, 0.987, 0.468, 0.030, False),
            (6, 0.993, 0.993, 0.993, 0.574, 0.047, True),  # Optimal threshold
            (7, 0.996, 0.996, 0.996, 0.675, 0.060, False),
            (8, 0.996, 0.996, 0.996, 0.775, 0.077, False),
            (9, 0.998, 0.998, 0.998, 0.871, 0.091, False),
            (10, 0.998, 0.998, 0.998, 0.964, 0.105, False),
        ]

        for row, (l, p, r, f1, mean_d, med_d, opt) in zip(table, expected_rows):
            self.assertEqual(row.window_length_l, l)
            self.assertEqual(row.layer, LayerTask.L1)
            self.assertAlmostEqual(row.precision, p, places=3)
            self.assertAlmostEqual(row.recall, r, places=3)
            self.assertAlmostEqual(row.f1_score, f1, places=3)
            self.assertAlmostEqual(row.mean_duration_seconds, mean_d, places=3)
            self.assertAlmostEqual(row.median_duration_seconds, med_d, places=3)
            self.assertEqual(row.is_optimal, opt)
            self.assertEqual(row.provenance, ProvenanceStatus.PAPER_REPORTED)

    def test_table_vi_exact_values_and_optimal_threshold(self) -> None:
        """Table VI: Layer 2 Time-Series LSTM (l in 1..10). Optimal is l=3."""
        table = get_paper_table_vi()
        self.assertEqual(len(table), 10)

        expected_rows = [
            (1, 0.825, 0.792, 0.782, 0.164, 0.002, False),
            (2, 0.985, 0.984, 0.985, 0.329, 0.022, False),
            (3, 0.991, 0.991, 0.991, 0.502, 0.050, True),  # Optimal threshold
            (4, 0.995, 0.995, 0.995, 0.685, 0.094, False),
            (5, 0.997, 0.997, 0.997, 0.872, 0.142, False),
            (6, 0.998, 0.998, 0.998, 1.063, 0.203, False),
            (7, 0.997, 0.997, 0.997, 1.260, 0.258, False),
            (8, 0.999, 0.999, 0.999, 1.450, 0.313, False),
            (9, 0.999, 0.999, 0.999, 1.630, 0.373, False),
            (10, 0.999, 0.999, 0.999, 1.803, 0.440, False),
        ]

        for row, (l, p, r, f1, mean_d, med_d, opt) in zip(table, expected_rows):
            self.assertEqual(row.window_length_l, l)
            self.assertEqual(row.layer, LayerTask.L2)
            self.assertAlmostEqual(row.precision, p, places=3)
            self.assertAlmostEqual(row.recall, r, places=3)
            self.assertAlmostEqual(row.f1_score, f1, places=3)
            self.assertAlmostEqual(row.mean_duration_seconds, mean_d, places=3)
            self.assertAlmostEqual(row.median_duration_seconds, med_d, places=3)
            self.assertEqual(row.is_optimal, opt)
            self.assertEqual(row.provenance, ProvenanceStatus.PAPER_REPORTED)

    def test_paper_tables_are_immutable(self) -> None:
        """Paper records and tuple containers must raise errors on mutation attempts."""
        row_iii = PAPER_TABLE_III[0]
        with self.assertRaises((TypeError, AttributeError)):
            row_iii.precision = 0.5  # type: ignore

        with self.assertRaises((TypeError, AttributeError)):
            PAPER_TABLE_III[0] = row_iii  # type: ignore


class TestProvenanceAndOrdering(unittest.TestCase):
    """Verify that all rows have explicit provenance badges and stable deterministic ordering."""

    def test_provenance_badge_presence(self) -> None:
        """All provenance statuses must have defined badges and appear in tables."""
        for p in ProvenanceStatus:
            self.assertTrue(p.badge.startswith("[") and p.badge.endswith("]"))

        table = generate_statistical_table()
        for row in table.rows:
            provenance_cell = row[2]
            self.assertTrue(
                any(b in provenance_cell for b in [
                    "[Paper-Reported]", "[Project-Observed]", "[Project-Calibrated]",
                    "[Project-Replication]", "[Project-Corrected]", "[Unavailable]"
                ]),
                f"Row missing valid provenance badge: {row}"
            )

    def test_deterministic_stable_ordering(self) -> None:
        """Repeated invocations of table generation must produce byte-identical output."""
        table1 = generate_timeseries_window_sweep_table()
        table2 = generate_timeseries_window_sweep_table()

        self.assertEqual(table1.to_markdown(), table2.to_markdown())
        self.assertEqual(table1.to_csv(), table2.to_csv())

        # Check window ordering: l strictly goes 1..10 for Layer 1, then 1..10 for Layer 2
        l1_windows = [r[1] for r in table1.rows if "Layer 1" in r[0] and "Paper" in r[2]]
        l2_windows = [r[1] for r in table1.rows if "Layer 2" in r[0] and "Paper" in r[2]]
        self.assertEqual(l1_windows, list(range(1, 11)))
        self.assertEqual(l2_windows, list(range(1, 11)))


class TestUnavailableResultBehavior(unittest.TestCase):
    """Verify that missing future results render as 'unavailable', never 0.0 or fabricated numbers."""

    def test_missing_future_statistical_results(self) -> None:
        """When evidence is omitted, project rows must display unavailable without 0.0 metrics."""
        table = generate_statistical_table(evidence_l1=None, evidence_l2=None)
        csv_str = table.to_csv()

        # Find project rows
        reader = csv.reader(io.StringIO(csv_str))
        headers = next(reader)
        project_rows = [r for r in reader if "Project Tabular Baseline" in r[1]]

        self.assertGreater(len(project_rows), 0)
        for r in project_rows:
            self.assertEqual(r[2], "[Unavailable]")
            # Precision, Recall, F1, FPR must be UNAVAILABLE_STR, never '0.0' or '0'
            self.assertEqual(r[4], UNAVAILABLE_STR)
            self.assertEqual(r[5], UNAVAILABLE_STR)
            self.assertEqual(r[6], UNAVAILABLE_STR)
            self.assertEqual(r[7], UNAVAILABLE_STR)
            self.assertNotIn("0.0", r[4:8])
            self.assertNotIn("0", r[4:8])

    def test_missing_future_timeseries_windows(self) -> None:
        """When partial timeseries results are provided, missing windows render as unavailable."""
        partial_l1 = {
            "manifest_version": "1.0.0",
            "task": "l1",
            "window_sweep": [
                {
                    "window_size": 6,
                    "metrics": {"precision": 0.9935, "recall": 0.9930, "f1_score": 0.9932},
                    "latencies_seconds": {"mean_duration": 0.570, "median_duration": 0.045},
                }
            ],
        }

        table = generate_timeseries_window_sweep_table(l1_metrics=partial_l1)
        csv_str = table.to_csv()
        reader = csv.reader(io.StringIO(csv_str))
        next(reader)  # header

        rows_by_window: dict[int, list[list[str]]] = {}
        for r in reader:
            if "Layer 1" in r[0]:
                w = int(r[1])
                rows_by_window.setdefault(w, []).append(r)

        # Window 6 has project run completed
        proj_w6 = [r for r in rows_by_window[6] if "Project" in r[2]][0]
        self.assertEqual(proj_w6[10], "completed")
        self.assertEqual(proj_w6[5], "0.9935")
        self.assertEqual(proj_w6[7], "0.9932")

        # Window 1 project run is unavailable
        proj_w1 = [r for r in rows_by_window[1] if "Project" in r[2]][0]
        self.assertEqual(proj_w1[10], "unavailable")
        self.assertEqual(proj_w1[3], "[Unavailable]")
        self.assertEqual(proj_w1[5], UNAVAILABLE_STR)
        self.assertEqual(proj_w1[6], UNAVAILABLE_STR)
        self.assertEqual(proj_w1[7], UNAVAILABLE_STR)
        self.assertNotIn("0.0", proj_w1[5:8])

    def test_format_metric_and_latency_helpers(self) -> None:
        """Format helpers must handle None gracefully without fabrication."""
        self.assertEqual(format_metric(None), UNAVAILABLE_STR)
        self.assertEqual(format_latency(None), UNAVAILABLE_STR)
        self.assertEqual(format_metric(0.99345, 3), "0.993")
        self.assertEqual(format_latency(1.397, 2), "1.40 s")


class TestObservedImprovementEvidence(unittest.TestCase):
    """Verify that improvement claims are derived from corrected observed runs."""

    def test_bi_gru_success_claim_uses_best_group_disjoint_f1(self) -> None:
        runs = []
        for task, baseline, improved in (
            ("l1", 0.917863, 0.965116),
            ("l2", 0.942457, 0.986439),
        ):
            runs.extend([
                {
                    "task": task,
                    "model": "paper_v4",
                    "window_size": 5,
                    "split_protocol": "session_scenario_disjoint",
                    "f1_score": baseline,
                },
                {
                    "task": task,
                    "model": "improved_bidi_gru",
                    "window_size": 7,
                    "split_protocol": "session_scenario_disjoint",
                    "f1_score": improved,
                },
            ])

        table = generate_improvements_table(timeseries_metrics={"runs": runs})
        neural_row = next(row for row in table.rows if row[0] == "5. Neural Architecture")

        self.assertEqual(neural_row[5], "verified improvement")
        self.assertIn("L1 0.9179->0.9651 (+4.73 pp)", neural_row[4])
        self.assertIn("L2 0.9425->0.9864 (+4.40 pp)", neural_row[4])

    def test_bi_gru_without_corrected_observations_is_not_claimed_successful(self) -> None:
        table = generate_improvements_table(
            timeseries_metrics={
                "runs": [{
                    "task": "l1",
                    "model": "improved_bidi_gru",
                    "window_size": 7,
                    "split_protocol": "paper_flow_random",
                    "f1_score": 0.99,
                }]
            }
        )
        neural_row = next(row for row in table.rows if row[0] == "5. Neural Architecture")

        self.assertEqual(neural_row[5], "implemented")
        self.assertIn("Awaiting observed comparison", neural_row[4])


class TestSchemaValidationAndRejection(unittest.TestCase):
    """Verify strict validation and rejection of invalid/incompatible metric payloads."""

    def test_rejects_missing_manifest_version(self) -> None:
        bad_payload = {"task": "l1", "models": {"rf": {"f1_macro": 0.99}}}
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_phase1_evidence_schema(bad_payload)
        self.assertIn("manifest_version", str(ctx.exception))

    def test_rejects_incompatible_manifest_version(self) -> None:
        bad_payload = {"manifest_version": "2.0.0", "task": "l1", "models": {"rf": {"f1_macro": 0.99}}}
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_phase1_evidence_schema(bad_payload)
        self.assertIn("Unsupported or missing manifest_version", str(ctx.exception))

    def test_rejects_invalid_task(self) -> None:
        bad_payload = {
            "manifest_version": "1.0.0",
            "task": "invalid_layer_task",
            "models": {"rf": {"f1_macro": 0.99}},
        }
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_phase1_evidence_schema(bad_payload)
        self.assertIn("task", str(ctx.exception))

    def test_rejects_empty_models(self) -> None:
        bad_payload = {"manifest_version": "1.0.0", "task": "l1", "models": {}}
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_phase1_evidence_schema(bad_payload)
        self.assertIn("non-empty dictionary", str(ctx.exception))

    def test_rejects_out_of_range_metrics(self) -> None:
        bad_payload = {
            "manifest_version": "1.0.0",
            "task": "l1",
            "models": {"rf": {"f1_macro": 1.5}},  # Out of [0, 1]
        }
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_phase1_evidence_schema(bad_payload)
        self.assertIn("out of valid range", str(ctx.exception))

    def test_rejects_negative_fpr(self) -> None:
        bad_payload = {
            "manifest_version": "1.0.0",
            "task": "l1",
            "models": {"rf": {"f1_macro": 0.99, "default_fpr": -0.05}},
        }
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_phase1_evidence_schema(bad_payload)
        self.assertIn("out of valid range", str(ctx.exception))

    def test_timeseries_rejects_invalid_window_size(self) -> None:
        bad_timeseries = {
            "manifest_version": "1.0.0",
            "task": "l1",
            "window_sweep": [
                {"window_size": 15, "metrics": {"f1_score": 0.99}}  # Max is 10
            ],
        }
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_timeseries_metrics_schema(bad_timeseries)
        self.assertIn("invalid window_size", str(ctx.exception))

    def test_timeseries_rejects_missing_metrics_or_sweep(self) -> None:
        bad_timeseries = {
            "manifest_version": "1.0.0",
            "task": "l1",
            "irrelevant_key": 123,
        }
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_timeseries_metrics_schema(bad_timeseries)
        self.assertIn("must contain 'metrics'", str(ctx.exception))


class TestManifestIntegration(unittest.TestCase):
    """Verify integration with actual repository manifest files."""

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent

    def test_load_phase1_evidence_files(self) -> None:
        """Existing repository Phase 1 manifests must pass schema validation."""
        l1_path = self.repo_root / "data" / "manifests" / "kaggle_phase1_l1_evidence.json"
        l2_path = self.repo_root / "data" / "manifests" / "kaggle_phase1_l2_evidence.json"

        if l1_path.is_file() and l2_path.is_file():
            l1_data = load_evidence_json(l1_path)
            l2_data = load_evidence_json(l2_path)
            self.assertEqual(l1_data["task"], "l1")
            self.assertEqual(l2_data["task"], "l2")

            # Generate full report with real manifests
            report = generate_full_comparison_report(evidence_l1=l1_data, evidence_l2=l2_data)
            self.assertEqual(len(report), 6)

            # Export Markdown & CSV
            md_doc = export_all_tables_to_markdown(report)
            csv_map = export_all_tables_to_csv(report)

            self.assertIn("Table III", md_doc)
            self.assertIn("Table IV", md_doc)
            self.assertIn("Random Forest", md_doc)
            self.assertEqual(len(csv_map), 6)
            for t_id, csv_content in csv_map.items():
                self.assertTrue(len(csv_content) > 50, f"CSV for {t_id} is unexpectedly empty.")

def _make_valid_latency_benchmark(
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


def _make_valid_latency_payload(benchmarks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "manifest_version": "1.0.0",
        "generated_at_utc": "2026-10-17T09:00:00Z",
        "claim_boundary": "Phase A operational latency microbenchmarks measured on first-window-per-test-flow samples.",
        "total_benchmarks": len(benchmarks),
        "benchmarks": benchmarks,
    }


class TestLatencyBenchmarksSchemaValidation(unittest.TestCase):
    """Verify strict validation and rejection of operational latency benchmark payloads."""

    def test_valid_schema_passes(self) -> None:
        payload = _make_valid_latency_payload([
            _make_valid_latency_benchmark(task="l1", model="paper_v4", window_size=6),
            _make_valid_latency_benchmark(task="l2", model="improved_bidi_gru", window_size=3),
        ])
        validate_latency_benchmarks_schema(payload)

    def test_rejects_missing_top_level_keys(self) -> None:
        for missing_key in ("manifest_version", "generated_at_utc", "claim_boundary", "total_benchmarks", "benchmarks"):
            payload = _make_valid_latency_payload([_make_valid_latency_benchmark()])
            del payload[missing_key]
            with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
                validate_latency_benchmarks_schema(payload)
            self.assertIn("Missing required top-level key", str(ctx.exception))

    def test_rejects_count_mismatch(self) -> None:
        payload = _make_valid_latency_payload([_make_valid_latency_benchmark()])
        payload["total_benchmarks"] = 5
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(payload)
        self.assertIn("does not match length", str(ctx.exception))

    def test_rejects_unrecognized_task(self) -> None:
        b = _make_valid_latency_benchmark(task="l3")
        payload = _make_valid_latency_payload([b])
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(payload)
        self.assertIn("unrecognized task", str(ctx.exception))

    def test_rejects_unrecognized_model(self) -> None:
        b = _make_valid_latency_benchmark(model="unknown_transformer")
        payload = _make_valid_latency_payload([b])
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(payload)
        self.assertIn("unrecognized model", str(ctx.exception))

    def test_rejects_unrecognized_split_protocol(self) -> None:
        b = _make_valid_latency_benchmark(split_protocol="arbitrary_split")
        payload = _make_valid_latency_payload([b])
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(payload)
        self.assertIn("unrecognized split_protocol", str(ctx.exception))

    def test_rejects_non_positive_sample_count(self) -> None:
        for bad_count in (0, -10):
            b = _make_valid_latency_benchmark(sample_count=bad_count)
            payload = _make_valid_latency_payload([b])
            with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
                validate_latency_benchmarks_schema(payload)
            self.assertIn("sample_count", str(ctx.exception))

    def test_rejects_batch_size_not_one(self) -> None:
        for bad_bs in (2, 0, 32):
            b = _make_valid_latency_benchmark()
            b["batch_size"] = bad_bs
            payload = _make_valid_latency_payload([b])
            with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
                validate_latency_benchmarks_schema(payload)
            self.assertIn("batch_size must be 1", str(ctx.exception))

    def test_rejects_missing_or_empty_claim_boundary(self) -> None:
        payload = _make_valid_latency_payload([_make_valid_latency_benchmark()])
        payload["claim_boundary"] = "   "
        with self.assertRaises(IncompatibleMetricSchemaError):
            validate_latency_benchmarks_schema(payload)

        b = _make_valid_latency_benchmark()
        b["claim_boundary"] = ""
        payload = _make_valid_latency_payload([b])
        with self.assertRaises(IncompatibleMetricSchemaError):
            validate_latency_benchmarks_schema(payload)

    def test_rejects_negative_or_infinite_metrics(self) -> None:
        b = _make_valid_latency_benchmark()
        b["traffic_collection_delay"]["mean_seconds"] = -0.5
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(_make_valid_latency_payload([b]))
        self.assertIn("must be non-negative and finite", str(ctx.exception))

        b = _make_valid_latency_benchmark()
        b["inference_latency"]["mean_ms"] = float("inf")
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(_make_valid_latency_payload([b]))
        self.assertIn("must be non-negative and finite", str(ctx.exception))

    def test_rejects_percentile_monotonicity_violation(self) -> None:
        b = _make_valid_latency_benchmark()
        b["inference_latency"]["p50_ms"] = 5.0
        b["inference_latency"]["p95_ms"] = 2.0  # p50 > p95!
        with self.assertRaises(IncompatibleMetricSchemaError) as ctx:
            validate_latency_benchmarks_schema(_make_valid_latency_payload([b]))
        self.assertIn("violates percentile monotonicity", str(ctx.exception))


class TestLatencyTradeoffGeneration(unittest.TestCase):
    """Verify Table 5 generation with and without operational latency evidence."""

    def test_omission_compatibility_preserves_seven_paper_rows(self) -> None:
        """When latency_benchmarks is None, table contains exactly 7 paper rows."""
        table = generate_latency_tradeoff_table(latency_benchmarks=None)
        self.assertEqual(len(table.rows), 7)
        # Check first row is paper baseline
        self.assertEqual(table.rows[0][0], LayerTask.L1.display_name)
        self.assertIn("Paper RF", table.rows[0][1])
        # Check no project-observed rows present
        for r in table.rows:
            self.assertNotIn("[Project-Observed]", r[1])

    def test_empty_benchmarks_omission_compatibility(self) -> None:
        """When benchmarks is empty list, table remains 7 paper rows."""
        payload = _make_valid_latency_payload([])
        table = generate_latency_tradeoff_table(latency_benchmarks=payload)
        self.assertEqual(len(table.rows), 7)

    def test_project_observed_rows_appended_for_session_disjoint(self) -> None:
        """Session-disjoint benchmarks append deterministic [Project-Observed] component rows."""
        b1 = _make_valid_latency_benchmark(
            task="l1",
            model="paper_v4",
            window_size=6,
            split_protocol="session_scenario_disjoint",
            sample_count=500,
            device="cpu",
            device_name="Apple M3 Max",
        )
        payload = _make_valid_latency_payload([b1])
        table = generate_latency_tradeoff_table(latency_benchmarks=payload)

        # 7 paper rows + 4 component rows = 11 rows
        self.assertEqual(len(table.rows), 11)

        # Verify paper rows remain intact in positions 0..6
        self.assertIn("Paper RF", table.rows[0][1])

        # Verify project rows in positions 7..10
        project_rows = table.rows[7:]
        self.assertEqual(len(project_rows), 4)

        expected_components = [
            "Traffic Collection Delay",
            "Sequence Preprocessing",
            "Model Inference",
            "End-to-End Latency",
        ]
        for idx, (row, comp_title) in enumerate(zip(project_rows, expected_components)):
            self.assertEqual(row[0], LayerTask.L1.display_name)
            # Provenance badge
            self.assertIn("[Project-Observed]", row[1])
            # Model name
            self.assertIn("Packet Clump LSTM", row[1])
            # Component name
            self.assertIn(comp_title, row[1])
            # Hardware/device
            self.assertIn("Apple M3 Max", row[1])
            # Window / Horizon with sample count
            self.assertIn("First 6 clumps", row[2])
            self.assertIn("n=500", row[2])

    def test_flow_random_benchmarks_filtered_out(self) -> None:
        """Benchmarks using paper_flow_random are excluded to prevent cross-session leakage rows."""
        b_rand = _make_valid_latency_benchmark(
            task="l1",
            model="paper_v4",
            window_size=6,
            split_protocol="paper_flow_random",
        )
        b_disj = _make_valid_latency_benchmark(
            task="l1",
            model="paper_v4",
            window_size=6,
            split_protocol="session_scenario_disjoint",
        )
        payload = _make_valid_latency_payload([b_rand, b_disj])
        table = generate_latency_tradeoff_table(latency_benchmarks=payload)

        # Only b_disj appended: 7 + 4 = 11 rows (b_rand skipped)
        self.assertEqual(len(table.rows), 11)

    def test_deterministic_ordering_layer_window_component(self) -> None:
        """Rows are strictly ordered: Layer 1 before Layer 2, window sizes ascending, components in pipeline order."""
        # Provide out-of-order benchmarks (L2 window 6, L1 window 6, L1 window 1)
        b_l2_w6 = _make_valid_latency_benchmark(task="l2", model="paper_v4", window_size=6)
        b_l1_w6 = _make_valid_latency_benchmark(task="l1", model="paper_v4", window_size=6)
        b_l1_w1 = _make_valid_latency_benchmark(task="l1", model="paper_v4", window_size=1)

        payload = _make_valid_latency_payload([b_l2_w6, b_l1_w6, b_l1_w1])
        table = generate_latency_tradeoff_table(latency_benchmarks=payload)

        # 7 paper + 3 * 4 = 19 rows
        self.assertEqual(len(table.rows), 19)

        # First 8 project rows must be Layer 1 (window 1, then window 6)
        p_rows = table.rows[7:]
        # Check window 1 comes first
        self.assertIn("First 1 clumps", p_rows[0][2])
        self.assertIn("Layer 1", p_rows[0][0])
        # Then window 6 Layer 1
        self.assertIn("First 6 clumps", p_rows[4][2])
        self.assertIn("Layer 1", p_rows[4][0])
        # Then window 6 Layer 2
        self.assertIn("First 6 clumps", p_rows[8][2])
        self.assertIn("Layer 2", p_rows[8][0])

    def test_units_not_mixed_and_inference_isolated(self) -> None:
        """Physical collection and end-to-end use 's'; preprocessing and inference use 'ms'."""
        b = _make_valid_latency_benchmark(
            task="l1",
            model="paper_v4",
            window_size=6,
            col_mean=0.523,
            prep_mean_ms=0.042,
            infer_mean_ms=1.120,
            e2e_mean=0.524,
        )
        payload = _make_valid_latency_payload([b])
        table = generate_latency_tradeoff_table(latency_benchmarks=payload)

        p_rows = table.rows[7:]
        col_row = p_rows[0]
        prep_row = p_rows[1]
        infer_row = p_rows[2]
        e2e_row = p_rows[3]

        # Collection in seconds
        self.assertTrue(col_row[4].endswith(" s"), f"Expected ' s' in {col_row[4]}")
        # Preprocessing in ms
        self.assertTrue(prep_row[4].endswith(" ms"), f"Expected ' ms' in {prep_row[4]}")
        # Inference in ms
        self.assertTrue(infer_row[4].endswith(" ms"), f"Expected ' ms' in {infer_row[4]}")
        # End-to-End in seconds
        self.assertTrue(e2e_row[4].endswith(" s"), f"Expected ' s' in {e2e_row[4]}")

        # Latency reduction on inference is N/A (sub-component) to avoid pretending inference = detection delay
        self.assertEqual(infer_row[6], "N/A (sub-component)")
        self.assertIn("does NOT equal detection delay", infer_row[7])

if __name__ == "__main__":
    unittest.main()
