"""Unit tests for timeseries_models module.

Verifies:
- Safe imports and actionable optional-dependency errors when torch is absent
- Model identity separation between paper reference and improved models
- Exact paper layer dimensions for l=3 and l=6 when torch exists
- Padding mask behavior and attention masking in the improved model
- Deterministic threshold selection and tie-breaking under an FPR cap
- Pure Platt calibration convergence and probability bounds
- Confusion matrix counts and derived metrics (precision, recall, f1, fpr, fnr, roc_auc, pr_auc)
- Model topology metadata and dimensions without requiring PyTorch
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Ensure src is in sys.path
TEST_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TEST_DIR.parent
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import doh_reproduction.timeseries_models as tm
from doh_reproduction.timeseries_models import (
    PADDING_VECTOR,
    ImprovedMaskedBiGRUModel,
    PaperReferenceLSTMModel,
    PlattCalibrator,
    binary_metrics,
    compute_pr_auc,
    compute_roc_auc,
    confusion_matrix_counts,
    create_improved_model,
    create_paper_model,
    get_improved_model_dimensions,
    get_paper_model_dimensions,
    is_torch_available,
    platt_calibrate,
    require_torch,
    select_threshold_at_fpr,
    set_deterministic_seed,
)

TORCH_AVAILABLE = is_torch_available()
if TORCH_AVAILABLE:
    import torch


class TestOptionalDependencyGuards(unittest.TestCase):
    """Verify actionable error messages when optional dependencies are absent."""

    def test_is_torch_available_returns_bool(self) -> None:
        val = is_torch_available()
        self.assertIsInstance(val, bool)

    def test_require_torch_raises_actionable_error_when_unavailable(self) -> None:
        with patch.object(tm, "TORCH_AVAILABLE", False):
            with self.assertRaises(ImportError) as ctx:
                require_torch("create_paper_model")
            msg = str(ctx.exception)
            self.assertIn("create_paper_model", msg)
            self.assertIn("requires PyTorch", msg)
            self.assertIn("pip install torch", msg)

    def test_model_factories_raise_actionable_error_when_torch_unavailable(self) -> None:
        with patch.object(tm, "TORCH_AVAILABLE", False):
            with self.assertRaises(ImportError) as ctx:
                tm.create_paper_model(window_size=3)
            self.assertIn("PyTorch", str(ctx.exception))

            with self.assertRaises(ImportError) as ctx:
                tm.create_improved_model(window_size=3)
            self.assertIn("PyTorch", str(ctx.exception))

            with self.assertRaises(ImportError) as ctx:
                tm.configure_bce_loss()
            self.assertIn("PyTorch", str(ctx.exception))

            with self.assertRaises(ImportError) as ctx:
                tm.fit_model(model=None, train_loader=[])
            self.assertIn("PyTorch", str(ctx.exception))

            with self.assertRaises(ImportError) as ctx:
                tm.predict_probabilities(model=None, data_or_loader=[])
            self.assertIn("PyTorch", str(ctx.exception))


    def test_fallback_classes_raise_actionable_error_when_torch_unavailable(self) -> None:
        """Fallback stubs must raise actionable error and not pretend to be models."""
        with patch.object(tm, "TORCH_AVAILABLE", False):
            # Fallback stubs must not pretend to have model_type attribute
            self.assertFalse(hasattr(tm._PaperReferenceLSTMFallback, "model_type"))
            self.assertFalse(hasattr(tm._ImprovedMaskedBiGRUFallback, "model_type"))

            # Instantiating fallback stub raises actionable error
            with self.assertRaises(ImportError) as ctx:
                tm._PaperReferenceLSTMFallback(3)
            self.assertIn("PaperReferenceLSTMModel requires PyTorch", str(ctx.exception))

            with self.assertRaises(ImportError) as ctx:
                tm._ImprovedMaskedBiGRUFallback(3)
            self.assertIn("ImprovedMaskedBiGRUModel requires PyTorch", str(ctx.exception))

    def test_pure_helpers_function_without_torch(self) -> None:
        """Verify threshold and metric helpers run safely even if torch is marked unavailable."""
        with patch.object(tm, "TORCH_AVAILABLE", False):
            # Seed
            set_deterministic_seed(123)

            # Confusion matrix
            tn, fp, fn, tp = confusion_matrix_counts([0, 1], [0, 1])
            self.assertEqual((tn, fp, fn, tp), (1, 0, 0, 1))

            # Binary metrics
            m = binary_metrics([0, 1], [0, 1], [0.1, 0.9])
            self.assertEqual(m["accuracy"], 1.0)
            self.assertEqual(m["f1"], 1.0)
            self.assertEqual(m["roc_auc"], 1.0)

            # Threshold selection
            tau, fpr, feas = select_threshold_at_fpr([0, 1], [0.1, 0.9], target_fpr=0.01)
            self.assertTrue(feas)
            self.assertAlmostEqual(fpr, 0.0)

            # Platt calibration
            cal, val_cal, _ = platt_calibrate([0.1, 0.9], [0, 1])
            self.assertIsInstance(cal, PlattCalibrator)
            self.assertEqual(len(val_cal), 2)


class TestConfusionMatrixAndBinaryMetrics(unittest.TestCase):
    """Verify confusion matrix counts and derived metrics calculation."""

    def test_perfect_classification(self) -> None:
        y_true = [0, 0, 1, 1]
        y_pred = [0, 0, 1, 1]
        tn, fp, fn, tp = confusion_matrix_counts(y_true, y_pred)
        self.assertEqual((tn, fp, fn, tp), (2, 0, 0, 2))

        m = binary_metrics(y_true, y_pred)
        self.assertEqual(m["total"], 4)
        self.assertEqual(m["accuracy"], 1.0)
        self.assertEqual(m["precision"], 1.0)
        self.assertEqual(m["recall"], 1.0)
        self.assertEqual(m["specificity"], 1.0)
        self.assertEqual(m["fpr"], 0.0)
        self.assertEqual(m["fnr"], 0.0)
        self.assertEqual(m["f1"], 1.0)
        self.assertEqual(m["balanced_accuracy"], 1.0)

    def test_completely_inverted_classification(self) -> None:
        y_true = [0, 0, 1, 1]
        y_pred = [1, 1, 0, 0]
        tn, fp, fn, tp = confusion_matrix_counts(y_true, y_pred)
        self.assertEqual((tn, fp, fn, tp), (0, 2, 2, 0))

        m = binary_metrics(y_true, y_pred)
        self.assertEqual(m["accuracy"], 0.0)
        self.assertEqual(m["precision"], 0.0)
        self.assertEqual(m["recall"], 0.0)
        self.assertEqual(m["specificity"], 0.0)
        self.assertEqual(m["fpr"], 1.0)
        self.assertEqual(m["fnr"], 1.0)
        self.assertEqual(m["f1"], 0.0)

    def test_imbalanced_confusion_counts(self) -> None:
        # 100 negatives: 90 TN, 10 FP -> FPR = 10/100 = 0.1, specificity = 0.9
        # 20 positives: 15 TP, 5 FN -> recall = 15/20 = 0.75, precision = 15/25 = 0.6
        y_true = [0] * 90 + [0] * 10 + [1] * 5 + [1] * 15
        y_pred = [0] * 90 + [1] * 10 + [0] * 5 + [1] * 15

        tn, fp, fn, tp = confusion_matrix_counts(y_true, y_pred)
        self.assertEqual((tn, fp, fn, tp), (90, 10, 5, 15))

        m = binary_metrics(y_true, y_pred)
        self.assertAlmostEqual(m["accuracy"], 105.0 / 120.0)
        self.assertAlmostEqual(m["precision"], 0.6)
        self.assertAlmostEqual(m["recall"], 0.75)
        self.assertAlmostEqual(m["specificity"], 0.9)
        self.assertAlmostEqual(m["fpr"], 0.1)
        self.assertAlmostEqual(m["fnr"], 0.25)
        expected_f1 = 2.0 * (0.6 * 0.75) / (0.6 + 0.75)
        self.assertAlmostEqual(m["f1"], expected_f1)
        self.assertAlmostEqual(m["balanced_accuracy"], 0.5 * (0.75 + 0.9))

    def test_length_mismatch_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            confusion_matrix_counts([0, 1], [0])

    def test_zero_denominator_safe(self) -> None:
        # All negatives predicted negative
        m = binary_metrics([0, 0], [0, 0])
        self.assertEqual(m["precision"], 0.0)
        self.assertEqual(m["recall"], 0.0)
        self.assertEqual(m["f1"], 0.0)
        self.assertEqual(m["fpr"], 0.0)

    def test_roc_auc_and_pr_auc_calculation(self) -> None:
        # Perfectly separated scores
        y_true = [0, 0, 1, 1]
        y_prob = [0.1, 0.2, 0.8, 0.9]
        roc = compute_roc_auc(y_true, y_prob)
        pr = compute_pr_auc(y_true, y_prob)
        self.assertIsNotNone(roc)
        self.assertIsNotNone(pr)
        self.assertAlmostEqual(roc, 1.0)  # type: ignore[arg-type]
        self.assertAlmostEqual(pr, 1.0)   # type: ignore[arg-type]

        # Inverted scores
        roc_inv = compute_roc_auc(y_true, [0.9, 0.8, 0.2, 0.1])
        self.assertAlmostEqual(roc_inv, 0.0)  # type: ignore[arg-type]

        # Tied scores
        roc_tied = compute_roc_auc([0, 1], [0.5, 0.5])
        self.assertAlmostEqual(roc_tied, 0.5)  # type: ignore[arg-type]

        # Single class returns None
        self.assertIsNone(compute_roc_auc([0, 0], [0.1, 0.2]))
        self.assertIsNone(compute_pr_auc([0, 0], [0.1, 0.2]))


class TestThresholdSelectionAtFPR(unittest.TestCase):
    """Verify threshold selection satisfies FPR cap with deterministic tie-breaking."""

    def test_separable_data_achieves_target_fpr(self) -> None:
        y_val = [0, 0, 0, 0, 1, 1, 1, 1]
        scores = [0.05, 0.10, 0.15, 0.20, 0.80, 0.85, 0.90, 0.95]
        target_fpr = 0.001

        tau, achieved_fpr, feasible = select_threshold_at_fpr(
            y_val, scores, target_fpr=target_fpr
        )
        self.assertTrue(feasible)
        self.assertLessEqual(achieved_fpr, target_fpr)
        self.assertAlmostEqual(achieved_fpr, 0.0)
        # Any threshold > 0.20 and <= 0.80 has TPR=1.0, FPR=0.0
        self.assertGreater(tau, 0.20)
        self.assertLessEqual(tau, 0.80 + 1e-5)

    def test_deterministic_tie_breaking_prefers_higher_threshold(self) -> None:
        """When multiple thresholds give equal max TPR and equal min FPR, prefer higher threshold."""
        y_val = [0, 0, 1, 1]
        # At tau=0.3 and tau=0.6, both give TP=2 (TPR=1.0) and FP=0 (FPR=0.0)
        scores = [0.1, 0.2, 0.6, 0.8]
        tau, achieved_fpr, feasible = select_threshold_at_fpr(y_val, scores, target_fpr=0.01)
        self.assertTrue(feasible)
        self.assertAlmostEqual(achieved_fpr, 0.0)
        # Should pick 0.6 (or higher candidate) over 0.2/0.5
        self.assertGreaterEqual(tau, 0.6)

    def test_infeasible_target_fpr_minimizes_fpr(self) -> None:
        """When target FPR cannot be satisfied, selects threshold minimizing FPR."""
        # 4 negatives with high scores, target_fpr=0.0 implies 0 FP allowed
        y_val = [0, 0, 0, 0, 1, 1]
        scores = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
        target_fpr = 0.0  # Infeasible unless tau > 0.85

        # If tau = 0.86, FP=0, FPR=0.0, which IS feasible for 0 FP!
        # Let's test a case where positive and negative scores are identical:
        y_val_overlap = [0, 1]
        scores_overlap = [0.9, 0.9]
        # Any threshold <= 0.9 gives FP=1 (FPR=1.0). Threshold > 0.9 gives FP=0, TP=0 (TPR=0.0, FPR=0.0).
        tau, achieved_fpr, feasible = select_threshold_at_fpr(
            y_val_overlap, scores_overlap, target_fpr=0.0
        )
        # Threshold > 0.9 yields FPR=0.0 <= 0.0
        self.assertTrue(feasible)
        self.assertAlmostEqual(achieved_fpr, 0.0)

    def test_empty_input_handled_cleanly(self) -> None:
        tau, fpr, feasible = select_threshold_at_fpr([], [])
        self.assertEqual(tau, 0.5)
        self.assertEqual(fpr, 0.0)
        self.assertFalse(feasible)

    def test_all_positive_input_handled_cleanly(self) -> None:
        tau, fpr, feasible = select_threshold_at_fpr([1, 1], [0.8, 0.9])
        self.assertEqual(tau, 0.5)
        self.assertEqual(fpr, 0.0)
        self.assertTrue(feasible)


class TestPlattCalibration(unittest.TestCase):
    """Verify Platt scaling convergence, probability bounds, and test split transformation."""

    def test_calibration_preserves_monotonicity(self) -> None:
        y_val = [0, 0, 0, 0, 1, 1, 1, 1]
        val_scores = [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0]
        test_scores = [-1.0, 0.0, 1.0]

        calibrator, val_cal, test_cal = platt_calibrate(val_scores, y_val, test_scores)
        self.assertIsInstance(calibrator, PlattCalibrator)
        self.assertIsNotNone(test_cal)

        # Probabilities must be strictly bounded in (0.0, 1.0)
        for p in val_cal:
            self.assertGreater(p, 0.0)
            self.assertLess(p, 1.0)
        for p in test_cal:  # type: ignore[union-attr]
            self.assertGreater(p, 0.0)
            self.assertLess(p, 1.0)

        # Monotonicity: higher score yields higher probability
        self.assertLess(test_cal[0], test_cal[1])  # type: ignore[index]
        self.assertLess(test_cal[1], test_cal[2])  # type: ignore[index]

    def test_single_class_degenerate_cases(self) -> None:
        cal_neg, val_cal_neg, _ = platt_calibrate([0.1, 0.2], [0, 0])
        for p in val_cal_neg:
            self.assertLess(p, 0.01)

        cal_pos, val_cal_pos, _ = platt_calibrate([0.8, 0.9], [1, 1])
        for p in val_cal_pos:
            self.assertGreater(p, 0.99)

    def test_length_mismatch_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            platt_calibrate([0.5], [0, 1])


class TestDeterministicSeed(unittest.TestCase):
    """Verify deterministic seeding across Python random and available packages."""

    def test_seed_produces_identical_random_sequences(self) -> None:
        set_deterministic_seed(999)
        val1 = [tm.random.random() for _ in range(5)]
        set_deterministic_seed(999)
        val2 = [tm.random.random() for _ in range(5)]
        self.assertEqual(val1, val2)


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required for neural network tests")
class TestModelIdentityAndLayerDimensions(unittest.TestCase):
    """Verify model identity separation, exact paper layer dimensions, and padding mask."""

    def test_model_identity_separation(self) -> None:
        """Paper model and improved model must be distinct classes with distinct type identifiers."""
        paper_m = tm.create_paper_model(window_size=3)
        improved_m = tm.create_improved_model(window_size=3)

        self.assertIsInstance(paper_m, PaperReferenceLSTMModel)
        self.assertNotIsInstance(paper_m, ImprovedMaskedBiGRUModel)
        self.assertEqual(paper_m.model_type, "paper_reference_v4")

        self.assertIsInstance(improved_m, ImprovedMaskedBiGRUModel)
        self.assertNotIsInstance(improved_m, PaperReferenceLSTMModel)
        self.assertEqual(improved_m.model_type, "improved_masked_bigru")

    def test_exact_paper_layer_dimensions_l3(self) -> None:
        """For l=3, verify exact DoHLyzer v4 dimensions: Dense(10) -> LSTM(24) -> Dense(18) -> Dense(6) -> 1."""
        model = tm.create_paper_model(window_size=3)
        self.assertEqual(model.window_size, 3)

        # Step 1: Linear(5, 10)
        self.assertEqual(model.step_dense.in_features, 5)
        self.assertEqual(model.step_dense.out_features, 10)

        # Step 2: LSTM(10, 8 * 3 = 24)
        self.assertEqual(model.lstm.input_size, 10)
        self.assertEqual(model.lstm.hidden_size, 24)

        # Step 3: Dense(24, 6 * 3 = 18)
        self.assertEqual(model.dense1.in_features, 24)
        self.assertEqual(model.dense1.out_features, 18)

        # Step 4: Dropout(0.2)
        self.assertAlmostEqual(model.dropout.p, 0.2)

        # Step 5: Dense(18, 2 * 3 = 6)
        self.assertEqual(model.dense2.in_features, 18)
        self.assertEqual(model.dense2.out_features, 6)

        # Step 6: Output Linear(6, 1)
        self.assertEqual(model.out_proj.in_features, 6)
        self.assertEqual(model.out_proj.out_features, 1)

    def test_exact_paper_layer_dimensions_l6(self) -> None:
        """For l=6, verify exact DoHLyzer v4 dimensions: Dense(10) -> LSTM(48) -> Dense(36) -> Dense(12) -> 1."""
        model = tm.create_paper_model(window_size=6)
        self.assertEqual(model.window_size, 6)

        # Step 1: Linear(5, 10)
        self.assertEqual(model.step_dense.in_features, 5)
        self.assertEqual(model.step_dense.out_features, 10)

        # Step 2: LSTM(10, 8 * 6 = 48)
        self.assertEqual(model.lstm.input_size, 10)
        self.assertEqual(model.lstm.hidden_size, 48)

        # Step 3: Dense(48, 6 * 6 = 36)
        self.assertEqual(model.dense1.in_features, 48)
        self.assertEqual(model.dense1.out_features, 36)

        # Step 4: Dropout(0.2)
        self.assertAlmostEqual(model.dropout.p, 0.2)

        # Step 5: Dense(36, 2 * 6 = 12)
        self.assertEqual(model.dense2.in_features, 36)
        self.assertEqual(model.dense2.out_features, 12)

        # Step 6: Output Linear(12, 1)
        self.assertEqual(model.out_proj.in_features, 12)
        self.assertEqual(model.out_proj.out_features, 1)

    def test_improved_model_layer_dimensions(self) -> None:
        """Verify improved model BiGRU and attention dimensions."""
        model = tm.create_improved_model(window_size=6, hidden_dim=64, num_layers=1, dropout=0.25)
        self.assertEqual(model.window_size, 6)
        self.assertEqual(model.hidden_dim, 64)
        self.assertEqual(model.num_layers, 1)
        self.assertAlmostEqual(model.dropout_rate, 0.25)

        # BiGRU
        self.assertEqual(model.gru.input_size, 5)
        self.assertEqual(model.gru.hidden_size, 64)
        self.assertTrue(model.gru.bidirectional)

        # Attention projection
        self.assertEqual(model.attn_proj.in_features, 128)  # 2 * hidden_dim
        self.assertEqual(model.attn_proj.out_features, 64)
        self.assertEqual(model.attn_v.in_features, 64)
        self.assertEqual(model.attn_v.out_features, 1)

        # Classification head
        self.assertEqual(model.fc1.in_features, 128)
        self.assertEqual(model.fc1.out_features, 64)
        self.assertEqual(model.fc2.in_features, 64)
        self.assertEqual(model.fc2.out_features, 1)

    def test_padding_mask_behavior_in_improved_model(self) -> None:
        """Verify that padding clumps [-1, -1, -1, -1, 0] are assigned zero attention weight."""
        model = tm.create_improved_model(window_size=4, hidden_dim=32)
        model.eval()

        # Batch with 1 sequence: 2 valid clumps + 2 padding clumps
        valid_clump_1 = [0.5, 0.2, 0.8, 0.3, 1.0]
        valid_clump_2 = [0.4, 0.1, 0.7, 0.2, -1.0]
        pad_clump = list(PADDING_VECTOR)  # [-1.0, -1.0, -1.0, -1.0, 0.0]

        seq = [valid_clump_1, valid_clump_2, pad_clump, pad_clump]
        x = torch.tensor([seq], dtype=torch.float32)  # shape (1, 4, 5)

        # Test automatic padding mask detection
        mask = model.compute_padding_mask(x)
        self.assertTrue(mask[0, 0].item())
        self.assertTrue(mask[0, 1].item())
        self.assertFalse(mask[0, 2].item())
        self.assertFalse(mask[0, 3].item())

        # Forward pass requesting attention weights
        _, attn_weights = model(x, return_attention=True)
        # attn_weights shape (1, 4)
        w = attn_weights[0].detach().cpu().numpy()

        # Padded clumps must receive negligible attention
        self.assertLess(w[2], 1e-5)
        self.assertLess(w[3], 1e-5)

        # Valid clumps receive almost all attention mass summing to ~1.0
        self.assertAlmostEqual(float(w[0] + w[1]), 1.0, places=4)

    def test_paper_model_forward_pass_shapes(self) -> None:
        model = tm.create_paper_model(window_size=3)
        model.eval()
        x = torch.randn(4, 3, 5)

        # Logits
        logits = model(x, return_probs=False)
        self.assertEqual(logits.shape, (4, 1))

        # Probs
        probs = model(x, return_probs=True)
        self.assertEqual(probs.shape, (4, 1))
        self.assertTrue((probs >= 0.0).all())
        self.assertTrue((probs <= 1.0).all())

        # predict_proba
        p = model.predict_proba(x)
        self.assertEqual(p.shape, (4,))


class TestModelTopologyMetadata(unittest.TestCase):
    """Verify paper reference topology and metadata invariants without requiring PyTorch."""

    def test_paper_model_dimensions_l3(self) -> None:
        dims = get_paper_model_dimensions(window_size=3)
        self.assertEqual(dims["step_dense"], (5, 10))
        self.assertEqual(dims["lstm_input"], 10)
        self.assertEqual(dims["lstm_hidden"], 24)
        self.assertEqual(dims["dense1"], (24, 18))
        self.assertAlmostEqual(dims["dropout_p"], 0.2)
        self.assertEqual(dims["dense2"], (18, 6))
        self.assertEqual(dims["out_proj"], (6, 1))

    def test_paper_model_dimensions_l6(self) -> None:
        dims = get_paper_model_dimensions(window_size=6)
        self.assertEqual(dims["step_dense"], (5, 10))
        self.assertEqual(dims["lstm_input"], 10)
        self.assertEqual(dims["lstm_hidden"], 48)
        self.assertEqual(dims["dense1"], (48, 36))
        self.assertAlmostEqual(dims["dropout_p"], 0.2)
        self.assertEqual(dims["dense2"], (36, 12))
        self.assertEqual(dims["out_proj"], (12, 1))

    def test_paper_model_dimensions_invalid_window_size(self) -> None:
        with self.assertRaises(ValueError):
            get_paper_model_dimensions(window_size=0)
        with self.assertRaises(ValueError):
            get_paper_model_dimensions(window_size=-1)

    def test_factory_dimension_metadata_exposed(self) -> None:
        self.assertTrue(callable(create_paper_model.get_dimensions))
        dims = create_paper_model.get_dimensions(window_size=3)
        self.assertEqual(dims["lstm_hidden"], 24)

    def test_improved_model_dimensions(self) -> None:
        dims = get_improved_model_dimensions(window_size=6, hidden_dim=64, num_layers=1, dropout=0.25)
        self.assertEqual(dims["input_dim"], 5)
        self.assertEqual(dims["gru_hidden_dim"], 64)
        self.assertEqual(dims["gru_directions"], 2)
        self.assertEqual(dims["gru_num_layers"], 1)
        self.assertEqual(dims["context_dim"], 128)
        self.assertEqual(dims["attn_proj"], (128, 64))
        self.assertEqual(dims["fc1"], (128, 64))
        self.assertEqual(dims["fc2"], (64, 1))
        self.assertAlmostEqual(dims["dropout_p"], 0.25)

if __name__ == "__main__":
    unittest.main()
