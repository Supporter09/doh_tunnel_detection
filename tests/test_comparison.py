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
    load_timeseries_metrics,
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


if __name__ == "__main__":
    unittest.main()
