"""Focused deterministic unit tests for PR-AUC and ROC-AUC metrics in statistical baseline runner."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Add the directory containing train_statistical.py to sys.path
SCRIPT_DIR = (
    Path(__file__).resolve().parent.parent
    / "experiments"
    / "kaggle"
    / "statistical_baseline"
)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import train_statistical
from train_statistical import (
    classify_feature_group,
    compute_ranking_metrics,
    extract_prediction_scores,
    run_training_pipeline,
    select_operating_threshold,
    validate_raw_config,
    validate_resolved_config,
)


class TestScoreAcquisitionAndRankingMetrics(unittest.TestCase):
    """Verify deterministic continuous score extraction and AUC metric calculation."""

    def test_probability_producing_model_path(self) -> None:
        """Verify predict_proba[:, 1] extraction and subsequent ranking metric calculation."""

        class ProbabilityModel:
            def predict_proba(self, X: Any) -> np.ndarray:
                # Shape (4, 2): column 1 contains positive class probabilities
                return np.array([[0.8, 0.2], [0.1, 0.9], [0.4, 0.6], [0.7, 0.3]])

        X = np.zeros((4, 2))
        y_true = np.array([0, 1, 1, 0])

        scores = extract_prediction_scores(ProbabilityModel(), X)
        self.assertIsNotNone(scores)
        np.testing.assert_allclose(scores, np.array([0.2, 0.9, 0.6, 0.3]))

        roc_auc, pr_auc = compute_ranking_metrics(y_true, scores)
        self.assertIsInstance(roc_auc, float)
        self.assertIsInstance(pr_auc, float)
        self.assertAlmostEqual(roc_auc, 1.0)
        self.assertAlmostEqual(pr_auc, 1.0)

    def test_decision_function_only_model_path(self) -> None:
        """Verify decision_function extraction and ranking metrics when predict_proba is absent."""

        class DecisionFunctionModel:
            def decision_function(self, X: Any) -> np.ndarray:
                # Shape (4,): unbounded margin scores
                return np.array([-2.5, 3.1, 1.4, -0.9])

        X = np.zeros((4, 2))
        y_true = np.array([0, 1, 1, 0])

        model = DecisionFunctionModel()
        self.assertFalse(hasattr(model, "predict_proba"))

        scores = extract_prediction_scores(model, X)
        self.assertIsNotNone(scores)
        np.testing.assert_allclose(scores, np.array([-2.5, 3.1, 1.4, -0.9]))

        roc_auc, pr_auc = compute_ranking_metrics(y_true, scores)
        self.assertIsInstance(roc_auc, float)
        self.assertIsInstance(pr_auc, float)
        self.assertAlmostEqual(roc_auc, 1.0)
        self.assertAlmostEqual(pr_auc, 1.0)

    def test_prefers_predict_proba_when_both_available(self) -> None:
        """Verify predict_proba is preferred over decision_function when both are present."""

        class DualScoringModel:
            def predict_proba(self, X: Any) -> np.ndarray:
                return np.array([[0.7, 0.3], [0.2, 0.8]])

            def decision_function(self, X: Any) -> np.ndarray:
                return np.array([-99.0, 99.0])

        scores = extract_prediction_scores(DualScoringModel(), np.zeros((2, 2)))
        self.assertIsNotNone(scores)
        np.testing.assert_allclose(scores, np.array([0.3, 0.8]))

    def test_unavailable_scoring_returns_none_and_null_metrics(self) -> None:
        """Verify models without continuous scoring yield None scores and null ranking metrics."""

        class DiscreteOnlyModel:
            def predict(self, X: Any) -> np.ndarray:
                return np.array([0, 1])

        scores = extract_prediction_scores(DiscreteOnlyModel(), np.zeros((2, 2)))
        self.assertIsNone(scores)

        roc_auc, pr_auc = compute_ranking_metrics(np.array([0, 1]), scores)
        self.assertIsNone(roc_auc)
        self.assertIsNone(pr_auc)

    def test_failed_scoring_returns_none_and_null_metrics(self) -> None:
        """Verify exceptions during scoring are gracefully caught and return null metrics."""

        class FailingPredictProbaModel:
            def predict_proba(self, X: Any) -> np.ndarray:
                raise RuntimeError("Internal numerical divergence")

        scores = extract_prediction_scores(FailingPredictProbaModel(), np.zeros((2, 2)))
        self.assertIsNone(scores)

        roc_auc, pr_auc = compute_ranking_metrics(np.array([0, 1]), scores)
        self.assertIsNone(roc_auc)
        self.assertIsNone(pr_auc)

    def test_single_class_y_true_returns_none_metrics(self) -> None:
        """Verify that single-class ground truth yields None without raising or fabricating values."""
        y_single = np.array([1, 1, 1, 1])
        scores = np.array([0.2, 0.5, 0.7, 0.9])

        roc_auc, pr_auc = compute_ranking_metrics(y_single, scores)
        self.assertIsNone(roc_auc)
        self.assertIsNone(pr_auc)


class TestEndToEndBaselineModelsPRAUC(unittest.TestCase):
    """Verify that all four baseline models produce valid pr_auc in the metrics JSON payload."""

    def test_all_four_models_produce_real_pr_auc_in_metrics_json(self) -> None:
        """Test GaussianNB, RandomForest, DecisionTree, and LinearSVC on valid binary data."""
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            csv_path = tmp_dir / "synthetic_binary_l1.csv"
            output_dir = tmp_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate synthetic separable binary data with documented L1 labels
            rng = np.random.RandomState(42)
            n_per_class = 40
            X_non_doh = rng.normal(loc=-1.5, scale=0.8, size=(n_per_class, 4))
            X_doh = rng.normal(loc=1.5, scale=0.8, size=(n_per_class, 4))
            X = np.vstack([X_non_doh, X_doh])
            labels = ["non_doh"] * n_per_class + ["doh"] * n_per_class

            df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(4)])
            df["Label"] = labels
            df.to_csv(csv_path, index=False)

            models = ["gaussian_nb", "random_forest", "decision_tree", "linear_svm"]
            run_training_pipeline(
                data_path=csv_path,
                task="l1",
                label_col="Label",
                models_to_run=models,
                seed=42,
                output_dir=output_dir,
            )

            metrics_path = output_dir / "metrics.json"
            self.assertTrue(metrics_path.is_file(), "metrics.json was not created by pipeline")

            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics_payload = json.load(f)

            self.assertEqual(metrics_payload.get("status"), "training_success")
            self.assertIn("models", metrics_payload)

            for model_name in models:
                self.assertIn(
                    model_name,
                    metrics_payload["models"],
                    f"Model {model_name} missing from metrics payload",
                )
                model_record = metrics_payload["models"][model_name]

                # Assert pr_auc is present, is a float, and is bounded [0, 1]
                self.assertIn("pr_auc", model_record)
                pr_auc = model_record["pr_auc"]
                self.assertIsInstance(
                    pr_auc,
                    float,
                    f"Model {model_name} pr_auc must be a float, got {type(pr_auc)}",
                )
                self.assertFalse(
                    np.isnan(pr_auc), f"Model {model_name} pr_auc must not be NaN"
                )
                self.assertGreaterEqual(pr_auc, 0.0)
                self.assertLessEqual(pr_auc, 1.0)

                # Assert roc_auc is present, is a float, and is bounded [0, 1]
                self.assertIn("roc_auc", model_record)
                roc_auc = model_record["roc_auc"]
                self.assertIsInstance(
                    roc_auc,
                    float,
                    f"Model {model_name} roc_auc must be a float, got {type(roc_auc)}",
                )
                self.assertFalse(
                    np.isnan(roc_auc), f"Model {model_name} roc_auc must not be NaN"
                )
                self.assertGreaterEqual(roc_auc, 0.0)
                self.assertLessEqual(roc_auc, 1.0)



class TestConfigValidation(unittest.TestCase):
    """Verify strict validation of raw JSON config and resolved config keys."""

    def test_valid_new_config_keys(self) -> None:
        """Verify valid configurations containing all new keys pass validation."""
        valid_cfg = {
            "mode": "audit",
            "model": "hist_gradient_boosting",
            "enable_score_calibration": True,
            "validation_fraction": 0.2,
            "target_false_positive_rate": 0.005,
            "feature_ablation": "group",
        }
        # Should not raise
        validate_raw_config(valid_cfg)

        resolved = {
            "mode": "audit",
            "model": "hist_gradient_boosting",
            "seed": 42,
            "max_samples_per_class": None,
            "enable_score_calibration": True,
            "validation_fraction": 0.2,
            "target_false_positive_rate": 0.005,
            "feature_ablation": "group",
        }
        validate_resolved_config(resolved)

    def test_reject_invalid_calibration_boolean(self) -> None:
        """Verify non-boolean enable_score_calibration is rejected."""
        for invalid in ["true", 1, 0, [True], {"enable": True}]:
            with self.assertRaises(ValueError):
                validate_raw_config({"enable_score_calibration": invalid})

    def test_reject_invalid_validation_fraction(self) -> None:
        """Verify validation_fraction outside (0.0, 1.0) or of invalid type is rejected."""
        for invalid in [0.0, 1.0, -0.2, 1.5, True, False, "0.25"]:
            with self.assertRaises(ValueError):
                validate_raw_config({"validation_fraction": invalid})

    def test_reject_invalid_target_false_positive_rate(self) -> None:
        """Verify target_false_positive_rate outside (0.0, 1.0) or of invalid type is rejected."""
        for invalid in [0.0, 1.0, -0.01, 2.0, True, False, "0.001"]:
            with self.assertRaises(ValueError):
                validate_raw_config({"target_false_positive_rate": invalid})

    def test_reject_invalid_feature_ablation(self) -> None:
        """Verify feature_ablation values other than 'none' or 'group' are rejected."""
        for invalid in ["all", "column", "group_ablation", 123, True]:
            with self.assertRaises(ValueError):
                validate_raw_config({"feature_ablation": invalid})

    def test_reject_unrecognized_config_key(self) -> None:
        """Verify unknown configuration keys cause immediate rejection."""
        with self.assertRaises(ValueError) as ctx:
            validate_raw_config({"mode": "audit", "arbitrary_custom_param": 42})
        self.assertIn("Unrecognized configuration key", str(ctx.exception))

    def test_valid_and_invalid_models(self) -> None:
        """Verify hist_gradient_boosting is accepted and unknown models are rejected."""
        validate_raw_config({"model": "hist_gradient_boosting"})
        with self.assertRaises(ValueError):
            validate_raw_config({"model": "xgboost"})
        with self.assertRaises(ValueError):
            validate_raw_config({"model": "lstm"})


class TestOperatingThresholdSelection(unittest.TestCase):
    """Verify deterministic operating threshold selection and FPR bounds."""

    def test_threshold_meets_target_fpr_when_feasible(self) -> None:
        """Verify threshold selection satisfies validation FPR <= target when feasible."""
        # 50 negative samples scored [0.01..0.05], 50 positive samples scored [0.60..0.95]
        rng = np.random.RandomState(42)
        neg_scores = rng.uniform(0.01, 0.05, size=50)
        pos_scores = rng.uniform(0.60, 0.95, size=50)
        y_val = np.array([0] * 50 + [1] * 50)
        val_scores = np.concatenate([neg_scores, pos_scores])

        target_fpr = 0.05
        selected_tau, achieved_fpr, is_feasible = select_operating_threshold(
            y_val, val_scores, target_fpr=target_fpr
        )

        self.assertTrue(is_feasible)
        self.assertIsInstance(selected_tau, float)
        self.assertIsInstance(achieved_fpr, float)
        self.assertLessEqual(achieved_fpr, target_fpr + 1e-9)

        # Verify predictions at threshold actually achieve achieved_fpr
        val_pred = (val_scores >= selected_tau).astype(int)
        actual_fp = np.sum((y_val == 0) & (val_pred == 1))
        actual_fpr = float(actual_fp / 50)
        self.assertAlmostEqual(achieved_fpr, actual_fpr)
        self.assertLessEqual(actual_fpr, target_fpr + 1e-9)

    def test_threshold_fallback_when_infeasible(self) -> None:
        """Verify threshold selection behaves deterministically when target is extremely low."""
        y_val = np.array([0, 0, 1, 1])
        # Identical scores: impossible to separate at FPR < 1.0 without predicting 0
        val_scores = np.array([0.5, 0.5, 0.5, 0.5])
        selected_tau, achieved_fpr, is_feasible = select_operating_threshold(
            y_val, val_scores, target_fpr=0.001
        )
        self.assertIsInstance(selected_tau, float)
        self.assertIsInstance(achieved_fpr, float)
        # Either achieved_fpr is 0.0 (by predicting nothing) or flag accurately indicates feasibility
        if achieved_fpr > 0.001:
            self.assertFalse(is_feasible)
        else:
            self.assertTrue(is_feasible)

    def test_empty_or_single_class_handled(self) -> None:
        """Verify degenerate inputs do not crash threshold selector."""
        tau, fpr, feasible = select_operating_threshold([], [], target_fpr=0.001)
        self.assertEqual(tau, 0.5)
        self.assertEqual(fpr, 0.0)
        self.assertFalse(feasible)


class TestCalibratedThresholdPipeline(unittest.TestCase):
    """Verify end-to-end score calibration and calibrated-threshold metrics."""

    def test_calibrated_pipeline_produces_calibration_and_threshold_metrics(self) -> None:
        """Test full pipeline with enable_score_calibration=True on synthetic binary data."""
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            csv_path = tmp_dir / "synthetic_l1_cal.csv"
            output_dir = tmp_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            rng = np.random.RandomState(42)
            n_samples = 60
            X_neg = rng.normal(loc=-1.5, scale=0.8, size=(n_samples, 4))
            X_pos = rng.normal(loc=1.5, scale=0.8, size=(n_samples, 4))
            X = np.vstack([X_neg, X_pos])
            labels = ["non_doh"] * n_samples + ["doh"] * n_samples

            df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(4)])
            df["Label"] = labels
            df.to_csv(csv_path, index=False)

            run_training_pipeline(
                data_path=csv_path,
                task="l1",
                label_col="Label",
                models_to_run=["random_forest"],
                seed=42,
                output_dir=output_dir,
                enable_score_calibration=True,
                validation_fraction=0.25,
                target_false_positive_rate=0.05,
            )

            metrics_path = output_dir / "metrics.json"
            self.assertTrue(metrics_path.is_file())
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)

            self.assertEqual(metrics.get("status"), "training_success")
            self.assertTrue(metrics.get("enable_score_calibration"))
            self.assertEqual(metrics.get("validation_fraction"), 0.25)
            self.assertEqual(metrics.get("target_false_positive_rate"), 0.05)

            rf_record = metrics["models"]["random_forest"]
            # Preserves historical metric keys
            self.assertIn("accuracy", rf_record)
            self.assertIn("precision_positive_class", rf_record)
            self.assertIn("false_positive_rate", rf_record)
            self.assertIn("roc_auc", rf_record)
            self.assertIn("pr_auc", rf_record)
            self.assertIn("confusion_matrix", rf_record)

            # Calibrated-threshold additions
            self.assertIn("default_threshold_metrics", rf_record)
            self.assertIn("selected_threshold", rf_record)
            self.assertIn("validation_fpr", rf_record)
            self.assertIn("calibrated_threshold_metrics", rf_record)
            self.assertIn("calibration", rf_record)

            self.assertIsInstance(rf_record["selected_threshold"], float)
            self.assertIsInstance(rf_record["validation_fpr"], float)
            self.assertGreaterEqual(rf_record["selected_threshold"], 0.0)
            self.assertLessEqual(rf_record["selected_threshold"], 1.0)

            cal_metrics = rf_record["calibrated_threshold_metrics"]
            self.assertIn("accuracy", cal_metrics)
            self.assertIn("f1_positive_class", cal_metrics)
            self.assertIn("false_positive_rate", cal_metrics)
            self.assertIn("confusion_matrix", cal_metrics)
            self.assertGreaterEqual(cal_metrics["accuracy"], 0.0)
            self.assertLessEqual(cal_metrics["accuracy"], 1.0)

            cal_meta = rf_record["calibration"]
            self.assertEqual(cal_meta["method"], "platt_scaling")
            self.assertEqual(cal_meta["validation_fraction"], 0.25)
            self.assertEqual(cal_meta["target_false_positive_rate"], 0.05)
            self.assertIn("threshold_feasible", cal_meta)

            # Check manifest data_split
            manifest_path = output_dir / "experiment_manifest.json"
            self.assertTrue(manifest_path.is_file())
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIn("validation_samples", manifest["data_split"])
            self.assertGreater(manifest["data_split"]["validation_samples"], 0)

    def test_discrete_model_produces_no_fabricated_threshold_metrics(self) -> None:
        """Verify models lacking continuous scores produce no fabricated threshold metrics."""
        class DiscreteStubModel:
            def fit(self, X: Any, y: Any) -> Any:
                return self

            def predict(self, X: Any) -> np.ndarray:
                return np.zeros(len(X), dtype=int)

            def get_params(self, deep: bool = True) -> dict[str, Any]:
                return {}

        scores_val = extract_prediction_scores(DiscreteStubModel(), np.zeros((4, 2)))
        self.assertIsNone(scores_val)


class TestHistGradientBoostingPipeline(unittest.TestCase):
    """Verify HistGradientBoostingClassifier availability through full training pipeline."""

    def test_hist_gradient_boosting_runs_end_to_end(self) -> None:
        """Verify HistGradientBoosting trains, evaluates, and emits expected artifacts."""
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            csv_path = tmp_dir / "synthetic_l1_hgb.csv"
            output_dir = tmp_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            rng = np.random.RandomState(42)
            n = 40
            X_neg = rng.normal(loc=-1.2, scale=0.8, size=(n, 4))
            X_pos = rng.normal(loc=1.2, scale=0.8, size=(n, 4))
            X = np.vstack([X_neg, X_pos])
            labels = ["non_doh"] * n + ["doh"] * n

            df = pd.DataFrame(X, columns=[f"feature_{i}" for i in range(4)])
            df["Label"] = labels
            df.to_csv(csv_path, index=False)

            run_training_pipeline(
                data_path=csv_path,
                task="l1",
                label_col="Label",
                models_to_run=["hist_gradient_boosting"],
                seed=42,
                output_dir=output_dir,
            )

            metrics_path = output_dir / "metrics.json"
            self.assertTrue(metrics_path.is_file())
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)

            self.assertIn("hist_gradient_boosting", metrics["models"])
            hgb_metrics = metrics["models"]["hist_gradient_boosting"]
            self.assertIn("accuracy", hgb_metrics)
            self.assertIn("roc_auc", hgb_metrics)
            self.assertIn("pr_auc", hgb_metrics)
            self.assertIsInstance(hgb_metrics["pr_auc"], float)
            self.assertFalse(np.isnan(hgb_metrics["pr_auc"]))
            self.assertGreaterEqual(hgb_metrics["pr_auc"], 0.0)
            self.assertLessEqual(hgb_metrics["pr_auc"], 1.0)

            cm_csv = output_dir / "confusion_matrix_hist_gradient_boosting.csv"
            self.assertTrue(cm_csv.is_file())


class TestGroupFeatureAblationAndRFImportance(unittest.TestCase):
    """Verify Random Forest feature importance output and group feature ablation output."""

    def test_classify_feature_group_rules(self) -> None:
        """Verify column classification into flow_volume, packet_length, packet_timing, response_timing."""
        self.assertEqual(classify_feature_group("Duration"), "flow_volume")
        self.assertEqual(classify_feature_group("duration"), "flow_volume")
        self.assertEqual(classify_feature_group("FlowBytesSent"), "flow_volume")
        self.assertEqual(classify_feature_group("FlowBytesReceived"), "flow_volume")
        self.assertEqual(classify_feature_group("FlowSentRate"), "flow_volume")
        self.assertEqual(classify_feature_group("FlowReceivedRate"), "flow_volume")
        self.assertEqual(classify_feature_group("flow_bytes_sent"), "flow_volume")

        self.assertEqual(classify_feature_group("PacketLengthVariance"), "packet_length")
        self.assertEqual(classify_feature_group("PacketLengthMean"), "packet_length")
        self.assertEqual(classify_feature_group("packet_length_median"), "packet_length")

        self.assertEqual(classify_feature_group("PacketTimeVariance"), "packet_timing")
        self.assertEqual(classify_feature_group("PacketTimeMean"), "packet_timing")
        self.assertEqual(classify_feature_group("packet_time_skew_from_median"), "packet_timing")

        self.assertEqual(classify_feature_group("ResponseTimeTimeVariance"), "response_timing")
        self.assertEqual(classify_feature_group("ResponseTimeTimeMean"), "response_timing")
        self.assertEqual(classify_feature_group("response_time_time_mode"), "response_timing")

        self.assertIsNone(classify_feature_group("UnrelatedCol"))
        self.assertIsNone(classify_feature_group("flow_id"))

    def test_rf_feature_importance_emitted_and_sorted(self) -> None:
        """Verify feature_importance_random_forest.csv is emitted only for RF on all features and sorted."""
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            csv_path = tmp_dir / "synthetic_l1_rf.csv"
            output_dir = tmp_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            rng = np.random.RandomState(42)
            n = 35
            X_neg = rng.normal(loc=-1.0, scale=0.8, size=(n, 3))
            X_pos = rng.normal(loc=1.0, scale=0.8, size=(n, 3))
            X = np.vstack([X_neg, X_pos])
            labels = ["non_doh"] * n + ["doh"] * n

            df = pd.DataFrame(X, columns=["Duration", "FlowBytesSent", "PacketLengthMean"])
            df["Label"] = labels
            df.to_csv(csv_path, index=False)

            run_training_pipeline(
                data_path=csv_path,
                task="l1",
                label_col="Label",
                models_to_run=["random_forest"],
                seed=42,
                output_dir=output_dir,
            )

            fi_path = output_dir / "feature_importance_random_forest.csv"
            self.assertTrue(fi_path.is_file(), "feature_importance_random_forest.csv was not created")

            fi_df = pd.read_csv(fi_path)
            self.assertIn("feature", fi_df.columns)
            self.assertIn("importance", fi_df.columns)
            self.assertEqual(len(fi_df), 3)

            # Assert sorted decreasingly by importance
            importances = fi_df["importance"].tolist()
            for i in range(len(importances) - 1):
                self.assertGreaterEqual(
                    importances[i],
                    importances[i + 1],
                    f"Importances not sorted decreasingly: {importances}",
                )

            # Assert listed in manifest output_artifacts
            manifest_path = output_dir / "experiment_manifest.json"
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIn("feature_importance_random_forest.csv", manifest["output_artifacts"])

    def test_group_feature_ablation_omits_nonexistent_columns(self) -> None:
        """Verify feature_ablation='group' evaluates RF subsets and omits nonexistent columns without failure."""
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            csv_path = tmp_dir / "synthetic_l1_ablation.csv"
            output_dir = tmp_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            rng = np.random.RandomState(42)
            n = 40
            # Only flow_volume and packet_length columns present; packet_timing and response_timing omitted
            X_neg = rng.normal(loc=-1.2, scale=0.8, size=(n, 4))
            X_pos = rng.normal(loc=1.2, scale=0.8, size=(n, 4))
            X = np.vstack([X_neg, X_pos])
            labels = ["non_doh"] * n + ["doh"] * n

            df = pd.DataFrame(
                X,
                columns=[
                    "Duration",
                    "FlowBytesSent",
                    "PacketLengthMean",
                    "PacketLengthVariance",
                ],
            )
            df["Label"] = labels
            df.to_csv(csv_path, index=False)

            # Should run smoothly and omit nonexistent columns rather than failing
            run_training_pipeline(
                data_path=csv_path,
                task="l1",
                label_col="Label",
                models_to_run=["random_forest"],
                seed=42,
                output_dir=output_dir,
                feature_ablation="group",
            )

            ablation_file = output_dir / "feature_ablations.json"
            self.assertTrue(ablation_file.is_file(), "feature_ablations.json was not created")

            with open(ablation_file, "r", encoding="utf-8") as f:
                abl_data = json.load(f)

            self.assertEqual(abl_data.get("feature_ablation_mode"), "group")
            self.assertEqual(abl_data.get("model"), "random_forest")
            self.assertIn("all_features", abl_data)
            self.assertIn("flow_volume", abl_data)
            self.assertIn("packet_length", abl_data)

            # Nonexistent groups (packet_timing, response_timing) handled gracefully
            self.assertIn("packet_timing", abl_data)
            self.assertIn("response_timing", abl_data)
            self.assertEqual(abl_data["packet_timing"]["removed_features"], [])
            self.assertEqual(abl_data["response_timing"]["removed_features"], [])

            # Flow volume removal removed Duration and FlowBytesSent
            self.assertIn("Duration", abl_data["flow_volume"]["removed_features"])
            self.assertIn("FlowBytesSent", abl_data["flow_volume"]["removed_features"])

            # Packet length removal removed PacketLengthMean and PacketLengthVariance
            self.assertIn("PacketLengthMean", abl_data["packet_length"]["removed_features"])
            self.assertIn("PacketLengthVariance", abl_data["packet_length"]["removed_features"])

            # Metrics are present and bounded
            for key in ["all_features", "flow_volume", "packet_length"]:
                rec = abl_data[key]
                self.assertIn("accuracy", rec)
                self.assertGreaterEqual(rec["accuracy"], 0.0)
                self.assertLessEqual(rec["accuracy"], 1.0)
                self.assertIn("false_positive_rate", rec)
                self.assertGreaterEqual(rec["false_positive_rate"], 0.0)
                self.assertLessEqual(rec["false_positive_rate"], 1.0)

            # Check manifest includes feature_ablations.json
            manifest_path = output_dir / "experiment_manifest.json"
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            self.assertIn("feature_ablations.json", manifest["output_artifacts"])

if __name__ == "__main__":
    unittest.main()
