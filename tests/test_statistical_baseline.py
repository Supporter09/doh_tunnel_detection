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
    compute_ranking_metrics,
    extract_prediction_scores,
    run_training_pipeline,
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


if __name__ == "__main__":
    unittest.main()
